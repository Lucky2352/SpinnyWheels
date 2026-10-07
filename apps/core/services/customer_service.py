from django.db import transaction

from apps.core.exceptions import ConflictError, DomainError, ResourceNotFoundError
from apps.core.repositories.customer_repository import (
    CustomerRepository,
    CustomerVehicleRepository,
)
from apps.core.repositories.vehicle_repository import VehicleRepository


class CustomerService:
    def __init__(self, customers=None, customer_vehicles=None, vehicles=None):
        self._customers = customers or CustomerRepository()
        self._customer_vehicles = customer_vehicles or CustomerVehicleRepository()
        self._vehicles = vehicles or VehicleRepository()

    def register_customer(
        self,
        *,
        first_name,
        last_name,
        email,
        phone="",
        external_user_id=None,
        address="",
        city="",
        state="",
        postal_code="",
    ):
        if self._customers.get_by_email(email):
            raise ConflictError("A customer with this email is already registered.")

        return self._customers.create(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            external_user_id=external_user_id,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
        )

    def get_customer(self, customer_id):
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise ResourceNotFoundError("Customer does not exist.")
        return customer

    def list_vehicles(self, customer_id):
        self.get_customer(customer_id)
        return self._customer_vehicles.list_by_customer(customer_id)

    @transaction.atomic
    def register_sale(
        self,
        *,
        customer_id,
        vehicle_id,
        registration_number,
        purchase_date,
        current_mileage=0,
    ):
        customer = self.get_customer(customer_id)
        vehicle = self._vehicles.get_by_id(vehicle_id)

        if vehicle is None:
            raise ResourceNotFoundError("Vehicle does not exist.")
        if not vehicle.is_in_stock:
            raise ConflictError("This vehicle is not available for sale.")
        if self._customer_vehicles.get_by_registration_number(registration_number):
            raise ConflictError("This registration number is already recorded.")
        if current_mileage < 0:
            raise DomainError("Current mileage cannot be negative.")

        customer_vehicle = self._customer_vehicles.create(
            customer=customer,
            vehicle=vehicle,
            registration_number=registration_number,
            purchase_date=purchase_date,
            current_mileage=current_mileage,
        )
        remaining_stock = vehicle.stock_quantity - 1
        self._vehicles.update(
            vehicle,
            stock_quantity=remaining_stock,
            is_available=remaining_stock > 0,
        )
        return customer_vehicle
