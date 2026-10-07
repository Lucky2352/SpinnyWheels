from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.core.models import (
    Appointment,
    CustomerVehicle,
    Feedback,
    ServiceRecord,
    ServiceRequest,
    TechnicianAssignment,
    TechnicianProfile,
    TestDrive,
)
from apps.core.models.choices import AssignmentStatus
from apps.core.tests import factories


class DealershipAndEmployeeModelTests(TestCase):
    def test_employee_belongs_to_dealership(self):
        dealership = factories.create_dealership()
        employee = factories.create_employee(dealership=dealership)

        self.assertEqual(employee.dealership, dealership)
        self.assertIn(employee, dealership.employees.all())
        self.assertEqual(employee.full_name, "Asha Menon")

    def test_employee_email_is_unique_per_dealership(self):
        dealership = factories.create_dealership()
        email = factories.unique_email("employee")
        factories.create_employee(dealership=dealership, email=email)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_employee(dealership=dealership, email=email)

    def test_dealership_with_employees_cannot_be_deleted(self):
        dealership = factories.create_dealership()
        factories.create_employee(dealership=dealership)

        with self.assertRaises(ProtectedError):
            dealership.delete()

    def test_employee_has_at_most_one_technician_profile(self):
        employee = factories.create_employee()
        factories.create_technician(employee=employee)

        with self.assertRaises(IntegrityError), transaction.atomic():
            TechnicianProfile.objects.create(employee=employee)

    def test_external_user_id_is_optional_and_unique(self):
        employee = factories.create_employee(external_user_id=None)
        factories.create_employee(external_user_id="auth-1")

        self.assertIsNone(employee.external_user_id)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_employee(external_user_id="auth-1")


