"""Fast Path + Gemini fallback tests for YourSpinny.

These regression tests pin down the two-pipeline contract:

* Common, high-confidence queries ("car under 2000000", "20 lakh ke andar car",
  "cheapest Honda", "automatic cars") are answered by the deterministic Fast
  Path with ZERO Gemini calls and no redundant inventory lookups.
* Complex / ambiguous / conversational / typo queries fall back to Gemini, and
  an invalid/absent Gemini output can never reach the ORM.

Gemini is fully mocked (``FakeGemini``), so no real API is ever contacted.
"""
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.core.models.choices import FuelType, TransmissionType
from apps.core.repositories.vehicle_repository import VehicleRepository
from apps.core.services.gemini_provider import GeminiProvider
from apps.core.services.yourspinny_service import YourSpinnyService
from apps.core.tests import factories


class FakeGemini:
    """Mocked Gemini that records every call made against it."""

    def __init__(
        self,
        intent=None,
        answer="AI answer",
        comparison="AI comparison",
        general_answer="AI general answer",
        available=True,
    ):
        self.is_available = available
        self._intent = intent
        self.answer = answer
        self.comparison = comparison
        self.general_answer = general_answer
        self.calls = {"extract_intent": 0, "generate_answer": 0, "answer_general": 0}

    def extract_intent(self, query):
        self.calls["extract_intent"] += 1
        if self._intent is None:
            return {}
        return dict(self._intent)

    def generate_answer(self, query, intent, payload):
        self.calls["generate_answer"] += 1
        return self.answer

    def answer_general(self, query, context=""):
        self.calls["answer_general"] += 1
        return f"{self.general_answer} :: {query}"

    def generate_comparison(self, vehicles):
        return self.comparison


class TrackingRepository(VehicleRepository):
    """Counts only the lazy inventory lookups and searches issued by pytest."""

    def __init__(self):
        super().__init__()
        self.lookup_calls = 0
        self.search_calls = 0

    def distinct_brands(self, *, dealership_id=None):
        self.lookup_calls += 1
        return super().distinct_brands(dealership_id=dealership_id)

    def distinct_models(self, *, dealership_id=None):
        self.lookup_calls += 1
        return super().distinct_models(dealership_id=dealership_id)

    def search(self, *, dealership_id=None, filters=None, sort=None, limit=None,
               exclusions=None):
        self.search_calls += 1
        return super().search(
            dealership_id=dealership_id,
            filters=filters,
            sort=sort,
            limit=limit,
            exclusions=exclusions,
        )


def intent(intent_type="SEARCH", **overrides):
    base_filters = {
        "price_min": None, "price_max": None, "brand": None, "model": None,
        "variant": None, "manufacturing_year": None, "year_min": None,
        "year_max": None, "fuel_type": None, "transmission": None,
        "transmission_group": None, "seating_capacity": None,
    }
    data = {
        "intent": intent_type,
        "filters": base_filters,
        "sort": None,
        "limit": None,
        "vehicle_names": [],
        "comparison_requested": False,
        "requires_recommendation": False,
    }
    data.update(overrides)
    return data


