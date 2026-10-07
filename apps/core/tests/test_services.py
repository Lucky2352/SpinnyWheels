from datetime import time
from decimal import Decimal

from django.test import TestCase

from apps.core.exceptions import (
    ConflictError,
    DomainError,
    InvalidStateError,
    ResourceNotFoundError,
)
from apps.core.models import Appointment, TestDrive, Vehicle
from apps.core.models.choices import (
    AppointmentStatus,
    AppointmentType,
    InvoiceStatus,
    Priority,
    ServiceStatus,
)
from apps.core.services.appointment_service import AppointmentService
from apps.core.services.customer_service import CustomerService
from apps.core.services.feedback_service import FeedbackService
from apps.core.services.invoice_service import InvoiceService
from apps.core.services.service_request_service import ServiceRequestService
from apps.core.services.vehicle_service import VehicleService
from apps.core.tests import factories


class CustomerServiceTests(TestCase):
    def test_register_customer_creates_profile(self):
        customer = CustomerService().register_customer(
            first_name="Neha",
            last_name="Patil",
            email="neha@example.test",
            phone="9123456780",
        )

        self.assertEqual(customer.full_name, "Neha Patil")
        self.assertIsNone(customer.external_user_id)

    def test_register_customer_rejects_duplicate_email(self):
        CustomerService().register_customer(
            first_name="Neha", last_name="Patil", email="neha@example.test"
        )

        with self.assertRaises(ConflictError):
            CustomerService().register_customer(
                first_name="Neha", last_name="Patil", email="NEHA@example.test"
            )

    def test_register_sale_links_vehicle_and_reduces_stock(self):
        customer = factories.create_customer()
        vehicle = factories.create_vehicle(stock_quantity=2)
        service = CustomerService()

        customer_vehicle = service.register_sale(
            customer_id=customer.pk,
            vehicle_id=vehicle.pk,
            registration_number="MH18AB1234",
            purchase_date=factories.future_date(-5),
            current_mileage=120,
        )

        vehicle.refresh_from_db()
        self.assertEqual(customer_vehicle.customer, customer)
        self.assertEqual(customer_vehicle.vehicle, vehicle)
        self.assertEqual(vehicle.stock_quantity, 1)
        self.assertTrue(vehicle.is_available)
        self.assertEqual(customer.vehicles.count(), 1)

    def test_register_sale_marks_vehicle_unavailable_when_stock_runs_out(self):
        customer = factories.create_customer()
        vehicle = factories.create_vehicle(stock_quantity=1)

        CustomerService().register_sale(
            customer_id=customer.pk,
            vehicle_id=vehicle.pk,
            registration_number="MH18AB1235",
            purchase_date=factories.future_date(-1),
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.stock_quantity, 0)
        self.assertFalse(vehicle.is_available)
        self.assertFalse(vehicle.is_in_stock)

    def test_register_sale_rejects_sold_out_vehicle(self):
        customer = factories.create_customer()
        vehicle = factories.create_vehicle(stock_quantity=0, is_available=False)

        with self.assertRaises(ConflictError):
            CustomerService().register_sale(
                customer_id=customer.pk,
                vehicle_id=vehicle.pk,
                registration_number="MH18AB1236",
                purchase_date=factories.future_date(-1),
            )

    def test_register_sale_rejects_duplicate_registration_number(self):
        customer = factories.create_customer()
        vehicle = factories.create_vehicle()
        factories.create_customer_vehicle(registration_number="MH18AB1237")

        with self.assertRaises(ConflictError):
            CustomerService().register_sale(
                customer_id=customer.pk,
                vehicle_id=vehicle.pk,
                registration_number="MH18AB1237",
                purchase_date=factories.future_date(-1),
            )

    def test_list_vehicles_requires_existing_customer(self):
        with self.assertRaises(ResourceNotFoundError):
            CustomerService().list_vehicles(999999)