class VehicleModelTests(TestCase):
    def test_vehicle_inventory_is_unique_per_dealership(self):
        dealership = factories.create_dealership()
        factories.create_vehicle(dealership=dealership)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_vehicle(dealership=dealership)

    def test_vehicle_price_cannot_be_negative(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_vehicle(price=Decimal("-1.00"))

    def test_is_in_stock_reflects_flag_and_quantity(self):
        vehicle = factories.create_vehicle(stock_quantity=1)
        self.assertTrue(vehicle.is_in_stock)

        vehicle.apply_changes(stock_quantity=0, is_available=False)
        self.assertFalse(vehicle.is_in_stock)

    def test_customer_vehicle_links_customer_to_inventory_model(self):
        customer = factories.create_customer()
        vehicle = factories.create_vehicle()
        customer_vehicle = factories.create_customer_vehicle(
            customer=customer, vehicle=vehicle
        )

        self.assertEqual(customer_vehicle.customer, customer)
        self.assertEqual(customer_vehicle.vehicle, vehicle)
        self.assertEqual(customer.vehicles.count(), 1)

    def test_registration_number_is_unique(self):
        registration_number = factories.unique_registration_number()
        factories.create_customer_vehicle(registration_number=registration_number)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_customer_vehicle(registration_number=registration_number)

    def test_sold_vehicle_model_cannot_be_deleted(self):
        customer_vehicle = factories.create_customer_vehicle()

        with self.assertRaises(ProtectedError):
            customer_vehicle.vehicle.delete()

    def test_deleting_customer_removes_owned_vehicles(self):
        customer = factories.create_customer()
        customer_vehicle = factories.create_customer_vehicle(customer=customer)

        customer.delete()

        self.assertFalse(CustomerVehicle.objects.filter(pk=customer_vehicle.pk).exists())


class AppointmentModelTests(TestCase):
    def test_test_drive_requires_appointment_and_vehicle(self):
        appointment = factories.create_appointment()
        vehicle = factories.create_vehicle()
        test_drive = factories.create_test_drive(appointment=appointment, vehicle=vehicle)

        self.assertEqual(test_drive.appointment, appointment)
        self.assertEqual(appointment.test_drive, test_drive)

    def test_appointment_allows_only_one_test_drive(self):
        appointment = factories.create_appointment()
        factories.create_test_drive(appointment=appointment)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_test_drive(appointment=appointment)

    def test_appointment_allows_only_one_service_request(self):
        appointment = factories.create_appointment()
        factories.create_service_request(appointment=appointment)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_service_request(appointment=appointment)

    def test_deleting_appointment_removes_its_test_drive(self):
        appointment = factories.create_appointment()
        test_drive = factories.create_test_drive(appointment=appointment)

        appointment.delete()

        self.assertFalse(TestDrive.objects.filter(pk=test_drive.pk).exists())
        self.assertEqual(Appointment.objects.count(), 0)

    def test_scheduled_for_combines_date_and_time(self):
        appointment = factories.create_appointment()
        expected = appointment.scheduled_for

        self.assertEqual(expected.date(), appointment.scheduled_date)
        self.assertEqual(expected.time(), appointment.scheduled_time)


class ServiceModelTests(TestCase):
    def test_technician_can_have_only_one_active_assignment(self):
        technician = factories.create_technician()
        factories.create_assignment(technician=technician)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_assignment(technician=technician)

    def test_technician_can_be_assigned_again_after_completion(self):
        technician = factories.create_technician()
        first = factories.create_assignment(technician=technician)
        first.apply_changes(status=AssignmentStatus.COMPLETED)

        second = factories.create_assignment(technician=technician)

        self.assertEqual(TechnicianAssignment.objects.filter(technician=technician).count(), 2)
        self.assertEqual(second.status, AssignmentStatus.ASSIGNED)

    def test_deleting_assignment_leaves_service_request(self):
        assignment = factories.create_assignment()

        assignment.delete()

        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(AssignmentStatus.ASSIGNED, "ASSIGNED")

    def test_service_record_costs_cannot_be_negative(self):
        request = factories.create_service_request()

        with self.assertRaises(IntegrityError), transaction.atomic():
            ServiceRecord.objects.create(
                service_request=request,
                customer_vehicle=request.customer_vehicle,
                technician=factories.create_technician(),
                description="Discounted entry",
                parts_cost=Decimal("10.00"),
                labor_cost=Decimal("5.00"),
                total_cost=Decimal("-5.00"),
            )

    def test_service_record_survives_deletion_of_operational_objects(self):
        record = factories.create_service_record()

        with self.assertRaises(ProtectedError):
            record.service_request.delete()
        with self.assertRaises(ProtectedError):
            record.technician.delete()

        self.assertTrue(ServiceRecord.objects.filter(pk=record.pk).exists())

    def test_deleting_assignment_keeps_service_request_and_record(self):
        assignment = factories.create_assignment()
        record = factories.create_service_record(service_request=assignment.service_request)

        assignment.delete()

        self.assertTrue(ServiceRequest.objects.filter(pk=assignment.service_request_id).exists())
        self.assertTrue(ServiceRecord.objects.filter(pk=record.pk).exists())

    def test_invoice_total_must_match_subtotal_plus_tax(self):
        record = factories.create_service_record()

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_invoice(
                service_record=record,
                subtotal=Decimal("1000.00"),
                tax=Decimal("180.00"),
                total=Decimal("1500.00"),
            )

    def test_invoice_is_unique_per_service_record(self):
        record = factories.create_service_record()
        factories.create_invoice(service_record=record)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_invoice(service_record=record)


class FeedbackModelTests(TestCase):
    def test_rating_is_limited_to_one_through_five(self):
        record = factories.create_service_record()

        for invalid_rating in (0, 6):
            with self.assertRaises(IntegrityError), transaction.atomic():
                factories.create_feedback(service_record=record, rating=invalid_rating)

    def test_single_feedback_per_customer_and_service_record(self):
        record = factories.create_service_record()
        factories.create_feedback(service_record=record)

        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.create_feedback(service_record=record)

    def test_feedback_is_removed_with_its_service_record(self):
        feedback = factories.create_feedback()

        feedback.service_record.delete()

        self.assertEqual(Feedback.objects.filter(pk=feedback.pk).count(), 0)
