import logging
from typing import Optional

import httpx
from django.conf import settings

try:
    from jose import jwt
    from jose.exceptions import JWTError, ExpiredSignatureError, JWTClaimsError
except ImportError:
    jwt = None
    JWTError = Exception
    ExpiredSignatureError = Exception
    JWTClaimsError = Exception
from rest_framework import authentication, exceptions

from apps.core.models import CustomerProfile, Employee
from apps.core.repositories.customer_repository import CustomerRepository
from apps.core.repositories.dealership_repository import DealershipRepository

logger = logging.getLogger("autoflow.auth")

SUPPORTED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


class SupabaseUser:
    def __init__(
        self,
        supabase_user_id: str,
        email: str,
        role: str,
        customer_profile: Optional[CustomerProfile] = None,
        employee_profile: Optional[Employee] = None,
    ):
        self.supabase_user_id = supabase_user_id
        self.email = email
        self.role = role
        self.customer_profile = customer_profile
        self.employee_profile = employee_profile
        self.is_authenticated = True

    @property
    def is_customer(self) -> bool:
        return self.role == "CUSTOMER"

    @property
    def is_employee(self) -> bool:
        return self.role in {"EMPLOYEE", "TECHNICIAN", "ADMIN", "OWNER"}

    @property
    def is_technician(self) -> bool:
        return self.role == "TECHNICIAN"

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"

    @property
    def is_owner(self) -> bool:
        return self.role == "OWNER"

    @property
    def is_owner_or_admin(self) -> bool:
        return self.role in {"OWNER", "ADMIN"}

    @property
    def is_employee_or_admin(self) -> bool:
        return self.role in {"EMPLOYEE", "TECHNICIAN", "ADMIN", "OWNER"}

    @property
    def is_staff(self) -> bool:
        return self.role in {"EMPLOYEE", "ADMIN", "OWNER"}

    @property
    def is_technician_or_admin(self) -> bool:
        return self.role in {"TECHNICIAN", "ADMIN"}

    @property
    def dealership_id(self) -> Optional[int]:
        if self.employee_profile:
            return self.employee_profile.dealership_id
        return None


class SupabaseJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    # Process-level JWKS cache shared by every authenticator instance. DRF
    # builds one authenticator per request, so an instance-level cache would
    # refetch the signing keys over the network on EVERY authenticated API
    # call. Tests may still override the cache on a single instance.
    _jwks_cache: Optional[dict] = None

    def __init__(self):
        self._jwks_client: Optional[httpx.AsyncClient] = None

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).split()

        if not auth_header or auth_header[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth_header) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header. No credentials provided.")
        elif len(auth_header) > 2:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        token = auth_header[1].decode()

        try:
            payload = self._verify_token(token)
        except ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Token has expired.")
        except JWTClaimsError as exc:
            raise exceptions.AuthenticationFailed(f"Invalid token claims: {exc}")
        except JWTError as exc:
            raise exceptions.AuthenticationFailed(f"Invalid token: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error during token verification")
            raise exceptions.AuthenticationFailed("Authentication failed.")

        supabase_user_id = payload.get("sub")
        email = payload.get("email")

        if not supabase_user_id:
            raise exceptions.AuthenticationFailed("Token missing subject claim.")

        user_context = self._resolve_local_profile(supabase_user_id, email, payload)
        if user_context is None:
            raise exceptions.AuthenticationFailed("User not found in application.")

        return (user_context, None)

    def _get_jwks(self) -> dict:
        cached = self.__dict__.get("_jwks_cache", type(self)._jwks_cache)
        if cached is not None:
            return cached

        jwks_url = getattr(settings, "SUPABASE_JWKS_URL", None)
        if not jwks_url:
            raise exceptions.AuthenticationFailed("Supabase JWKS URL not configured.")

        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        type(self)._jwks_cache = response.json()
        return type(self)._jwks_cache

    def _verify_token(self, token: str) -> dict:
        jwks = self._get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        algorithm = unverified_header.get("alg")

        if not kid:
            raise JWTError("Token header missing key ID.")

        if algorithm not in SUPPORTED_ALGORITHMS:
            raise JWTError(f"Unsupported signing algorithm: {algorithm}")

        key_data = next((key for key in jwks.get("keys", []) if key.get("kid") == kid), None)
        if not key_data:
            raise JWTError("Unable to find matching key for token.")

        if key_data.get("alg") and key_data["alg"] != algorithm:
            raise JWTError("Token algorithm does not match the signing key.")

        key = self._build_public_key(key_data, algorithm)

        supabase_url = getattr(settings, "SUPABASE_URL", None)
        if not supabase_url:
            raise exceptions.AuthenticationFailed("Supabase URL not configured.")

        audience = "authenticated"
        issuer = f"{supabase_url}/auth/v1"

        payload = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            options={"verify_aud": True, "verify_iss": True, "verify_exp": True},
        )

        return payload

    def _build_public_key(self, key_data: dict, algorithm: str):
        from jose.backends import ECKey, RSAKey

        expected_kty = "EC" if algorithm.startswith("ES") else "RSA"
        if key_data.get("kty") != expected_kty:
            raise JWTError("Signing key type does not match the token algorithm.")

        backend = ECKey if algorithm.startswith("ES") else RSAKey

        try:
            return backend(key_data, algorithm)
        except Exception as exc:
            raise JWTError(f"Unable to load signing key: {exc}")

    def _resolve_local_profile(
        self, supabase_user_id: str, email: str, payload: dict
    ) -> Optional[SupabaseUser]:
        customer_repo = CustomerRepository()
        employee = (
            Employee.objects.select_related("dealership", "technician_profile")
            .filter(external_user_id=supabase_user_id)
            .first()
        )

        if employee is not None:
            if not employee.is_active:
                raise exceptions.AuthenticationFailed(
                    "This staff account has been deactivated."
                )
            return SupabaseUser(
                supabase_user_id=supabase_user_id,
                email=email or employee.email,
                role=employee.role,
                employee_profile=employee,
            )

        customer = customer_repo.get_by_external_user_id(supabase_user_id)

        if customer is None:
            customer = self._link_or_provision_customer(supabase_user_id, email, payload)

        return SupabaseUser(
            supabase_user_id=supabase_user_id,
            email=email or customer.email,
            role="CUSTOMER",
            customer_profile=customer,
        )

    def _link_or_provision_customer(
        self, supabase_user_id: str, email: Optional[str], payload: dict
    ) -> CustomerProfile:
        if not email:
            raise exceptions.AuthenticationFailed("Token missing email claim.")

        customer_repo = CustomerRepository()
        existing = customer_repo.get_by_email(email)

        if existing is not None:
            if existing.external_user_id and existing.external_user_id != supabase_user_id:
                raise exceptions.AuthenticationFailed("Email is linked to a different account.")
            if not existing.external_user_id:
                return customer_repo.update(existing, external_user_id=supabase_user_id)
            return existing

        first_name, last_name = self._split_name(payload, email)

        return customer_repo.create(
            external_user_id=supabase_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

    def _split_name(self, payload: dict, email: str) -> tuple:
        metadata = payload.get("user_metadata") or {}
        full_name = (metadata.get("full_name") or metadata.get("name") or "").strip()

        if not full_name:
            full_name = email.split("@")[0].replace(".", " ").replace("_", " ").strip()

        parts = full_name.split()
        first_name = parts[0][:100] if parts else "Customer"
        last_name = (" ".join(parts[1:]) or first_name)[:100]
        return first_name, last_name

    def authenticate_header(self, request):
        return self.keyword