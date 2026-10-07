from datetime import date, time, timedelta
from unittest.mock import patch, MagicMock

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.authentication.supabase import SupabaseJWTAuthentication
from apps.core.models import (
    Appointment,
    CustomerProfile,
    CustomerVehicle,
    Employee,
    ServiceRecord,
    ServiceRequest,
    TechnicianAssignment,
    TechnicianProfile,
    TestDrive,
    Vehicle,
)
from apps.core.models.choices import (
    AssignmentStatus,
    EmployeeRole,
    ServiceStatus,
    Specialization,
)
from apps.core.tests import factories


class HealthEndpointTests(APITestCase):
    def test_health_reports_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "ok"})


class AvailableVehicleEndpointTests(APITestCase):
    def test_only_available_vehicles_are_returned(self):
        dealership = factories.create_dealership()
        available = factories.create_vehicle(dealership=dealership)
        factories.create_vehicle(
            dealership=dealership, model="Innova", stock_quantity=0
        )

        response = self.client.get(
            reverse("vehicle-available-list"), {"dealership": dealership.pk}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [available.pk])

    def test_response_exposes_read_only_availability_flag(self):
        vehicle = factories.create_vehicle()

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertTrue(response.data[0]["is_in_stock"])
        self.assertEqual(response.data[0]["fuel_type"], vehicle.fuel_type)

    def test_response_includes_dealership_name(self):
        dealership = factories.create_dealership(name="AutoFlow Motors Hinjewadi")
        factories.create_vehicle(dealership=dealership)

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertEqual(response.data[0]["dealership_name"], "AutoFlow Motors Hinjewadi")


