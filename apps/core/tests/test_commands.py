from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.management.commands.create_owner import create_supabase_auth_user
from apps.core.models import Dealership, Employee
from apps.core.tests import factories

CREATE_OWNER = "apps.core.management.commands.create_owner.create_supabase_auth_user"


class CreateOwnerCommandTests(TestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()

    def call_command(self, **overrides):
        options = {
            "first_name": "Nikhil",
            "last_name": "Sharma",
            "email": "owner-intent@example.test",
            "password": "owner-password-1",
            "dealership_id": self.dealership.pk,
        }
        options.update(overrides)
        return call_command("create_owner", **options)

    @patch(CREATE_OWNER, return_value="supabase-owner-uuid-1")
    def test_owner_provisioning_creates_one_owner(self, mock_create):
        self.call_command()

        owner = Employee.objects.get(dealership=self.dealership)
        self.assertEqual(owner.role, "OWNER")
        self.assertEqual(owner.email, "owner-intent@example.test")
        self.assertEqual(owner.external_user_id, "supabase-owner-uuid-1")
        self.assertEqual(
            Employee.objects.filter(dealership=self.dealership, role="OWNER").count(), 1
        )
        mock_create.assert_called_once_with("owner-intent@example.test", "owner-password-1")

    @patch(CREATE_OWNER, return_value="supabase-owner-uuid-1")
    def test_second_owner_for_same_dealership_is_refused(self, mock_create):
        self.call_command()

        with self.assertRaises(CommandError) as ctx:
            self.call_command(email="second-owner@example.test")

        self.assertIn("already has an owner", str(ctx.exception))
        self.assertEqual(
            Employee.objects.filter(dealership=self.dealership, role="OWNER").count(), 1
        )
        self.assertFalse(
            Employee.objects.filter(email="second-owner@example.test").exists()
        )

    @patch(CREATE_OWNER, return_value="supabase-owner-uuid-1")
    def test_failed_second_owner_does_not_create_a_supabase_user(self, mock_create):
        self.call_command()
        mock_create.reset_mock()

        with self.assertRaises(CommandError):
            self.call_command(email="second-owner@example.test")

        mock_create.assert_not_called()

    @patch(CREATE_OWNER, side_effect=Exception("supabase unreachable"))
    def test_supabase_failure_rolls_back_local_owner(self, mock_create):
        with self.assertRaises(Exception):
            self.call_command()

        self.assertEqual(Employee.objects.count(), 0)
        self.assertFalse(Employee.objects.filter(email="owner-intent@example.test").exists())

    @patch(CREATE_OWNER)
    def test_duplicate_employee_email_is_refused_before_supabase_call(self, mock_create):
        factories.create_employee(email="owner-intent@example.test")

        with self.assertRaises(CommandError):
            self.call_command()

        mock_create.assert_not_called()

    @patch(CREATE_OWNER)
    def test_duplicate_email_after_owner_exists_does_not_duplicate_supabase_call(self, mock_create):
        with self.assertRaises(CommandError):
            self.call_command(password="short")

        mock_create.assert_not_called()
        self.assertEqual(Employee.objects.count(), 0)

    @patch(CREATE_OWNER)
    def test_short_password_without_supabase_user_id_is_refused(self, mock_create):
        with self.assertRaises(CommandError) as ctx:
            self.call_command(password="short")

        self.assertIn("at least 8 characters", str(ctx.exception))
        self.assertEqual(Employee.objects.count(), 0)

    def test_existing_supabase_user_can_be_linked_without_signup(self):
        self.call_command(password="", supabase_user_id="existing-supabase-uuid-9")

        owner = Employee.objects.get(dealership=self.dealership)
        self.assertEqual(owner.external_user_id, "existing-supabase-uuid-9")
        self.assertEqual(owner.role, "OWNER")

    def test_unknown_dealership_is_rejected(self):
        with self.assertRaises(CommandError):
            self.call_command(dealership_id=999999)

    def test_dealership_can_be_created_during_setup(self):
        self.call_command(
            dealership_id=None,
            dealership_name="AutoFlow Motors Baner",
            address="21 Baner Road",
            city="Pune",
            state="Maharashtra",
            postal_code="411045",
            phone="9822001100",
            dealership_email="baner@example.test",
            supabase_user_id="supabase-uuid-baner",
        )

        owner = Employee.objects.get(email="owner-intent@example.test")
        self.assertEqual(owner.dealership.name, "AutoFlow Motors Baner")
        self.assertEqual(owner.role, "OWNER")

    def test_owner_link_via_existing_supabase_user_creates_single_owner_row(self):
        self.call_command(supabase_user_id="supabase-uuid-signup")

        self.assertEqual(Employee.objects.filter(role="OWNER").count(), 1)
        self.assertEqual(Employee.objects.filter(dealership=self.dealership).count(), 1)

    def test_owner_uniqueness_is_enforced_in_the_database(self):
        factories.create_owner(dealership=self.dealership)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                factories.create_owner(dealership=self.dealership)

        self.assertEqual(
            Employee.objects.filter(dealership=self.dealership, role="OWNER").count(), 1
        )

    def test_each_dealership_may_have_its_own_owner(self):
        other = factories.create_dealership()

        self.call_command(email="owner-a@example.test", supabase_user_id="supabase-uuid-a")
        self.call_command(
            dealership_id=other.pk,
            email="owner-b@example.test",
            supabase_user_id="supabase-uuid-b",
        )

        self.assertEqual(Employee.objects.filter(role="OWNER").count(), 2)
        self.assertEqual(
            Employee.objects.filter(dealership=other, role="OWNER").count(), 1
        )


class CreateSupabaseAuthUserTests(TestCase):
    @patch("apps.core.management.commands.create_owner.httpx.post")
    def test_signup_returns_user_id(self, mock_post):
        mock_post.return_value = _response(200, {"id": "supabase-uuid-1"})

        user_id = create_supabase_auth_user("owner@example.test", "password-123")

        self.assertEqual(user_id, "supabase-uuid-1")

    @patch("apps.core.management.commands.create_owner.httpx.post")
    def test_signup_error_is_surfaced(self, mock_post):
        mock_post.return_value = _response(422, {"msg": "User already registered"})

        with self.assertRaises(Exception) as ctx:
            create_supabase_auth_user("owner@example.test", "password-123")

        self.assertIn("already registered", str(ctx.exception))

    @patch("apps.core.management.commands.create_owner.httpx.post")
    def test_missing_user_id_is_reported(self, mock_post):
        mock_post.return_value = _response(200, {"access_token": "only-token"})

        with self.assertRaises(Exception) as ctx:
            create_supabase_auth_user("owner@example.test", "password-123")

        self.assertIn("did not return a user id", str(ctx.exception))

    @patch("apps.core.management.commands.create_owner.httpx.post")
    def test_nested_user_payload_is_supported(self, mock_post):
        mock_post.return_value = _response(200, {"user": {"id": "supabase-uuid-2"}})

        self.assertEqual(
            create_supabase_auth_user("owner@example.test", "password-123"),
            "supabase-uuid-2",
        )


class SeedShowroomInventoryCommandTests(TestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()

    def test_seed_populates_indian_inventory(self):
        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)

        self.assertGreater(self._vehicle_count(), 15)
        self.assertTrue(self.dealership.vehicles.filter(brand="Maruti Suzuki").exists())

    def test_seed_is_idempotent(self):
        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)
        first_count = self._vehicle_count()

        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)
        second_count = self._vehicle_count()

        self.assertEqual(first_count, second_count)
        self.assertGreater(first_count, 15)

    def test_seed_contains_required_models(self):
        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)

        models = set(
            self.dealership.vehicles.values_list("model", flat=True)
        )
        self.assertTrue(
            {
                "Wagon R",
                "Swift",
                "Brezza",
                "Grand Vitara",
                "Punch",
                "Nexon",
                "Harrier",
                "Safari",
                "Creta",
                "Verna",
                "Venue",
                "Thar",
                "Scorpio-N",
                "XUV700",
                "Fortuner",
                "Innova HyCross",
                "Seltos",
                "Virtus",
                "Slavia",
                "Defender 110",
            }.issubset(models)
        )

    def test_seeded_prices_are_positive_inr_amounts(self):
        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)

        for vehicle in self.dealership.vehicles.all():
            self.assertGreater(float(vehicle.price), 0)

    def test_seeded_vehicles_are_available(self):
        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)

        self.assertEqual(
            self.dealership.vehicles.filter(is_available=True).count(),
            self.dealership.vehicles.count(),
        )

    def test_seed_does_not_touch_other_dealerships(self):
        other = factories.create_dealership()

        call_command("seed_showroom_inventory", dealership_id=self.dealership.pk)

        self.assertEqual(other.vehicles.count(), 0)

    def test_seed_requires_a_dealership_when_none_exist(self):
        Dealership.objects.all().delete()

        with self.assertRaises(CommandError):
            call_command("seed_showroom_inventory")

    def _vehicle_count(self):
        return self.dealership.vehicles.count()


def _response(status_code, payload):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return payload

    return FakeResponse()