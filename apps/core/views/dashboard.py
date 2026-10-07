from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.authentication.permissions import IsAuthenticated, IsEmployee
from apps.core.exceptions import DomainError, PermissionDeniedError
from apps.core.serializers.dashboard import DealershipDashboardSerializer
from apps.core.services.dashboard_service import DashboardService


class DealershipDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsEmployee]

    def get(self, request):
        try:
            summary = DashboardService().dealership_summary(request.user.dealership_id)
        except DomainError as exc:
            raise PermissionDeniedError(str(exc))

        return Response(DealershipDashboardSerializer(summary).data)
