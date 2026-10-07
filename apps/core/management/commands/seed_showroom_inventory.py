from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.core.repositories.dealership_repository import DealershipRepository
from apps.core.services.vehicle_service import VehicleService

SHOWROOM_INVENTORY = (
    {
        "brand": "Maruti Suzuki",
        "model": "Wagon R",
        "variant": "VXi",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("650000.00"),
        "stock_quantity": 6,
        "description": "City hatchback with a tall seating position, flexible boot and the most affordable running cost in the segment.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Wagon R",
        "variant": "VXi AMT",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AMT",
        "seating_capacity": 5,
        "price": Decimal("715000.00"),
        "stock_quantity": 3,
        "description": "Automated city hatchback for stop-and-go traffic, with the same platform and cabin as the manual VXi.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Wagon R",
        "variant": "LXi CNG",
        "manufacturing_year": 2023,
        "fuel_type": "CNG",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("710000.00"),
        "stock_quantity": 2,
        "description": "CNG variant with a factory-fitted dual-tank setup for the lowest per-kilometre cost in the showroom.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Swift",
        "variant": "ZXi",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("950000.00"),
        "stock_quantity": 5,
        "description": "Lightweight premium hatchback with a responsive 1.2-litre engine and engaging manual gearbox.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Swift",
        "variant": "ZXi AMT",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AMT",
        "seating_capacity": 5,
        "price": Decimal("1075000.00"),
        "stock_quantity": 4,
        "description": "Swift with a seven-speed automated manual for effortless city driving and highway cruise.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Brezza",
        "variant": "ZXi",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("1060000.00"),
        "stock_quantity": 5,
        "description": "Compact SUV with high ground clearance, all-weather tyres and a practical second row for family use.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Grand Vitara",
        "variant": "Zeta Hybrid",
        "manufacturing_year": 2024,
        "fuel_type": "HYBRID",
        "transmission": "AUTOMATIC",
        "seating_capacity": 5,
        "price": Decimal("2050000.00"),
        "stock_quantity": 3,
        "description": "Strong hybrid compact SUV with all-wheel drive, regenerative braking and an e-CVT gearbox.",
    },
    {
        "brand": "Maruti Suzuki",
        "model": "Grand Vitara",
        "variant": "Zeta",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 5,
        "price": Decimal("1890000.00"),
        "stock_quantity": 2,
        "description": "Petrol automatic compact SUV with a panoramic sunroof and connected car tech.",
    },
    {
        "brand": "Tata",
        "model": "Punch",
        "variant": "Adventure",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("800000.00"),
        "stock_quantity": 6,
        "description": "Roof-mounted five-star safety rated compact SUV with a tough body and elevated driving position.",
    },
    {
        "brand": "Tata",
        "model": "Punch",
        "variant": "Adventure AMT",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AMT",
        "seating_capacity": 5,
        "price": Decimal("945000.00"),
        "stock_quantity": 3,
        "description": "Punch with an automated manual gearbox, alloy wheels and a sporty black exterior package.",
    },
    {
        "brand": "Tata",
        "model": "Nexon",
        "variant": "XZ+",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AMT",
        "seating_capacity": 5,
        "price": Decimal("1350000.00"),
        "stock_quantity": 5,
        "description": "Five-star safety rated compact SUV with a spacious cabin, big touchscreen and wireless charging.",
    },
    {
        "brand": "Tata",
        "model": "Harrier",
        "variant": "Adventure X",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 5,
        "price": Decimal("2250000.00"),
        "stock_quantity": 3,
        "description": "Diesel automatic midsize SUV with a wide bench seat, panoramic roof and 350-litre boot.",
    },
    {
        "brand": "Tata",
        "model": "Safari",
        "variant": "XZ",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("2550000.00"),
        "stock_quantity": 2,
        "description": "Seven-seat diesel automatic SUV built for long family road trips with a genuinely usable third row.",
    },
    {
        "brand": "Hyundai",
        "model": "Creta",
        "variant": "SX",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 5,
        "price": Decimal("1500000.00"),
        "stock_quantity": 4,
        "description": "India's best-selling compact SUV, with a smooth automatic, ventilated seats and an airy cabin.",
    },
    {
        "brand": "Hyundai",
        "model": "Verna",
        "variant": "SX",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "CVT",
        "seating_capacity": 5,
        "price": Decimal("1250000.00"),
        "stock_quantity": 4,
        "description": "Feature-loaded sedan with a segment-first CVT, cooled driver seat and a premium glasshouse.",
    },
    {
        "brand": "Hyundai",
        "model": "Venue",
        "variant": "S",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("850000.00"),
        "stock_quantity": 5,
        "description": "Compact SUV-crossover with a clutchless manual option and best-in-class rear seat space.",
    },
    {
        "brand": "Mahindra",
        "model": "Thar",
        "variant": "4x4 Hard Top",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "MANUAL",
        "seating_capacity": 6,
        "price": Decimal("2400000.00"),
        "stock_quantity": 3,
        "description": "Off-road focused SUV with selectable drive modes, low-range gearing and a removable hard top.",
    },
    {
        "brand": "Mahindra",
        "model": "Scorpio-N",
        "variant": "Z8 L",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("2950000.00"),
        "stock_quantity": 2,
        "description": "Seven-seat diesel automatic SUV with a wide body, panoramic roof and long-distance touring setup.",
    },
    {
        "brand": "Mahindra",
        "model": "XUV700",
        "variant": "AX5 Pro",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("2300000.00"),
        "stock_quantity": 3,
        "description": "Diesel automatic midsize SUV with dual-screen cabin, ADAS and a flexible seven-seat layout.",
    },
    {
        "brand": "Toyota",
        "model": "Fortuner",
        "variant": "4x2 Automatic",
        "manufacturing_year": 2024,
        "fuel_type": "DIESEL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("4000000.00"),
        "stock_quantity": 2,
        "description": "Body-on-frame diesel SUV with permanent four-wheel drive and a captain-chair second row.",
    },
    {
        "brand": "Toyota",
        "model": "Innova HyCross",
        "variant": "GX",
        "manufacturing_year": 2024,
        "fuel_type": "HYBRID",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("2850000.00"),
        "stock_quantity": 3,
        "description": "Self-charging hybrid MPV with a flexible second row, twin power sliding doors and long road-trip range.",
    },
    {
        "brand": "Kia",
        "model": "Seltos",
        "variant": "HTK+",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("1400000.00"),
        "stock_quantity": 4,
        "description": "Feature-rich compact SUV with a clutchless manual, ventilated seats and a connected cockpit.",
    },
    {
        "brand": "Volkswagen",
        "model": "Virtus",
        "variant": "TSI Comfort",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 5,
        "price": Decimal("1300000.00"),
        "stock_quantity": 3,
        "description": "German-engineered sedan with a 1.5-litre TSI motor, six-speed automatic and a premium cabin.",
    },
    {
        "brand": "Skoda",
        "model": "Slavia",
        "variant": "Classic",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "MANUAL",
        "seating_capacity": 5,
        "price": Decimal("1350000.00"),
        "stock_quantity": 3,
        "description": "European compact sedan with a spacious interior, big central display and torque steer feel.",
    },
    {
        "brand": "Land Rover",
        "model": "Defender 110",
        "variant": "X-Dynamic",
        "manufacturing_year": 2024,
        "fuel_type": "PETROL",
        "transmission": "AUTOMATIC",
        "seating_capacity": 7,
        "price": Decimal("10700000.00"),
        "stock_quantity": 1,
        "description": "Flagship off-roader with air suspension, terrain response systems and a seven-seat cabin.",
    },
)