class FastPathServiceTests(TestCase):
    """The Fast Path resolves common queries with zero Gemini calls."""

    def setUp(self):
        self.dealership = factories.create_dealership()
        self.city = factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, fuel_type=FuelType.PETROL,
            price=Decimal("1500000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        self.amaze = factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="Amaze", variant="E",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("900000.00"), seating_capacity=5, manufacturing_year=2023,
        )
        self.swift = factories.create_vehicle(
            dealership=self.dealership, brand="Maruti", model="Swift", variant="ZXI",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("800000.00"), seating_capacity=5, manufacturing_year=2023,
        )
        self.innova = factories.create_vehicle(
            dealership=self.dealership, brand="Toyota", model="Innova", variant="GX",
            transmission=TransmissionType.AUTOMATIC, fuel_type=FuelType.DIESEL,
            price=Decimal("2500000.00"), seating_capacity=7, manufacturing_year=2025,
        )
        self.verna = factories.create_vehicle(
            dealership=self.dealership, brand="Hyundai", model="Verna", variant="SX",
            transmission=TransmissionType.DCT, fuel_type=FuelType.PETROL,
            price=Decimal("1400000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        self.ev = factories.create_vehicle(
            dealership=self.dealership, brand="Tata", model="Nexon", variant="EV",
            transmission=TransmissionType.AUTOMATIC, fuel_type=FuelType.ELECTRIC,
            price=Decimal("1200000.00"), seating_capacity=5, manufacturing_year=2025,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Kia", model="Seltos", variant="HTX",
            price=Decimal("1800000.00"), is_available=False,
        )

    def ask(self, query, **kwargs):
        gemini = FakeGemini(intent=intent())
        service = YourSpinnyService(
            gemini=gemini,
            vehicle_repo=TrackingRepository(),
        )
        result = service.ask(query=query, **kwargs)
        return result, gemini, service

    # ------------------------------------------------------------------
    # Mandatory regression: common queries never touch Gemini
    # ------------------------------------------------------------------

    def test_car_under_2000000_does_not_invoke_gemini(self):
        result, gemini, _ = self.ask("car under 2000000")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["intent_source"], "local")
        self.assertEqual(result["total_matches"], 5)
        self.assertEqual(gemini.calls["extract_intent"], 0)
        self.assertEqual(gemini.calls["generate_answer"], 0)
        self.assertEqual(result["filters"]["price_max"], 2000000)

    def test_hinglish_budget_does_not_invoke_gemini(self):
        result, gemini, _ = self.ask("20 lakh ke andar car")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["filters"]["price_max"], 2000000)
        self.assertEqual(gemini.calls["extract_intent"], 0)
        self.assertEqual(gemini.calls["generate_answer"], 0)

    def test_cheapest_honda_is_fast_path_recommendation(self):
        result, gemini, _ = self.ask("cheapest Honda")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["intent"], "RECOMMENDATION")
        self.assertEqual(result["query_type"], "INVENTORY_RECOMMENDATION")
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual(result["results"][0]["model"], "Amaze")
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_common_search_queries_are_fast_path(self):
        for query, expected_max in (
            ("automatic cars", None),
            ("Honda cars", None),
            ("cars between 10 and 15 lakh", 1500000),
            ("cars above 15 lakh", None),
            ("5 seater automatic under 15 lakh", 1500000),
        ):
            result, gemini, _ = self.ask(query)
            self.assertEqual(result["processing_path"], "fast_path", query)
            self.assertEqual(result["intent_source"], "local", query)
            self.assertEqual(
                result["filters"].get("price_max"), expected_max, query
            )
            self.assertEqual(gemini.calls["extract_intent"], 0, query)

    # ------------------------------------------------------------------
    # Mandatory regression: unknown / complex queries DO invoke Gemini
    # ------------------------------------------------------------------

    def test_unknown_complex_query_invokes_gemini(self):
        result, gemini, _ = self.ask("family car under 15 lakh")

        self.assertEqual(gemini.calls["extract_intent"], 1)
        self.assertEqual(result["processing_path"], "gemini_fallback")
        self.assertEqual(result["intent_source"], "gemini")

    def test_typo_query_invokes_gemini(self):
        result, gemini, _ = self.ask("hyndai city car")

        self.assertEqual(gemini.calls["extract_intent"], 1)
        self.assertEqual(result["processing_path"], "gemini_fallback")

    def test_ambiguous_budget_with_other_filters_goes_to_gemini(self):
        result, gemini, _ = self.ask("around 20 lakh automatic")

        self.assertEqual(gemini.calls["extract_intent"], 1)
        self.assertEqual(result["processing_path"], "gemini_fallback")

    def test_fast_path_answer_is_deterministic_template(self):
        # Fast-path answers are deterministic Django text, never "AI answer".
        result, _, _ = self.ask("automatic cars")
        self.assertTrue(result["answer"].strip())
        self.assertNotEqual(result["answer"], "AI answer")

    # ------------------------------------------------------------------
    # Lazy, memoized inventory lookup — no redundant DB queries
    # ------------------------------------------------------------------

    def test_vocab_only_query_never_touches_inventory_lookup(self):
        _, _, service = self.ask("car under 2000000")

        self.assertEqual(service._vehicles.lookup_calls, 0)
        self.assertEqual(service._vehicles.search_calls, 1)

    def test_brand_query_uses_memoized_lookup_once(self):
        _, _, service = self.ask("Honda cars")
        # One full lazy lookup = distinct_brands + distinct_models.
        self.assertEqual(service._vehicles.lookup_calls, 2)

        # Second query on the same service reuses the memoised lookup.
        service.ask(query="Maruti cars")
        self.assertEqual(service._vehicles.lookup_calls, 2)

    # ------------------------------------------------------------------
    # General knowledge questions are never inventory searches
    # ------------------------------------------------------------------

    def test_faq_question_answers_without_database(self):
        result, gemini, service = self.ask("what is ABS")

        self.assertEqual(result["query_type"], "GENERAL_INFO")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total_matches"], 0)
        self.assertEqual(service._vehicles.search_calls, 0)
        self.assertIn("braking", result["answer"].lower())
        self.assertEqual(gemini.calls["answer_general"], 0)

    def test_general_question_not_in_faq_uses_gemini_knowledge(self):
        result, gemini, service = self.ask("how does a turbocharger work")

        self.assertEqual(result["query_type"], "GENERAL_INFO")
        self.assertEqual(result["results"], [])
        self.assertEqual(service._vehicles.search_calls, 0)
        # The answer itself is generated by Gemini (general knowledge), while
        # the intent was classified locally as a general question.
        self.assertEqual(gemini.calls["answer_general"], 1)
        self.assertEqual(gemini.calls["extract_intent"], 0)
        self.assertTrue(result["answer"].strip())

    # ------------------------------------------------------------------
    # Vehicle information ("tell me about X")
    # ------------------------------------------------------------------

    def test_vehicle_info_found_in_inventory(self):
        result, gemini, _ = self.ask("tell me about Honda City")

        self.assertEqual(result["query_type"], "VEHICLE_INFO")
        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["model"], "City")
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_vehicle_info_not_stocked_uses_general_answer(self):
        # "tell me about Maruti Ertiga": Ertiga is not stocked, so this must
        # produce a general answer — never a "no vehicles found" search reply
        # and never a silent list of every other car.
        result, gemini, _ = self.ask("tell me about Maruti Ertiga")

        self.assertEqual(result["results"], [])
        self.assertNotIn("no vehicles found", result["answer"].lower())
        self.assertTrue(result["answer"].strip())

    # ------------------------------------------------------------------
    # Availability ("do you have X?") — truthful yes/no
    # ------------------------------------------------------------------

    def test_availability_when_in_stock(self):
        result, gemini, _ = self.ask("is Innova available")

        self.assertEqual(result["query_type"], "INVENTORY_AVAILABILITY")
        self.assertTrue(result["results"])
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_availability_when_not_in_stock_is_truthful_no(self):
        result, _, _ = self.ask("do you have Maruti Ertiga")

        self.assertEqual(result["query_type"], "INVENTORY_AVAILABILITY")
        self.assertEqual(result["results"], [])
        self.assertTrue(result["no_match"])
        self.assertIn("not currently available", result["answer"].lower())

    # ------------------------------------------------------------------
    # Exclusions ("but not diesel") — ORM exclusions, never positive filters
    # ------------------------------------------------------------------

    def test_exclusions_are_applied_and_never_become_filters(self):
        result, gemini, _ = self.ask("cars under 20 lakh but not diesel")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(gemini.calls["extract_intent"], 0)
        self.assertIsNone(result["filters"].get("fuel_type"))
        self.assertEqual(result.get("exclusions", {}).get("fuel_types"), ["DIESEL"])
        self.assertNotIn("Innova", [v["model"] for v in result["results"]])

    def test_automatic_exclusion_expands_to_the_automatic_family(self):
        result, _, _ = self.ask("automatic cars but not cvt")

        transmissions = {v["transmission"] for v in result["results"]}
        self.assertNotIn("CVT", transmissions)
        self.assertIn("CVT", result["exclusions"]["transmissions"])

    # ------------------------------------------------------------------
    # Clarification / out-of-scope
    # ------------------------------------------------------------------

    def test_ambiguous_budget_alone_is_clarification(self):
        result, gemini, service = self.ask("around 20 lakh")

        self.assertEqual(result["query_type"], "CLARIFICATION")
        self.assertEqual(result["results"], [])
        self.assertEqual(service._vehicles.search_calls, 0)
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_greeting_is_out_of_scope(self):
        result, _, _ = self.ask("hello")

        self.assertEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["results"], [])

    # ------------------------------------------------------------------
    # Context modes
    # ------------------------------------------------------------------

    def test_new_search_drops_previous_filters(self):
        result, _, _ = self.ask(
            "Honda cars", context_filters={"price_max": 2000000}
        )
        self.assertEqual(result["context_mode"], "NEW_SEARCH")
        self.assertEqual(result["filters"].get("brand"), "Honda")
        # New search names the vehicle class, so the old price context is gone.
        self.assertIsNone(result["filters"].get("price_max"))
        self.assertEqual(result["total_matches"], 2)

    def test_follow_up_only_replaces_touched_filter_category(self):
        result, _, _ = self.ask(
            "only automatic",
            context_filters={"price_max": 3000000, "seating_capacity": 7},
        )
        self.assertEqual(result["context_mode"], "FOLLOW_UP")
        # Transmission category was replaced; price and seating survive from
        # the previous turn.
        self.assertEqual(result["filters"]["transmission_group"], "AUTOMATIC")
        self.assertEqual(result["filters"]["price_max"], 3000000)
        self.assertEqual(result["filters"]["seating_capacity"], 7)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["model"], "Innova")

    # ------------------------------------------------------------------
    # Context resolution ordering: follow-up replaces the category it mentions
    # ------------------------------------------------------------------

    def test_follow_up_price_replaces_price_but_keeps_fuel(self):
        result, _, _ = self.ask(
            "make it under 10 lakh",
            context_filters={"price_max": 1500000, "fuel_type": "PETROL"},
        )
        self.assertEqual(result["context_mode"], "FOLLOW_UP")
        self.assertEqual(result["filters"]["price_max"], 1000000)
        self.assertEqual(result["filters"]["fuel_type"], "PETROL")

    def test_follow_up_clears_filters_category_when_needed(self):
        result, _, _ = self.ask(
            "up to 25 lakh",
            context_filters={"price_max": 1500000, "seating_capacity": 7},
        )
        self.assertEqual(result["context_mode"], "FOLLOW_UP")
        self.assertEqual(result["filters"]["price_max"], 2500000)
        self.assertEqual(result["filters"]["seating_capacity"], 7)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["model"], "Innova")


