from apps.core.models import Invoice


class InvoiceRepository:
    def get_by_id(self, invoice_id):
        return Invoice.objects.select_related("service_record").filter(pk=invoice_id).first()

    def get_by_number(self, invoice_number):
        return Invoice.objects.filter(invoice_number__iexact=invoice_number).first()

    def get_by_service_record(self, service_record_id):
        return Invoice.objects.filter(service_record_id=service_record_id).first()

    def list_by_status(self, status=None):
        queryset = Invoice.objects.select_related("service_record").all()
        if status:
            queryset = queryset.filter(status=status)
        return list(queryset.order_by("-created_at"))

    def create(self, **fields):
        return Invoice.objects.create(**fields)

    def update(self, invoice, **fields):
        return invoice.apply_changes(**fields)
