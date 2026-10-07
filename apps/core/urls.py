from django.urls import path

from apps.core.views.appointment import (
    AppointmentListView,
    AppointmentStatusView,
    TestDriveCreateView,
)
from apps.core.views.customer import CustomerVehicleCollectionView
from apps.core.views.dashboard import DealershipDashboardView
from apps.core.views.employee import EmployeeCollectionView, EmployeeDetailView
from apps.core.views.health import HealthView
from apps.core.views.service_request import (
    ServiceRequestAssignmentView,
    ServiceRequestCollectionView,
    TechnicianAssignmentCollectionView,
    TechnicianAssignmentDetailView,
)
from apps.core.views.technician import TechnicianCollectionView, TechnicianDetailView
from apps.core.views.user import CurrentUserView
from apps.core.views.vehicle import (
    AvailableVehicleListView,
    VehicleInventoryCollectionView,
    VehicleInventoryDetailView,
)
from apps.core.views.yourspinny import (
    YourSpinnyAskView,
    YourSpinnyCompareView,
    YourSpinnyQueryView,
    YourSpinnyRecommendationView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path("dashboard/", DealershipDashboardView.as_view(), name="dealership-dashboard"),
    path("vehicles/", VehicleInventoryCollectionView.as_view(), name="vehicle-inventory"),
    path(
        "vehicles/<int:pk>/",
        VehicleInventoryDetailView.as_view(),
        name="vehicle-inventory-detail",
    ),
    path("vehicles/available/", AvailableVehicleListView.as_view(), name="vehicle-available-list"),
    path(
        "customer/vehicles/",
        CustomerVehicleCollectionView.as_view(),
        name="customer-vehicle-list",
    ),
    path("appointments/", AppointmentListView.as_view(), name="appointment-list"),
    path(
        "appointments/test-drives/",
        TestDriveCreateView.as_view(),
        name="test-drive-create",
    ),
    path("service-requests/", ServiceRequestCollectionView.as_view(), name="service-request-collection"),
    path(
        "service-requests/<int:pk>/assignments/",
        ServiceRequestAssignmentView.as_view(),
        name="service-request-assignment",
    ),
    path(
        "technician-assignments/",
        TechnicianAssignmentCollectionView.as_view(),
        name="technician-assignment-list",
    ),
    path(
        "technician-assignments/<int:pk>/",
        TechnicianAssignmentDetailView.as_view(),
        name="technician-assignment-detail",
    ),
    path("employees/", EmployeeCollectionView.as_view(), name="employee-collection"),
    path("employees/<int:pk>/", EmployeeDetailView.as_view(), name="employee-detail"),
    path("technicians/", TechnicianCollectionView.as_view(), name="technician-collection"),
    path("technicians/<int:pk>/", TechnicianDetailView.as_view(), name="technician-detail"),
    path(
        "appointments/<int:pk>/status/",
        AppointmentStatusView.as_view(),
        name="appointment-status",
    ),
    path(
        "yourspinny/recommendations/",
        YourSpinnyRecommendationView.as_view(),
        name="yourspinny-recommendations",
    ),
    path(
        "yourspinny/compare/",
        YourSpinnyCompareView.as_view(),
        name="yourspinny-compare",
    ),
    path(
        "yourspinny/query/",
        YourSpinnyQueryView.as_view(),
        name="yourspinny-query",
    ),
    path(
        "yourspinny/ask/",
        YourSpinnyAskView.as_view(),
        name="yourspinny-ask",
    ),
]
