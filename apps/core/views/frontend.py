from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404
from django.views import View
from django.views.generic import TemplateView


class FaviconView(View):
    def get(self, request, *args, **kwargs):
        found = finders.find("favicon.svg")
        if not found:
            raise Http404("favicon not found")
        return FileResponse(open(found, "rb"), content_type="image/svg+xml")


class IndexView(TemplateView):
    template_name = "pages/index.html"


class ProtectedPageMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["protected_page"] = True
        return context


class DashboardView(ProtectedPageMixin, TemplateView):
    template_name = "pages/dashboard.html"


class MyVehiclesView(ProtectedPageMixin, TemplateView):
    template_name = "pages/my-vehicles.html"


class VehiclesView(ProtectedPageMixin, TemplateView):
    template_name = "pages/vehicles.html"


class VehicleDetailView(ProtectedPageMixin, TemplateView):
    template_name = "pages/vehicle-details.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vehicle_id"] = kwargs.get("pk")
        return context


class AppointmentsView(ProtectedPageMixin, TemplateView):
    template_name = "pages/appointments.html"


class ServiceRequestsView(ProtectedPageMixin, TemplateView):
    template_name = "pages/service-requests.html"


class InventoryView(ProtectedPageMixin, TemplateView):
    template_name = "pages/inventory.html"


class EmployeesView(ProtectedPageMixin, TemplateView):
    template_name = "pages/employees.html"


class TechniciansView(ProtectedPageMixin, TemplateView):
    template_name = "pages/technicians.html"


class WorkQueueView(ProtectedPageMixin, TemplateView):
    template_name = "pages/work-queue.html"


class MyWorkView(ProtectedPageMixin, TemplateView):
    template_name = "pages/my-work.html"


class YourSpinnyView(ProtectedPageMixin, TemplateView):
    template_name = "pages/yourspinny.html"


class LoginView(TemplateView):
    template_name = "pages/login.html"


class RegisterView(TemplateView):
    template_name = "pages/register.html"