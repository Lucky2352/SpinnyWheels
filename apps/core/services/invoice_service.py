from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import (
    ConflictError,
    DomainError,
    InvalidStateError,
    ResourceNotFoundError,
)
from apps.core.models.choices import InvoiceStatus
from apps.core.repositories.invoice_repository import InvoiceRepository
from apps.core.repositories.service_repository import ServiceRecordRepository

MONEY_PRECISION = Decimal("0.01")


class InvoiceService:
    def __init__(self, invoices=None, service_records=None):
        self._invoices = invoices or InvoiceRepository()
        self._service_records = service_records or ServiceRecordRepository()

    @transaction.atomic
    def generate(self, service_record_id, *, tax_percentage=Decimal("0.00")):
        service_record = self._service_records.get_by_id(service_record_id)
        if service_record is None:
            raise ResourceNotFoundError("Service record does not exist.")
        if self._invoices.get_by_service_record(service_record_id) is not None:
            raise ConflictError("An invoice already exists for this service record.")
        if tax_percentage < 0:
            raise DomainError("Tax percentage cannot be negative.")

        subtotal = Decimal(service_record.total_cost).quantize(MONEY_PRECISION)
        tax = (subtotal * Decimal(tax_percentage) / Decimal("100")).quantize(
            MONEY_PRECISION, rounding=ROUND_HALF_UP
        )

        try:
            return self._invoices.create(
                service_record=service_record,
                invoice_number=f"INV-{service_record.pk:06d}",
                subtotal=subtotal,
                tax=tax,
                total=subtotal + tax,
            )
        except IntegrityError as exc:
            raise ConflictError("An invoice already exists for this service record.") from exc

    def issue(self, invoice_id):
        invoice = self._get_invoice(invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise InvalidStateError(
                f"An invoice in {invoice.status} state cannot be issued."
            )
        return self._invoices.update(
            invoice, status=InvoiceStatus.ISSUED, issued_at=timezone.now()
        )

    def mark_paid(self, invoice_id):
        invoice = self._get_invoice(invoice_id)
        if invoice.status != InvoiceStatus.ISSUED:
            raise InvalidStateError(
                f"An invoice in {invoice.status} state cannot be marked as paid."
            )
        return self._invoices.update(invoice, status=InvoiceStatus.PAID)

    def get_invoice(self, invoice_id):
        return self._get_invoice(invoice_id)

    def list_by_status(self, status=None):
        return self._invoices.list_by_status(status)

    def _get_invoice(self, invoice_id):
        invoice = self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise ResourceNotFoundError("Invoice does not exist.")
        return invoice