class TestDriveEndpointTests(APITestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.customer = factories.create_customer(external_user_id="auth-test-cust-1")
        self.vehicle = factories.create_vehicle(dealership=self.dealership)

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": "Bearer fake-token-for-auth-test-cust-1"}

    def _mock_auth(self, mock_verify_token):
        mock_verify_token.return_value = {"sub": "auth-test-cust-1", "email": self.customer.email}

    def payload(self, **overrides):
        data = {
            "customer_id": self.customer.pk,
            "dealership_id": self.dealership.pk,
            "vehicle_id": self.vehicle.pk,
            "scheduled_date": (date.today() + timedelta(days=3)).isoformat(),
            "scheduled_time": time(11, 30).isoformat(),
            "notes": "Evening availability preferred",
        }
        data.update(overrides)
        return data

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_scheduling_a_test_drive_creates_appointment_and_test_drive(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("test-drive-create"), self.payload(), format="json", **self._auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(TestDrive.objects.count(), 1)
        self.assertEqual(response.data["appointment"]["status"], "PENDING")
        self.assertEqual(response.data["appointment"]["appointment_type"], "TEST_DRIVE")
        self.assertEqual(response.data["vehicle"]["id"], self.vehicle.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_invalid_payload_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("test-drive-create"),
            self.payload(scheduled_time="not-a-time"),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scheduled_time", response.data)
        self.assertEqual(Appointment.objects.count(), 0)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_unknown_vehicle_returns_not_found(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("test-drive-create"), self.payload(vehicle_id=999999), format="json", **self._auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Appointment.objects.count(), 0)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_past_appointment_is_rejected_with_bad_request(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("test-drive-create"),
            self.payload(
                scheduled_date=(date.today() - timedelta(days=1)).isoformat()
            ),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("past", response.data["detail"])


class AppointmentListEndpointTests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-test-cust-2")
        self.other_customer = factories.create_customer()
        self.dealership = factories.create_dealership()

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": "Bearer fake-token-for-auth-test-cust-2"}

    def _mock_auth(self, mock_verify_token):
        mock_verify_token.return_value = {"sub": "auth-test-cust-2", "email": self.customer.email}

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_filtering_requires_customer_or_status(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.get(reverse("appointment-list"), **self._auth_header())

        # For authenticated customers, they can list their own appointments without filters
        # Returns empty list if no appointments
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_filtering_by_customer_returns_only_their_appointments(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        appointment = factories.create_appointment(customer=self.customer, dealership=self.dealership)
        factories.create_appointment()

        response = self.client.get(
            reverse("appointment-list"), {"customer_id": self.customer.pk}, **self._auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [appointment.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_unknown_status_value_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.get(reverse("appointment-list"), {"status": "ARCHIVED"}, **self._auth_header())

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_response_includes_display_labels_and_dealership_name(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        dealership = factories.create_dealership(name="AutoFlow Motors Baner")
        factories.create_appointment(
            customer=self.customer, dealership=dealership, status="CONFIRMED"
        )

        response = self.client.get(reverse("appointment-list"), **self._auth_header())

        self.assertEqual(response.data[0]["dealership_name"], "AutoFlow Motors Baner")
        self.assertEqual(response.data[0]["status_display"], "Confirmed")
        self.assertEqual(response.data[0]["appointment_type_display"], "Service")


class ServiceRequestEndpointTests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-test-cust-3")
        self.customer_vehicle = factories.create_customer_vehicle(customer=self.customer)

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": "Bearer fake-token-for-auth-test-cust-3"}

    def _mock_auth(self, mock_verify_token):
        mock_verify_token.return_value = {"sub": "auth-test-cust-3", "email": self.customer.email}

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_creating_a_service_request(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": self.customer_vehicle.pk,
                "service_type": "REPAIR",
                "problem_description": "Air conditioning not cooling",
                "priority": "HIGH",
                "estimated_cost": "4200.00",
            },
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(response.data["priority"], "HIGH")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_unknown_service_type_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": self.customer_vehicle.pk,
                "service_type": "BODY_PAINT",
                "problem_description": "Scratches on the door",
            },
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("service_type", response.data)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_listing_service_requests_by_status(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        request = factories.create_service_request(
            customer_vehicle=self.customer_vehicle, status="PENDING"
        )
        factories.create_service_request(status="COMPLETED")

        response = self.client.get(
            reverse("service-request-collection"), {"status": "PENDING"}, **self._auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [request.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_unknown_customer_vehicle_returns_not_found(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": 999999,
                "service_type": "REPAIR",
                "problem_description": "Unknown vehicle",
            },
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ServiceRequest.objects.count(), 0)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_listing_includes_customer_vehicle_detail(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        factories.create_service_request(customer_vehicle=self.customer_vehicle)

        response = self.client.get(reverse("service-request-collection"), **self._auth_header())

        detail = response.data[0]["customer_vehicle_detail"]
        self.assertEqual(detail["id"], self.customer_vehicle.pk)
        self.assertEqual(detail["registration_number"], self.customer_vehicle.registration_number)
        self.assertEqual(detail["vehicle"]["brand"], self.customer_vehicle.vehicle.brand)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_another_customers_service_request_is_not_returned(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        factories.create_service_request()

        response = self.client.get(reverse("service-request-collection"), **self._auth_header())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])


class CustomerVehicleListEndpointTests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-test-cust-4")
        self.other_customer = factories.create_customer()
        self.vehicle = factories.create_customer_vehicle(customer=self.customer)

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": "Bearer fake-token-for-auth-test-cust-4"}

    def _mock_auth(self, mock_verify_token):
        mock_verify_token.return_value = {"sub": "auth-test-cust-4", "email": self.customer.email}

    def test_requires_authentication(self):
        response = self.client.get(reverse("customer-vehicle-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_returns_only_the_authenticated_customers_vehicles(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        factories.create_customer_vehicle(customer=self.other_customer)

        response = self.client.get(reverse("customer-vehicle-list"), **self._auth_header())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [self.vehicle.pk])
        self.assertEqual(response.data[0]["vehicle"]["id"], self.vehicle.vehicle.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_id_is_derived_from_the_token(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        response = self.client.get(
            reverse("customer-vehicle-list"),
            {"customer_id": self.other_customer.pk},
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [self.vehicle.pk])


class CustomerVehicleCreateEndpointTests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-test-cust-5")
        self.other_customer = factories.create_customer()
        self.vehicle = factories.create_vehicle()

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": "Bearer fake-token-for-auth-test-cust-5"}

    def _mock_auth(self, mock_verify_token):
        mock_verify_token.return_value = {"sub": "auth-test-cust-5", "email": self.customer.email}

    def _payload(self, **overrides):
        return {
            "vehicle_id": self.vehicle.pk,
            "registration_number": "MH18XY9999",
            "purchase_date": "2024-03-15",
            "current_mileage": 12000,
            **overrides,
        }

    def test_requires_authentication(self):
        response = self.client.post(reverse("customer-vehicle-list"), self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_registers_a_vehicle_for_their_own_profile(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["registration_number"], "MH18XY9999")
        self.assertEqual(response.data["vehicle"]["id"], self.vehicle.pk)

        created = CustomerVehicle.objects.get(registration_number="MH18XY9999")
        self.assertEqual(created.customer_id, self.customer.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_id_in_payload_is_ignored_and_derived_from_the_token(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(customer_id=self.other_customer.pk),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created = CustomerVehicle.objects.get(registration_number="MH18XY9999")
        self.assertEqual(created.customer_id, self.customer.pk)
        self.assertNotEqual(created.customer_id, self.other_customer.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_registered_vehicle_is_returned_by_the_customer_vehicle_list(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        create_response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(),
            format="json",
            **self._auth_header(),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        list_response = self.client.get(
            reverse("customer-vehicle-list"), **self._auth_header()
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["registration_number"] for item in list_response.data],
            ["MH18XY9999"],
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_duplicate_registration_number_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        factories.create_customer_vehicle(registration_number="MH18XY9999")

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_unknown_vehicle_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(vehicle_id=999999),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_negative_mileage_is_rejected_by_validation(self, mock_verify_token):
        self._mock_auth(mock_verify_token)

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(current_mileage=-5),
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_missing_registration_number_is_rejected(self, mock_verify_token):
        self._mock_auth(mock_verify_token)
        payload = self._payload()
        payload.pop("registration_number")

        response = self.client.post(
            reverse("customer-vehicle-list"),
            payload,
            format="json",
            **self._auth_header(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_register_a_customer_vehicle(self, mock_verify_token):
        employee = factories.create_staff_employee(external_user_id="auth-staff-5")
        mock_verify_token.return_value = {
            "sub": "auth-staff-5",
            "email": employee.email,
        }

        response = self.client.post(
            reverse("customer-vehicle-list"),
            self._payload(),
            format="json",
            HTTP_AUTHORIZATION="Bearer fake-token-for-auth-staff-5",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class InventoryRoleTestCase(APITestCase):
    def authenticate_as(self, employee, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": employee.external_user_id,
            "email": employee.email,
        }
        return {"HTTP_AUTHORIZATION": f"Bearer token-for-{employee.external_user_id}"}


class VehicleInventoryCreateTests(InventoryRoleTestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.owner = factories.create_owner(dealership=self.dealership)
        self.payload = {
            "dealership_id": self.dealership.pk,
            "brand": "Mahindra",
            "model": "XUV 3XO",
            "variant": "MX2 Pro",
            "manufacturing_year": 2025,
            "fuel_type": "PETROL",
            "transmission": "MANUAL",
            "seating_capacity": 5,
            "price": "1240000.00",
            "stock_quantity": 3,
        }

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_create_vehicle(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["brand"], "Mahindra")
        self.assertEqual(response.data["model"], "XUV 3XO")
        self.assertEqual(response.data["dealership"], self.dealership.pk)
        self.assertTrue(response.data["is_in_stock"])
        self.assertEqual(Vehicle.objects.filter(model="XUV 3XO").count(), 1)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_admin_can_create_vehicle(self, mock_verify_token):
        admin = factories.create_admin(dealership=self.dealership)
        headers = self.authenticate_as(admin, mock_verify_token)

        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["model"], "XUV 3XO")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_create_vehicle(self, mock_verify_token):
        customer = factories.create_customer()
        headers = self.authenticate_as(customer, mock_verify_token)

        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Vehicle.objects.filter(model="XUV 3XO").exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_create_vehicle(self, mock_verify_token):
        technician = factories.create_employee(
            dealership=self.dealership, role="TECHNICIAN"
        )
        headers = self.authenticate_as(technician, mock_verify_token)

        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_create_vehicle(self, mock_verify_token):
        employee = factories.create_staff_employee(dealership=self.dealership)
        headers = self.authenticate_as(employee, mock_verify_token)

        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_anonymous_cannot_create_vehicle(self, mock_verify_token):
        response = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_client_supplied_role_is_ignored(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "role": "OWNER", "is_active": True}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        vehicle = Vehicle.objects.get(model="XUV 3XO")
        self.assertFalse(hasattr(vehicle, "role"))
        self.assertTrue(vehicle.is_available)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_cannot_create_vehicle_in_another_dealership(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "dealership_id": factories.create_dealership().pk}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Vehicle.objects.filter(model="XUV 3XO").exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_negative_price_is_rejected(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "price": "-1.00"}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("price", response.data)
        self.assertFalse(Vehicle.objects.filter(model="XUV 3XO").exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_non_numeric_price_is_rejected(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "price": "not-a-number"}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("price", response.data)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_negative_stock_is_rejected(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "stock_quantity": -5}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("stock_quantity", response.data)
        self.assertFalse(Vehicle.objects.filter(model="XUV 3XO").exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_invalid_fuel_type_is_rejected(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "fuel_type": "PLUTONIUM"}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("fuel_type", response.data)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_invalid_seating_capacity_is_rejected(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        payload = {**self.payload, "seating_capacity": 0}

        response = self.client.post(
            reverse("vehicle-inventory"), payload, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_new_vehicle_appears_in_available_inventory(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        created = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertIn(created.data["id"], [item["id"] for item in response.data])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_created_vehicle_details_can_be_retrieved(self, mock_verify_token):
        headers = self.authenticate_as(self.owner, mock_verify_token)
        created = self.client.post(
            reverse("vehicle-inventory"), self.payload, format="json", **headers
        )

        response = self.client.get(
            reverse("vehicle-inventory-detail", args=[created.data["id"]]), **headers
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["variant"], "MX2 Pro")
        self.assertEqual(response.data["price"], "1240000.00")
        self.assertEqual(response.data["stock_quantity"], 3)


class VehicleInventoryUpdateTests(InventoryRoleTestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.owner = factories.create_owner(dealership=self.dealership)
        self.vehicle = factories.create_vehicle(dealership=self.dealership)

    def patch_vehicle(self, payload, employee=None):
        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            employee = employee or self.owner
            headers = self.authenticate_as(employee, mock_verify)
            return self.client.patch(
                reverse("vehicle-inventory-detail", args=[self.vehicle.pk]),
                payload,
                format="json",
                **headers,
            )

    def test_owner_can_update_price(self):
        response = self.patch_vehicle({"price": "1890000.00"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["price"], "1890000.00")
        self.vehicle.refresh_from_db()
        self.assertEqual(str(self.vehicle.price), "1890000.00")

    def test_owner_can_update_stock(self):
        response = self.patch_vehicle({"stock_quantity": 7})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["stock_quantity"], 7)

    def test_owner_can_update_availability(self):
        response = self.patch_vehicle({"is_available": False})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_available"])

    def test_owner_can_update_specifications(self):
        response = self.patch_vehicle(
            {"variant": "ZX CVT", "seating_capacity": 7, "transmission": "CVT"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["variant"], "ZX CVT")
        self.assertEqual(response.data["seating_capacity"], 7)
        self.assertEqual(response.data["transmission"], "CVT")

    def test_reinstating_availability_restores_stock_visibility(self):
        self.patch_vehicle({"is_available": False})
        self.patch_vehicle({"is_available": True})

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertIn(self.vehicle.pk, [item["id"] for item in response.data])

    def test_zero_stock_forces_unavailable(self):
        response = self.patch_vehicle({"stock_quantity": 0})

        self.assertFalse(response.data["is_available"])
        self.assertFalse(response.data["is_in_stock"])

    def test_owner_can_deactivate_vehicle(self):
        response = self.patch_vehicle({})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(self.owner, mock_verify)
            response = self.client.delete(
                reverse("vehicle-inventory-detail", args=[self.vehicle.pk]), **headers
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_available"])
        self.assertEqual(response.data["stock_quantity"], 0)
        self.vehicle.refresh_from_db()
        self.assertTrue(Vehicle.objects.filter(pk=self.vehicle.pk).exists())

    def test_deactivated_vehicle_disappears_from_available_inventory(self):
        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(self.owner, mock_verify)
            self.client.delete(
                reverse("vehicle-inventory-detail", args=[self.vehicle.pk]), **headers
            )

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertNotIn(self.vehicle.pk, [item["id"] for item in response.data])

    def test_negative_price_is_rejected(self):
        response = self.patch_vehicle({"price": "-500"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.vehicle.refresh_from_db()
        self.assertEqual(str(self.vehicle.price), "1500000.00")

    def test_negative_stock_is_rejected(self):
        response = self.patch_vehicle({"stock_quantity": -3})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.stock_quantity, 2)

    def test_customer_cannot_update_vehicle(self):
        response = self.patch_vehicle({"price": "1.00"}, factories.create_customer())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.vehicle.refresh_from_db()
        self.assertEqual(str(self.vehicle.price), "1500000.00")

    def test_customer_cannot_deactivate_vehicle(self):
        customer = factories.create_customer()

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(customer, mock_verify)
            response = self.client.delete(
                reverse("vehicle-inventory-detail", args=[self.vehicle.pk]), **headers
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.is_available)

    def test_technician_cannot_update_vehicle(self):
        technician = factories.create_employee(
            dealership=self.dealership, role="TECHNICIAN"
        )

        response = self.patch_vehicle({"price": "1.00"}, technician)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_employee_cannot_update_vehicle(self):
        employee = factories.create_staff_employee(dealership=self.dealership)

        response = self.patch_vehicle({"price": "1.00"}, employee)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_cannot_update_another_dealership_vehicle(self):
        foreign = factories.create_vehicle()

        response = self.patch_vehicle({"price": "1.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle = foreign
        response = self.patch_vehicle({"price": "1.00"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        foreign.refresh_from_db()
        self.assertEqual(str(foreign.price), "1500000.00")


class VehicleInventoryListTests(InventoryRoleTestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.owner = factories.create_owner(dealership=self.dealership)

    def test_owner_sees_inventory_including_unavailable_vehicles(self):
        factories.create_vehicle(dealership=self.dealership, model="Sold Out", stock_quantity=0)
        factories.create_vehicle(dealership=self.dealership, model="In Stock")

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(self.owner, mock_verify)
            response = self.client.get(reverse("vehicle-inventory"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_owner_inventory_is_scoped_to_own_dealership(self):
        factories.create_vehicle(dealership=self.dealership, model="Mine")
        factories.create_vehicle(dealership=factories.create_dealership(), model="Theirs")

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(self.owner, mock_verify)
            response = self.client.get(reverse("vehicle-inventory"), **headers)

        self.assertEqual([item["model"] for item in response.data], ["Mine"])

    def test_inventory_search_filters_results(self):
        factories.create_vehicle(dealership=self.dealership, model="Harrier")
        factories.create_vehicle(dealership=self.dealership, model="Thar")

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(self.owner, mock_verify)
            response = self.client.get(
                reverse("vehicle-inventory"), {"search": "harri"}, **headers
            )

        self.assertEqual([item["model"] for item in response.data], ["Harrier"])

    def test_customer_cannot_read_inventory_endpoint(self):
        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(factories.create_customer(), mock_verify)
            response = self.client.get(reverse("vehicle-inventory"), **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_can_read_available_inventory(self):
        factories.create_vehicle(dealership=self.dealership, model="Punch")

        response = self.client.get(reverse("vehicle-available-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Punch", [item["model"] for item in response.data])


class CurrentUserEndpointTests(InventoryRoleTestCase):
    def test_owner_is_reported_as_inventory_manager(self):
        dealership = factories.create_dealership()
        owner = factories.create_owner(dealership=dealership)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("current-user"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], "OWNER")
        self.assertTrue(response.data["can_manage_inventory"])
        self.assertTrue(response.data["is_employee"])
        self.assertEqual(response.data["dealership_id"], dealership.pk)
        self.assertEqual(response.data["dealership_name"], dealership.name)

    def test_customer_cannot_manage_inventory(self):
        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(factories.create_customer(), mock_verify)
            response = self.client.get(reverse("current-user"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], "CUSTOMER")
        self.assertTrue(response.data["is_customer"])
        self.assertFalse(response.data["can_manage_inventory"])
        self.assertFalse(response.data["is_employee"])

    def test_technician_cannot_manage_inventory(self):
        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(factories.create_employee(), mock_verify)
            response = self.client.get(reverse("current-user"), **headers)

        self.assertFalse(response.data["can_manage_inventory"])

    def test_anonymous_cannot_read_current_user(self):
        response = self.client.get(reverse("current-user"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DealershipDashboardAccessTests(InventoryRoleTestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()

    def test_owner_can_read_the_dealership_dashboard(self):
        owner = factories.create_owner(dealership=self.dealership)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dealership_id"], self.dealership.pk)
        self.assertEqual(
            sorted(response.data["metrics"]),
            ["in_stock_vehicles", "showroom_vehicles", "upcoming_appointments", "upcoming_test_drives"],
        )

    def test_owner_dashboard_counts_dealership_inventory(self):
        owner = factories.create_owner(dealership=self.dealership)
        factories.create_vehicle(dealership=self.dealership, model="City")
        factories.create_vehicle(dealership=self.dealership, model="Punch")
        factories.create_vehicle(
            dealership=self.dealership,
            model="Dzire",
            is_available=False,
            stock_quantity=0,
        )

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.data["metrics"]["showroom_vehicles"], 3)
        self.assertEqual(response.data["metrics"]["in_stock_vehicles"], 2)

    def test_owner_dashboard_ignores_other_dealerships(self):
        owner = factories.create_owner(dealership=self.dealership)
        other_dealership = factories.create_dealership()
        factories.create_vehicle(dealership=self.dealership, model="City")
        factories.create_vehicle(dealership=other_dealership, model="Punch")
        factories.create_appointment(dealership=other_dealership)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.data["metrics"]["showroom_vehicles"], 1)
        self.assertEqual(response.data["metrics"]["upcoming_appointments"], 0)
        self.assertEqual(response.data["recent_appointments"], [])

    def test_owner_dashboard_counts_upcoming_appointments_and_test_drives(self):
        owner = factories.create_owner(dealership=self.dealership)
        customer = factories.create_customer()
        vehicle = factories.create_vehicle(dealership=self.dealership)

        pending = factories.create_appointment(
            customer=customer,
            dealership=self.dealership,
            status="PENDING",
        )
        completed = factories.create_appointment(
            customer=customer,
            dealership=self.dealership,
            status="COMPLETED",
        )
        past = factories.create_appointment(
            customer=customer,
            dealership=self.dealership,
            scheduled_date=date.today() - timedelta(days=3),
        )
        test_drive = factories.create_appointment(
            customer=customer,
            dealership=self.dealership,
            appointment_type="TEST_DRIVE",
        )
        factories.create_test_drive(appointment=test_drive, vehicle=vehicle)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.data["metrics"]["upcoming_appointments"], 2)
        self.assertEqual(response.data["metrics"]["upcoming_test_drives"], 1)
        self.assertEqual(len(response.data["recent_appointments"]), 4)
        self.assertEqual(
            sorted(item["id"] for item in response.data["recent_appointments"]),
            sorted([pending.pk, completed.pk, past.pk, test_drive.pk]),
        )
        self.assertIn("dealership_name", response.data["recent_appointments"][0])

    def test_dealership_dashboard_is_limited_to_eight_recent_appointments(self):
        owner = factories.create_owner(dealership=self.dealership)

        for _ in range(9):
            factories.create_appointment(dealership=self.dealership)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(len(response.data["recent_appointments"]), 8)

    def test_employee_and_technician_can_read_the_dealership_dashboard(self):
        employee = factories.create_staff_employee(dealership=self.dealership)
        technician = factories.create_employee(dealership=self.dealership)

        for actor in (employee, technician):
            with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
                headers = self.authenticate_as(actor, mock_verify)
                response = self.client.get(reverse("dealership-dashboard"), **headers)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["dealership_id"], self.dealership.pk)

    def test_admin_can_read_the_dealership_dashboard(self):
        admin = factories.create_admin(dealership=self.dealership)

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(admin, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_cannot_read_the_dealership_dashboard(self):
        customer = factories.create_customer()

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(customer, mock_verify)
            response = self.client.get(reverse("dealership-dashboard"), **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_read_the_dealership_dashboard(self):
        response = self.client.get(reverse("dealership-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_still_cannot_read_customer_owned_vehicles(self):
        owner = factories.create_owner(dealership=self.dealership)
        factories.create_customer_vehicle()

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(owner, mock_verify)
            response = self.client.get(reverse("customer-vehicle-list"), **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_dashboard_endpoints_remain_available_to_customers(self):
        customer = factories.create_customer()
        factories.create_appointment(customer=customer)
        factories.create_customer_vehicle(customer=customer)
        factories.create_service_request()

        with patch.object(SupabaseJWTAuthentication, "_verify_token") as mock_verify:
            headers = self.authenticate_as(customer, mock_verify)

            for name in (
                "customer-vehicle-list",
                "appointment-list",
                "service-request-collection",
            ):
                response = self.client.get(reverse(name), **headers)
                self.assertEqual(response.status_code, status.HTTP_200_OK, name)


class CustomerVehicleWorkflowIntactTests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-cust-intact-1")
        self.vehicle = factories.create_vehicle(brand="Honda", model="City")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_vehicle_workflow_is_unaffected_by_inventory_permissions(self, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": "auth-cust-intact-1",
            "email": self.customer.email,
        }
        headers = {"HTTP_AUTHORIZATION": "Bearer token-for-auth-cust-intact-1"}

        registered = self.client.post(
            reverse("customer-vehicle-list"),
            {
                "vehicle_id": self.vehicle.pk,
                "registration_number": "HR26EV0001",
                "purchase_date": date(2020, 8, 6).isoformat(),
                "current_mileage": 24,
            },
            format="json",
            **headers,
        )

        self.assertEqual(registered.status_code, status.HTTP_201_CREATED)

        service_request = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": registered.data["id"],
                "service_type": "GENERAL_SERVICE",
                "problem_description": "Periodic service",
                "priority": "MEDIUM",
            },
            format="json",
            **headers,
        )

        self.assertEqual(service_request.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CustomerVehicle.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.count(), 1)


class StaffRoleTestCase(APITestCase):
    def authenticate(self, actor, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": actor.external_user_id,
            "email": actor.email,
        }
        return {"HTTP_AUTHORIZATION": f"Bearer token-for-{actor.external_user_id}"}

    def setUp(self):
        self.dealership = factories.create_dealership()
        self.other_dealership = factories.create_dealership()
        self.owner = factories.create_owner(dealership=self.dealership)
        self.admin = factories.create_admin(dealership=self.dealership)
        self.staff = factories.create_staff_employee(dealership=self.dealership)
        self.technician_employee = factories.create_employee(dealership=self.dealership)
        self.technician = factories.create_technician(
            dealership=self.dealership, employee=self.technician_employee
        )
        self.customer = factories.create_customer()


class EmployeeManagementTests(StaffRoleTestCase):
    def payload(self, **overrides):
        data = {
            "first_name": "Kabir",
            "last_name": "Nair",
            "email": "kabir.nair@dealership.test",
            "phone": "9812345678",
            "role": "EMPLOYEE",
        }
        data.update(overrides)
        return data

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_create_employee(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("employee-collection"), self.payload(), format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], "EMPLOYEE")
        self.assertEqual(
            Employee.objects.get(email="kabir.nair@dealership.test").dealership_id,
            self.dealership.pk,
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_admin_can_create_employee(self, mock_verify_token):
        headers = self.authenticate(self.admin, mock_verify_token)

        response = self.client.post(
            reverse("employee-collection"), self.payload(), format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_created_employee_is_always_scoped_to_caller_dealership(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        self.client.post(
            reverse("employee-collection"),
            self.payload(dealership_id=self.other_dealership.pk),
            format="json",
            **headers,
        )

        created = Employee.objects.get(email="kabir.nair@dealership.test")
        self.assertEqual(created.dealership_id, self.dealership.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_role_cannot_be_assigned_through_staff_management(self, mock_verify_token):
        headers = self.authenticate(self.admin, mock_verify_token)

        response = self.client.post(
            reverse("employee-collection"),
            self.payload(role="OWNER"),
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Employee.objects.filter(role=EmployeeRole.OWNER).count() > 1)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_duplicate_email_in_same_dealership_is_rejected(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("employee-collection"),
            self.payload(email=self.staff.email),
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_edit_employee(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.patch(
            reverse("employee-detail", args=[self.staff.pk]),
            {"role": "TECHNICIAN", "phone": "9000000000"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, EmployeeRole.TECHNICIAN)
        self.assertEqual(self.staff.phone, "9000000000")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_deactivate_employee(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.delete(
            reverse("employee-detail", args=[self.staff.pk]), **headers
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_deactivated_technician_is_marked_unavailable(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        self.client.delete(reverse("employee-detail", args=[self.technician_employee.pk]), **headers)

        self.technician.refresh_from_db()
        self.assertFalse(self.technician.is_available)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_inactive_employee_cannot_authenticate(self, mock_verify_token):
        self.client.delete(
            reverse("employee-detail", args=[self.staff.pk]),
            **self.authenticate(self.owner, mock_verify_token),
        )

        headers = self.authenticate(self.staff, mock_verify_token)
        response = self.client.get(reverse("employee-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(CustomerProfile.objects.filter(email=self.staff.email).exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_inactive_technician_cannot_authenticate(self, mock_verify_token):
        self.client.delete(
            reverse("employee-detail", args=[self.technician_employee.pk]),
            **self.authenticate(self.owner, mock_verify_token),
        )

        headers = self.authenticate(self.technician_employee, mock_verify_token)
        response = self.client.get(reverse("technician-assignment-list"), **headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_reactivated_employee_can_authenticate_again(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)
        self.client.delete(reverse("employee-detail", args=[self.staff.pk]), **headers)
        self.client.patch(
            reverse("employee-detail", args=[self.staff.pk]),
            {"is_active": True},
            format="json",
            **headers,
        )

        response = self.client.get(
            reverse("employee-collection"),
            **self.authenticate(self.staff, mock_verify_token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_list_is_limited_to_own_dealership(self, mock_verify_token):
        outsider = factories.create_staff_employee(dealership=self.other_dealership)
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.get(reverse("employee-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed = {row["id"] for row in response.data}
        self.assertIn(self.staff.pk, listed)
        self.assertIn(self.owner.pk, listed)
        self.assertNotIn(outsider.pk, listed)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_cannot_read_or_edit_employee_from_another_dealership(self, mock_verify_token):
        outsider = factories.create_staff_employee(dealership=self.other_dealership)
        headers = self.authenticate(self.owner, mock_verify_token)

        read = self.client.get(reverse("employee-detail", args=[outsider.pk]), **headers)
        edit = self.client.patch(
            reverse("employee-detail", args=[outsider.pk]),
            {"first_name": "Hijacked"},
            format="json",
            **headers,
        )
        remove = self.client.delete(reverse("employee-detail", args=[outsider.pk]), **headers)

        self.assertEqual(read.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(remove.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_cannot_be_edited_or_deactivated_through_staff_management(self, mock_verify_token):
        headers = self.authenticate(self.admin, mock_verify_token)

        edit = self.client.patch(
            reverse("employee-detail", args=[self.owner.pk]),
            {"first_name": "Renamed"},
            format="json",
            **headers,
        )
        remove = self.client.delete(reverse("employee-detail", args=[self.owner.pk]), **headers)

        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(remove.status_code, status.HTTP_403_FORBIDDEN)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertEqual(self.owner.first_name, "Nikhil")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_manage_employees(self, mock_verify_token):
        headers = self.authenticate(self.staff, mock_verify_token)

        listed = self.client.get(reverse("employee-collection"), **headers)
        created = self.client.post(
            reverse("employee-collection"), self.payload(), format="json", **headers
        )

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(created.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_manage_employees(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.get(reverse("employee-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_manage_employees(self, mock_verify_token):
        headers = self.authenticate_customer(mock_verify_token)

        listed = self.client.get(reverse("employee-collection"), **headers)
        created = self.client.post(
            reverse("employee-collection"), self.payload(), format="json", **headers
        )

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(created.status_code, status.HTTP_403_FORBIDDEN)

    def authenticate_customer(self, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": self.customer.external_user_id,
            "email": self.customer.email,
        }
        return {"HTTP_AUTHORIZATION": f"Bearer token-for-{self.customer.external_user_id}"}


class TechnicianManagementTests(StaffRoleTestCase):
    def setUp(self):
        super().setUp()
        self.new_technician = factories.create_employee(
            dealership=self.dealership, role=EmployeeRole.TECHNICIAN
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_list_technicians_for_own_dealership(self, mock_verify_token):
        outsider = factories.create_technician(dealership=self.other_dealership)
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.get(reverse("technician-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed = {row["id"] for row in response.data}
        self.assertEqual(listed, {self.technician.pk})
        self.assertNotIn(outsider.pk, listed)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_create_technician_profile(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("technician-collection"),
            {"employee_id": self.new_technician.pk, "specialization": "BRAKES"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["specialization"], Specialization.BRAKES)
        self.assertEqual(response.data["employee_id"], self.new_technician.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_admin_can_create_technician_profile(self, mock_verify_token):
        headers = self.authenticate(self.admin, mock_verify_token)

        response = self.client.post(
            reverse("technician-collection"),
            {"employee_id": self.new_technician.pk, "specialization": "ELECTRICAL"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_profile_requires_the_technician_role(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("technician-collection"),
            {"employee_id": self.staff.pk, "specialization": "ENGINE"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TechnicianProfile.objects.count(), 1)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_duplicate_profile_is_rejected(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("technician-collection"),
            {"employee_id": self.technician_employee.pk},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_cannot_create_profile_for_another_dealership_employee(self, mock_verify_token):
        outsider = factories.create_employee(
            dealership=self.other_dealership, role=EmployeeRole.TECHNICIAN
        )
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("technician-collection"),
            {"employee_id": outsider.pk, "specialization": "ENGINE"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(TechnicianProfile.objects.filter(employee=outsider).exists())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_update_specialization_and_availability(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.patch(
            reverse("technician-detail", args=[self.technician.pk]),
            {"specialization": "BODYWORK", "is_available": False},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.technician.refresh_from_db()
        self.assertEqual(self.technician.specialization, Specialization.BODYWORK)
        self.assertFalse(self.technician.is_available)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_with_active_assignment_cannot_be_made_available(self, mock_verify_token):
        service_request = factories.create_service_request(dealership=self.dealership)
        factories.create_assignment(service_request=service_request, technician=self.technician)
        headers = self.authenticate(self.admin, mock_verify_token)

        response = self.client.patch(
            reverse("technician-detail", args=[self.technician.pk]),
            {"is_available": True},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_cannot_manage_technician_from_another_dealership(self, mock_verify_token):
        outsider = factories.create_technician(dealership=self.other_dealership)
        headers = self.authenticate(self.owner, mock_verify_token)

        read = self.client.get(reverse("technician-detail", args=[outsider.pk]), **headers)
        edit = self.client.patch(
            reverse("technician-detail", args=[outsider.pk]),
            {"specialization": "ENGINE"},
            format="json",
            **headers,
        )

        self.assertEqual(read.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_and_technician_cannot_manage_technicians(self, mock_verify_token):
        staff_headers = self.authenticate(self.staff, mock_verify_token)
        tech_headers = self.authenticate(self.technician_employee, mock_verify_token)

        self.assertEqual(
            self.client.get(reverse("technician-collection"), **staff_headers).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(reverse("technician-collection"), **tech_headers).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_manage_technicians(self, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": self.customer.external_user_id,
            "email": self.customer.email,
        }
        headers = {"HTTP_AUTHORIZATION": f"Bearer token-for-{self.customer.external_user_id}"}

        listed = self.client.get(reverse("technician-collection"), **headers)
        created = self.client.post(
            reverse("technician-collection"),
            {"employee_id": self.technician_employee.pk},
            format="json",
            **headers,
        )

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(created.status_code, status.HTTP_403_FORBIDDEN)


class WorkQueueAccessTests(StaffRoleTestCase):
    def setUp(self):
        super().setUp()
        self.own_request = factories.create_service_request(dealership=self.dealership)
        self.other_request = factories.create_service_request(
            dealership=self.other_dealership
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_sees_only_own_dealership_service_requests(self, mock_verify_token):
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.get(reverse("service-request-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [self.own_request.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_can_filter_own_dealership_service_requests(self, mock_verify_token):
        factories.create_service_request(
            dealership=self.dealership, status=ServiceStatus.COMPLETED
        )
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.get(
            reverse("service-request-collection"), {"status": "COMPLETED"}, **headers
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], ServiceStatus.COMPLETED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_can_assign_own_dealership_technician(self, mock_verify_token):
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.post(
            reverse("service-request-assignment", args=[self.own_request.pk]),
            {"technician_id": self.technician.pk, "notes": "Full service"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["technician"], self.technician.pk)
        self.own_request.refresh_from_db()
        self.assertEqual(self.own_request.status, ServiceStatus.CONFIRMED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_assign_technician_from_another_dealership(self, mock_verify_token):
        outsider = factories.create_technician(dealership=self.other_dealership)
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.post(
            reverse("service-request-assignment", args=[self.own_request.pk]),
            {"technician_id": outsider.pk},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(TechnicianAssignment.objects.count(), 0)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_assign_on_another_dealership_request(self, mock_verify_token):
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.post(
            reverse("service-request-assignment", args=[self.other_request.pk]),
            {"technician_id": self.technician.pk},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_assign_technicians(self, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": self.customer.external_user_id,
            "email": self.customer.email,
        }
        headers = {"HTTP_AUTHORIZATION": f"Bearer token-for-{self.customer.external_user_id}"}

        response = self.client.post(
            reverse("service-request-assignment", args=[self.own_request.pk]),
            {"technician_id": self.technician.pk},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_only_sees_assigned_service_requests(self, mock_verify_token):
        assigned = factories.create_assignment(
            service_request=self.own_request, technician=self.technician
        )
        self.assertIsNotNone(assigned.pk)
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.get(reverse("service-request-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [self.own_request.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_without_profile_sees_no_service_requests(self, mock_verify_token):
        bare = factories.create_employee(dealership=self.dealership)
        factories.create_service_request(dealership=self.dealership)
        headers = self.authenticate(bare, mock_verify_token)

        response = self.client.get(reverse("service-request-collection"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_can_advance_appointment_status(self, mock_verify_token):
        appointment = factories.create_appointment(dealership=self.dealership)
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.patch(
            reverse("appointment-status", args=[appointment.pk]),
            {"status": "CONFIRMED"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_update_another_dealership_appointment(self, mock_verify_token):
        appointment = factories.create_appointment(dealership=self.other_dealership)
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.patch(
            reverse("appointment-status", args=[appointment.pk]),
            {"status": "CONFIRMED"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "PENDING")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_invalid_status_transition_is_rejected(self, mock_verify_token):
        appointment = factories.create_appointment(
            dealership=self.dealership, status="PENDING"
        )
        headers = self.authenticate(self.staff, mock_verify_token)

        response = self.client.patch(
            reverse("appointment-status", args=[appointment.pk]),
            {"status": "COMPLETED"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_read_dealership_appointments(self, mock_verify_token):
        factories.create_appointment(dealership=self.dealership)
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.get(reverse("appointment-list"), **headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_update_appointment_status(self, mock_verify_token):
        appointment = factories.create_appointment(dealership=self.dealership)
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.patch(
            reverse("appointment-status", args=[appointment.pk]),
            {"status": "CONFIRMED"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_list_own_dealership_appointments(self, mock_verify_token):
        factories.create_appointment(customer=self.customer, dealership=self.dealership)
        other_customer = factories.create_customer()
        factories.create_appointment(customer=other_customer, dealership=self.other_dealership)

        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.get(reverse("appointment-list"), {}, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["dealership"], self.dealership.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_list_own_dealership_service_requests(self, mock_verify_token):
        factories.create_service_request(dealership=self.dealership)
        factories.create_service_request(dealership=self.other_dealership)

        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.get(reverse("service-request-collection"), {}, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        for item in response.data:
            self.assertEqual(item["dealership"], self.dealership.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_can_list_own_dealership_technicians(self, mock_verify_token):
        other_tech = factories.create_technician(dealership=self.other_dealership)
        factories.create_technician(dealership=self.dealership)

        headers = self.authenticate(self.owner, mock_verify_token)

        response = self.client.get(reverse("technician-collection"), {}, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        for item in response.data:
            self.assertNotEqual(item["employee_id"], other_tech.employee_id)


class TechnicianWorkAccessTests(StaffRoleTestCase):
    def setUp(self):
        super().setUp()
        self.service_request = factories.create_service_request(dealership=self.dealership)
        self.assignment = factories.create_assignment(
            service_request=self.service_request,
            technician=self.technician,
            status=AssignmentStatus.ASSIGNED,
        )
        self.other_technician = factories.create_technician(
            dealership=self.dealership
        )
        self.other_assignment = factories.create_assignment(
            service_request=factories.create_service_request(dealership=self.dealership),
            technician=self.other_technician,
            status=AssignmentStatus.ASSIGNED,
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_sees_only_own_assignments(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.get(reverse("technician-assignment-list"), **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [self.assignment.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_can_start_own_assignment(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "start"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.IN_PROGRESS)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_can_complete_own_assignment_with_service_record(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)
        self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "start"},
            format="json",
            **headers,
        )

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {
                "action": "complete",
                "description": "Replaced engine oil and filters",
                "parts_cost": "3200.00",
                "labor_cost": "1800.00",
            },
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.COMPLETED)
        self.service_request.refresh_from_db()
        self.assertEqual(self.service_request.status, ServiceStatus.COMPLETED)
        self.assertEqual(ServiceRecord.objects.count(), 1)
        self.assertEqual(str(ServiceRecord.objects.get().total_cost), "5000.00")
        self.technician.refresh_from_db()
        self.assertTrue(self.technician.is_available)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_start_another_technicians_assignment(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.other_assignment.pk]),
            {"action": "start"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.other_assignment.refresh_from_db()
        self.assertEqual(self.other_assignment.status, AssignmentStatus.ASSIGNED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_cannot_complete_another_technicians_assignment(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.other_assignment.pk]),
            {"action": "complete", "description": "Should not be allowed"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ServiceRecord.objects.count(), 0)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_act_on_assignments_through_my_work_endpoint(self, mock_verify_token):
        headers = self.authenticate(self.staff, mock_verify_token)

        listed = self.client.get(reverse("technician-assignment-list"), **headers)

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_cannot_act_on_assignments_through_my_work_endpoint(self, mock_verify_token):
        headers = self.authenticate(self.owner, mock_verify_token)

        listed = self.client.get(reverse("technician-assignment-list"), **headers)

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_reach_technician_work(self, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": self.customer.external_user_id,
            "email": self.customer.email,
        }
        headers = {"HTTP_AUTHORIZATION": f"Bearer token-for-{self.customer.external_user_id}"}

        listed = self.client.get(reverse("technician-assignment-list"), **headers)
        completed = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "complete", "description": "Should not be allowed"},
            format="json",
            **headers,
        )

        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(completed.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_assignment_action_must_be_start_or_complete(self, mock_verify_token):
        headers = self.authenticate(self.technician_employee, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "cancel"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.ASSIGNED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_without_profile_cannot_start_work(self, mock_verify_token):
        bare = factories.create_employee(dealership=self.dealership)
        headers = self.authenticate(bare, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "start"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_cross_dealership_when_acting_on_assignments(self, mock_verify_token):
        outsider_employee = factories.create_staff_employee(dealership=self.other_dealership)
        headers = self.authenticate(outsider_employee, mock_verify_token)

        response = self.client.post(
            reverse("technician-assignment-detail", args=[self.assignment.pk]),
            {"action": "start"},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)