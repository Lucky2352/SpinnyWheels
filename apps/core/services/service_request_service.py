from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import (
    ConflictError,
    DomainError,
    InvalidStateError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from apps.core.models.choices import AssignmentStatus, Priority, ServiceStatus
from apps.core.models.servicing import ACTIVE_ASSIGNMENT_STATUSES
from apps.core.repositories.appointment_repository import AppointmentRepository
from apps.core.repositories.customer_repository import CustomerVehicleRepository
from apps.core.repositories.service_repository import (
    ServiceRecordRepository,
    ServiceRequestRepository,
    TechnicianAssignmentRepository,
)
from apps.core.repositories.technician_repository import TechnicianRepository


class ServiceRequestService:
    def __init__(
        self,
        service_requests=None,
        assignments=None,
        service_records=None,
        technicians=None,
        customer_vehicles=None,
        appointments=None,
    ):
        self._service_requests = service_requests or ServiceRequestRepository()
        self._assignments = assignments or TechnicianAssignmentRepository()
        self._service_records = service_records or ServiceRecordRepository()
        self._technicians = technicians or TechnicianRepository()
        self._customer_vehicles = customer_vehicles or CustomerVehicleRepository()
        self._appointments = appointments or AppointmentRepository()

    def get_service_request(self, service_request_id):
        service_request = self._service_requests.get_by_id(service_request_id)
        if service_request is None:
            raise ResourceNotFoundError("Service request does not exist.")
        return service_request

    def list_by_status(self, status=None):
        return self._service_requests.list_by_status(status)

    def list_for_dealership(self, dealership_id, *, status=None):
        return self._service_requests.list_by_dealership(dealership_id, status=status)

    def list_for_technician(self, technician_id, *, status=None):
        return self._service_requests.list_assigned_to_technician(
            technician_id, status=status
        )

    def list_assignments_for_technician(self, technician_id, *, status=None):
        return self._assignments.list_for_technician(technician_id, status=status)

    def list_assignments_for_service_request(self, service_request_id):
        self.get_service_request(service_request_id)
        return self._assignments.list_for_service_request(service_request_id)

    def list_available_technicians(self, *, specialization=None):
        return self._technicians.list_available(specialization=specialization)

    @transaction.atomic
    def submit(
        self,
        *,
        customer_vehicle_id,
        service_type,
        problem_description,
        priority=Priority.MEDIUM,
        appointment_id=None,
        estimated_cost=None,
    ):
        customer_vehicle = self._customer_vehicles.get_by_id(customer_vehicle_id)
        if customer_vehicle is None:
            raise ResourceNotFoundError("Customer vehicle does not exist.")
        if estimated_cost is not None and estimated_cost < 0:
            raise DomainError("Estimated cost cannot be negative.")

        appointment = None
        if appointment_id is not None:
            appointment = self._appointments.get_by_id(appointment_id)
            if appointment is None:
                raise ResourceNotFoundError("Appointment does not exist.")
            if appointment.customer_id != customer_vehicle.customer_id:
                raise DomainError(
                    "The appointment belongs to a different customer."
                )

        dealership_id = appointment.dealership_id if appointment else customer_vehicle.vehicle.dealership_id

        try:
            return self._service_requests.create(
                dealership_id=dealership_id,
                appointment=appointment,
                customer_vehicle=customer_vehicle,
                service_type=service_type,
                problem_description=problem_description,
                priority=priority,
                estimated_cost=estimated_cost,
            )
        except IntegrityError as exc:
            raise ConflictError(
                "This appointment already has a service request."
            ) from exc

    def confirm(self, service_request_id):
        service_request = self.get_service_request(service_request_id)
        if service_request.status != ServiceStatus.PENDING:
            raise InvalidStateError(
                f"A service request in {service_request.status} state cannot be confirmed."
            )
        return self._service_requests.update(
            service_request, status=ServiceStatus.CONFIRMED
        )

    def cancel(self, service_request_id):
        service_request = self.get_service_request(service_request_id)
        if service_request.status in {ServiceStatus.COMPLETED, ServiceStatus.CANCELLED}:
            raise InvalidStateError(
                f"A service request in {service_request.status} state cannot be cancelled."
            )
        return self._service_requests.update(
            service_request, status=ServiceStatus.CANCELLED
        )

    @transaction.atomic
    def assign_technician(
        self, *, service_request_id, technician_id, notes="", dealership_id=None
    ):
        service_request = self.get_service_request(service_request_id)
        technician = self._technicians.get_by_id(technician_id)

        if technician is None:
            raise ResourceNotFoundError("Technician does not exist.")
        if dealership_id is not None and technician.employee.dealership_id != dealership_id:
            raise PermissionDeniedError(
                "You can only assign technicians from your own dealership."
            )
        if not technician.is_available:
            raise ConflictError("This technician is not available.")
        if service_request.status in {ServiceStatus.COMPLETED, ServiceStatus.CANCELLED}:
            raise InvalidStateError(
                f"A service request in {service_request.status} state cannot be assigned."
            )

        try:
            assignment = self._assignments.create(
                service_request=service_request,
                technician=technician,
                notes=notes,
            )
        except IntegrityError as exc:
            raise ConflictError(
                "This technician already has an active assignment."
            ) from exc

        self._technicians.update(technician, is_available=False)
        if service_request.status == ServiceStatus.PENDING:
            self._service_requests.update(
                service_request, status=ServiceStatus.CONFIRMED
            )
        return assignment

    def start_assignment(self, assignment_id, *, technician_id=None, dealership_id=None):
        assignment = self._get_assignment(
            assignment_id, technician_id=technician_id, dealership_id=dealership_id
        )
        if assignment.status != AssignmentStatus.ASSIGNED:
            raise InvalidStateError(
                f"An assignment in {assignment.status} state cannot be started."
            )
        return self._assignments.update(
            assignment, status=AssignmentStatus.IN_PROGRESS, started_at=timezone.now()
        )

    @transaction.atomic
    def complete_assignment(
        self,
        assignment_id,
        *,
        description,
        parts_cost=Decimal("0.00"),
        labor_cost=Decimal("0.00"),
        service_date=None,
        technician_id=None,
        dealership_id=None,
    ):
        assignment = self._get_assignment(
            assignment_id, technician_id=technician_id, dealership_id=dealership_id
        )

        if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
            raise InvalidStateError(
                f"An assignment in {assignment.status} state cannot be completed."
            )
        if parts_cost < 0 or labor_cost < 0:
            raise DomainError("Service costs cannot be negative.")

        parts = Decimal(parts_cost).quantize(Decimal("0.01"))
        labor = Decimal(labor_cost).quantize(Decimal("0.01"))

        service_record = self._service_records.create(
            service_request=assignment.service_request,
            customer_vehicle=assignment.service_request.customer_vehicle,
            technician=assignment.technician,
            description=description,
            parts_cost=parts,
            labor_cost=labor,
            total_cost=parts + labor,
            service_date=service_date or date.today(),
        )
        self._assignments.update(
            assignment, status=AssignmentStatus.COMPLETED, completed_at=timezone.now()
        )
        self._service_requests.update(
            assignment.service_request, status=ServiceStatus.COMPLETED
        )
        self._technicians.update(assignment.technician, is_available=True)
        return service_record

    def _get_assignment(self, assignment_id, *, technician_id=None, dealership_id=None):
        assignment = self._assignments.get_by_id(assignment_id)
        if assignment is None:
            raise ResourceNotFoundError("Technician assignment does not exist.")
        if technician_id is not None and assignment.technician_id != technician_id:
            raise PermissionDeniedError(
                "You can only update assignments assigned to you."
            )
        if (
            dealership_id is not None
            and assignment.service_request.dealership_id != dealership_id
        ):
            raise PermissionDeniedError(
                "You can only manage assignments for your own dealership."
            )
        return assignment