class Command(BaseCommand):
    help = "Seed the showroom inventory with realistic Indian market vehicles."

    def add_arguments(self, parser):
        parser.add_argument("--dealership-id", type=int)

    def handle(self, *args, **options):
        dealership = self._resolve_dealership(DealershipRepository(), options)
        service = VehicleService()
        created = 0

        for entry in SHOWROOM_INVENTORY:
            _, was_created = service.get_or_create_inventory(
                dealership=dealership,
                brand=entry["brand"],
                model=entry["model"],
                variant=entry["variant"],
                manufacturing_year=entry["manufacturing_year"],
                fuel_type=entry["fuel_type"],
                transmission=entry["transmission"],
                seating_capacity=entry["seating_capacity"],
                price=entry["price"],
                description=entry["description"],
                stock_quantity=entry["stock_quantity"],
                is_available=True,
            )
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new vehicle(s) for {dealership.name}. "
                f"{len(SHOWROOM_INVENTORY)} vehicles in the seed set, existing rows untouched."
            )
        )

    def _resolve_dealership(self, dealerships, options):
        if options["dealership_id"]:
            dealership = dealerships.get_by_id(options["dealership_id"])
            if dealership is None:
                raise CommandError(f"Dealership {options['dealership_id']} does not exist.")
            return dealership

        active = dealerships.list_active()

        if not active:
            raise CommandError("No active dealership exists. Pass --dealership-id.")

        if len(active) > 1:
            raise CommandError("Multiple dealerships exist. Pass --dealership-id.")

        return active[0]