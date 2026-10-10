"""OUT_OF_SCOPE regression tests for YourSpinny.

Irrelevant questions must be refused politely without touching vehicle
inventory; automotive questions must keep working exactly as before.
Gemini is fully mocked, so no real API is ever contacted.
"""
from decimal import Decimal

from django.test import TestCase

from apps.core.models.choices import FuelType, TransmissionType
from apps.core.repositories.vehicle_repository import VehicleRepository
from apps.core.services.yourspinny_service import OUT_OF_SCOPE_MESSAGE, YourSpinnyService
from apps.core.tests import factories


class FakeGemini:
    def __init__(self, intent=None, available=True):
        self.is_available = available
        self._intent = intent
        self.calls = {"extract_intent": 0, "generate_answer": 0, "answer_general": 0}

    def extract_intent(self, query):
        self.calls["extract_intent"] += 1
        if self._intent is None:
            return {}
        return dict(self._intent)

    def generate_answer(self, query, intent, payload):
        self.calls["generate_answer"] += 1
        return "AI answer"

    def answer_general(self, query, context=""):
        self.calls["answer_general"] += 1
        return "AI general answer :: %s" % query

    def generate_comparison(self, vehicles):
        return "AI comparison"


class TrackingRepository(VehicleRepository):
    def __init__(self):
        super().__init__()
        self.search_calls = 0

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


class OutOfScopeTests(TestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, fuel_type=FuelType.PETROL,
            price=Decimal("1500000.00"), seating_capacity=5, manufacturing_year=2024,
        )
        factories.create_vehicle(
            dealership=self.dealership, brand="Maruti", model="Swift", variant="ZXI",
            transmission=TransmissionType.MANUAL, fuel_type=FuelType.PETROL,
            price=Decimal("800000.00"), seating_capacity=5, manufacturing_year=2023,
        )

    def ask(self, query, **kwargs):
        gemini = FakeGemini(intent=None, available=False)
        service = YourSpinnyService(
            gemini=gemini, vehicle_repo=TrackingRepository(), **kwargs
        )
        result = service.ask(query=query)
        return result, gemini, service

    def test_capital_of_france_is_out_of_scope(self):
        result, _, _ = self.ask("What is the capital of France?")

        self.assertEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["results"], [])
        self.assertIn("automobile AI assistant", result["answer"])

    def test_joke_is_out_of_scope(self):
        result, _, _ = self.ask("Tell me a joke")

        self.assertEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["results"], [])
        self.assertIn("automobile AI assistant", result["answer"])

    def test_cricket_match_is_out_of_scope(self):
        result, _, _ = self.ask("Who won the cricket match?")

        self.assertEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["results"], [])
        self.assertIn("automobile AI assistant", result["answer"])

    def test_automatic_transmission_is_not_out_of_scope(self):
        result, _, _ = self.ask("What is automatic transmission?")

        self.assertNotEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["query_type"], "GENERAL_INFO")

    def test_which_car_should_i_buy_is_not_out_of_scope(self):
        result, _, _ = self.ask("Which car should I buy?")

        self.assertNotEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(result["intent"], "RECOMMENDATION")

    def test_cars_under_20_lakh_still_searches_inventory(self):
        result, _, _ = self.ask("Show me cars under 20 lakh")

        self.assertEqual(result["query_type"], "INVENTORY_SEARCH")
        self.assertTrue(result["results"])
        self.assertEqual(result["total_matches"], 2)

    def test_fast_path_inventory_query_does_not_call_gemini(self):
        gemini = FakeGemini(intent=None, available=True)
        service = YourSpinnyService(gemini=gemini)

        result = service.ask(query="cars under 20 lakh")

        self.assertEqual(result["processing_path"], "fast_path")
        self.assertEqual(gemini.calls["extract_intent"], 0)
        self.assertEqual(gemini.calls["generate_answer"], 0)

    def test_complex_query_still_falls_back_to_gemini(self):
        gemini = FakeGemini(intent=None, available=True)
        service = YourSpinnyService(gemini=gemini)

        service.ask(query="family car under 15 lakh")

        self.assertEqual(gemini.calls["extract_intent"], 1)

    def test_out_of_scope_does_not_query_inventory(self):
        result, _, service = self.ask("What is the capital of France?")

        self.assertEqual(result["query_type"], "OUT_OF_SCOPE")
        self.assertEqual(service._vehicles.search_calls, 0)

    def test_out_of_scope_produces_no_vehicle_cards(self):
        result, _, _ = self.ask("Tell me a joke")

        self.assertEqual(result["results"], [])
        self.assertIsNone(result["recommendation"])
        self.assertIsNone(result["comparison"])
        self.assertIsNone(result["closest_above"])
        self.assertEqual(result["answer"], OUT_OF_SCOPE_MESSAGE)
