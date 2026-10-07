from datetime import date

from apps.core.exceptions import DomainError
from apps.core.repositories.dashboard_repository import DashboardRepository

RECENT_ACTIVITY_LIMIT = 8


class DashboardService:
    def __init__(self, dashboard=None):
        self._dashboard = dashboard or DashboardRepository()

    def dealership_summary(self, dealership_id):
        if not dealership_id:
            raise DomainError("This account is not linked to a dealership.")

        today = date.today()

        return {
            "dealership_id": dealership_id,
            "metrics": {
                "showroom_vehicles": self._dashboard.count_inventory(dealership_id),
                "in_stock_vehicles": self._dashboard.count_in_stock_inventory(dealership_id),
                "upcoming_appointments": self._dashboard.count_upcoming_appointments(
                    dealership_id, today=today
                ),
                "upcoming_test_drives": self._dashboard.count_upcoming_test_drives(
                    dealership_id, today=today
                ),
            },
            "recent_appointments": self._dashboard.list_recent_appointments(
                dealership_id, RECENT_ACTIVITY_LIMIT
            ),
        }
