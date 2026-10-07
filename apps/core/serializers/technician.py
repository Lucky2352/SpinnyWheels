from rest_framework import serializers

from apps.core.models import TechnicianProfile
from apps.core.models.choices import Specialization


class TechnicianCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(min_value=1)
    specialization = serializers.ChoiceField(
        choices=Specialization.choices, required=False, default=Specialization.GENERAL
    )


class TechnicianUpdateSerializer(serializers.Serializer):
    specialization = serializers.ChoiceField(choices=Specialization.choices, required=False)
    is_available = serializers.BooleanField(required=False)


class TechnicianSerializer(serializers.ModelSerializer):
    employee_id = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()
    employee_email = serializers.SerializerMethodField()
    employee_active = serializers.SerializerMethodField()
    specialization_display = serializers.CharField(
        source="get_specialization_display", read_only=True
    )

    class Meta:
        model = TechnicianProfile
        fields = (
            "id",
            "employee_id",
            "employee_name",
            "employee_email",
            "employee_active",
            "specialization",
            "specialization_display",
            "is_available",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_employee_id(self, obj):
        return obj.employee.id if obj.employee else None

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None

    def get_employee_email(self, obj):
        return obj.employee.email if obj.employee else None

    def get_employee_active(self, obj):
        return obj.employee.is_active if obj.employee else None