class FastPathComparisonTests(TestCase):
    """Compare works on the Fast Path without Gemini for stocked vehicles."""

    def setUp(self):
        self.dealership = factories.create_dealership()
        self.city = factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, fuel_type=FuelType.PETROL,
            price=Decimal("1500000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        self.verna = factories.create_vehicle(
            dealership=self.dealership, brand="Hyundai", model="Verna", variant="SX",
            transmission=TransmissionType.DCT, fuel_type=FuelType.PETROL,
            price=Decimal("1400000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        self.innova = factories.create_vehicle(
            dealership=self.dealership, brand="Toyota", model="Innova", variant="GX",
            transmission=TransmissionType.AUTOMATIC, fuel_type=FuelType.DIESEL,
            price=Decimal("2500000.00"), seating_capacity=7, manufacturing_year=2025,
        )

    def _ask(self, query, gemini=None):
        gemini = gemini or FakeGemini(intent=intent())
        return YourSpinnyService(gemini=gemini).ask(query=query), gemini

    def test_comparison_a_both_stocked_is_fast_path(self):
        result, gemini = self._ask("compare Honda City and Hyundai Verna")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["intent"], "COMPARISON")
        self.assertEqual(result["query_type"], "INVENTORY_COMPARISON")
        self.assertEqual(len(result["results"]), 2)
        self.assertIsNotNone(result["comparison"])
        self.assertTrue(result["comparison"]["analysis"].strip())
        self.assertEqual(gemini.calls["generate_answer"], 0)
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_comparison_b_neither_stocked_uses_gemini_general(self):
        result, gemini = self._ask("compare BMW X5 and Mercedes GLE")

        self.assertEqual(result["query_type"], "GENERAL_COMPARISON")
        self.assertEqual(result["results"], [])
        self.assertEqual(gemini.calls["answer_general"], 1)
        self.assertIn("BMW X5", result["answer"])

    def test_comparison_c_one_stocked_distinguishes_showroom_facts(self):
        result, gemini = self._ask("compare Honda City and Rolls Royce Phantom")

        self.assertEqual(result["intent"], "COMPARISON")
        self.assertTrue(result["results"])
        self.assertIn("Honda City", result["answer"])
        # Missing vehicle must be clearly separated, never silently dropped.
        self.assertIn("not part of our current showroom inventory", result["answer"])
        self.assertEqual(gemini.calls["answer_general"], 1)

    def test_comparison_offline_both_missing_is_truthful(self):
        offline = FakeGemini(intent=intent(), available=False, general_answer="")
        result, _ = self._ask("compare BMW X5 and Mercedes GLE", gemini=offline)

        self.assertTrue(result["no_match"])
        self.assertIn("couldn't find", result["answer"].lower())


