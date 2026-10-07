from decimal import Decimal

from rest_framework import serializers

from apps.core.models import Vehicle
from apps.core.models.choices import FuelType, TransmissionType
from apps.core.models.vehicle import MAX_MANUFACTURING_YEAR


class VehicleCreateSerializer(serializers.Serializer):
    dealership_id = serializers.IntegerField(min_value=1)
    brand = serializers.CharField(max_length=100)
    model = serializers.CharField(max_length=100)
    variant = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    manufacturing_year = serializers.IntegerField(min_value=1900, max_value=MAX_MANUFACTURING_YEAR)
    fuel_type = serializers.ChoiceField(choices=FuelType.choices)
    transmission = serializers.ChoiceField(choices=TransmissionType.choices)
    seating_capacity = serializers.IntegerField(min_value=1, max_value=15, required=False, default=5)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00")
    )
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)
    stock_quantity = serializers.IntegerField(min_value=0, required=False, default=1)
    is_available = serializers.BooleanField(required=False, default=True)


class VehicleUpdateSerializer(serializers.Serializer):
    variant = serializers.CharField(max_length=100, required=False, allow_blank=True)
    manufacturing_year = serializers.IntegerField(
        min_value=1900, max_value=MAX_MANUFACTURING_YEAR, required=False
    )
    fuel_type = serializers.ChoiceField(choices=FuelType.choices, required=False)
    transmission = serializers.ChoiceField(choices=TransmissionType.choices, required=False)
    seating_capacity = serializers.IntegerField(min_value=1, max_value=15, required=False)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), required=False
    )
    description = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    stock_quantity = serializers.IntegerField(min_value=0, required=False)
    is_available = serializers.BooleanField(required=False)


class VehicleSerializer(serializers.ModelSerializer):
    dealership = serializers.PrimaryKeyRelatedField(read_only=True)
    dealership_name = serializers.SerializerMethodField()
    is_in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vehicle
        fields = (
            "id",
            "dealership",
            "dealership_name",
            "brand",
            "model",
            "variant",
            "manufacturing_year",
            "fuel_type",
            "transmission",
            "seating_capacity",
            "price",
            "description",
            "stock_quantity",
            "is_available",
            "is_in_stock",
        )
        read_only_fields = fields

    def get_dealership_name(self, obj):
        return obj.dealership.name if obj.dealership else None
