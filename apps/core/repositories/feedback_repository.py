from apps.core.models import Feedback


class FeedbackRepository:
    def get_by_id(self, feedback_id):
        return Feedback.objects.select_related("customer", "service_record").filter(
            pk=feedback_id
        ).first()

    def get_by_customer_and_service_record(self, customer_id, service_record_id):
        return Feedback.objects.filter(
            customer_id=customer_id, service_record_id=service_record_id
        ).first()

    def list_for_service_record(self, service_record_id):
        return list(
            Feedback.objects.select_related("customer")
            .filter(service_record_id=service_record_id)
            .order_by("-created_at")
        )

    def create(self, **fields):
        return Feedback.objects.create(**fields)
