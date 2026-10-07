from apps.core.exceptions import (
    ConflictError,
    DomainError,
    ResourceNotFoundError,
)
from apps.core.repositories.customer_repository import CustomerRepository
from apps.core.repositories.feedback_repository import FeedbackRepository
from apps.core.repositories.service_repository import ServiceRecordRepository


class FeedbackService:
    def __init__(self, feedback=None, customers=None, service_records=None):
        self._feedback = feedback or FeedbackRepository()
        self._customers = customers or CustomerRepository()
        self._service_records = service_records or ServiceRecordRepository()

    def submit(self, *, customer_id, service_record_id, rating, comment=""):
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise ResourceNotFoundError("Customer does not exist.")

        service_record = self._service_records.get_by_id(service_record_id)
        if service_record is None:
            raise ResourceNotFoundError("Service record does not exist.")
        if service_record.customer_vehicle.customer_id != customer_id:
            raise DomainError("This service record belongs to a different customer.")
        if not 1 <= rating <= 5:
            raise DomainError("Rating must be between 1 and 5.")
        if self._feedback.get_by_customer_and_service_record(customer_id, service_record_id):
            raise ConflictError("Feedback has already been submitted for this service record.")

        return self._feedback.create(
            customer=customer,
            service_record=service_record,
            rating=rating,
            comment=comment,
        )

    def list_for_service_record(self, service_record_id):
        return self._feedback.list_for_service_record(service_record_id)
