from datetime import date
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models.appointment import Appointment
from apps.core.models.base import TimestampedModel
from apps.core.models.choices import (
    AssignmentStatus,
    InvoiceStatus,
    Priority,
    ServiceStatus,
    ServiceType,
)
from apps.core.models.customer import CustomerProfile, CustomerVehicle
from apps.core.models.dealership import Dealership, TechnicianProfile

ACTIVE_ASSIGNMENT_STATUSES = (AssignmentStatus.ASSIGNED, AssignmentStatus.IN_PROGRESS)


class ServiceRequest(TimestampedModel):
    dealership = models.ForeignKey(
        Dealership,
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="service_request",
        null=True,
        blank=True,
    )
    customer_vehicle = models.ForeignKey(
        CustomerVehicle,
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    service_type = models.CharField(max_length=20, choices=ServiceType.choices)
    problem_description = models.TextField()
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=ServiceStatus.choices,
        default=ServiceStatus.PENDING,
    )
    estimated_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "priority"), name="service_req_status_prio_idx"),
            models.Index(
                fields=("dealership", "status"), name="service_req_dealer_status_idx"
            ),
        ]

    def __str__(self):
        return f"{self.get_service_type_display()} - {self.customer_vehicle.registration_number}"


class TechnicianAssignment(TimestampedModel):
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    technician = models.ForeignKey(
        TechnicianProfile,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
    )

    class Meta:
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("technician",),
                condition=Q(status__in=ACTIVE_ASSIGNMENT_STATUSES),
                name="uniq_active_assignment_per_technician",
            ),
        ]

    def __str__(self):
        return f"{self.technician} on {self.service_request_id}"


class ServiceRecord(TimestampedModel):
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.PROTECT,
        related_name="service_records",
    )
    customer_vehicle = models.ForeignKey(
        CustomerVehicle,
        on_delete=models.PROTECT,
        related_name="service_records",
    )
    technician = models.ForeignKey(
        TechnicianProfile,
        on_delete=models.PROTECT,
        related_name="service_records",
    )
    description = models.TextField()
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    labor_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    service_date = models.DateField(default=date.today)

    class Meta:
        ordering = ("-service_date", "-created_at")
        indexes = [
            models.Index(
                fields=("customer_vehicle", "service_date"),
                name="service_record_veh_date_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(parts_cost__gte=0) & Q(labor_cost__gte=0) & Q(total_cost__gte=0),
                name="service_record_costs_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.customer_vehicle.registration_number} on {self.service_date}"


class Invoice(TimestampedModel):
    service_record = models.ForeignKey(
        ServiceRecord,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    invoice_number = models.CharField(max_length=32, unique=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
    )
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("service_record",),
                name="uniq_invoice_per_service_record",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0) & Q(tax__gte=0) & Q(total=F("subtotal") + F("tax")),
                name="invoice_amounts_consistent",
            ),
        ]

    def __str__(self):
        return self.invoice_number


class Feedback(TimestampedModel):
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    service_record = models.ForeignKey(
        ServiceRecord,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5),
                name="feedback_rating_within_range",
            ),
            models.UniqueConstraint(
                fields=("customer", "service_record"),
                name="uniq_feedback_per_service_record",
            ),
        ]

    def __str__(self):
        return f"{self.rating} stars by {self.customer_id}"
