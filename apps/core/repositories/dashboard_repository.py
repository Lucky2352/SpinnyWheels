from apps.core.models import Appointment, TestDrive, Vehicle
from apps.core.models.choices import AppointmentStatus

ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)


class DashboardRepository:
    def count_inventory(self, dealership_id):
        return Vehicle.objects.filter(dealership_id=dealership_id).count()

    def count_in_stock_inventory(self, dealership_id):
        return Vehicle.objects.filter(
            dealership_id=dealership_id,
            is_available=True,
            stock_quantity__gt=0,
        ).count()

    def count_upcoming_appointments(self, dealership_id, *, today):
        return Appointment.objects.filter(
            dealership_id=dealership_id,
            scheduled_date__gte=today,
            status__in=ACTIVE_APPOINTMENT_STATUSES,
        ).count()

    def count_upcoming_test_drives(self, dealership_id, *, today):
        return TestDrive.objects.filter(
            appointment__dealership_id=dealership_id,
            appointment__scheduled_date__gte=today,
            appointment__status__in=ACTIVE_APPOINTMENT_STATUSES,
        ).count()

    def list_recent_appointments(self, dealership_id, limit):
        return list(
            Appointment.objects.filter(dealership_id=dealership_id)
            .select_related("dealership")
            .order_by("-created_at")[:limit]
        )
