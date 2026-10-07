from apps.core.models.appointment import Appointment, TestDrive
from apps.core.models.customer import CustomerProfile, CustomerVehicle
from apps.core.models.dealership import Dealership, Employee, TechnicianProfile
from apps.core.models.servicing import (
    Feedback,
    Invoice,
    ServiceRecord,
    ServiceRequest,
    TechnicianAssignment,
)
from apps.core.models.vehicle import Vehicle

__all__ = [
    "Appointment",
    "CustomerProfile",
    "CustomerVehicle",
    "Dealership",
    "Employee",
    "Feedback",
    "Invoice",
    "ServiceRecord",
    "ServiceRequest",
    "TechnicianAssignment",
    "TechnicianProfile",
    "TestDrive",
    "Vehicle",
]
