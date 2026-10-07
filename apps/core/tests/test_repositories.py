from decimal import Decimal

from django.test import TestCase

from apps.core.models import Vehicle
from apps.core.models.choices import AppointmentStatus, AssignmentStatus
from apps.core.repositories.appointment_repository import (
    AppointmentRepository,
    TestDriveRepository,
)
from apps.core.repositories.customer_repository import (
    CustomerRepository,
    CustomerVehicleRepository,
)
from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.repositories.feedback_repository import FeedbackRepository
from apps.core.repositories.invoice_repository import InvoiceRepository
from apps.core.repositories.service_repository import (
    ServiceRecordRepository,
    ServiceRequestRepository,
    TechnicianAssignmentRepository,
)
from apps.core.repositories.technician_repository import TechnicianRepository
from apps.core.repositories.vehicle_repository import VehicleRepository
from apps.core.tests import factories


class DealershipRepositoryTests(TestCase):
    def test_get_by_id_returns_none_for_unknown_id(self):
        self.assertIsNone(DealershipRepository().get_by_id(999999))

    def test_create_and_update_dealership(self):
        repository = DealershipRepository()

        dealership = repository.create(
            name="AutoFlow South",
            address="4 South Road",
            city="Pune",
            state="Maharashtra",
            postal_code="411014",
            phone="9876500000",
            email="south@autoflow.test",
        )
        updated = repository.update(dealership, city="Mumbai", state="Maharashtra")

        self.assertEqual(updated.city, "Mumbai")
        self.assertEqual(repository.list_active(), [dealership])

    def test_inactive_dealership_is_not_listed_as_active(self):
        repository = DealershipRepository()
        dealership = repository.create(
            name="AutoFlow Closed",
            address="9 Old Road",
            city="Nashik",
            state="Maharashtra",
            postal_code="422001",
            phone="9876500001",
            email="closed@autoflow.test",
            is_active=False,
        )

        self.assertEqual(repository.list_active(), [])
        self.assertIsNotNone(repository.get_by_id(dealership.pk))


class CustomerRepositoryTests(TestCase):
    def test_get_by_email_is_case_insensitive(self):
        customer = factories.create_customer(email="Ravi.Kumar@Example.test")
        repository = CustomerRepository()

        self.assertEqual(repository.get_by_email("ravi.kumar@example.TEST"), customer)

    def test_customer_vehicle_lookup_by_registration_number(self):
        customer_vehicle = factories.create_customer_vehicle(
            registration_number="MH18ZZ1234"
        )
        repository = CustomerVehicleRepository()

        self.assertEqual(
            repository.get_by_registration_number("mh18zz1234"), customer_vehicle
        )
        self.assertIsNone(repository.get_by_registration_number("MH18ZZ9999"))

    def test_list_by_customer_returns_only_owned_vehicles(self):
        customer = factories.create_customer()
        owned = factories.create_customer_vehicle(customer=customer)
        factories.create_customer_vehicle()

        self.assertEqual(CustomerVehicleRepository().list_by_customer(customer.pk), [owned])


class VehicleRepositoryTests(TestCase):
    def test_get_by_id_returns_none_for_unknown_id(self):
        self.assertIsNone(VehicleRepository().get_by_id(999999))

    def test_list_available_excludes_sold_out_and_flagged_vehicles(self):
        available = factories.create_vehicle(brand="Toyota", model="Glanza")
        sold_out = factories.create_vehicle(brand="Toyota", model="Innova", stock_quantity=0)
        flagged = factories.create_vehicle(
            brand="Toyota", model="Fortuner", stock_quantity=1, is_available=False
        )

        listed = VehicleRepository().list_available()

        self.assertIn(available, listed)
        self.assertNotIn(sold_out, listed)
        self.assertNotIn(flagged, listed)

    def test_list_available_filters_by_brand_and_dealership(self):
        dealership = factories.create_dealership()
        other_dealership = factories.create_dealership()
        matching = factories.create_vehicle(brand="Kia", model="Seltos", dealership=dealership)
        other_in_brand = factories.create_vehicle(
            brand="Kia", model="Sonet", dealership=other_dealership
        )
        same_dealership = factories.create_vehicle(
            brand="Honda", model="Amaze", dealership=dealership
        )

        repository = VehicleRepository()

        self.assertEqual(
            {vehicle.pk for vehicle in repository.list_available(brand="kia")},
            {matching.pk, other_in_brand.pk},
        )
        self.assertEqual(
            {vehicle.pk for vehicle in repository.list_available(dealership_id=dealership.pk)},
            {matching.pk, same_dealership.pk},
        )

    def test_update_persists_changes_and_delete_removes_row(self):
        repository = VehicleRepository()
        vehicle = factories.create_vehicle(price=Decimal("1200000.00"))

        updated = repository.update(vehicle, price=Decimal("1150000.00"))
        self.assertEqual(updated.price, Decimal("1150000.00"))
        self.assertEqual(Vehicle.objects.get(pk=vehicle.pk).price, Decimal("1150000.00"))

        repository.delete(vehicle)
        self.assertFalse(Vehicle.objects.filter(pk=vehicle.pk).exists())


