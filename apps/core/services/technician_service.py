from django.db import IntegrityError

from apps.core.exceptions import (
    ConflictError,
    DomainError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from apps.core.models.choices import EmployeeRole
from apps.core.repositories.employee_repository import EmployeeRepository
from apps.core.repositories.service_repository import TechnicianAssignmentRepository
from apps.core.repositories.technician_repository import TechnicianRepository


class TechnicianService:
    def __init__(self, technicians=None, employees=None, assignments=None):
        self._technicians = technicians or TechnicianRepository()
        self._employees = employees or EmployeeRepository()
        self._assignments = assignments or TechnicianAssignmentRepository()

    def list_technicians(self, dealership_id):
        return self._technicians.list_by_dealership(dealership_id)

    def get_managed(self, technician_id, dealership_id):
        technician = self._technicians.get_by_id(technician_id)
        if technician is None or technician.employee.dealership_id != dealership_id:
            raise PermissionDeniedError(
                "You can only manage technicians of your own dealership."
            )
        return technician

    def create_profile(self, *, dealership_id, employee_id, specialization):
        employee = self._employees.get_by_id(employee_id)
        if employee is None or employee.dealership_id != dealership_id:
            raise ResourceNotFoundError("Employee does not exist.")
        if employee.role != EmployeeRole.TECHNICIAN:
            raise DomainError("Only employees with the technician role can have a profile.")
        if self._technicians.get_by_employee(employee_id) is not None:
            raise ConflictError("This employee already has a technician profile.")

        try:
            return self._technicians.create(
                employee=employee, specialization=specialization
            )
        except IntegrityError as exc:
            raise ConflictError("This employee already has a technician profile.") from exc

    def update_profile(self, technician_id, dealership_id, *, specialization=None, is_available=None):
        technician = self.get_managed(technician_id, dealership_id)

        if is_available is True:
            active = self._assignments.get_active_for_technician(technician_id)
            if active is not None:
                raise ConflictError(
                    "This technician still has an active assignment and cannot be made available."
                )

        if not technician.employee.is_active:
            raise ConflictError("This employee is inactive.")

        fields = {}
        if specialization is not None:
            fields["specialization"] = specialization
        if is_available is not None:
            fields["is_available"] = is_available
        return self._technicians.update(technician, **fields)