class VehicleServiceTests(TestCase):
    def test_add_inventory_registers_vehicle(self):
        dealership = factories.create_dealership()

        vehicle = VehicleService().add_inventory(
            dealership_id=dealership.pk,
            brand="Hyundai",
            model="Verna",
            manufacturing_year=2025,
            fuel_type="PETROL",
            transmission="AMT",
            price=Decimal("1350000.00"),
            stock_quantity=3,
        )

        self.assertEqual(vehicle.dealership, dealership)
        self.assertTrue(vehicle.is_available)
        self.assertEqual(Vehicle.objects.count(), 1)

    def test_add_inventory_rejects_duplicate_inventory_row(self):
        dealership = factories.create_dealership()
        service = VehicleService()
        payload = {
            "dealership_id": dealership.pk,
            "brand": "Hyundai",
            "model": "Verna",
            "manufacturing_year": 2025,
            "fuel_type": "PETROL",
            "transmission": "AMT",
            "price": Decimal("1350000.00"),
        }
        service.add_inventory(**payload)

        with self.assertRaises(ConflictError):
            service.add_inventory(**payload)
        self.assertEqual(Vehicle.objects.count(), 1)

    def test_add_inventory_requires_existing_dealership(self):
        with self.assertRaises(ResourceNotFoundError):
            VehicleService().add_inventory(
                dealership_id=999999,
                brand="Hyundai",
                model="Verna",
                manufacturing_year=2025,
                fuel_type="PETROL",
                transmission="AMT",
                price=Decimal("1350000.00"),
            )

    def test_get_available_rejects_sold_out_vehicle(self):
        vehicle = factories.create_vehicle(stock_quantity=0, is_available=False)

        with self.assertRaises(ConflictError):
            VehicleService().get_available(vehicle.pk)

    def test_get_available_requires_existing_vehicle(self):
        with self.assertRaises(ResourceNotFoundError):
            VehicleService().get_available(999999)


