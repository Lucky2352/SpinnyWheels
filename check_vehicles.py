import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from apps.core.models.vehicle import Vehicle
from apps.core.models.dealership import Dealership

d = Dealership.objects.get(id=1)
print('Dealership:', d.name, '(ID=', d.id, ')')
vehicles = Vehicle.objects.filter(dealership=d)
print('Count:', vehicles.count())
for v in vehicles:
    print(' ', v.brand, v.model, v.variant, '(', v.manufacturing_year, ') -', v.fuel_type, '-', v.transmission, '-', v.seating_capacity, 'seats - Rs.', v.price, '- stock=', v.stock_quantity, '- avail=', v.is_available)