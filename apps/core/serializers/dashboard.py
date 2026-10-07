from rest_framework import serializers

from apps.core.serializers.appointment import AppointmentSerializer


class DealershipDashboardSerializer(serializers.Serializer):
    dealership_id = serializers.IntegerField(min_value=1)
    metrics = serializers.DictField(child=serializers.IntegerField(min_value=0))
    recent_appointments = AppointmentSerializer(many=True)
