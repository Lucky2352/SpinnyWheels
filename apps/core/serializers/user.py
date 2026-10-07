from rest_framework import serializers

from apps.core.authentication.supabase import SupabaseUser


class CurrentUserSerializer(serializers.Serializer):
    email = serializers.EmailField(read_only=True)
    role = serializers.CharField(read_only=True)
    is_customer = serializers.BooleanField(read_only=True)
    is_employee = serializers.BooleanField(read_only=True)
    is_technician = serializers.BooleanField(read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    is_owner = serializers.BooleanField(read_only=True)
    can_manage_inventory = serializers.BooleanField(source="is_owner_or_admin", read_only=True)
    dealership_id = serializers.IntegerField(read_only=True)
    dealership_name = serializers.CharField(
        source="employee_profile.dealership.name", read_only=True, default=""
    )

    def to_representation(self, instance: SupabaseUser):
        representation = super().to_representation(instance)
        if instance.is_customer:
            representation["customer_id"] = (
                instance.customer_profile.pk if instance.customer_profile else None
            )
        return representation