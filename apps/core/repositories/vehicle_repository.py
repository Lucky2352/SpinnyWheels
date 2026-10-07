from django.db.models import Q

from apps.core.models import Vehicle


class VehicleRepository:
    AUTOMATIC_TRANSMISSIONS = ("AUTOMATIC", "AMT", "CVT", "DCT")

    def get_by_id(self, vehicle_id):
        return Vehicle.objects.select_related("dealership").filter(pk=vehicle_id).first()

    def _available_queryset(self, dealership_id=None):
        queryset = Vehicle.objects.select_related("dealership").filter(
            is_available=True, stock_quantity__gt=0
        )
        if dealership_id:
            queryset = queryset.filter(dealership_id=dealership_id)
        return queryset

    def search(self, *, dealership_id=None, filters=None, sort=None, limit=None,
               exclusions=None):
        """Dynamically filter inventory with the ORM.

        Only validated, structured filters ever reach this method; the query is
        built with Django ORM lookups, never with generated SQL.  Explicit
        exclusions ("but not diesel") are applied as ORM exclusions so they can
        never silently become positive filters.
        """
        queryset = self._available_queryset(dealership_id)
        filters = filters or {}

        if filters.get("price_max") is not None:
            queryset = queryset.filter(price__lte=filters["price_max"])
        if filters.get("price_min") is not None:
            queryset = queryset.filter(price__gte=filters["price_min"])
        if filters.get("brand"):
            queryset = queryset.filter(brand__icontains=filters["brand"])
        if filters.get("model"):
            queryset = queryset.filter(model__icontains=filters["model"])
        if filters.get("variant"):
            queryset = queryset.filter(variant__icontains=filters["variant"])
        if filters.get("manufacturing_year") is not None:
            queryset = queryset.filter(manufacturing_year=filters["manufacturing_year"])
        if filters.get("year_min") is not None:
            queryset = queryset.filter(manufacturing_year__gte=filters["year_min"])
        if filters.get("year_max") is not None:
            queryset = queryset.filter(manufacturing_year__lte=filters["year_max"])
        if filters.get("fuel_type"):
            queryset = queryset.filter(fuel_type__iexact=filters["fuel_type"])
        if filters.get("transmission"):
            queryset = queryset.filter(transmission__iexact=filters["transmission"])
        if filters.get("transmission_group") == "AUTOMATIC":
            queryset = queryset.filter(transmission__in=list(self.AUTOMATIC_TRANSMISSIONS))
        elif filters.get("transmission_group") == "MANUAL":
            queryset = queryset.filter(transmission__iexact="MANUAL")
        if filters.get("seating_capacity") is not None:
            queryset = queryset.filter(seating_capacity=filters["seating_capacity"])

        queryset = self._apply_exclusions(queryset, exclusions)

        ordering = {"price_asc": "price", "price_desc": "-price"}.get(sort)
        if ordering:
            queryset = queryset.order_by(ordering, "brand", "model", "variant")

        if limit:
            queryset = queryset[:limit]
        return list(queryset)

    def _apply_exclusions(self, queryset, exclusions):
        if not exclusions:
            return queryset

        brand_q = Q()
        for brand in exclusions.get("brands") or []:
            brand_q |= Q(brand__iexact=brand)
        if exclusions.get("brands"):
            queryset = queryset.exclude(brand_q)

        model_q = Q()
        for model in exclusions.get("models") or []:
            model_q |= Q(model__iexact=model)
        if exclusions.get("models"):
            queryset = queryset.exclude(model_q)

        if exclusions.get("fuel_types"):
            queryset = queryset.exclude(fuel_type__in=list(exclusions["fuel_types"]))

        if exclusions.get("transmissions"):
            queryset = queryset.exclude(transmission__in=list(exclusions["transmissions"]))

        return queryset

    def find_by_names(self, names, *, dealership_id=None):
        """Resolve natural-language vehicle names (e.g. 'Honda City') to records."""
        results: list[Vehicle] = []
        seen: set[int] = set()
        for name in names or []:
            tokens = [t for t in str(name).split() if t]
            if not tokens:
                continue
            query = Q()
            for token in tokens:
                query &= (
                    Q(brand__icontains=token)
                    | Q(model__icontains=token)
                    | Q(variant__icontains=token)
                )
            queryset = self._available_queryset(dealership_id).filter(query)
            for vehicle in queryset[:10]:
                if vehicle.pk not in seen:
                    seen.add(vehicle.pk)
                    results.append(vehicle)
        return results

    def distinct_brands(self, *, dealership_id=None):
        return list(
            self._available_queryset(dealership_id)
            .order_by("brand")
            .values_list("brand", flat=True)
            .distinct()
        )

    def distinct_models(self, *, dealership_id=None):
        return list(
            self._available_queryset(dealership_id)
            .order_by("brand", "model")
            .values_list("brand", "model")
            .distinct()
        )

    def list_available(self, *, brand=None, dealership_id=None):
        queryset = self._available_queryset(dealership_id).order_by(
            "brand", "model", "variant"
        )
        if brand:
            queryset = queryset.filter(brand__iexact=brand)
        return list(queryset)

    def list_inventory(self, *, dealership_id=None, brand=None, search=None):
        queryset = Vehicle.objects.select_related("dealership")
        if dealership_id:
            queryset = queryset.filter(dealership_id=dealership_id)
        if brand:
            queryset = queryset.filter(brand__iexact=brand)
        if search:
            queryset = queryset.filter(
                Q(brand__icontains=search)
                | Q(model__icontains=search)
                | Q(variant__icontains=search)
            )
        return list(queryset.order_by("brand", "model", "variant"))

    def list_by_dealership(self, dealership_id):
        return list(
            Vehicle.objects.filter(dealership_id=dealership_id).order_by(
                "brand", "model", "variant"
            )
        )

    def create(self, **fields):
        return Vehicle.objects.create(**fields)

    def get_or_create(self, **fields):
        return Vehicle.objects.get_or_create(**fields)

    def update(self, vehicle, **fields):
        return vehicle.apply_changes(**fields)

    def delete(self, vehicle):
        vehicle.delete()
