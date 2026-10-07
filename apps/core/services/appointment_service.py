from datetime import date

from django.db import transaction

from apps.core.exceptions import (
    ConflictError,
    DomainError,
    InvalidStateError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from apps.core.models.choices import AppointmentStatus, AppointmentType
from apps.core.repositories.appointment_repository import (
    AppointmentRepository,
    TestDriveRepository,
)
from apps.core.repositories.customer_repository import CustomerRepository
from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.repositories.vehicle_repository import VehicleRepository

ALLOWED_TRANSITIONS = {
    AppointmentStatus.PENDING: {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
    AppointmentStatus.CONFIRMED: {AppointmentStatus.IN_PROGRESS, AppointmentStatus.CANCELLED},
    AppointmentStatus.IN_PROGRESS: {AppointmentStatus.COMPLETED},
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.CANCELLED: set(),
}


class AppointmentService:
    def __init__(
        self,
        appointments=None,
        test_drives=None,
        customers=None,
        dealerships=None,
        vehicles=None,
    ):
        self._appointments = appointments or AppointmentRepository()
        self._test_drives = test_drives or TestDriveRepository()
        self._customers = customers or CustomerRepository()
        self._dealerships = dealerships or DealershipRepository()
        self._vehicles = vehicles or VehicleRepository()

    def schedule(
        self,
        *,
        customer_id,
        dealership_id,
        appointment_type,
        scheduled_date,
        scheduled_time,
        notes="",
    ):
        if appointment_type == AppointmentType.TEST_DRIVE:
            raise DomainError("Test drive appointments must be scheduled with a vehicle.")
        return self._create_appointment(
            customer_id,
            dealership_id,
            appointment_type,
            scheduled_date,
            scheduled_time,
            notes,
        )

    @transaction.atomic
    def schedule_test_drive(
        self,
        *,
        customer_id,
        dealership_id,
        vehicle_id,
        scheduled_date,
        scheduled_time,
        notes="",
    ):
        vehicle = self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("Vehicle does not exist.")
        if not vehicle.is_in_stock:
            raise ConflictError("This vehicle is not available for a test drive.")

        appointment = self._create_appointment(
            customer_id,
            dealership_id,
            AppointmentType.TEST_DRIVE,
            scheduled_date,
            scheduled_time,
            notes,
        )
        return self._test_drives.create(appointment=appointment, vehicle=vehicle)

    def get_appointment(self, appointment_id):
        appointment = self._appointments.get_by_id(appointment_id)
        if appointment is None:
            raise ResourceNotFoundError("Appointment does not exist.")
        return appointment

    def get_test_drive(self, appointment_id):
        test_drive = self._test_drives.get_by_appointment(appointment_id)
        if test_drive is None:
            raise ResourceNotFoundError("This appointment has no test drive.")
        return test_drive

    def confirm(self, appointment_id):
        return self._transition(appointment_id, AppointmentStatus.CONFIRMED)

    def start(self, appointment_id):
        return self._transition(appointment_id, AppointmentStatus.IN_PROGRESS)

    def complete(self, appointment_id):
        return self._transition(appointment_id, AppointmentStatus.COMPLETED)

    def cancel(self, appointment_id):
        return self._transition(appointment_id, AppointmentStatus.CANCELLED)

    def list_for_customer(self, customer_id, *, status=None):
        return self._appointments.list_by_customer(customer_id, status=status)

    def list_by_status(self, status=None, *, scheduled_date=None):
        return self._appointments.list_by_status(status, scheduled_date=scheduled_date)

    def list_for_dealership(self, dealership_id, *, status=None, scheduled_date=None):
        return self._appointments.list_by_dealership(
            dealership_id, status=status, scheduled_date=scheduled_date
        )

    def update_status(self, appointment_id, dealership_id, *, status):
        appointment = self.get_appointment(appointment_id)
        if appointment.dealership_id != dealership_id:
            raise PermissionDeniedError(
                "You can only manage appointments for your own dealership."
            )
        return self._transition(appointment_id, status)

    def _create_appointment(
        self,
        customer_id,
        dealership_id,
        appointment_type,
        scheduled_date,
        scheduled_time,
        notes,
    ):
        if self._customers.get_by_id(customer_id) is None:
            raise ResourceNotFoundError("Customer does not exist.")
        if self._dealerships.get_by_id(dealership_id) is None:
            raise ResourceNotFoundError("Dealership does not exist.")
        if scheduled_date < date.today():
            raise DomainError("Appointments cannot be scheduled in the past.")

        return self._appointments.create(
            customer_id=customer_id,
            dealership_id=dealership_id,
            appointment_type=appointment_type,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            notes=notes,
        )

    def _transition(self, appointment_id, new_status):
        appointment = self.get_appointment(appointment_id)
        allowed = ALLOWED_TRANSITIONS.get(appointment.status, set())

        if new_status not in allowed:
            raise InvalidStateError(
                f"An appointment cannot move from {appointment.status} to {new_status}."
            )
        return self._appointments.update(appointment, status=new_status)
