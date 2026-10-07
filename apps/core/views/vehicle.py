from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsOwnerOrAdmin
from apps.core.exceptions import PermissionDeniedError
from apps.core.serializers.vehicle import (
    VehicleCreateSerializer,
    VehicleSerializer,
    VehicleUpdateSerializer,
)
from apps.core.services.vehicle_service import VehicleService


class AvailableVehicleListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        dealership_id = request.query_params.get("dealership")
        vehicles = VehicleService().list_available(
            brand=request.query_params.get("brand"),
            dealership_id=int(dealership_id) if dealership_id else None,
        )
        return Response(VehicleSerializer(vehicles, many=True).data)


class VehicleInventoryCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request):
        dealership_id = request.user.dealership_id
        vehicles = VehicleService().list_inventory(
            dealership_id=dealership_id,
            search=request.query_params.get("search"),
        )
        return Response(VehicleSerializer(vehicles, many=True).data)

    def post(self, request):
        serializer = VehicleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = dict(serializer.validated_data)
        dealership_id = validated_data.pop("dealership_id")
        self._ensure_own_dealership(request, dealership_id)

        is_available = validated_data.pop("is_available", None)
        stock_quantity = validated_data.pop("stock_quantity", 1)

        vehicle = VehicleService().add_inventory(
            dealership_id=dealership_id,
            stock_quantity=stock_quantity,
            is_available=is_available,
            **validated_data,
        )

        return Response(VehicleSerializer(vehicle).data, status=status.HTTP_201_CREATED)

    def _ensure_own_dealership(self, request, dealership_id):
        if dealership_id != request.user.dealership_id:
            raise PermissionDeniedError(
                "You can only manage inventory for your own dealership."
            )


class VehicleInventoryDetailView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request, pk):
        vehicle = self._get_managed_vehicle(request, pk)
        return Response(VehicleSerializer(vehicle).data)

    def patch(self, request, pk):
        serializer = VehicleUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        self._get_managed_vehicle(request, pk)

        updated = VehicleService().update_inventory(pk, **serializer.validated_data)
        return Response(VehicleSerializer(updated).data)

    def delete(self, request, pk):
        self._get_managed_vehicle(request, pk)

        deactivated = VehicleService().deactivate_inventory(pk)
        return Response(VehicleSerializer(deactivated).data, status=status.HTTP_200_OK)

    def _get_managed_vehicle(self, request, pk):
        vehicle = VehicleService().get_inventory(pk)
        if vehicle.dealership_id != request.user.dealership_id:
            raise PermissionDeniedError(
                "You can only manage inventory for your own dealership."
            )
        return vehicle