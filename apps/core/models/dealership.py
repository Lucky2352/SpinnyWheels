from django.db import models

from apps.core.models.base import TimestampedModel
from apps.core.models.choices import EmployeeRole, Specialization


class Dealership(TimestampedModel):
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Employee(TimestampedModel):
    dealership = models.ForeignKey(
        Dealership,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    external_user_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(
        max_length=20,
        choices=EmployeeRole.choices,
        default=EmployeeRole.EMPLOYEE,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("last_name", "first_name")
        constraints = [
            models.UniqueConstraint(
                fields=("dealership", "email"),
                name="uniq_employee_email_per_dealership",
            ),
            models.UniqueConstraint(
                fields=("dealership",),
                condition=models.Q(role="OWNER"),
                name="uniq_owner_per_dealership",
            ),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class TechnicianProfile(TimestampedModel):
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="technician_profile",
    )
    specialization = models.CharField(
        max_length=20,
        choices=Specialization.choices,
        default=Specialization.GENERAL,
    )
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ("employee__last_name",)
        verbose_name = "technician profile"

    def __str__(self):
        return str(self.employee)
