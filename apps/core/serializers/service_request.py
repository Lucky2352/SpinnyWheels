from decimal import Decimal

from rest_framework import serializers

from apps.core.models import ServiceRecord, ServiceRequest, TechnicianAssignment
from apps.core.models.choices import (
    AssignmentStatus,
    Priority,
    ServiceStatus,
    ServiceType,
)
from apps.core.serializers.customer import CustomerVehicleSerializer


class ServiceRequestCreateSerializer(serializers.Serializer):
    customer_vehicle_id = serializers.IntegerField(min_value=1)
    appointment_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    service_type = serializers.ChoiceField(choices=ServiceType.choices)
    problem_description = serializers.CharField(max_length=4000)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False, default=Priority.MEDIUM)
    estimated_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )


class ServiceRequestFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ServiceStatus.choices, required=False)


class ServiceRequestSerializer(serializers.ModelSerializer):
    customer_vehicle_detail = CustomerVehicleSerializer(source="customer_vehicle", read_only=True)
    dealership_name = serializers.SerializerMethodField()
    service_type_display = serializers.CharField(source="get_service_type_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ServiceRequest
        fields = (
            "id",
            "appointment",
            "customer_vehicle",
            "customer_vehicle_detail",
            "dealership",
            "dealership_name",
            "service_type",
            "service_type_display",
            "problem_description",
            "priority",
            "priority_display",
            "status",
            "status_display",
            "estimated_cost",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_dealership_name(self, obj):
        return obj.dealership.name if obj.dealership else None


class TechnicianAssignmentCreateSerializer(serializers.Serializer):
    technician_id = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class ServiceCompletionSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=4000)
    parts_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), required=False
    )
    labor_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), required=False
    )
    service_date = serializers.DateField(required=False)


class AssignmentFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AssignmentStatus.choices, required=False)


class TechnicianAssignmentSerializer(serializers.ModelSerializer):
    technician_name = serializers.CharField(source="technician.employee.full_name", read_only=True)
    technician_specialization = serializers.CharField(
        source="technician.specialization", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_request_detail = serializers.SerializerMethodField()

    class Meta:
        model = TechnicianAssignment
        fields = (
            "id",
            "service_request",
            "service_request_detail",
            "technician",
            "technician_name",
            "technician_specialization",
            "status",
            "status_display",
            "notes",
            "assigned_at",
            "started_at",
            "completed_at",
        )
        read_only_fields = fields

    def get_service_request_detail(self, assignment):
        service_request = assignment.service_request
        vehicle = service_request.customer_vehicle
        return {
            "id": service_request.pk,
            "service_type": service_request.service_type,
            "service_type_display": service_request.get_service_type_display(),
            "problem_description": service_request.problem_description,
            "status": service_request.status,
            "status_display": service_request.get_status_display(),
            "priority": service_request.priority,
            "registration_number": vehicle.registration_number,
            "customer_name": vehicle.customer.full_name,
        }


class ServiceRecordSerializer(serializers.ModelSerializer):
    technician_name = serializers.CharField(source="technician.employee.full_name", read_only=True)
    registration_number = serializers.CharField(
        source="customer_vehicle.registration_number", read_only=True
    )

    class Meta:
        model = ServiceRecord
        fields = (
            "id",
            "service_request",
            "customer_vehicle",
            "registration_number",
            "technician",
            "technician_name",
            "description",
            "parts_cost",
            "labor_cost",
            "total_cost",
            "service_date",
            "created_at",
        )
        read_only_fields = fields
