from django.db import IntegrityError, transaction

from apps.core.exceptions import (
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from apps.core.models import TechnicianProfile
from apps.core.models.choices import EmployeeRole, Specialization
from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.repositories.employee_repository import EmployeeRepository

MANAGEABLE_ROLES = (EmployeeRole.ADMIN, EmployeeRole.EMPLOYEE, EmployeeRole.TECHNICIAN)


class EmployeeService:
    def __init__(self, employees=None, dealerships=None):
        self._employees = employees or EmployeeRepository()
        self._dealerships = dealerships or DealershipRepository()

    def get_owner(self, dealership_id):
        owner = self._employees.get_owner_by_dealership(dealership_id)
        if owner is None:
            raise ResourceNotFoundError("This dealership does not have an owner yet.")
        return owner

    @transaction.atomic
    def create_owner(
        self,
        *,
        dealership_id,
        external_user_id,
        first_name,
        last_name,
        email,
        phone="",
    ):
        dealership = self._dealerships.get_by_id(dealership_id)
        if dealership is None:
            raise ResourceNotFoundError("Dealership does not exist.")

        if self._employees.get_owner_by_dealership(dealership_id) is not None:
            raise ConflictError("This dealership already has an owner.")

        if self._employees.get_by_email(email) is not None:
            raise ConflictError("An employee with this email already exists.")

        try:
            return self._employees.create(
                dealership=dealership,
                external_user_id=external_user_id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                role=EmployeeRole.OWNER,
            )
        except IntegrityError as exc:
            raise ConflictError("This dealership already has an owner.") from exc

    def list_staff(self, dealership_id):
        return self._employees.list_by_dealership(dealership_id)

    def get_managed(self, employee_id, dealership_id):
        employee = self._employees.get_by_id(employee_id)
        if employee is None or employee.dealership_id != dealership_id:
            raise PermissionDeniedError(
                "You can only manage employees of your own dealership."
            )
        return employee

    @transaction.atomic
    def create_staff(
        self,
        *,
        dealership_id,
        first_name,
        last_name,
        email,
        role,
        phone="",
    ):
        if role not in MANAGEABLE_ROLES:
            raise PermissionDeniedError("This role cannot be assigned through staff management.")

        dealership = self._dealerships.get_by_id(dealership_id)
        if dealership is None:
            raise ResourceNotFoundError("Dealership does not exist.")

        existing = self._employees.get_by_email(email)
        if existing is not None and existing.dealership_id == dealership_id:
            raise ConflictError("An employee with this email already exists.")

        try:
            employee = self._employees.create(
                dealership=dealership,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                role=role,
            )
        except IntegrityError as exc:
            raise ConflictError("An employee with this email already exists.") from exc

        if role == EmployeeRole.TECHNICIAN:
            TechnicianProfile.objects.create(
                employee=employee, specialization=Specialization.GENERAL
            )

        return employee

    def update_staff(self, employee_id, dealership_id, *, role=None, **fields):
        employee = self.get_managed(employee_id, dealership_id)

        if role is not None and role not in MANAGEABLE_ROLES:
            raise PermissionDeniedError("This role cannot be assigned through staff management.")

        if employee.role == EmployeeRole.OWNER:
            raise PermissionDeniedError("The dealership owner cannot be edited here.")

        email = fields.get("email")
        if email and email.lower() != employee.email.lower():
            existing = self._employees.get_by_email(email)
            if existing is not None and existing.dealership_id == dealership_id:
                raise ConflictError("An employee with this email already exists.")

        try:
            if role is not None:
                return self._employees.update(employee, role=role, **fields)
            return self._employees.update(employee, **fields)
        except IntegrityError as exc:
            raise ConflictError("An employee with this email already exists.") from exc

    @transaction.atomic
    def deactivate_staff(self, employee_id, dealership_id):
        employee = self.get_managed(employee_id, dealership_id)

        if employee.role == EmployeeRole.OWNER:
            raise PermissionDeniedError("The dealership owner cannot be deactivated.")

        if not employee.is_active:
            raise ConflictError("This employee is already inactive.")

        technician = getattr(employee, "technician_profile", None)
        if technician is not None:
            technician.is_available = False
            technician.save(update_fields=["is_available", "updated_at"])

        return self._employees.update(employee, is_active=False)