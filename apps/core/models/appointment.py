from datetime import datetime

from django.db import models

from apps.core.models.base import TimestampedModel
from apps.core.models.choices import AppointmentStatus, AppointmentType
from apps.core.models.customer import CustomerProfile
from apps.core.models.dealership import Dealership
from apps.core.models.vehicle import Vehicle


class Appointment(TimestampedModel):
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    dealership = models.ForeignKey(
        Dealership,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    appointment_type = models.CharField(max_length=20, choices=AppointmentType.choices)
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("scheduled_date", "scheduled_time")
        indexes = [
            models.Index(fields=("status", "scheduled_date"), name="appointment_status_date_idx"),
            models.Index(fields=("dealership", "scheduled_date"), name="appointment_dealer_date_idx"),
        ]

    @property
    def scheduled_for(self):
        return datetime.combine(self.scheduled_date, self.scheduled_time)

    def __str__(self):
        return f"{self.get_appointment_type_display()} on {self.scheduled_date}"


class TestDrive(TimestampedModel):
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="test_drive",
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="test_drives",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "test drives"

    def __str__(self):
        return f"Test drive of {self.vehicle} on {self.appointment.scheduled_date}"
