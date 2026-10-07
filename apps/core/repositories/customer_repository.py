from apps.core.models import CustomerProfile, CustomerVehicle


class CustomerRepository:
    def get_by_id(self, customer_id):
        return CustomerProfile.objects.filter(pk=customer_id).first()

    def get_by_email(self, email):
        return CustomerProfile.objects.filter(email__iexact=email).first()

    def get_by_external_user_id(self, external_user_id):
        return CustomerProfile.objects.filter(external_user_id=external_user_id).first()

    def list_all(self):
        return list(CustomerProfile.objects.all())

    def create(self, **fields):
        return CustomerProfile.objects.create(**fields)

    def update(self, customer, **fields):
        return customer.apply_changes(**fields)


class CustomerVehicleRepository:
    def get_by_id(self, customer_vehicle_id):
        return CustomerVehicle.objects.select_related("customer", "vehicle").filter(
            pk=customer_vehicle_id
        ).first()

    def get_by_registration_number(self, registration_number):
        return CustomerVehicle.objects.filter(
            registration_number__iexact=registration_number
        ).first()

    def list_by_customer(self, customer_id):
        return list(
            CustomerVehicle.objects.select_related("vehicle")
            .filter(customer_id=customer_id)
            .order_by("-purchase_date")
        )

    def create(self, **fields):
        return CustomerVehicle.objects.create(**fields)

    def update(self, customer_vehicle, **fields):
        return customer_vehicle.apply_changes(**fields)