class FastPathFallbackWithInvalidGeminiTests(TestCase):
    """Invalid Gemini output can never reach the ORM, even on fallback."""

    def setUp(self):
        self.dealership = factories.create_dealership()
        factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, fuel_type=FuelType.PETROL,
            price=Decimal("1500000.00"), seating_capacity=5, manufacturing_year=2024,
        )

    def test_malicious_gemini_filters_are_sanitized(self):
        gemini = FakeGemini(
            intent={
                "intent": "SEARCH",
                "filters": {
                    "price_max": "drop table vehicles",
                    "fuel_type": "plasma",
                    "seating_capacity": 99,
                    "brand": 123,
                },
            }
        )
        service = YourSpinnyService(gemini=gemini)

        # A non-fast-path query so Gemini is actually asked for an intent.
        result = service.ask(query="best sporty coupe for highway driving")

        self.assertEqual(result["processing_path"], "gemini_fallback")
        self.assertIsNone(result["filters"].get("price_max"))
        self.assertIsNone(result["filters"].get("fuel_type"))
        self.assertIsNone(result["filters"].get("seating_capacity"))
        self.assertIsNone(result["filters"].get("brand"))
        # The engine still answered with real (unfiltered) inventory.
        self.assertEqual(result["total_matches"], 1)


