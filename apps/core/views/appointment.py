from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import (
    IsAuthenticated,
    IsCustomer,
    IsStaff,
)
from apps.core.authentication.supabase import SupabaseUser
from apps.core.exceptions import DomainError
from apps.core.serializers.appointment import (
    AppointmentFilterSerializer,
    AppointmentSerializer,
    AppointmentStatusUpdateSerializer,
    TestDriveRequestSerializer,
    TestDriveSerializer,
)
from apps.core.services.appointment_service import AppointmentService


class TestDriveCreateView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def post(self, request):
        serializer = TestDriveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer_id = request.user.customer_profile.pk
        validated_data = serializer.validated_data
        validated_data["customer_id"] = customer_id

        test_drive = AppointmentService().schedule_test_drive(**validated_data)
        return Response(TestDriveSerializer(test_drive).data, status=status.HTTP_201_CREATED)


class AppointmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        return [IsAuthenticated()]

    def get(self, request):
        serializer = AppointmentFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data

        service = AppointmentService()

        user = request.user
        if user.is_customer:
            if "customer_id" in filters and filters["customer_id"] != user.customer_profile.pk:
                return Response(
                    {"detail": "You can only view your own appointments."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            appointments = service.list_for_customer(
                user.customer_profile.pk, status=filters.get("status")
            )
        elif user.is_employee:
            appointments = service.list_for_dealership(
                user.dealership_id,
                status=filters.get("status"),
                scheduled_date=filters.get("scheduled_date"),
            )
        else:
            raise DomainError("Invalid user role for appointment access.")

        return Response(AppointmentSerializer(appointments, many=True).data)


class AppointmentStatusView(APIView):
    permission_classes = [IsAuthenticated, IsStaff]

    def patch(self, request, pk):
        serializer = AppointmentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        appointment = AppointmentService().update_status(
            pk, request.user.dealership_id, **serializer.validated_data
        )
        return Response(AppointmentSerializer(appointment).data)