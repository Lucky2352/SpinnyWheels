import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.exceptions import DomainError
from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.repositories.employee_repository import EmployeeRepository
from apps.core.services.employee_service import EmployeeService


def create_supabase_auth_user(email, password):
    supabase_url = (settings.SUPABASE_URL or "").rstrip("/")
    publishable_key = settings.SUPABASE_PUBLISHABLE_KEY or ""

    if not supabase_url or not publishable_key:
        raise DomainError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be configured.")

    response = httpx.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": publishable_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=30.0,
    )

    if response.status_code >= 400:
        raise DomainError(f"Supabase rejected the owner account: {response.text.strip()}")

    payload = response.json()
    user_id = payload.get("id") or (payload.get("user") or {}).get("id")

    if not user_id:
        raise DomainError("Supabase did not return a user id for the owner account.")

    return user_id


class Command(BaseCommand):
    help = "Provision the single Owner for a dealership."

    def add_arguments(self, parser):
        parser.add_argument("--first-name", required=True)
        parser.add_argument("--last-name", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", default="")
        parser.add_argument("--dealership-id", type=int)
        parser.add_argument("--dealership-name")
        parser.add_argument("--address", default="")
        parser.add_argument("--city", default="")
        parser.add_argument("--state", default="")
        parser.add_argument("--postal-code", default="")
        parser.add_argument("--dealership-email", default="")
        parser.add_argument("--phone", default="")
        parser.add_argument("--supabase-user-id")

    def handle(self, *args, **options):
        employees = EmployeeRepository()
        dealerships = DealershipRepository()

        dealership = self._resolve_dealership(dealerships, options)

        existing_owner = employees.get_owner_by_dealership(dealership.pk)
        if existing_owner is not None:
            raise CommandError(
                f"Dealership '{dealership.name}' already has an owner ({existing_owner.email}). "
                "No additional owner was created."
            )

        if employees.get_by_email(options["email"]) is not None:
            raise CommandError(
                f"An employee with email {options['email']} already exists. "
                "No additional owner was created."
            )

        supabase_user_id = options["supabase_user_id"]
        if not supabase_user_id and len(options["password"]) < 8:
            raise CommandError(
                "Provide --supabase-user-id or a --password of at least 8 characters."
            )

        try:
            owner = self._provision(employees, options, dealership, supabase_user_id)
        except DomainError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(f"Owner {owner.email} created for {dealership.name}.")
        )
        self.stdout.write(f"Dealership: {dealership.name}, {dealership.city}")
        self.stdout.write(f"Supabase user id: {owner.external_user_id}")

    def _resolve_dealership(self, dealerships, options):
        if options["dealership_id"]:
            dealership = dealerships.get_by_id(options["dealership_id"])
            if dealership is None:
                raise CommandError(f"Dealership {options['dealership_id']} does not exist.")
            return dealership

        if options["dealership_name"]:
            return dealerships.create(
                name=options["dealership_name"],
                address=options["address"],
                city=options["city"],
                state=options["state"],
                postal_code=options["postal_code"],
                phone=options["phone"],
                email=options["email"],
            )

        active = dealerships.list_active()

        if not active:
            raise CommandError(
                "No active dealership exists. Pass --dealership-id, or --dealership-name "
                "together with --address, --city, --state, --postal-code, --phone and --dealership-email."
            )

        if len(active) == 1:
            return active[0]

        self.stdout.write("Active dealerships:")
        for dealership in active:
            self.stdout.write(f"  {dealership.pk}  {dealership.name}")

        raise CommandError("Multiple dealerships exist. Pass --dealership-id.")

    def _provision(self, employees, options, dealership, supabase_user_id):
        service = EmployeeService()

        common = {
            "dealership_id": dealership.pk,
            "first_name": options["first_name"],
            "last_name": options["last_name"],
            "email": options["email"],
            "phone": options["phone"],
        }

        if supabase_user_id:
            return service.create_owner(
                external_user_id=supabase_user_id, **common
            )

        with transaction.atomic():
            owner = service.create_owner(external_user_id=None, **common)
            new_user_id = create_supabase_auth_user(options["email"], options["password"])
            employees.update(owner, external_user_id=new_user_id)

        return owner