class FastPathOfflineTests(TestCase):
    """Fast Path keeps working when Gemini is completely unavailable."""

    def setUp(self):
        self.dealership = factories.create_dealership()
        self.swift = factories.create_vehicle(
            dealership=self.dealership, brand="Maruti", model="Swift", variant="ZXI",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("800000.00"), seating_capacity=5, manufacturing_year=2023,
        )
        self.innova = factories.create_vehicle(
            dealership=self.dealership, brand="Toyota", model="Innova", variant="GX",
            transmission=TransmissionType.AUTOMATIC, fuel_type=FuelType.DIESEL,
            price=Decimal("2500000.00"), seating_capacity=7, manufacturing_year=2025,
        )

    def test_fast_path_queries_work_offline(self):
        service = YourSpinnyService(gemini=FakeGemini(available=False))

        result = service.ask(query="cheapest car")
        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["results"][0]["model"], "Swift")

        # Swift (8L) fits under 20 lakh; Innova (25L) does not.
        result = service.ask(query="cars under 20 lakh")
        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["total_matches"], 1)

    def test_unknown_queries_offline_use_legacy_fallback(self):
        service = YourSpinnyService(gemini=FakeGemini(available=False))

        result = service.ask(query="family car under 15 lakh")
        self.assertEqual(result["processing_path"], "gemini_fallback")
        self.assertEqual(result["intent_source"], "local")
        self.assertGreaterEqual(result["total_matches"], 1)


