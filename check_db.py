from apps.core.models.vehicle import Vehicle
from apps.core.models.dealership import Dealership

print('Dealerships:')
for d in Dealership.objects.all():
    print(f'  ID={d.id}, name={d.name}, active={d.is_active}')
print(f'Total vehicles: {Vehicle.objects.count()}')
print('Vehicles per dealership:')
for d in Dealership.objects.all():
    print(f'  {d.name}: {Vehicle.objects.filter(dealership=d).count()}')