class AppointmentServiceTests(TestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.customer = factories.create_customer()
        self.vehicle = factories.create_vehicle(dealership=self.dealership)
        self.service = AppointmentService()

    def test_schedule_test_drive_creates_appointment_and_test_drive(self):
        scheduled_date = factories.future_date(3)

        test_drive = self.service.schedule_test_drive(
            customer_id=self.customer.pk,
            dealership_id=self.dealership.pk,
            vehicle_id=self.vehicle.pk,
            scheduled_date=scheduled_date,
            scheduled_time=time(11, 0),
            notes="Interested in the diesel variant",
        )

        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(TestDrive.objects.count(), 1)
        appointment = test_drive.appointment
        self.assertEqual(appointment.appointment_type, AppointmentType.TEST_DRIVE)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertEqual(appointment.customer, self.customer)
        self.assertEqual(test_drive.vehicle, self.vehicle)

    def test_schedule_test_drive_rejects_unavailable_vehicle(self):
        sold_out = factories.create_vehicle(
            dealership=self.dealership, model="Amaze", stock_quantity=0
        )

        with self.assertRaises(ConflictError):
            self.service.schedule_test_drive(
                customer_id=self.customer.pk,
                dealership_id=self.dealership.pk,
                vehicle_id=sold_out.pk,
                scheduled_date=factories.future_date(3),
                scheduled_time=time(11, 0),
            )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_schedule_rejects_past_dates(self):
        with self.assertRaises(DomainError):
            self.service.schedule(
                customer_id=self.customer.pk,
                dealership_id=self.dealership.pk,
                appointment_type=AppointmentType.SERVICE,
                scheduled_date=factories.future_date(-1),
                scheduled_time=time(9, 0),
            )

    def test_schedule_requires_vehicle_for_test_drives(self):
        with self.assertRaises(DomainError):
            self.service.schedule(
                customer_id=self.customer.pk,
                dealership_id=self.dealership.pk,
                appointment_type=AppointmentType.TEST_DRIVE,
                scheduled_date=factories.future_date(1),
                scheduled_time=time(9, 0),
            )

    def test_schedule_requires_existing_customer(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.schedule(
                customer_id=999999,
                dealership_id=self.dealership.pk,
                appointment_type=AppointmentType.SERVICE,
                scheduled_date=factories.future_date(1),
                scheduled_time=time(9, 0),
            )

    def test_confirmed_appointment_can_be_cancelled(self):
        appointment = factories.create_appointment(
            customer=self.customer, dealership=self.dealership
        )

        confirmed = self.service.confirm(appointment.pk)
        cancelled = self.service.cancel(confirmed.pk)

        self.assertEqual(confirmed.status, AppointmentStatus.CONFIRMED)
        self.assertEqual(cancelled.status, AppointmentStatus.CANCELLED)

    def test_completed_appointment_cannot_be_cancelled(self):
        appointment = factories.create_appointment(
            customer=self.customer, dealership=self.dealership
        )
        self.service.confirm(appointment.pk)
        self.service.start(appointment.pk)
        self.service.complete(appointment.pk)

        with self.assertRaises(InvalidStateError):
            self.service.cancel(appointment.pk)

    def test_cancelled_appointment_cannot_be_confirmed(self):
        appointment = factories.create_appointment(
            customer=self.customer, dealership=self.dealership
        )
        self.service.cancel(appointment.pk)

        with self.assertRaises(InvalidStateError):
            self.service.confirm(appointment.pk)

    def test_transitions_require_existing_appointment(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.confirm(999999)

    def test_listing_by_customer_and_status(self):
        pending = factories.create_appointment(customer=self.customer)
        factories.create_appointment(
            customer=self.customer, status=AppointmentStatus.CONFIRMED
        )
        factories.create_appointment()

        listed = self.service.list_for_customer(self.customer.pk)

        self.assertEqual(len(listed), 2)
        self.assertIn(pending, listed)
        self.assertEqual(len(self.service.list_by_status(AppointmentStatus.CONFIRMED)), 1)


class ServiceRequestServiceTests(TestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.customer = factories.create_customer()
        self.customer_vehicle = factories.create_customer_vehicle(customer=self.customer)
        self.technician = factories.create_technician(dealership=self.dealership)
        self.service = ServiceRequestService()

    def test_submit_creates_pending_request(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="REPAIR",
            problem_description="Brake noise while braking",
            priority=Priority.HIGH,
            estimated_cost=Decimal("7500.00"),
        )

        self.assertEqual(service_request.status, ServiceStatus.PENDING)
        self.assertEqual(service_request.customer_vehicle, self.customer_vehicle)
        self.assertEqual(service_request.priority, Priority.HIGH)
        self.assertIsNone(service_request.appointment)

    def test_submit_requires_existing_customer_vehicle(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.submit(
                customer_vehicle_id=999999,
                service_type="REPAIR",
                problem_description="Brake noise",
            )

    def test_submit_rejects_negative_estimate(self):
        with self.assertRaises(DomainError):
            self.service.submit(
                customer_vehicle_id=self.customer_vehicle.pk,
                service_type="REPAIR",
                problem_description="Brake noise",
                estimated_cost=Decimal("-1.00"),
            )

    def test_submit_rejects_appointment_of_another_customer(self):
        appointment = factories.create_appointment(dealership=self.dealership)

        with self.assertRaises(DomainError):
            self.service.submit(
                customer_vehicle_id=self.customer_vehicle.pk,
                appointment_id=appointment.pk,
                service_type="SERVICE",
                problem_description="Periodic service",
            )

    def test_assign_technician_confirms_request_and_blocks_technician(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="GENERAL_SERVICE",
            problem_description="Periodic service",
        )

        assignment = self.service.assign_technician(
            service_request_id=service_request.pk, technician_id=self.technician.pk
        )

        self.technician.refresh_from_db()
        service_request.refresh_from_db()
        self.assertEqual(assignment.status, "ASSIGNED")
        self.assertEqual(service_request.status, ServiceStatus.CONFIRMED)
        self.assertFalse(self.technician.is_available)

    def test_assign_technician_rejects_technician_with_active_assignment(self):
        first_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="GENERAL_SERVICE",
            problem_description="Periodic service",
        )
        self.service.assign_technician(
            service_request_id=first_request.pk, technician_id=self.technician.pk
        )
        second_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="REPAIR",
            problem_description="Clutch issue",
        )

        with self.assertRaises(ConflictError):
            self.service.assign_technician(
                service_request_id=second_request.pk, technician_id=self.technician.pk
            )

    def test_assign_technician_rejects_unavailable_technician(self):
        unavailable = factories.create_technician(
            dealership=self.dealership, is_available=False
        )
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="REPAIR",
            problem_description="Clutch issue",
        )

        with self.assertRaises(ConflictError):
            self.service.assign_technician(
                service_request_id=service_request.pk, technician_id=unavailable.pk
            )

    def test_assign_technician_requires_existing_technician(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="REPAIR",
            problem_description="Clutch issue",
        )

        with self.assertRaises(ResourceNotFoundError):
            self.service.assign_technician(
                service_request_id=service_request.pk, technician_id=999999
            )

    def test_complete_assignment_records_work_and_releases_technician(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="GENERAL_SERVICE",
            problem_description="Periodic service",
        )
        assignment = self.service.assign_technician(
            service_request_id=service_request.pk, technician_id=self.technician.pk
        )
        self.service.start_assignment(assignment.pk)

        record = self.service.complete_assignment(
            assignment.pk,
            description="Replaced engine oil and air filter",
            parts_cost=Decimal("3200.00"),
            labor_cost=Decimal("1800.00"),
        )

        self.technician.refresh_from_db()
        service_request.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(record.total_cost, Decimal("5000.00"))
        self.assertEqual(record.customer_vehicle, self.customer_vehicle)
        self.assertEqual(record.technician, self.technician)
        self.assertEqual(assignment.status, "COMPLETED")
        self.assertIsNotNone(assignment.completed_at)
        self.assertEqual(service_request.status, ServiceStatus.COMPLETED)
        self.assertTrue(self.technician.is_available)

    def test_completed_assignment_cannot_be_completed_again(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="GENERAL_SERVICE",
            problem_description="Periodic service",
        )
        assignment = self.service.assign_technician(
            service_request_id=service_request.pk, technician_id=self.technician.pk
        )
        self.service.complete_assignment(assignment.pk, description="Work done")

        with self.assertRaises(InvalidStateError):
            self.service.complete_assignment(assignment.pk, description="Work done again")

    def test_complete_assignment_rejects_negative_costs(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="GENERAL_SERVICE",
            problem_description="Periodic service",
        )
        assignment = self.service.assign_technician(
            service_request_id=service_request.pk, technician_id=self.technician.pk
        )

        with self.assertRaises(DomainError):
            self.service.complete_assignment(
                assignment.pk, description="Work done", parts_cost=Decimal("-10.00")
            )

    def test_cannot_assign_technician_to_cancelled_request(self):
        service_request = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="REPAIR",
            problem_description="Clutch issue",
        )
        self.service.cancel(service_request.pk)

        with self.assertRaises(InvalidStateError):
            self.service.assign_technician(
                service_request_id=service_request.pk, technician_id=self.technician.pk
            )

    def test_listing_available_technicians_filters_by_specialization(self):
        busy = self.technician
        busy.apply_changes(is_available=False)
        free_brakes_tech = factories.create_technician(
            dealership=self.dealership, specialization="BRAKES"
        )

        listed = self.service.list_available_technicians(specialization="BRAKES")

        self.assertEqual(listed, [free_brakes_tech])
        self.assertEqual(self.service.list_available_technicians(), [free_brakes_tech])

    def test_listing_service_requests_by_status(self):
        pending = self.service.submit(
            customer_vehicle_id=self.customer_vehicle.pk,
            service_type="INSPECTION",
            problem_description="Pre-purchase inspection",
        )
        factories.create_service_request(status=ServiceStatus.COMPLETED)

        listed = self.service.list_by_status(ServiceStatus.PENDING)

        self.assertEqual([item.pk for item in listed], [pending.pk])


class InvoiceServiceTests(TestCase):
    def setUp(self):
        self.record = factories.create_service_record()
        self.service = InvoiceService()

    def test_generate_calculates_tax_and_total(self):
        invoice = self.service.generate(self.record.pk, tax_percentage=Decimal("18.00"))

        self.assertEqual(invoice.invoice_number, f"INV-{self.record.pk:06d}")
        self.assertEqual(invoice.subtotal, Decimal("5000.00"))
        self.assertEqual(invoice.tax, Decimal("900.00"))
        self.assertEqual(invoice.total, Decimal("5900.00"))
        self.assertEqual(invoice.status, InvoiceStatus.DRAFT)
        self.assertIsNone(invoice.issued_at)

    def test_generate_rejects_duplicate_invoice(self):
        self.service.generate(self.record.pk)

        with self.assertRaises(ConflictError):
            self.service.generate(self.record.pk)

    def test_generate_requires_existing_service_record(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.generate(999999)

    def test_issue_and_pay_move_invoice_forward(self):
        invoice = self.service.generate(self.record.pk)

        issued = self.service.issue(invoice.pk)
        paid = self.service.mark_paid(issued.pk)

        self.assertEqual(issued.status, InvoiceStatus.ISSUED)
        self.assertIsNotNone(issued.issued_at)
        self.assertEqual(paid.status, InvoiceStatus.PAID)

    def test_paid_invoice_cannot_be_issued(self):
        invoice = self.service.generate(self.record.pk)
        self.service.issue(invoice.pk)
        self.service.mark_paid(invoice.pk)

        with self.assertRaises(InvalidStateError):
            self.service.issue(invoice.pk)

    def test_invoice_requires_existing_invoice(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service.issue(999999)


class FeedbackServiceTests(TestCase):
    def setUp(self):
        self.customer_vehicle = factories.create_customer_vehicle()
        self.record = factories.create_service_record(
            customer_vehicle=self.customer_vehicle
        )
        self.service = FeedbackService()

    def test_submit_accepts_feedback_from_the_owner(self):
        feedback = self.service.submit(
            customer_id=self.customer_vehicle.customer_id,
            service_record_id=self.record.pk,
            rating=4,
            comment="Serviced on time",
        )

        self.assertEqual(feedback.rating, 4)
        self.assertEqual(feedback.customer, self.customer_vehicle.customer)

    def test_submit_rejects_rating_outside_range(self):
        with self.assertRaises(DomainError):
            self.service.submit(
                customer_id=self.customer_vehicle.customer_id,
                service_record_id=self.record.pk,
                rating=6,
            )

    def test_submit_rejects_feedback_from_other_customers(self):
        other_customer = factories.create_customer()

        with self.assertRaises(DomainError):
            self.service.submit(
                customer_id=other_customer.pk,
                service_record_id=self.record.pk,
                rating=5,
            )

    def test_submit_rejects_duplicate_feedback(self):
        customer_id = self.customer_vehicle.customer_id
        self.service.submit(
            customer_id=customer_id, service_record_id=self.record.pk, rating=5
        )

        with self.assertRaises(ConflictError):
            self.service.submit(
                customer_id=customer_id, service_record_id=self.record.pk, rating=3
            )

    def test_listing_feedback_for_service_record(self):
        self.service.submit(
            customer_id=self.customer_vehicle.customer_id,
            service_record_id=self.record.pk,
            rating=5,
        )

        self.assertEqual(len(self.service.list_for_service_record(self.record.pk)), 1)
