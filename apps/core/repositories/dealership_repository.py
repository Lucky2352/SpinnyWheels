from apps.core.models import Dealership


class DealershipRepository:
    def get_by_id(self, dealership_id):
        return Dealership.objects.filter(pk=dealership_id).first()

    def list_active(self):
        return list(Dealership.objects.filter(is_active=True).order_by("name"))

    def create(self, **fields):
        return Dealership.objects.create(**fields)

    def update(self, dealership, **fields):
        return dealership.apply_changes(**fields)
