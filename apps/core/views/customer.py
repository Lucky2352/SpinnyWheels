from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsCustomer
from apps.core.serializers.customer import (
    CustomerVehicleCreateSerializer,
    CustomerVehicleSerializer,
)
from apps.core.services.customer_service import CustomerService


class CustomerVehicleCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request):
        vehicles = CustomerService().list_vehicles(request.user.customer_profile.pk)
        return Response(CustomerVehicleSerializer(vehicles, many=True).data)

    def post(self, request):
        serializer = CustomerVehicleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer_vehicle = CustomerService().register_sale(
            customer_id=request.user.customer_profile.pk,
            **serializer.validated_data,
        )
        return Response(
            CustomerVehicleSerializer(customer_vehicle).data,
            status=status.HTTP_201_CREATED,
        )
