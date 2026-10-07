from apps.core.models import Dealership, Vehicle

vehicles = Vehicle.objects.filter(dealership_id=1).order_by('brand', 'model', 'variant')
print(f'Total vehicles in dealership 1: {vehicles.count()}')
for v in vehicles:
    print(f'  {v.brand} {v.model} {v.variant} - {v.fuel_type} {v.transmission} - {v.price} - Stock: {v.stock_quantity} - Avail: {v.is_available} - Year: {v.manufacturing_year} - Seats: {v.seating_capacity}')