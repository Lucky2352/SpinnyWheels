from apps.core.models import ServiceRecord, ServiceRequest, TechnicianAssignment
from apps.core.models.servicing import ACTIVE_ASSIGNMENT_STATUSES


class ServiceRequestRepository:
    def get_by_id(self, service_request_id):
        return (
            ServiceRequest.objects.select_related("customer_vehicle__vehicle", "appointment")
            .filter(pk=service_request_id)
            .first()
        )

    def list_by_status(self, status=None):
        queryset = ServiceRequest.objects.select_related(
            "customer_vehicle__vehicle", "appointment"
        ).all()
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-created_at"))

    def list_by_dealership(self, dealership_id, *, status=None):
        queryset = ServiceRequest.objects.select_related(
            "customer_vehicle__vehicle", "appointment", "dealership"
        ).filter(dealership_id=dealership_id)
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-created_at"))

    def list_assigned_to_technician(self, technician_id, *, status=None):
        queryset = (
            ServiceRequest.objects.select_related("customer_vehicle__vehicle", "appointment")
            .filter(assignments__technician_id=technician_id)
            .distinct()
        )
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-created_at"))

    def list_by_customer_vehicle(self, customer_vehicle_id):
        return list(
            ServiceRequest.objects.select_related("customer_vehicle__vehicle")
            .filter(customer_vehicle_id=customer_vehicle_id)
            .order_by("-created_at")
        )

    def list_by_customer_vehicles(self, customer_vehicle_ids):
        if not customer_vehicle_ids:
            return []
        return list(
            ServiceRequest.objects.select_related("customer_vehicle__vehicle")
            .filter(customer_vehicle_id__in=customer_vehicle_ids)
            .order_by("-created_at")
        )

    def create(self, **fields):
        return ServiceRequest.objects.create(**fields)

    def update(self, service_request, **fields):
        return service_request.apply_changes(**fields)


class TechnicianAssignmentRepository:
    def get_by_id(self, assignment_id):
        return (
            TechnicianAssignment.objects.select_related(
                "technician__employee",
                "service_request__customer_vehicle",
                "service_request__dealership",
            )
            .filter(pk=assignment_id)
            .first()
        )

    def list_for_technician(self, technician_id, *, status=None):
        queryset = TechnicianAssignment.objects.select_related(
            "technician__employee", "service_request__customer_vehicle__customer"
        ).filter(technician_id=technician_id)
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-assigned_at"))

    def list_for_service_request(self, service_request_id):
        return list(
            TechnicianAssignment.objects.select_related(
                "technician__employee", "service_request__customer_vehicle__customer"
            )
            .filter(service_request_id=service_request_id)
            .order_by("-assigned_at")
        )

    def get_active_for_technician(self, technician_id):
        return (
            TechnicianAssignment.objects.filter(
                technician_id=technician_id, status__in=ACTIVE_ASSIGNMENT_STATUSES
            )
            .first()
        )

    def create(self, **fields):
        return TechnicianAssignment.objects.create(**fields)

    def update(self, assignment, **fields):
        return assignment.apply_changes(**fields)


class ServiceRecordRepository:
    def get_by_id(self, service_record_id):
        return (
            ServiceRecord.objects.select_related(
                "customer_vehicle", "technician__employee", "service_request"
            )
            .filter(pk=service_record_id)
            .first()
        )

    def list_by_customer_vehicle(self, customer_vehicle_id):
        return list(
            ServiceRecord.objects.select_related("technician__employee")
            .filter(customer_vehicle_id=customer_vehicle_id)
            .order_by("-service_date")
        )

    def create(self, **fields):
        return ServiceRecord.objects.create(**fields)

    def update(self, service_record, **fields):
        return service_record.apply_changes(**fields)
