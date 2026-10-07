from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsOwnerOrAdmin
from apps.core.serializers.employee import (
    EmployeeCreateSerializer,
    EmployeeSerializer,
    EmployeeUpdateSerializer,
)
from apps.core.services.employee_service import EmployeeService


class EmployeeCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request):
        employees = EmployeeService().list_staff(request.user.dealership_id)
        return Response(EmployeeSerializer(employees, many=True).data)

    def post(self, request):
        serializer = EmployeeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        employee = EmployeeService().create_staff(
            dealership_id=request.user.dealership_id, **serializer.validated_data
        )
        return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)


class EmployeeDetailView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request, pk):
        employee = EmployeeService().get_managed(pk, request.user.dealership_id)
        return Response(EmployeeSerializer(employee).data)

    def patch(self, request, pk):
        serializer = EmployeeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        employee = EmployeeService().update_staff(
            pk, request.user.dealership_id, **serializer.validated_data
        )
        return Response(EmployeeSerializer(employee).data)

    def delete(self, request, pk):
        employee = EmployeeService().deactivate_staff(pk, request.user.dealership_id)
        return Response(EmployeeSerializer(employee).data)