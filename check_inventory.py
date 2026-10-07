from apps.core.models import Dealership, Vehicle

dealerships = Dealership.objects.all()
print('Dealerships:')
for d in dealerships:
    print(f'  ID: {d.id}, Name: {d.name}, Active: {d.is_active}')
    vehicles = Vehicle.objects.filter(dealership=d)
    print(f'    Vehicles: {vehicles.count()}')
    for v in vehicles[:10]:
        print(f'      {v.brand} {v.model} {v.variant} - {v.fuel_type} {v.transmission} - {v.price} - Stock: {v.stock_quantity} - Avail: {v.is_available}')
    if vehicles.count() > 10:
        print(f'      ... and {vehicles.count() - 10} more')