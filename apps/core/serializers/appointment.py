from rest_framework import serializers

from apps.core.models import Appointment, TestDrive
from apps.core.models.choices import AppointmentStatus
from apps.core.serializers.vehicle import VehicleSerializer


class TestDriveRequestSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(min_value=1, required=False)
    dealership_id = serializers.IntegerField(min_value=1)
    vehicle_id = serializers.IntegerField(min_value=1)
    scheduled_date = serializers.DateField()
    scheduled_time = serializers.TimeField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class AppointmentFilterSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=AppointmentStatus.choices, required=False)
    scheduled_date = serializers.DateField(required=False)


class AppointmentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AppointmentStatus.choices)


class AppointmentSerializer(serializers.ModelSerializer):
    dealership_name = serializers.SerializerMethodField()
    appointment_type_display = serializers.CharField(
        source="get_appointment_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "id",
            "customer",
            "dealership",
            "dealership_name",
            "appointment_type",
            "appointment_type_display",
            "scheduled_date",
            "scheduled_time",
            "status",
            "status_display",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_dealership_name(self, obj):
        return obj.dealership.name if obj.dealership else None


class TestDriveSerializer(serializers.ModelSerializer):
    appointment = AppointmentSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)

    class Meta:
        model = TestDrive
        fields = ("id", "appointment", "vehicle", "created_at", "updated_at")
        read_only_fields = fields
