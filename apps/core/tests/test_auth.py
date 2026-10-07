from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from rest_framework import status, exceptions
from rest_framework.test import APITestCase
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError

from apps.core.authentication.supabase import SupabaseJWTAuthentication, SupabaseUser
from apps.core.models import CustomerProfile, Employee
from apps.core.models.choices import EmployeeRole
from apps.core.tests import factories


class SupabaseUserTests(TestCase):
    def test_customer_user_properties(self):
        customer = factories.create_customer()
        user = SupabaseUser(
            supabase_user_id="auth-123",
            email="test@example.com",
            role="CUSTOMER",
            customer_profile=customer,
        )

        self.assertTrue(user.is_customer)
        self.assertFalse(user.is_employee)
        self.assertFalse(user.is_technician)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_employee_or_admin)
        self.assertFalse(user.is_technician_or_admin)
        self.assertIsNone(user.dealership_id)

    def test_employee_user_properties(self):
        employee = factories.create_staff_employee()
        user = SupabaseUser(
            supabase_user_id="auth-456",
            email="staff@example.com",
            role="EMPLOYEE",
            employee_profile=employee,
        )

        self.assertFalse(user.is_customer)
        self.assertTrue(user.is_employee)
        self.assertFalse(user.is_technician)
        self.assertFalse(user.is_admin)
        self.assertTrue(user.is_employee_or_admin)
        self.assertFalse(user.is_technician_or_admin)
        self.assertEqual(user.dealership_id, employee.dealership_id)

    def test_technician_user_properties(self):
        technician = factories.create_technician()
        user = SupabaseUser(
            supabase_user_id="auth-789",
            email="tech@example.com",
            role="TECHNICIAN",
            employee_profile=technician.employee,
        )

        self.assertFalse(user.is_customer)
        self.assertTrue(user.is_employee)
        self.assertTrue(user.is_technician)
        self.assertFalse(user.is_admin)
        self.assertTrue(user.is_employee_or_admin)
        self.assertTrue(user.is_technician_or_admin)
        self.assertEqual(user.dealership_id, technician.employee.dealership_id)

    def test_admin_user_properties(self):
        admin = factories.create_admin()
        user = SupabaseUser(
            supabase_user_id="auth-999",
            email="admin@example.com",
            role="ADMIN",
            employee_profile=admin,
        )

        self.assertFalse(user.is_customer)
        self.assertTrue(user.is_employee)
        self.assertFalse(user.is_technician)
        self.assertTrue(user.is_admin)
        self.assertTrue(user.is_employee_or_admin)
        self.assertTrue(user.is_technician_or_admin)
        self.assertEqual(user.dealership_id, admin.dealership_id)


