from apps.core.models import Employee


class EmployeeRepository:
    def get_by_id(self, employee_id):
        return (
            Employee.objects.select_related("dealership", "technician_profile")
            .filter(pk=employee_id)
            .first()
        )

    def get_by_email(self, email):
        return Employee.objects.filter(email__iexact=email).first()

    def get_by_external_user_id(self, external_user_id):
        return Employee.objects.select_related("dealership").filter(
            external_user_id=external_user_id
        ).first()

    def get_owner_by_dealership(self, dealership_id):
        return Employee.objects.filter(dealership_id=dealership_id, role="OWNER").first()

    def list_by_dealership(self, dealership_id=None):
        queryset = Employee.objects.select_related("dealership", "technician_profile")
        if dealership_id:
            queryset = queryset.filter(dealership_id=dealership_id)
        return list(queryset.order_by("last_name", "first_name"))

    def create(self, **fields):
        return Employee.objects.create(**fields)

    def update(self, employee, **fields):
        return employee.apply_changes(**fields)