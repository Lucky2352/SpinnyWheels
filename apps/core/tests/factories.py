import itertools
from datetime import date, time, timedelta
from decimal import Decimal

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
from apps.core.models.choices import (
    AppointmentStatus,
    AppointmentType,
    AssignmentStatus,
    EmployeeRole,
    FuelType,
    InvoiceStatus,
    Priority,
    ServiceStatus,
    ServiceType,
    Specialization,
    TransmissionType,
)

_counter = itertools.count(1)


def unique_email(prefix="customer"):
    return f"{prefix}{next(_counter)}@example.test"


def unique_registration_number():
    return f"MH18XY{next(_counter):04d}"


def future_date(days=7):
    return date.today() + timedelta(days=days)


def create_dealership(**overrides):
    values = {
        "name": f"AutoFlow Motors {next(_counter)}",
        "address": "1 Auto Plaza, FC Road",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411001",
        "phone": "9876543210",
        "email": unique_email("store"),
    }
    return Dealership.objects.create(**{**values, **overrides})


def create_employee(dealership=None, **overrides):
    values = {
        "dealership": dealership or create_dealership(),
        "first_name": "Asha",
        "last_name": "Menon",
        "email": unique_email("employee"),
        "role": EmployeeRole.TECHNICIAN,
        "external_user_id": f"auth-employee-{next(_counter)}",
    }
    return Employee.objects.create(**{**values, **overrides})


def create_admin(dealership=None, **overrides):
    values = {
        "dealership": dealership or create_dealership(),
        "first_name": "Admin",
        "last_name": "User",
        "email": unique_email("admin"),
        "role": EmployeeRole.ADMIN,
        "external_user_id": f"auth-admin-{next(_counter)}",
    }
    return Employee.objects.create(**{**values, **overrides})


def create_owner(dealership=None, **overrides):
    values = {
        "dealership": dealership or create_dealership(),
        "first_name": "Nikhil",
        "last_name": "Sharma",
        "email": unique_email("owner"),
        "role": EmployeeRole.OWNER,
        "external_user_id": f"auth-owner-{next(_counter)}",
    }
    return Employee.objects.create(**{**values, **overrides})


def create_staff_employee(dealership=None, **overrides):
    values = {
        "dealership": dealership or create_dealership(),
        "first_name": "Staff",
        "last_name": "Member",
        "email": unique_email("staff"),
        "role": EmployeeRole.EMPLOYEE,
        "external_user_id": f"auth-staff-{next(_counter)}",
    }
    return Employee.objects.create(**{**values, **overrides})


def create_technician(dealership=None, **overrides):
    employee = overrides.pop("employee", None) or create_employee(dealership)
    values = {"specialization": Specialization.ENGINE}
    return TechnicianProfile.objects.create(employee=employee, **{**values, **overrides})


def create_customer(**overrides):
    values = {
        "first_name": "Ravi",
        "last_name": "Kumar",
        "email": unique_email(),
        "phone": "9000000000",
        "external_user_id": f"auth-customer-{next(_counter)}",
    }
    return CustomerProfile.objects.create(**{**values, **overrides})


def create_vehicle(dealership=None, unique_variant=False, **overrides):
    values = {
        "dealership": dealership or create_dealership(),
        "brand": "Honda",
        "model": "City",
        "variant": f"Variant{next(_counter)}" if unique_variant else "",
        "manufacturing_year": 2024,
        "fuel_type": FuelType.PETROL,
        "transmission": TransmissionType.CVT,
        "price": Decimal("1500000.00"),
        "stock_quantity": 2,
    }
    return Vehicle.objects.create(**{**values, **overrides})


def create_customer_vehicle(customer=None, vehicle=None, **overrides):
    values = {
        "customer": customer or create_customer(),
        "vehicle": vehicle or create_vehicle(),
        "registration_number": unique_registration_number(),
        "purchase_date": future_date(-180),
        "current_mileage": 15000,
    }
    return CustomerVehicle.objects.create(**{**values, **overrides})


def create_appointment(customer=None, dealership=None, **overrides):
    values = {
        "customer": customer or create_customer(),
        "dealership": dealership or create_dealership(),
        "appointment_type": AppointmentType.SERVICE,
        "scheduled_date": future_date(),
        "scheduled_time": time(10, 30),
        "status": AppointmentStatus.PENDING,
    }
    return Appointment.objects.create(**{**values, **overrides})


def create_test_drive(appointment=None, vehicle=None, **overrides):
    values = {
        "appointment": appointment or create_appointment(),
        "vehicle": vehicle or create_vehicle(),
    }
    return TestDrive.objects.create(**{**values, **overrides})


def create_service_request(customer_vehicle=None, dealership=None, **overrides):
    if customer_vehicle is None:
        if dealership is None:
            dealership = create_dealership()
        vehicle = create_vehicle(dealership=dealership, unique_variant=True)
        customer_vehicle = create_customer_vehicle(vehicle=vehicle)
    else:
        if dealership is None:
            dealership = customer_vehicle.vehicle.dealership
    values = {
        "dealership": dealership,
        "customer_vehicle": customer_vehicle,
        "service_type": ServiceType.GENERAL_SERVICE,
        "problem_description": "Periodic maintenance due",
        "priority": Priority.MEDIUM,
        "status": ServiceStatus.PENDING,
        "estimated_cost": Decimal("5000.00"),
    }
    return ServiceRequest.objects.create(**{**values, **overrides})


def create_assignment(service_request=None, technician=None, **overrides):
    values = {
        "service_request": service_request or create_service_request(),
        "technician": technician or create_technician(),
        "status": AssignmentStatus.ASSIGNED,
    }
    return TechnicianAssignment.objects.create(**{**values, **overrides})


def create_service_record(service_request=None, **overrides):
    request = service_request or create_service_request()
    values = {
        "service_request": request,
        "customer_vehicle": request.customer_vehicle,
        "technician": create_technician(),
        "description": "Replaced engine oil and filters",
        "parts_cost": Decimal("3200.00"),
        "labor_cost": Decimal("1800.00"),
        "total_cost": Decimal("5000.00"),
        "service_date": date.today(),
    }
    return ServiceRecord.objects.create(**{**values, **overrides})


def create_invoice(service_record=None, **overrides):
    record = service_record or create_service_record()
    values = {
        "service_record": record,
        "invoice_number": f"INV-{record.pk:06d}",
        "subtotal": record.total_cost,
        "tax": Decimal("0.00"),
        "total": record.total_cost,
        "status": InvoiceStatus.DRAFT,
    }
    return Invoice.objects.create(**{**values, **overrides})


def create_feedback(customer=None, service_record=None, **overrides):
    record = service_record or create_service_record()
    values = {
        "customer": customer or record.customer_vehicle.customer,
        "service_record": record,
        "rating": 5,
        "comment": "Quick and professional work",
    }
    return Feedback.objects.create(**{**values, **overrides})
