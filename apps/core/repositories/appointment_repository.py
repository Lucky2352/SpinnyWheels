from apps.core.models import Appointment, TestDrive


class AppointmentRepository:
    def get_by_id(self, appointment_id):
        return (
            Appointment.objects.select_related("customer", "dealership")
            .filter(pk=appointment_id)
            .first()
        )

    def list_by_customer(self, customer_id, *, status=None):
        queryset = Appointment.objects.select_related("dealership").filter(
            customer_id=customer_id
        )
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-scheduled_date", "-scheduled_time"))

    def list_by_status(self, status=None, *, scheduled_date=None):
        queryset = Appointment.objects.select_related("customer", "dealership").all()
        if status:
            queryset = queryset.filter(status=status)
        if scheduled_date:
            queryset = queryset.filter(scheduled_date=scheduled_date)
        return list(queryset.order_by("scheduled_date", "scheduled_time"))

    def list_by_dealership(self, dealership_id, *, status=None, scheduled_date=None):
        queryset = Appointment.objects.select_related(
            "customer", "dealership"
        ).filter(dealership_id=dealership_id)
        if status:
            queryset = queryset.filter(status=status)
        if scheduled_date:
            queryset = queryset.filter(scheduled_date=scheduled_date)
        return list(queryset.order_by("scheduled_date", "scheduled_time"))

    def create(self, **fields):
        return Appointment.objects.create(**fields)

    def update(self, appointment, **fields):
        return appointment.apply_changes(**fields)


class TestDriveRepository:
    def get_by_id(self, test_drive_id):
        return (
            TestDrive.objects.select_related("appointment", "vehicle__dealership")
            .filter(pk=test_drive_id)
            .first()
        )

    def get_by_appointment(self, appointment_id):
        return (
            TestDrive.objects.select_related("appointment", "vehicle__dealership")
            .filter(appointment_id=appointment_id)
            .first()
        )

    def create(self, **fields):
        return TestDrive.objects.create(**fields)
