from django.db import models


class EmployeeRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    EMPLOYEE = "EMPLOYEE", "Employee"
    TECHNICIAN = "TECHNICIAN", "Technician"


class FuelType(models.TextChoices):
    PETROL = "PETROL", "Petrol"
    DIESEL = "DIESEL", "Diesel"
    CNG = "CNG", "CNG"
    ELECTRIC = "ELECTRIC", "Electric"
    HYBRID = "HYBRID", "Hybrid"


class TransmissionType(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    AUTOMATIC = "AUTOMATIC", "Automatic"
    AMT = "AMT", "AMT"
    CVT = "CVT", "CVT"
    DCT = "DCT", "DCT"


class AppointmentType(models.TextChoices):
    TEST_DRIVE = "TEST_DRIVE", "Test Drive"
    SERVICE = "SERVICE", "Service"
    REPAIR = "REPAIR", "Repair"
    CONSULTATION = "CONSULTATION", "Consultation"


class AppointmentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class ServiceType(models.TextChoices):
    GENERAL_SERVICE = "GENERAL_SERVICE", "General Service"
    REPAIR = "REPAIR", "Repair"
    INSPECTION = "INSPECTION", "Inspection"
    MAINTENANCE = "MAINTENANCE", "Maintenance"


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class ServiceStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class Specialization(models.TextChoices):
    ENGINE = "ENGINE", "Engine"
    BRAKES = "BRAKES", "Brakes"
    ELECTRICAL = "ELECTRICAL", "Electrical"
    BODYWORK = "BODYWORK", "Bodywork"
    GENERAL = "GENERAL", "General"


class AssignmentStatus(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUED = "ISSUED", "Issued"
    PAID = "PAID", "Paid"
    CANCELLED = "CANCELLED", "Cancelled"
