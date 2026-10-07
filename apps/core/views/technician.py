from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsOwnerOrAdmin
from apps.core.serializers.technician import (
    TechnicianCreateSerializer,
    TechnicianSerializer,
    TechnicianUpdateSerializer,
)
from apps.core.services.technician_service import TechnicianService


class TechnicianCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request):
        technicians = TechnicianService().list_technicians(request.user.dealership_id)
        return Response(TechnicianSerializer(technicians, many=True).data)

    def post(self, request):
        serializer = TechnicianCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        technician = TechnicianService().create_profile(
            dealership_id=request.user.dealership_id, **serializer.validated_data
        )
        return Response(TechnicianSerializer(technician).data, status=status.HTTP_201_CREATED)


class TechnicianDetailView(APIView):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request, pk):
        technician = TechnicianService().get_managed(pk, request.user.dealership_id)
        return Response(TechnicianSerializer(technician).data)

    def patch(self, request, pk):
        serializer = TechnicianUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        technician = TechnicianService().update_profile(
            pk, request.user.dealership_id, **serializer.validated_data
        )
        return Response(TechnicianSerializer(technician).data)