class SupabaseJWTAuthenticationTests(TestCase):
    def setUp(self):
        self.auth = SupabaseJWTAuthentication()
        self.customer = factories.create_customer(external_user_id="auth-cust-test-1")
        self.employee = factories.create_staff_employee(external_user_id="auth-emp-test-1")
        self.technician = factories.create_technician()
        self.technician.employee.external_user_id = "auth-tech-test-1"
        self.technician.employee.save()
        self.admin = factories.create_admin(external_user_id="auth-admin-test-1")

    def test_missing_token_returns_none(self):
        request = MagicMock()
        request.headers = {}
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_invalid_auth_header_raises_error(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer"}
        with self.assertRaisesMessage(Exception, "No credentials provided"):
            self.auth.authenticate(request)

    def test_expired_token_raises_error(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer expired.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.side_effect = ExpiredSignatureError("Token has expired")
            with self.assertRaisesMessage(exceptions.AuthenticationFailed, "Token has expired"):
                self.auth.authenticate(request)

    def test_invalid_token_raises_error(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer invalid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.side_effect = JWTError("Invalid token")
            with self.assertRaisesMessage(exceptions.AuthenticationFailed, "Invalid token: Invalid token"):
                self.auth.authenticate(request)

    def test_first_time_supabase_user_is_provisioned(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "unknown-user-id",
                "email": "unknown@example.com",
            }
            result = self.auth.authenticate(request)

        user, _ = result
        self.assertTrue(user.is_customer)
        self.assertEqual(user.customer_profile.external_user_id, "unknown-user-id")
        self.assertEqual(user.customer_profile.email, "unknown@example.com")

    def test_valid_customer_token_returns_user(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "auth-cust-test-1",
                "email": self.customer.email,
            }
            result = self.auth.authenticate(request)
            self.assertIsNotNone(result)
            user, _ = result
            self.assertIsInstance(user, SupabaseUser)
            self.assertTrue(user.is_customer)
            self.assertEqual(user.customer_profile.pk, self.customer.pk)

    def test_valid_employee_token_returns_user(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "auth-emp-test-1",
                "email": self.employee.email,
            }
            result = self.auth.authenticate(request)
            self.assertIsNotNone(result)
            user, _ = result
            self.assertIsInstance(user, SupabaseUser)
            self.assertTrue(user.is_employee)
            self.assertEqual(user.employee_profile.pk, self.employee.pk)

    def test_valid_technician_token_returns_user(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "auth-tech-test-1",
                "email": self.technician.employee.email,
            }
            result = self.auth.authenticate(request)
            self.assertIsNotNone(result)
            user, _ = result
            self.assertIsInstance(user, SupabaseUser)
            self.assertTrue(user.is_technician)
            self.assertEqual(user.employee_profile.pk, self.technician.employee.pk)

    def test_valid_admin_token_returns_user(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "auth-admin-test-1",
                "email": self.admin.email,
            }
            result = self.auth.authenticate(request)
            self.assertIsNotNone(result)
            user, _ = result
            self.assertIsInstance(user, SupabaseUser)
            self.assertTrue(user.is_admin)
            self.assertEqual(user.employee_profile.pk, self.admin.pk)

    def test_token_without_sub_claim_raises_error(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.token.here"}

        with patch.object(self.auth, "_verify_token") as mock_verify:
            mock_verify.return_value = {"email": "test@example.com"}
            with self.assertRaisesMessage(Exception, "Token missing subject claim"):
                self.auth.authenticate(request)


class TokenVerificationTests(TestCase):
    def setUp(self):
        self.auth = SupabaseJWTAuthentication()
        self.issuer = f"{settings.SUPABASE_URL}/auth/v1"
        self.claims = {
            "sub": "sub-verification-1",
            "email": "verify@example.com",
            "aud": "authenticated",
            "iss": self.issuer,
            "role": "authenticated",
            "iat": 1700000000,
            "exp": 4102444800,
        }

    def _es256(self, kid="es-kid-1", **overrides):
        from cryptography.hazmat.primitives.asymmetric import ec
        from jose.backends import ECKey

        key = ec.generate_private_key(ec.SECP256R1())
        public_jwk = ECKey(key.public_key(), "ES256").to_dict()
        public_jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
        token = jwt.encode(
            dict(self.claims, **overrides), key, algorithm="ES256", headers={"kid": kid}
        )
        return token, {"keys": [public_jwk]}

    def _rs256(self, kid="rsa-kid-1", **overrides):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from jose.backends import RSAKey

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_jwk = RSAKey(public_pem, "RS256").to_dict()
        public_jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
        token = jwt.encode(
            dict(self.claims, **overrides),
            RSAKey(private_pem, "RS256"),
            algorithm="RS256",
            headers={"kid": kid},
        )
        return token, {"keys": [public_jwk]}

    def _verify(self, token, jwks):
        self.auth._jwks_cache = jwks
        return self.auth._verify_token(token)

    def test_es256_token_is_accepted(self):
        token, jwks = self._es256()

        payload = self._verify(token, jwks)

        self.assertEqual(payload["sub"], self.claims["sub"])
        self.assertEqual(payload["email"], self.claims["email"])

    def test_rs256_token_is_accepted(self):
        token, jwks = self._rs256()

        payload = self._verify(token, jwks)

        self.assertEqual(payload["sub"], self.claims["sub"])

    def test_unsupported_algorithm_is_rejected(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        key = ec.generate_private_key(ec.SECP256R1())
        token = jwt.encode(
            dict(self.claims),
            "shared-secret-value-long-enough-for-hs256",
            algorithm="HS256",
            headers={"kid": "es-kid-1"},
        )

        with self.assertRaisesMessage(JWTError, "Unsupported signing algorithm"):
            self._verify(token, {"keys": []})

    def test_unknown_kid_is_rejected(self):
        token, _ = self._es256(kid="not-in-set")

        with self.assertRaisesMessage(JWTError, "Unable to find matching key"):
            self._verify(token, {"keys": []})

    def test_algorithm_mismatch_with_key_is_rejected(self):
        token, jwks = self._es256()
        mismatched = dict(jwks["keys"][0])
        mismatched["alg"] = "RS256"

        with self.assertRaisesMessage(JWTError, "does not match the signing key"):
            self._verify(token, {"keys": [mismatched]})

    def test_key_type_mismatch_is_rejected(self):
        token, jwks = self._es256()
        mismatched = dict(jwks["keys"][0])
        mismatched["kty"] = "RSA"

        with self.assertRaisesMessage(JWTError, "key type does not match"):
            self._verify(token, {"keys": [mismatched]})

    def test_tampered_token_is_rejected(self):
        token, jwks = self._es256()
        header, payload, signature = token.split(".")
        tampered = ".".join([header, payload, signature[:-4] + "AAAA"])

        with self.assertRaises(JWTError):
            self._verify(tampered, jwks)

    def test_expired_token_is_rejected(self):
        token, jwks = self._es256(exp=1700000001)

        with self.assertRaises(ExpiredSignatureError):
            self._verify(token, jwks)

    def test_wrong_audience_is_rejected(self):
        token, jwks = self._es256(aud="some-other-audience")

        with self.assertRaises(JWTClaimsError):
            self._verify(token, jwks)

    def test_wrong_issuer_is_rejected(self):
        token, jwks = self._es256(iss="https://evil.example.com/auth/v1")

        with self.assertRaises(JWTClaimsError):
            self._verify(token, jwks)


class ProfileProvisioningTests(TestCase):
    def setUp(self):
        self.auth = SupabaseJWTAuthentication()

    def _authenticate(self, payload):
        request = MagicMock()
        request.headers = {"authorization": "Bearer token"}
        with patch.object(self.auth, "_verify_token", return_value=payload):
            return self.auth.authenticate(request)[0]

    def test_new_supabase_user_is_provisioned_as_customer(self):
        user = self._authenticate(
            {"sub": "new-sub-1", "email": "brand.new@example.com"}
        )

        self.assertTrue(user.is_customer)
        self.assertEqual(user.customer_profile.external_user_id, "new-sub-1")
        self.assertEqual(user.customer_profile.email, "brand.new@example.com")

    def test_public_signup_claiming_owner_role_is_ignored(self):
        user = self._authenticate(
            {
                "sub": "new-sub-owner-claim",
                "email": "sneaky@example.com",
                "role": "OWNER",
                "app_metadata": {"role": "OWNER"},
                "user_metadata": {"role": "OWNER", "full_name": "Sneaky Owner"},
            }
        )

        self.assertEqual(user.role, "CUSTOMER")
        self.assertTrue(user.is_customer)
        self.assertFalse(user.is_owner)
        self.assertFalse(user.is_owner_or_admin)
        self.assertFalse(user.is_employee)
        self.assertEqual(Employee.objects.filter(role="OWNER").count(), 0)

    def test_provisioning_uses_supabase_metadata_name_when_present(self):
        user = self._authenticate(
            {
                "sub": "new-sub-2",
                "email": "named@example.com",
                "user_metadata": {"full_name": "Ada Lovelace"},
            }
        )

        self.assertEqual(user.customer_profile.first_name, "Ada")
        self.assertEqual(user.customer_profile.last_name, "Lovelace")

    def test_provisioning_falls_back_to_email_when_metadata_is_empty(self):
        user = self._authenticate(
            {
                "sub": "new-sub-3",
                "email": "grace.hopper@example.com",
                "user_metadata": {"full_name": ""},
            }
        )

        self.assertEqual(user.customer_profile.first_name, "grace")
        self.assertEqual(user.customer_profile.last_name, "hopper")

    def test_existing_customer_is_linked_by_email(self):
        existing = factories.create_customer(
            external_user_id=None, email="linked@example.com"
        )

        user = self._authenticate({"sub": "link-sub-1", "email": "linked@example.com"})

        existing.refresh_from_db()
        self.assertEqual(existing.external_user_id, "link-sub-1")
        self.assertEqual(user.customer_profile.pk, existing.pk)

    def test_repeated_login_does_not_create_duplicate_profiles(self):
        payload = {"sub": "repeat-sub-1", "email": "repeat@example.com"}

        first = self._authenticate(payload)
        second = self._authenticate(payload)

        self.assertEqual(first.customer_profile.pk, second.customer_profile.pk)
        self.assertEqual(CustomerProfile.objects.filter(email="repeat@example.com").count(), 1)

    def test_email_already_linked_to_another_account_is_rejected(self):
        factories.create_customer(external_user_id="someone-else", email="taken@example.com")

        with self.assertRaisesMessage(
            exceptions.AuthenticationFailed, "different account"
        ):
            self._authenticate({"sub": "intruder-sub", "email": "taken@example.com"})

    def test_missing_email_claim_is_rejected(self):
        with self.assertRaisesMessage(
            exceptions.AuthenticationFailed, "missing email claim"
        ):
            self._authenticate({"sub": "no-email-sub"})

    def test_employee_is_not_shadowed_by_customer_provisioning(self):
        employee = factories.create_staff_employee(external_user_id="staff-sub-1")

        user = self._authenticate(
            {"sub": "staff-sub-1", "email": employee.email}
        )

        self.assertTrue(user.is_employee)
        self.assertIsNone(user.customer_profile)
        self.assertEqual(CustomerProfile.objects.filter(email=employee.email).count(), 0)


class PermissionClassesTests(TestCase):
    def setUp(self):
        self.customer = factories.create_customer()
        self.employee = factories.create_staff_employee()
        self.technician = factories.create_technician()
        self.admin = factories.create_admin()

        self.customer_user = SupabaseUser(
            supabase_user_id="auth-1", email="c@test.com", role="CUSTOMER", customer_profile=self.customer
        )
        self.employee_user = SupabaseUser(
            supabase_user_id="auth-2", email="e@test.com", role="EMPLOYEE", employee_profile=self.employee
        )
        self.technician_user = SupabaseUser(
            supabase_user_id="auth-3", email="t@test.com", role="TECHNICIAN", employee_profile=self.technician.employee
        )
        self.admin_user = SupabaseUser(
            supabase_user_id="auth-4", email="a@test.com", role="ADMIN", employee_profile=self.admin
        )

    def test_is_authenticated_allows_any_authenticated(self):
        from apps.core.authentication.permissions import IsAuthenticated

        perm = IsAuthenticated()
        request = MagicMock()
        request.user = self.customer_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.employee_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = None
        self.assertFalse(perm.has_permission(request, None))

    def test_is_customer_only_allows_customer(self):
        from apps.core.authentication.permissions import IsCustomer

        perm = IsCustomer()
        request = MagicMock()
        request.user = self.customer_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.employee_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.technician_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.admin_user
        self.assertFalse(perm.has_permission(request, None))

    def test_is_employee_allows_employee_technician_admin(self):
        from apps.core.authentication.permissions import IsEmployee

        perm = IsEmployee()
        request = MagicMock()

        request.user = self.employee_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.technician_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.admin_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.customer_user
        self.assertFalse(perm.has_permission(request, None))

    def test_is_technician_only_allows_technician(self):
        from apps.core.authentication.permissions import IsTechnician

        perm = IsTechnician()
        request = MagicMock()

        request.user = self.technician_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.employee_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.admin_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.customer_user
        self.assertFalse(perm.has_permission(request, None))

    def test_is_admin_only_allows_admin(self):
        from apps.core.authentication.permissions import IsAdmin

        perm = IsAdmin()
        request = MagicMock()

        request.user = self.admin_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.technician_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.employee_user
        self.assertFalse(perm.has_permission(request, None))

    def test_is_employee_or_admin(self):
        from apps.core.authentication.permissions import IsEmployeeOrAdmin

        perm = IsEmployeeOrAdmin()
        request = MagicMock()

        request.user = self.employee_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.technician_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.admin_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.customer_user
        self.assertFalse(perm.has_permission(request, None))

    def test_is_technician_or_admin(self):
        from apps.core.authentication.permissions import IsTechnicianOrAdmin

        perm = IsTechnicianOrAdmin()
        request = MagicMock()

        request.user = self.technician_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.admin_user
        self.assertTrue(perm.has_permission(request, None))

        request.user = self.employee_user
        self.assertFalse(perm.has_permission(request, None))

        request.user = self.customer_user
        self.assertFalse(perm.has_permission(request, None))


class OwnershipPermissionTests(TestCase):
    def setUp(self):
        self.customer = factories.create_customer()
        self.other_customer = factories.create_customer()
        self.customer_user = SupabaseUser(
            supabase_user_id="auth-1", email="c@test.com", role="CUSTOMER", customer_profile=self.customer
        )
        self.other_customer_user = SupabaseUser(
            supabase_user_id="auth-2", email="c2@test.com", role="CUSTOMER", customer_profile=self.other_customer
        )

        self.dealership = factories.create_dealership()
        self.employee = factories.create_staff_employee(dealership=self.dealership)
        self.other_dealership = factories.create_dealership()
        self.other_employee = factories.create_staff_employee(dealership=self.other_dealership)

        self.employee_user = SupabaseUser(
            supabase_user_id="auth-3", email="e@test.com", role="EMPLOYEE", employee_profile=self.employee
        )
        self.other_employee_user = SupabaseUser(
            supabase_user_id="auth-4", email="e2@test.com", role="EMPLOYEE", employee_profile=self.other_employee
        )

        self.technician = factories.create_technician(dealership=self.dealership)
        self.technician_user = SupabaseUser(
            supabase_user_id="auth-5", email="t@test.com", role="TECHNICIAN", employee_profile=self.technician.employee
        )

    def test_customer_can_access_own_appointment(self):
        from apps.core.authentication.permissions import CanAccessCustomerResource

        perm = CanAccessCustomerResource()
        appointment = factories.create_appointment(customer=self.customer)
        request = MagicMock()
        request.user = self.customer_user
        self.assertTrue(perm.has_object_permission(request, None, appointment))

    def test_customer_cannot_access_other_customer_appointment(self):
        from apps.core.authentication.permissions import CanAccessCustomerResource

        perm = CanAccessCustomerResource()
        appointment = factories.create_appointment(customer=self.other_customer)
        request = MagicMock()
        request.user = self.customer_user
        self.assertFalse(perm.has_object_permission(request, None, appointment))

    def test_employee_can_access_dealership_appointment(self):
        from apps.core.authentication.permissions import CanAccessCustomerResource

        perm = CanAccessCustomerResource()
        appointment = factories.create_appointment(dealership=self.dealership)
        request = MagicMock()
        request.user = self.employee_user
        self.assertTrue(perm.has_object_permission(request, None, appointment))

    def test_employee_cannot_access_other_dealership_appointment(self):
        from apps.core.authentication.permissions import CanAccessCustomerResource

        perm = CanAccessCustomerResource()
        appointment = factories.create_appointment(dealership=self.other_dealership)
        request = MagicMock()
        request.user = self.employee_user
        self.assertFalse(perm.has_object_permission(request, None, appointment))

    def test_technician_can_access_assigned_service_request(self):
        from apps.core.authentication.permissions import IsTechnicianAssigned

        perm = IsTechnicianAssigned()
        service_request = factories.create_service_request()
        factories.create_assignment(service_request=service_request, technician=self.technician)

        request = MagicMock()
        request.user = self.technician_user
        self.assertTrue(perm.has_object_permission(request, None, service_request))

    def test_technician_cannot_access_unassigned_service_request(self):
        from apps.core.authentication.permissions import IsTechnicianAssigned

        perm = IsTechnicianAssigned()
        other_technician = factories.create_technician(dealership=self.dealership)
        service_request = factories.create_service_request()
        factories.create_assignment(service_request=service_request, technician=other_technician)

        request = MagicMock()
        request.user = self.technician_user
        self.assertFalse(perm.has_object_permission(request, None, service_request))

    def test_dealership_member_permission(self):
        from apps.core.authentication.permissions import IsDealershipMember

        perm = IsDealershipMember()
        request = MagicMock()
        request.user = self.employee_user
        request.query_params = {"dealership": str(self.dealership.pk)}
        view = MagicMock()
        view.kwargs = {}
        self.assertTrue(perm.has_permission(request, view))

        request.query_params = {"dealership": str(self.other_dealership.pk)}
        self.assertFalse(perm.has_permission(request, view))


class APITests(APITestCase):
    def setUp(self):
        self.customer = factories.create_customer(external_user_id="auth-cust-api-1")
        self.other_customer = factories.create_customer(external_user_id="auth-cust-api-2")
        self.dealership = factories.create_dealership()
        self.employee = factories.create_staff_employee(dealership=self.dealership, external_user_id="auth-emp-api-1")
        self.technician = factories.create_technician(dealership=self.dealership)
        self.technician.employee.external_user_id = "auth-tech-api-1"
        self.technician.employee.save()
        self.admin = factories.create_admin(dealership=self.dealership, external_user_id="auth-admin-api-1")
        self.vehicle = factories.create_vehicle(dealership=self.dealership)

    def _auth_header(self, user_id):
        return {"HTTP_AUTHORIZATION": f"Bearer fake-token-for-{user_id}"}

    def _mock_auth(self, mock_verify_token, sub, email):
        mock_verify_token.return_value = {"sub": sub, "email": email}

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_health_endpoint_public(self, mock_verify_token):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "ok"})

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_vehicles_available_public(self, mock_verify_token):
        response = self.client.get(reverse("vehicle-available-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_create_test_drive_requires_auth(self, mock_verify_token):
        mock_verify_token.side_effect = Exception("Invalid token")
        response = self.client.post(
            reverse("test-drive-create"),
            {
                "customer_id": self.customer.pk,
                "dealership_id": self.dealership.pk,
                "vehicle_id": self.vehicle.pk,
                "scheduled_date": (datetime.now().date() + timedelta(days=3)).isoformat(),
                "scheduled_time": "10:00:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_create_test_drive(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        response = self.client.post(
            reverse("test-drive-create"),
            {
                "dealership_id": self.dealership.pk,
                "vehicle_id": self.vehicle.pk,
                "scheduled_date": (datetime.now().date() + timedelta(days=3)).isoformat(),
                "scheduled_time": "10:00:00",
            },
            format="json",
            **self._auth_header("auth-cust-api-1"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["appointment"]["customer"], self.customer.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_create_test_drive_for_other_customer(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        response = self.client.post(
            reverse("test-drive-create"),
            {
                "customer_id": self.other_customer.pk,
                "dealership_id": self.dealership.pk,
                "vehicle_id": self.vehicle.pk,
                "scheduled_date": (datetime.now().date() + timedelta(days=3)).isoformat(),
                "scheduled_time": "10:00:00",
            },
            format="json",
            **self._auth_header("auth-cust-api-1"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["appointment"]["customer"], self.customer.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_list_own_appointments(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        appointment = factories.create_appointment(customer=self.customer, dealership=self.dealership)
        factories.create_appointment(customer=self.other_customer)

        response = self.client.get(
            reverse("appointment-list"), {"customer_id": self.customer.pk}, **self._auth_header("auth-cust-api-1")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [appointment.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_list_other_customer_appointments(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        response = self.client.get(
            reverse("appointment-list"), {"customer_id": self.other_customer.pk}, **self._auth_header("auth-cust-api-1")
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_can_only_list_own_dealership_appointments(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-emp-api-1", self.employee.email)

        appointment = factories.create_appointment(customer=self.customer, dealership=self.dealership)
        factories.create_appointment(customer=self.other_customer)

        response = self.client.get(
            reverse("appointment-list"), {"status": "PENDING"}, **self._auth_header("auth-emp-api-1")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [appointment.pk])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_create_service_request_requires_customer_auth(self, mock_verify_token):
        mock_verify_token.side_effect = Exception("Invalid token")
        customer_vehicle = factories.create_customer_vehicle(customer=self.customer)

        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": customer_vehicle.pk,
                "service_type": "REPAIR",
                "problem_description": "AC not working",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_create_service_request_for_own_vehicle(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        customer_vehicle = factories.create_customer_vehicle(customer=self.customer)

        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": customer_vehicle.pk,
                "service_type": "REPAIR",
                "problem_description": "AC not working",
            },
            format="json",
            **self._auth_header("auth-cust-api-1"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_cannot_create_service_request_for_other_vehicle(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        other_vehicle = factories.create_customer_vehicle(customer=self.other_customer)

        response = self.client.post(
            reverse("service-request-collection"),
            {
                "customer_vehicle_id": other_vehicle.pk,
                "service_type": "REPAIR",
                "problem_description": "AC not working",
            },
            format="json",
            **self._auth_header("auth-cust-api-1"),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_can_list_service_requests(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-emp-api-1", self.employee.email)

        factories.create_service_request()

        response = self.client.get(
            reverse("service-request-collection"), {"status": "PENDING"}, **self._auth_header("auth-emp-api-1")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_list_own_service_requests(self, mock_verify_token):
        self._mock_auth(mock_verify_token, "auth-cust-api-1", self.customer.email)

        customer_vehicle = factories.create_customer_vehicle(customer=self.customer)
        sr = factories.create_service_request(customer_vehicle=customer_vehicle)
        factories.create_service_request()

        response = self.client.get(
            reverse("service-request-collection"), **self._auth_header("auth-cust-api-1")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], sr.pk)