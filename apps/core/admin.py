from django.contrib import admin

from apps.core.models import (
    Appointment,
    CustomerProfile,
    CustomerVehicle,
    Dealership,
    Employee,
    Feedback,
    Invoice,
    ServiceRecord,
    ServiceRequest,
    TechnicianAssignment,
    TechnicianProfile,
    TestDrive,
    Vehicle,
)


@admin.register(Dealership)
class DealershipAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "phone", "email", "is_active", "created_at")
    list_filter = ("is_active", "state")
    search_fields = ("name", "city", "email", "phone")
    ordering = ("name",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "dealership", "role", "email", "is_active", "created_at")
    list_filter = ("role", "is_active", "dealership")
    search_fields = ("first_name", "last_name", "email", "external_user_id")
    list_select_related = ("dealership",)


@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(admin.ModelAdmin):
    list_display = ("employee", "specialization", "is_available", "created_at")
    list_filter = ("specialization", "is_available")
    search_fields = ("employee__first_name", "employee__last_name")
    list_select_related = ("employee",)


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "city", "external_user_id", "created_at")
    list_filter = ("state",)
    search_fields = ("first_name", "last_name", "email", "phone", "external_user_id")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "brand",
        "model",
        "variant",
        "manufacturing_year",
        "fuel_type",
        "transmission",
        "price",
        "stock_quantity",
        "is_available",
        "dealership",
    )
    list_filter = ("fuel_type", "transmission", "is_available", "brand", "dealership")
    search_fields = ("brand", "model", "variant")
    list_select_related = ("dealership",)


@admin.register(CustomerVehicle)
class CustomerVehicleAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number",
        "customer",
        "vehicle",
        "purchase_date",
        "current_mileage",
    )
    list_filter = ("purchase_date",)
    search_fields = ("registration_number", "customer__first_name", "customer__last_name")
    list_select_related = ("customer", "vehicle")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "appointment_type",
        "customer",
        "dealership",
        "scheduled_date",
        "scheduled_time",
        "status",
    )
    list_filter = ("appointment_type", "status", "scheduled_date", "dealership")
    search_fields = ("customer__first_name", "customer__last_name", "notes")
    list_select_related = ("customer", "dealership")
    date_hierarchy = "scheduled_date"


@admin.register(TestDrive)
class TestDriveAdmin(admin.ModelAdmin):
    list_display = ("id", "appointment", "vehicle", "created_at")
    list_filter = ("vehicle__brand",)
    list_select_related = ("appointment", "vehicle")


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_vehicle",
        "service_type",
        "priority",
        "status",
        "estimated_cost",
        "created_at",
    )
    list_filter = ("service_type", "priority", "status")
    search_fields = ("customer_vehicle__registration_number", "problem_description")
    list_select_related = ("customer_vehicle", "appointment")
    raw_id_fields = ("appointment",)


@admin.register(TechnicianAssignment)
class TechnicianAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "service_request",
        "technician",
        "status",
        "assigned_at",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "assigned_at")
    list_select_related = ("service_request", "technician__employee")


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_vehicle",
        "technician",
        "service_date",
        "parts_cost",
        "labor_cost",
        "total_cost",
    )
    list_filter = ("service_date",)
    search_fields = ("customer_vehicle__registration_number", "description")
    list_select_related = ("customer_vehicle", "technician__employee")
    raw_id_fields = ("service_request",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "service_record", "subtotal", "tax", "total", "status", "issued_at")
    list_filter = ("status", "issued_at")
    search_fields = ("invoice_number",)
    list_select_related = ("service_record",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "service_record", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("comment", "customer__first_name", "customer__last_name")
    list_select_related = ("customer", "service_record")