class AppointmentRepositoryTests(TestCase):
    def test_list_by_customer_can_be_narrowed_by_status(self):
        customer = factories.create_customer()
        confirmed = factories.create_appointment(
            customer=customer, status=AppointmentStatus.CONFIRMED
        )
        factories.create_appointment(
            customer=customer, status=AppointmentStatus.PENDING
        )
        factories.create_appointment()

        repository = AppointmentRepository()

        self.assertEqual(
            repository.list_by_customer(customer.pk, status=AppointmentStatus.CONFIRMED),
            [confirmed],
        )
        self.assertEqual(len(repository.list_by_customer(customer.pk)), 2)

    def test_list_by_status_filters_on_scheduled_date(self):
        today = factories.future_date(1)
        on_date = factories.create_appointment(scheduled_date=today)
        factories.create_appointment(scheduled_date=factories.future_date(3))

        repository = AppointmentRepository()
        listed = repository.list_by_status(scheduled_date=today)

        self.assertEqual([item.pk for item in listed], [on_date.pk])

    def test_test_drive_lookup_by_appointment(self):
        appointment = factories.create_appointment()
        test_drive = factories.create_test_drive(appointment=appointment)

        self.assertEqual(TestDriveRepository().get_by_appointment(appointment.pk), test_drive)
        self.assertIsNone(TestDriveRepository().get_by_id(999999))


class TechnicianRepositoryTests(TestCase):
    def test_list_available_excludes_unavailable_technicians(self):
        available = factories.create_technician(specialization="BRAKES")
        factories.create_technician(specialization="BRAKES", is_available=False)

        repository = TechnicianRepository()

        self.assertEqual(repository.list_available(specialization="BRAKES"), [available])
        self.assertEqual(len(repository.list_available()), 1)

    def test_get_by_employee(self):
        technician = factories.create_technician()

        self.assertEqual(
            TechnicianRepository().get_by_employee(technician.employee_id), technician
        )


class ServiceRepositoryTests(TestCase):
    def test_service_request_listing_by_status(self):
        request = factories.create_service_request(status="PENDING")
        factories.create_service_request(status="COMPLETED")

        self.assertEqual(
            ServiceRequestRepository().list_by_status("PENDING"), [request]
        )
        self.assertEqual(len(ServiceRequestRepository().list_by_status()), 2)

    def test_active_assignment_lookup(self):
        technician = factories.create_technician()
        assignment = factories.create_assignment(technician=technician)
        repository = TechnicianAssignmentRepository()

        self.assertEqual(repository.get_active_for_technician(technician.pk), assignment)

        assignment.apply_changes(status=AssignmentStatus.COMPLETED)
        self.assertIsNone(repository.get_active_for_technician(technician.pk))

    def test_service_record_listing_is_ordered_by_service_date(self):
        customer_vehicle = factories.create_customer_vehicle()
        older = factories.create_service_record(
            customer_vehicle=customer_vehicle,
            service_date=factories.future_date(-30),
        )
        newer = factories.create_service_record(customer_vehicle=customer_vehicle)

        listed = ServiceRecordRepository().list_by_customer_vehicle(customer_vehicle.pk)

        self.assertEqual(listed, [newer, older])


class InvoiceAndFeedbackRepositoryTests(TestCase):
    def test_invoice_lookup_helpers(self):
        invoice = factories.create_invoice()
        repository = InvoiceRepository()

        self.assertEqual(repository.get_by_service_record(invoice.service_record_id), invoice)
        self.assertEqual(repository.get_by_number(invoice.invoice_number.lower()), invoice)
        self.assertEqual(repository.list_by_status("DRAFT"), [invoice])

    def test_feedback_lookup_helpers(self):
        feedback = factories.create_feedback()
        repository = FeedbackRepository()

        self.assertEqual(
            repository.get_by_customer_and_service_record(
                feedback.customer_id, feedback.service_record_id
            ),
            feedback,
        )
        self.assertEqual(repository.list_for_service_record(feedback.service_record_id), [feedback])
