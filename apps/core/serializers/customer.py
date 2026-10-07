from rest_framework import serializers

from apps.core.models import CustomerVehicle
from apps.core.serializers.vehicle import VehicleSerializer


class CustomerVehicleCreateSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField(min_value=1)
    registration_number = serializers.CharField(max_length=32)
    purchase_date = serializers.DateField()
    current_mileage = serializers.IntegerField(min_value=0, required=False, default=0)


class CustomerVehicleSerializer(serializers.ModelSerializer):
    vehicle = VehicleSerializer(read_only=True)

    class Meta:
        model = CustomerVehicle
        fields = (
            "id",
            "registration_number",
            "purchase_date",
            "current_mileage",
            "vehicle",
        )
        read_only_fields = fields