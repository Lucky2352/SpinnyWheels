from apps.core.models import TechnicianProfile


class TechnicianRepository:
    def get_by_id(self, technician_id):
        return (
            TechnicianProfile.objects.select_related("employee")
            .filter(pk=technician_id)
            .first()
        )

    def get_by_employee(self, employee_id):
        return (
            TechnicianProfile.objects.select_related("employee")
            .filter(employee_id=employee_id)
            .first()
        )

    def list_available(self, *, specialization=None):
        queryset = (
            TechnicianProfile.objects.select_related("employee")
            .filter(is_available=True)
            .order_by("employee__last_name")
        )
        if specialization:
            queryset = queryset.filter(specialization=specialization)
        return list(queryset)

    def list_by_dealership(self, dealership_id, *, specialization=None):
        queryset = TechnicianProfile.objects.select_related(
            "employee", "employee__dealership"
        ).filter(employee__dealership_id=dealership_id)
        if specialization:
            queryset = queryset.filter(specialization=specialization)
        return list(queryset.order_by("employee__last_name", "employee__first_name"))

    def create(self, **fields):
        return TechnicianProfile.objects.create(**fields)

    def update(self, technician, **fields):
        return technician.apply_changes(**fields)
