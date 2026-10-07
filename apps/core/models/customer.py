from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models.base import TimestampedModel
from apps.core.models.vehicle import Vehicle


class CustomerProfile(TimestampedModel):
    external_user_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ("last_name", "first_name")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class CustomerVehicle(TimestampedModel):
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="vehicles",
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="owned_vehicles",
    )
    registration_number = models.CharField(max_length=32, unique=True)
    purchase_date = models.DateField()
    current_mileage = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ("-purchase_date",)

    def __str__(self):
        return f"{self.registration_number} - {self.vehicle}"
