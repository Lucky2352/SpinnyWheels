from django.db import IntegrityError, transaction

from apps.core.exceptions import ConflictError, DomainError, ResourceNotFoundError
from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.repositories.vehicle_repository import VehicleRepository


class VehicleService:
    def __init__(self, vehicles=None, dealerships=None):
        self._vehicles = vehicles or VehicleRepository()
        self._dealerships = dealerships or DealershipRepository()

    def list_available(self, *, brand=None, dealership_id=None):
        return self._vehicles.list_available(brand=brand, dealership_id=dealership_id)

    def get_available(self, vehicle_id):
        vehicle = self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("Vehicle does not exist.")
        if not vehicle.is_in_stock:
            raise ConflictError("This vehicle is not available.")
        return vehicle

    @transaction.atomic
    def add_inventory(
        self,
        *,
        dealership_id,
        brand,
        model,
        manufacturing_year,
        fuel_type,
        transmission,
        price,
        variant="",
        seating_capacity=5,
        description="",
        stock_quantity=1,
        is_available=None,
    ):
        dealership = self._dealerships.get_by_id(dealership_id)
        if dealership is None:
            raise ResourceNotFoundError("Dealership does not exist.")

        if is_available is None:
            is_available = stock_quantity > 0

        try:
            return self._vehicles.create(
                dealership=dealership,
                brand=brand,
                model=model,
                variant=variant,
                manufacturing_year=manufacturing_year,
                fuel_type=fuel_type,
                transmission=transmission,
                seating_capacity=seating_capacity,
                price=price,
                description=description,
                stock_quantity=stock_quantity,
                is_available=is_available and stock_quantity > 0,
            )
        except IntegrityError as exc:
            raise ConflictError(
                "This vehicle already exists in the dealership inventory."
            ) from exc

    def list_inventory(self, *, dealership_id=None, brand=None, search=None):
        return self._vehicles.list_inventory(
            dealership_id=dealership_id, brand=brand, search=search
        )

    def get_or_create_inventory(self, *, dealership, **fields):
        return self._vehicles.get_or_create(dealership=dealership, **fields)

    def get_inventory(self, vehicle_id):
        vehicle = self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise ResourceNotFoundError("Vehicle does not exist.")
        return vehicle

    @transaction.atomic
    def update_inventory(
        self,
        vehicle_id,
        *,
        price=None,
        stock_quantity=None,
        is_available=None,
        variant=None,
        manufacturing_year=None,
        fuel_type=None,
        transmission=None,
        seating_capacity=None,
        description=None,
    ):
        vehicle = self.get_inventory(vehicle_id)

        if price is not None:
            if price < 0:
                raise DomainError("Price cannot be negative.")
            vehicle.price = price

        if stock_quantity is not None:
            if stock_quantity < 0:
                raise DomainError("Stock quantity cannot be negative.")
            vehicle.stock_quantity = stock_quantity
            if stock_quantity == 0:
                vehicle.is_available = False
            elif is_available:
                vehicle.is_available = True

        if is_available is not None and stock_quantity is None:
            vehicle.is_available = is_available and vehicle.stock_quantity > 0

        for name, value in (
            ("variant", variant),
            ("manufacturing_year", manufacturing_year),
            ("fuel_type", fuel_type),
            ("transmission", transmission),
            ("seating_capacity", seating_capacity),
            ("description", description),
        ):
            if value is not None:
                setattr(vehicle, name, value)

        try:
            vehicle.save()
        except IntegrityError as exc:
            raise ConflictError(
                "This vehicle already exists in the dealership inventory."
            ) from exc

        return vehicle

    def deactivate_inventory(self, vehicle_id):
        vehicle = self.get_inventory(vehicle_id)
        return self._vehicles.update(vehicle, is_available=False, stock_quantity=0)
