from datetime import date
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models.base import TimestampedModel
from apps.core.models.choices import FuelType, TransmissionType
from apps.core.models.dealership import Dealership

MAX_MANUFACTURING_YEAR = date.today().year + 1


class Vehicle(TimestampedModel):
    dealership = models.ForeignKey(
        Dealership,
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    variant = models.CharField(max_length=100, blank=True)
    manufacturing_year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1900), MaxValueValidator(MAX_MANUFACTURING_YEAR)],
    )
    fuel_type = models.CharField(max_length=20, choices=FuelType.choices)
    transmission = models.CharField(max_length=20, choices=TransmissionType.choices)
    seating_capacity = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    description = models.TextField(blank=True)
    stock_quantity = models.PositiveIntegerField(default=1)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ("brand", "model", "variant")
        indexes = [
            models.Index(fields=("dealership", "brand"), name="vehicle_dealership_brand_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("dealership", "brand", "model", "variant", "manufacturing_year"),
                name="uniq_vehicle_inventory",
            ),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="vehicle_price_non_negative"),
        ]

    @property
    def is_in_stock(self):
        return self.is_available and self.stock_quantity > 0

    def __str__(self):
        return f"{self.brand} {self.model} {self.variant}".strip()
