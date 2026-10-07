from rest_framework import serializers

from apps.core.models import Employee
from apps.core.models.choices import EmployeeRole

ASSIGNABLE_ROLES = [
    choice for choice in EmployeeRole.choices if choice[0] != EmployeeRole.OWNER
]


class EmployeeCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=ASSIGNABLE_ROLES)


class EmployeeUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=ASSIGNABLE_ROLES, required=False)
    is_active = serializers.BooleanField(required=False)


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    is_technician = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = (
            "id",
            "full_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "role_display",
            "is_active",
            "is_technician",
            "external_user_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_is_technician(self, employee):
        return hasattr(employee, "technician_profile")