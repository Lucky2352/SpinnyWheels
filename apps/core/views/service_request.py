from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import (
    IsAuthenticated,
    IsCustomer,
    IsEmployeeOrAdmin,
    IsCustomerOrEmployeeOrAdmin,
    IsTechnician,
)
from apps.core.exceptions import DomainError, PermissionDeniedError
from apps.core.serializers.service_request import (
    AssignmentFilterSerializer,
    ServiceCompletionSerializer,
    ServiceRecordSerializer,
    ServiceRequestCreateSerializer,
    ServiceRequestFilterSerializer,
    ServiceRequestSerializer,
    TechnicianAssignmentCreateSerializer,
    TechnicianAssignmentSerializer,
)
from apps.core.services.service_request_service import ServiceRequestService


class ServiceRequestCollectionView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsCustomer()]
        return [IsAuthenticated(), IsCustomerOrEmployeeOrAdmin()]

    def post(self, request):
        serializer = ServiceRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer_vehicle_id = serializer.validated_data["customer_vehicle_id"]
        service = ServiceRequestService()
        customer_vehicle = service._customer_vehicles.get_by_id(customer_vehicle_id)

        if customer_vehicle is None:
            return Response(
                {"detail": "Customer vehicle does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if customer_vehicle.customer_id != request.user.customer_profile.pk:
            return Response(
                {"detail": "You can only create service requests for your own vehicles."},
                status=status.HTTP_403_FORBIDDEN,
            )

        service_request = service.submit(**serializer.validated_data)
        return Response(
            ServiceRequestSerializer(service_request).data, status=status.HTTP_201_CREATED
        )

    def get(self, request):
        serializer = ServiceRequestFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        service = ServiceRequestService()
        user = request.user
        status_filter = serializer.validated_data.get("status")

        if user.is_customer:
            customer_vehicles = user.customer_profile.vehicles.all()
            vehicle_ids = [cv.pk for cv in customer_vehicles]
            service_requests = service._service_requests.list_by_customer_vehicles(vehicle_ids)
            if status_filter:
                service_requests = [sr for sr in service_requests if sr.status == status_filter]
        elif user.is_technician:
            technician = _technician_profile(user)
            if technician is None:
                return Response([], status=status.HTTP_200_OK)
            service_requests = service.list_for_technician(technician.pk, status=status_filter)
        elif user.is_employee:
            service_requests = service.list_for_dealership(
                user.dealership_id, status=status_filter
            )
        else:
            return Response(
                {"detail": "Insufficient permissions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(ServiceRequestSerializer(service_requests, many=True).data)


class ServiceRequestAssignmentView(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeOrAdmin]

    def get(self, request, pk):
        service = ServiceRequestService()
        service_request = service.get_service_request(pk)
        self._ensure_own_dealership(request, service_request)

        assignments = service.list_assignments_for_service_request(pk)
        return Response(TechnicianAssignmentSerializer(assignments, many=True).data)

    def post(self, request, pk):
        serializer = TechnicianAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ServiceRequestService()
        service_request = service.get_service_request(pk)
        self._ensure_own_dealership(request, service_request)

        assignment = service.assign_technician(
            service_request_id=pk,
            dealership_id=request.user.dealership_id,
            **serializer.validated_data,
        )
        return Response(
            TechnicianAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED
        )

    def _ensure_own_dealership(self, request, service_request):
        if service_request.dealership_id != request.user.dealership_id:
            raise PermissionDeniedError(
                "You can only manage service requests for your own dealership."
            )


class TechnicianAssignmentCollectionView(APIView):
    permission_classes = [IsAuthenticated, IsTechnician]

    def get(self, request):
        serializer = AssignmentFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        technician = _technician_profile(request.user)
        if technician is None:
            return Response([], status=status.HTTP_200_OK)

        assignments = ServiceRequestService().list_assignments_for_technician(
            technician.pk, status=serializer.validated_data.get("status")
        )
        return Response(TechnicianAssignmentSerializer(assignments, many=True).data)


class TechnicianAssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated, IsEmployeeOrAdmin]

    def post(self, request, pk):
        service = ServiceRequestService()
        technician_id, dealership_id = _assignment_scope(request)
        action = request.data.get("action")

        if action == "start":
            assignment = service.start_assignment(
                pk, technician_id=technician_id, dealership_id=dealership_id
            )
            return Response(TechnicianAssignmentSerializer(assignment).data)

        if action != "complete":
            raise DomainError("Choose either start or complete for this assignment.")

        serializer = ServiceCompletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service_record = service.complete_assignment(
            pk,
            technician_id=technician_id,
            dealership_id=dealership_id,
            **serializer.validated_data,
        )
        return Response(ServiceRecordSerializer(service_record).data)


def _assignment_scope(request):
    if request.user.is_technician:
        technician = _technician_profile(request.user)
        if technician is None:
            raise PermissionDeniedError(
                "This account has no technician profile to work with."
            )
        return technician.pk, technician.employee.dealership_id
    return None, request.user.dealership_id


def _technician_profile(user):
    if not user.employee_profile:
        return None
    return getattr(user.employee_profile, "technician_profile", None)