class BrandResolutionTests(TestCase):
    """Regression: real inventory brands resolve on the Fast Path.

    * "tata" is both a goodbye word and the Tata brand: brand usage must win
      whenever the query names vehicles, while a genuine goodbye ("bye",
      "tata" alone) must stay conversational.
    * Multi-word brands ("Maruti Suzuki") must resolve from any distinctive
      brand word ("Maruti cars"), using inventory brand values only.
    """

    def setUp(self):
        self.dealership = factories.create_dealership()
        factories.create_vehicle(
            dealership=self.dealership, brand="Tata", model="Nexon", variant="Smart",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("825000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Tata", model="Punch", variant="Pure",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("715000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Maruti Suzuki", model="Swift", variant="VXi",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("795000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Maruti Suzuki", model="Baleno", variant="Delta",
            transmission=TransmissionType.AMT, fuel_type=FuelType.PETROL,
            price=Decimal("945000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Hyundai", model="Creta", variant="E",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("1105000.00"), seating_capacity=5, manufacturing_year=2023,
        )

    def ask(self, query, **kwargs):
        gemini = FakeGemini(intent=intent())
        service = YourSpinnyService(gemini=gemini)
        return service.ask(query=query, dealership_id=self.dealership.pk, **kwargs), gemini

    def assertBrandSearch(self, query, brand, total):
        result, gemini = self.ask(query)
        self.assertEqual(result["processing_path"], "fast_path", query)
        self.assertEqual(result["intent"], "SEARCH", query)
        self.assertEqual(result["filters"]["brand"], brand, query)
        self.assertEqual(result["total_matches"], total, query)
        self.assertEqual(gemini.calls["extract_intent"], 0, query)
        models = {v["model"] for v in result["results"]}
        self.assertTrue(models, query)
        return result

    def test_tata_brand_queries_are_inventory_searches(self):
        for query in (
            "tata cars",
            "Tata cars",
            "show me Tata cars",
            "which Tata cars do you have?",
            "Tata vehicles",
            "Tata cars under 15 lakh",
        ):
            with self.subTest(query=query):
                result = self.assertBrandSearch(query, "Tata", 2)
                self.assertTrue(
                    all(v["brand"] == "Tata" for v in result["results"]), query
                )

    def test_maruti_brand_queries_resolve_maruti_suzuki(self):
        for query in (
            "Maruti cars",
            "Maruti Suzuki cars",
            "show me Maruti cars",
            "show me Maruti Suzuki cars",
            "Maruti vehicles",
        ):
            with self.subTest(query=query):
                result = self.assertBrandSearch(query, "Maruti Suzuki", 2)
                self.assertTrue(
                    all(v["brand"] == "Maruti Suzuki" for v in result["results"]),
                    query,
                )

    def test_maruti_queries_combine_with_other_filters(self):
        result, gemini = self.ask("Maruti Suzuki under 10 lakh")
        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["filters"]["brand"], "Maruti Suzuki")
        self.assertEqual(result["filters"]["price_max"], 1000000)
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual(gemini.calls["extract_intent"], 0)

        result, gemini = self.ask("automatic Maruti cars")
        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["filters"]["brand"], "Maruti Suzuki")
        self.assertEqual(result["filters"]["transmission_group"], "AUTOMATIC")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["model"], "Baleno")
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_other_brands_keep_working(self):
        result, gemini = self.ask("Hyundai cars")
        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(result["filters"]["brand"], "Hyundai")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(gemini.calls["extract_intent"], 0)

    def test_genuine_goodbyes_stay_conversational(self):
        for query in ("bye", "tata"):
            with self.subTest(query=query):
                result, gemini = self.ask(query)
                self.assertEqual(result["query_type"], "OUT_OF_SCOPE", query)
                self.assertEqual(result["results"], [], query)


class MagicMockClient:
    """Minimal stand-in for genai.Client with a text-returning model."""

    def __init__(self):
        response = MagicMock()
        response.text = "A turbocharger forces more air into the engine."
        model = MagicMock()
        model.generate_content.return_value = response
        self.models = model


class FastPathGeminiProviderContractTests(TestCase):
    """The Gemini provider prompt + answer_general stay wired up."""

    def test_answer_general_returns_text(self):
        provider = GeminiProvider(api_key="test-key", model="test-model")
        provider._client = MagicMockClient()
        answer = provider.answer_general("how does a turbocharger work")
        self.assertTrue(answer)

    def test_answer_general_requires_api_key(self):
        # No API key in the environment -> provider unavailable, no call.
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            provider = GeminiProvider()
            self.assertFalse(provider.is_available)
            with self.assertRaises(RuntimeError):
                provider.answer_general("what is abs")