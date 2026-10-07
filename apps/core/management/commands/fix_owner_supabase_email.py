import os

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import DomainError
from apps.core.models.dealership import Employee


def load_admin_key():
    return (
        os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()


def admin_headers(admin_key):
    return {
        "apikey": admin_key,
        "Authorization": f"Bearer {admin_key}",
        "Content-Type": "application/json",
    }


def describe(response):
    return (response.text or "").strip().replace("\n", " ")[:300]


def require_same_id(payload, expected_id):
    returned_id = payload.get("id")

    if returned_id != expected_id:
        raise DomainError(
            f"Supabase returned user id {returned_id}, expected {expected_id}. "
            "No local data was changed."
        )


def fetch_supabase_user(supabase_url, admin_key, user_id):
    response = httpx.get(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers=admin_headers(admin_key),
        timeout=30.0,
    )

    if response.status_code == 404:
        raise DomainError(f"Supabase has no auth user with id {user_id}.")

    if response.status_code >= 400:
        raise DomainError(f"Supabase rejected the lookup: {describe(response)}")

    payload = response.json()
    require_same_id(payload, user_id)

    return payload


def update_supabase_user(supabase_url, admin_key, user_id, new_email):
    response = httpx.put(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers=admin_headers(admin_key),
        json={"email": new_email, "email_confirm": True},
        timeout=30.0,
    )

    if response.status_code >= 400:
        raise DomainError(f"Supabase rejected the email update: {describe(response)}")

    payload = response.json()
    require_same_id(payload, user_id)

    return payload


class Command(BaseCommand):
    help = "Confirm and re-address the existing Supabase auth user of the dealership Owner."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--dealership-id", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        supabase_url = (settings.SUPABASE_URL or "").rstrip("/")
        admin_key = load_admin_key()

        if not supabase_url:
            raise CommandError("SUPABASE_URL is not configured.")

        if not admin_key:
            raise CommandError(
                "SUPABASE_SECRET_KEY is not configured. Add it to .env, run this command, "
                "then delete the line from .env again."
            )

        owner = self._resolve_owner(options)
        target_email = options["email"].strip()

        if not owner.external_user_id:
            raise CommandError(f"Owner {owner.email} has no external_user_id.")

        user_id = owner.external_user_id

        before = {
            "role": owner.role,
            "dealership_id": owner.dealership_id,
            "external_user_id": owner.external_user_id,
        }

        self.stdout.write(f"Local owner      : pk={owner.pk} email={owner.email}")
        self.stdout.write(f"Supabase user id : {user_id}")

        try:
            current = fetch_supabase_user(supabase_url, admin_key, user_id)
        except DomainError as exc:
            raise CommandError(str(exc))

        self.stdout.write(f"Supabase email   : {current.get('email')}")
        self.stdout.write(f"Confirmed at     : {current.get('email_confirmed_at') or 'never'}")

        already_correct = (
            (current.get("email") or "").lower() == target_email.lower()
            and bool(current.get("email_confirmed_at"))
        )

        if already_correct:
            self.stdout.write(
                self.style.WARNING("Supabase already matches the target and is confirmed; no update sent.")
            )
        elif options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run. Would set email to {target_email} and set email_confirm=true."
                )
            )
        else:
            try:
                updated = update_supabase_user(supabase_url, admin_key, user_id, target_email)
            except DomainError as exc:
                raise CommandError(str(exc))

            self._verify_supabase(updated, user_id, target_email)

            self.stdout.write(
                self.style.SUCCESS(f"Supabase email   : {updated.get('email')}")
            )
            self.stdout.write(
                f"Confirmed at     : {updated.get('email_confirmed_at') or 'never'}"
            )

        if not options["dry_run"] and owner.email != target_email:
            owner.email = target_email
            owner.save(update_fields=["email"])
            self.stdout.write(f"Local email synced to {target_email}")

        self._report_local(owner, before, target_email)

    def _resolve_owner(self, options):
        queryset = Employee.objects.filter(role="OWNER")

        if options["dealership_id"]:
            queryset = queryset.filter(dealership_id=options["dealership_id"])

        owners = list(queryset)

        if not owners:
            raise CommandError("No Owner employee found.")

        if len(owners) > 1:
            raise CommandError("Multiple Owner employees found. Pass --dealership-id.")

        return owners[0]

    def _verify_supabase(self, payload, user_id, target_email):
        if (payload.get("email") or "").lower() != target_email.lower():
            raise CommandError(
                f"Supabase reports email {payload.get('email')}, expected {target_email}."
            )

        if not payload.get("email_confirmed_at"):
            raise CommandError("Supabase reports the email is still unconfirmed.")

    def _report_local(self, owner, before, target_email):
        problems = []

        if owner.email != target_email:
            problems.append(f"email is {owner.email}")
        if owner.role != "OWNER":
            problems.append(f"role is {owner.role}")
        if owner.role != before["role"]:
            problems.append("role changed during this run")
        if owner.dealership_id != before["dealership_id"]:
            problems.append("dealership changed during this run")
        if owner.external_user_id != before["external_user_id"]:
            problems.append("external_user_id changed during this run")

        self.stdout.write("")
        self.stdout.write("Local Employee")
        self.stdout.write(f"  pk                : {owner.pk}")
        self.stdout.write(f"  email             : {owner.email}")
        self.stdout.write(f"  role              : {owner.role}")
        self.stdout.write(f"  dealership_id     : {owner.dealership_id}")
        self.stdout.write(f"  external_user_id  : {owner.external_user_id}")
        self.stdout.write(f"  owners in database : {Employee.objects.filter(role='OWNER').count()}")

        if problems:
            for problem in problems:
                self.stdout.write(self.style.ERROR(f"  FAILED: {problem}"))
            raise CommandError("Local verification failed.")
