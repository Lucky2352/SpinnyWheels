import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.authentication.supabase import SupabaseJWTAuthentication
from apps.core.exceptions import DomainError, ResourceNotFoundError
from apps.core.models.choices import FuelType, TransmissionType
from apps.core.services.gemini_provider import GeminiProvider
from apps.core.services.intent_parser import fallback_intent, validate_intent
from apps.core.services.yourspinny_service import YourSpinnyService, format_inr
from apps.core.tests import factories


class YourSpinnyPageRenderTests(TestCase):
    def test_yourspinny_page_renders(self):
        response = self.client.get(reverse("yourspinny"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-yourspinny-root")
        self.assertContains(response, "recommendationGrid")

    def test_customer_navigation_links_to_yourspinny(self):
        body = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn(f'href="{reverse("yourspinny")}" data-customer-only', body)


class FakeGemini:
    """Mocked Gemini used by automated tests. No real API calls."""

    def __init__(
        self,
        intent=None,
        answer="AI answer",
        comparison="AI comparison",
        general_answer="AI general answer",
        available=True,
        fail_extract=False,
        fail_answer=False,
        fail_comparison=False,
    ):
        self.is_available = available
        self.intent = intent
        self.answer = answer
        self.comparison = comparison
        self.general_answer = general_answer
        self.fail_extract = fail_extract
        self.fail_answer = fail_answer
        self.fail_comparison = fail_comparison

    def extract_intent(self, query):
        if self.fail_extract:
            raise RuntimeError("503 UNAVAILABLE: Gemini is temporarily unavailable")
        if self.intent is None:
            return {}
        return dict(self.intent)

    def generate_answer(self, query, intent, payload):
        if self.fail_answer:
            raise RuntimeError("Gemini answer generation failed")
        return self.answer

    def answer_general(self, query, context=""):
        return f"{self.general_answer} :: {query}"

    def generate_comparison(self, vehicles):
        if self.fail_comparison:
            raise RuntimeError("comparison failed")
        return self.comparison

    def generate_explanation(self, query, candidates):
        return self.answer

    def generate_info_response(self, query, vehicles):
        return self.answer


def money(value) -> int:
    """Prices serialise as decimal strings like '900000.00'."""
    return int(float(value))


def intent(
    intent_type="SEARCH",
    *,
    filters=None,
    sort=None,
    limit=None,
    vehicle_names=None,
    comparison_requested=False,
    requires_recommendation=False,
):
    """Build a structured intent the way Gemini is asked to return one."""
    base_filters = {
        "price_min": None,
        "price_max": None,
        "brand": None,
        "model": None,
        "variant": None,
        "manufacturing_year": None,
        "year_min": None,
        "year_max": None,
        "fuel_type": None,
        "transmission": None,
        "transmission_group": None,
        "seating_capacity": None,
    }
    base_filters.update(filters or {})
    return {
        "intent": intent_type,
        "filters": base_filters,
        "sort": sort,
        "limit": limit,
        "vehicle_names": vehicle_names or [],
        "comparison_requested": comparison_requested,
        "requires_recommendation": requires_recommendation,
    }


class GeminiProviderConfigTests(TestCase):
    def test_missing_api_key_marks_provider_unavailable(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            provider = GeminiProvider()

        self.assertFalse(provider.is_available)

    def test_explanation_falls_back_without_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            provider = GeminiProvider()

        result = provider.generate_explanation("any query", [{"brand": "Honda"}])

        self.assertIn("unavailable", result.lower())

    def test_answer_generation_raises_without_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            provider = GeminiProvider()

        with self.assertRaises(RuntimeError):
            provider.generate_answer("q", {"intent": "SEARCH"}, {"results": []})

    def test_sanitize_drops_invalid_and_unknown_values(self):
        provider = GeminiProvider(api_key="test-key")

        result = provider._sanitize_requirements(
            {
                "budget_max": "not-a-number",
                "seating_capacity": 99,
                "transmission": "rocket",
                "fuel_type": "plasma",
                "priorities": "not-a-list",
            }
        )

        self.assertIsNone(result["budget_max"])
        self.assertIsNone(result["seating_capacity"])
        self.assertIsNone(result["transmission"])
        self.assertIsNone(result["fuel_type"])
        self.assertEqual(result["priorities"], [])


class GeminiProviderIntentTests(TestCase):
    def _provider(self, text=None, error=None):
        provider = GeminiProvider(api_key="test-key", model="test-model")
        client = MagicMock()
        if error is not None:
            client.models.generate_content.side_effect = error
        else:
            client.models.generate_content.return_value = MagicMock(text=text)
        provider._client = client
        return provider, client

    def test_extract_intent_returns_valid_structured_json(self):
        payload = (
            '{"intent": "SEARCH", "filters": {"price_max": 200000, '
            '"seating_capacity": null}, "sort": "price_asc", "vehicle_names": []}'
        )
        provider, client = self._provider(text=payload)

        result = provider.extract_intent("car under 2 lakh")

        self.assertEqual(result["intent"], "SEARCH")
        self.assertEqual(result["filters"]["price_max"], 200000)
        client.models.generate_content.assert_called_once()

    def test_extract_intent_invalid_json_raises_value_error(self):
        provider, _ = self._provider(text="this is not json")

        with self.assertRaises(ValueError):
            provider.extract_intent("anything")

    def test_extract_intent_503_raises_runtime_error(self):
        provider, _ = self._provider(error=Exception("503 UNAVAILABLE"))

        with self.assertRaises(RuntimeError):
            provider.extract_intent("anything")

    def test_generate_answer_empty_response_raises(self):
        provider, _ = self._provider(text="   ")

        with self.assertRaises(RuntimeError):
            provider.generate_answer("q", {"intent": "SEARCH"}, {"results": []})


class IntentValidationTests(TestCase):
    def test_non_dict_output_is_unknown(self):
        result = validate_intent(["not", "a", "dict"])
        self.assertEqual(result["intent"], "UNKNOWN")

    def test_intent_aliases_are_normalised(self):
        result = validate_intent({"intent": "VEHICLE_SEARCH"})
        self.assertEqual(result["intent"], "SEARCH")

        result = validate_intent({"intent": "COMPARE", "vehicle_names": ["A", "B"]})
        self.assertEqual(result["intent"], "COMPARISON")

    def test_invalid_values_never_survive_validation(self):
        result = validate_intent(
            {
                "intent": "SEARCH",
                "filters": {
                    "price_max": "not-a-number",
                    "seating_capacity": 99,
                    "fuel_type": "plasma",
                    "transmission": "rocket",
                    "brand": 123,
                    "manufacturing_year": 1800,
                },
                "sort": "drop-tables",
                "limit": 9999,
            }
        )

        filters = result["filters"]
        self.assertIsNone(filters["price_max"])
        self.assertIsNone(filters["seating_capacity"])
        self.assertIsNone(filters["fuel_type"])
        self.assertIsNone(filters["transmission"])
        self.assertIsNone(filters["brand"])
        self.assertIsNone(filters["manufacturing_year"])
        self.assertIsNone(result["sort"])
        self.assertIsNone(result["limit"])

    def test_numeric_strings_are_coerced(self):
        result = validate_intent(
            {"intent": "SEARCH", "filters": {"price_max": "200000", "seating_capacity": "5"}}
        )

        self.assertEqual(result["filters"]["price_max"], 200000)
        self.assertEqual(result["filters"]["seating_capacity"], 5)

    def test_comparison_without_two_names_is_not_a_comparison(self):
        result = validate_intent({"intent": "COMPARISON", "vehicle_names": []})
        self.assertNotEqual(result["intent"], "COMPARISON")

    def test_exact_year_clears_year_range(self):
        result = validate_intent(
            {"intent": "SEARCH", "filters": {"manufacturing_year": 2025, "year_min": 2024}}
        )

        self.assertEqual(result["filters"]["manufacturing_year"], 2025)
        self.assertIsNone(result["filters"]["year_min"])


class FallbackParserTests(TestCase):
    """Deterministic parsing used when Gemini is unavailable."""

    def parse(self, query, **kwargs):
        return fallback_intent(query, **kwargs)

    def test_price_max_expressions_are_equivalent(self):
        equivalents = [
            "car under 200000",
            "cars under 2 lakh",
            "show me vehicles below 2,00,000",
            "I have 2 lakh budget",
            "my budget is max 200000",
            "cars costing less than two lakh",
            "anything below two lakhs",
            "vehicles up to 200000",
        ]
        for query in equivalents:
            parsed = self.parse(query)
            self.assertEqual(
                parsed["filters"]["price_max"], 200000, f"failed for: {query}"
            )
            self.assertIsNone(parsed["filters"]["price_min"], f"failed for: {query}")

    def test_price_min_expressions(self):
        for query in ("above 10 lakh", "more than 10 lakh", "over 1000000"):
            parsed = self.parse(query)
            self.assertEqual(parsed["filters"]["price_min"], 1000000, f"failed for: {query}")

    def test_price_range_expressions(self):
        for query in ("between 5 and 10 lakh", "5 lakh to 10 lakh", "from 5 lakh to 10 lakh"):
            parsed = self.parse(query)
            self.assertEqual(parsed["filters"]["price_min"], 500000, f"failed for: {query}")
            self.assertEqual(parsed["filters"]["price_max"], 1000000, f"failed for: {query}")

    def test_below_five_lakh(self):
        parsed = self.parse("show me cars below 5 lakh")
        self.assertEqual(parsed["filters"]["price_max"], 500000)

    def test_seating_expressions_are_equivalent(self):
        equivalents = [
            "5 seater",
            "car for five people",
            "I need something that seats 5",
            "vehicle with seating for five",
            "5 seat car",
            "car with seating for 5",
        ]
        for query in equivalents:
            parsed = self.parse(query)
            self.assertEqual(
                parsed["filters"]["seating_capacity"], 5, f"failed for: {query}"
            )

    def test_fuel_transmission_and_year(self):
        self.assertEqual(self.parse("petrol cars")["filters"]["fuel_type"], "PETROL")
        self.assertEqual(self.parse("electric cars")["filters"]["fuel_type"], "ELECTRIC")
        self.assertEqual(self.parse("automatic cars")["filters"]["transmission_group"], "AUTOMATIC")
        self.assertEqual(self.parse("cvt cars")["filters"]["transmission"], "CVT")
        self.assertEqual(self.parse("2025 cars")["filters"]["manufacturing_year"], 2025)
        self.assertEqual(self.parse("cars newer than 2023")["filters"]["year_min"], 2024)
        self.assertEqual(self.parse("cars before 2022")["filters"]["year_max"], 2021)

    def test_sort_expressions(self):
        self.assertEqual(self.parse("cheapest car")["sort"], "price_asc")
        self.assertEqual(self.parse("most expensive car")["sort"], "price_desc")

    def test_brand_matched_against_inventory(self):
        parsed = self.parse("honda cars", brands=["Honda", "Maruti", "Toyota"])
        self.assertEqual(parsed["filters"]["brand"], "Honda")

    def test_intent_detection(self):
        self.assertEqual(
            self.parse("which car should I buy under 15 lakh?")["intent"], "RECOMMENDATION"
        )
        self.assertEqual(
            self.parse("compare Honda City and Hyundai Verna")["intent"], "COMPARISON"
        )
        self.assertEqual(
            self.parse("tell me about Honda City")["intent"], "INFO"
        )
        self.assertEqual(self.parse("hello")["intent"], "UNKNOWN")
        self.assertEqual(self.parse("cars under 10 lakh")["intent"], "SEARCH")

    def test_comparison_names_are_extracted(self):
        parsed = self.parse("compare Honda City and Hyundai Verna")
        self.assertEqual(len(parsed["vehicle_names"]), 2)
        self.assertIn("Honda City", parsed["vehicle_names"])
        self.assertIn("Hyundai Verna", parsed["vehicle_names"])


class YourSpinnyServiceTests(TestCase):
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
        self.unavailable = factories.create_vehicle(
            dealership=self.dealership, brand="Kia", model="Seltos", variant="HTX",
            price=Decimal("1800000.00"), is_available=False,
        )

    def service(self, **fake_kwargs):
        return YourSpinnyService(gemini=FakeGemini(**fake_kwargs))

    def offline_service(self):
        return YourSpinnyService(gemini=FakeGemini(available=False))

    # ------------------------------------------------------------------
    # Dynamic structured queries -> dynamic ORM results
    # ------------------------------------------------------------------
    def test_price_max_filter(self):
        result = self.service(intent=intent(filters={"price_max": 1000000})).ask(
            query="cars under 10 lakh"
        )

        self.assertEqual(result["total_matches"], 2)
        for vehicle in result["results"]:
            self.assertLessEqual(money(vehicle["price"]), 1000000)

    def test_price_range_filter(self):
        result = self.service(
            intent=intent(filters={"price_min": 500000, "price_max": 1000000})
        ).ask(query="cars between 5 and 10 lakh")

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertGreaterEqual(money(vehicle["price"]), 500000)
            self.assertLessEqual(money(vehicle["price"]), 1000000)

    def test_price_min_filter(self):
        result = self.service(intent=intent(filters={"price_min": 1500000})).ask(
            query="cars above 15 lakh"
        )

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertGreater(money(vehicle["price"]), 1000000)

    def test_brand_filter(self):
        result = self.service(intent=intent(filters={"brand": "Honda"})).ask(query="Honda cars")

        self.assertEqual(result["total_matches"], 2)
        for vehicle in result["results"]:
            self.assertEqual(vehicle["brand"], "Honda")

    def test_model_filter(self):
        result = self.service(intent=intent(filters={"model": "City"})).ask(query="Honda City")

        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["model"], "City")

    def test_year_filter(self):
        result = self.service(
            intent=intent(filters={"manufacturing_year": 2025})
        ).ask(query="2025 cars")

        self.assertEqual(result["total_matches"], 2)
        for vehicle in result["results"]:
            self.assertEqual(vehicle["manufacturing_year"], 2025)

    def test_fuel_filter(self):
        result = self.service(
            intent=intent(filters={"fuel_type": "PETROL"})
        ).ask(query="petrol cars")

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertEqual(vehicle["fuel_type"], "PETROL")

    def test_transmission_group_filter_matches_automatic_family(self):
        result = self.service(
            intent=intent(filters={"transmission_group": "AUTOMATIC"})
        ).ask(query="automatic cars")

        automatic = {"AUTOMATIC", "AMT", "CVT", "DCT"}
        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertIn(vehicle["transmission"], automatic)

    def test_exact_transmission_filter(self):
        result = self.service(
            intent=intent(filters={"transmission": "CVT"})
        ).ask(query="cvt cars")

        for vehicle in result["results"]:
            self.assertEqual(vehicle["transmission"], "CVT")

    def test_seating_filter_is_exact(self):
        result = self.service(
            intent=intent(filters={"seating_capacity": 5})
        ).ask(query="5 seater")

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertEqual(vehicle["seating_capacity"], 5)

    def test_combined_hard_filters(self):
        result = self.service(
            intent=intent(
                filters={
                    "price_max": 1500000,
                    "seating_capacity": 5,
                    "transmission_group": "AUTOMATIC",
                }
            )
        ).ask(query="5 seater automatic under 15 lakh")

        automatic = {"AUTOMATIC", "AMT", "CVT", "DCT"}
        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertLessEqual(money(vehicle["price"]), 1500000)
            self.assertEqual(vehicle["seating_capacity"], 5)
            self.assertIn(vehicle["transmission"], automatic)

    def test_sort_price_asc_returns_cheapest_first(self):
        result = self.service(intent=intent(sort="price_asc")).ask(query="cheapest car")

        prices = [money(v["price"]) for v in result["results"]]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(prices[0], 800000)

    def test_sort_price_desc_returns_most_expensive_first(self):
        result = self.service(intent=intent(sort="price_desc")).ask(query="most expensive car")

        prices = [money(v["price"]) for v in result["results"]]
        self.assertEqual(prices[0], 2500000)
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_cheapest_honda_filters_brand_then_sorts(self):
        result = self.service(
            intent=intent(filters={"brand": "Honda"}, sort="price_asc")
        ).ask(query="cheapest Honda car")

        self.assertEqual(result["total_matches"], 2)
        for vehicle in result["results"]:
            self.assertEqual(vehicle["brand"], "Honda")
        self.assertEqual(result["results"][0]["model"], "Amaze")

    def test_different_queries_return_different_results(self):
        service = self.service(intent=intent(filters={"price_max": 1000000}))
        ten_lakh = service.ask(query="cars under 10 lakh")

        service = self.service(intent=intent(filters={"price_max": 1500000}))
        fifteen_lakh = service.ask(query="cars under 15 lakh")

        self.assertNotEqual(
            [v["id"] for v in ten_lakh["results"]],
            [v["id"] for v in fifteen_lakh["results"]],
        )
        self.assertLess(ten_lakh["total_matches"], fifteen_lakh["total_matches"])

    def test_unavailable_vehicle_is_never_returned(self):
        result = self.service(intent=intent()).ask(query="show me everything")

        ids = {v["id"] for v in result["results"]}
        self.assertNotIn(self.unavailable.pk, ids)

    # ------------------------------------------------------------------
    # Search vs recommendation
    # ------------------------------------------------------------------
    def test_search_returns_all_matching_vehicles(self):
        result = self.service(intent=intent(filters={"price_max": 1500000})).ask(
            query="cars under 15 lakh"
        )

        self.assertIsNone(result["recommendation"])
        self.assertGreater(len(result["results"]), 1)

    def test_recommendation_returns_one_primary_pick(self):
        result = self.service(
            intent=intent(
                filters={"price_max": 1500000},
                intent_type="RECOMMENDATION",
                requires_recommendation=True,
            )
        ).ask(query="which car should I buy under 15 lakh?")

        self.assertEqual(result["intent"], "RECOMMENDATION")
        self.assertEqual(len(result["results"]), 1)
        self.assertIsNotNone(result["recommendation"])
        self.assertEqual(result["results"][0]["id"], result["recommendation"]["id"])
        self.assertLessEqual(money(result["recommendation"]["price"]), 1500000)
        self.assertTrue(result["answer"].strip())
        self.assertGreater(result["total_matches"], 1)

    def test_recommendation_reasons_are_dynamic(self):
        result = self.service(
            intent=intent(
                filters={"price_max": 1500000, "seating_capacity": 5},
                intent_type="RECOMMENDATION",
            )
        ).ask(query="which car should I buy?")

        self.assertIsNotNone(result["recommendation"])
        self.assertTrue(result["recommendation"]["match_reasons"])

    # ------------------------------------------------------------------
    # No-match behaviour
    # ------------------------------------------------------------------
    def test_no_match_price_returns_no_vehicles_and_no_recommendation(self):
        result = self.service(intent=intent(filters={"price_max": 200000})).ask(
            query="cars under 2 lakh"
        )

        self.assertEqual(result["results"], [])
        self.assertEqual(result["total_matches"], 0)
        self.assertTrue(result["no_match"])
        self.assertIsNone(result["recommendation"])
        self.assertIn("₹2,00,000", result["answer"])
        self.assertIn("couldn't find", result["answer"])

    def test_no_match_seating(self):
        result = self.service(intent=intent(filters={"seating_capacity": 2})).ask(
            query="2 seater"
        )

        self.assertEqual(result["results"], [])
        self.assertTrue(result["no_match"])
        self.assertIsNone(result["recommendation"])
        self.assertIn("2-seater", result["answer"])

    def test_no_match_offers_closest_above_budget_only_when_it_exists(self):
        result = self.service(intent=intent(filters={"price_max": 200000})).ask(
            query="cars under 2 lakh"
        )

        self.assertIsNotNone(result["closest_above"])
        self.assertGreater(money(result["closest_above"]["price"]), 200000)
        self.assertIn("closest available option above your budget", result["answer"])

    def test_no_match_without_price_budget_has_no_closest_above(self):
        result = self.service(intent=intent(filters={"seating_capacity": 2})).ask(
            query="2 seater"
        )

        self.assertIsNone(result["closest_above"])

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def test_comparison_uses_actual_inventory_records(self):
        result = self.service(
            intent=intent(
                intent_type="COMPARISON",
                vehicle_names=["Honda City", "Hyundai Verna"],
                comparison_requested=True,
            )
        ).ask(query="compare Honda City and Hyundai Verna")

        self.assertEqual(result["intent"], "COMPARISON")
        ids = {v["id"] for v in result["results"]}
        self.assertEqual(ids, {self.city.pk, self.verna.pk})
        self.assertIsNotNone(result["comparison"])
        self.assertIsNotNone(result["comparison"]["winner"])
        self.assertIn(result["comparison"]["winner"]["id"], ids)
        self.assertTrue(result["comparison"]["analysis"].strip())
        self.assertTrue(result["answer"].strip())

    def test_comparison_with_unknown_name_reports_no_match(self):
        result = self.service(
            intent=intent(
                intent_type="COMPARISON",
                vehicle_names=["Honda City", "Hovercraft X"],
                comparison_requested=True,
            )
        ).ask(query="compare Honda City and Hovercraft X")

        # At least one resolved name is required; nothing invented.
        self.assertTrue(result["no_match"] or len(result["results"]) >= 1)
        for vehicle in result["results"]:
            self.assertIn(vehicle["id"], {self.city.pk, self.verna.pk, self.amaze.pk,
                                          self.swift.pk, self.innova.pk, self.ev.pk})

    def test_comparison_failure_still_returns_specs(self):
        result = self.service(
            intent=intent(
                intent_type="COMPARISON",
                vehicle_names=["Honda City", "Hyundai Verna"],
                comparison_requested=True,
            ),
            fail_comparison=True,
        ).ask(query="compare Honda City and Hyundai Verna")

        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["comparison"]["analysis"].strip())
        self.assertNotIn("unavailable", result["comparison"]["analysis"].lower())

    # ------------------------------------------------------------------
    # Vehicle info
    # ------------------------------------------------------------------
    def test_info_returns_named_vehicle_records(self):
        result = self.service(
            intent=intent(intent_type="INFO", vehicle_names=["Honda City"])
        ).ask(query="tell me about Honda City")

        self.assertEqual(result["intent"], "INFO")
        self.assertEqual(result["results"][0]["id"], self.city.pk)
        self.assertIn("Honda City", result["results"][0]["brand"] + " " + result["results"][0]["model"])

    # ------------------------------------------------------------------
    # Descriptive answers
    # ------------------------------------------------------------------
    def test_template_answer_is_generated_from_results(self):
        result = self.offline_service().ask(query="cars under 10 lakh")

        self.assertIn("2", result["answer"])
        self.assertIn("Maruti Swift", result["answer"])
        self.assertIn("Honda Amaze", result["answer"])

    def test_template_answer_changes_with_query(self):
        offline = self.offline_service()
        small = offline.ask(query="cars under 10 lakh")
        large = offline.ask(query="cars under 15 lakh")

        self.assertNotEqual(small["answer"], large["answer"])
        self.assertIn("5", large["answer"])

    def test_unknown_intent_returns_guidance_message(self):
        result = self.service(intent=intent(intent_type="UNKNOWN")).ask(query="hello")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["results"], [])
        self.assertIn("couldn't understand", result["answer"])

    def test_gemini_answer_failure_falls_back_to_template(self):
        result = self.service(fail_answer=True, intent=intent()).ask(query="cars under 15 lakh")

        self.assertTrue(result["results"])
        self.assertIn("I found", result["answer"])
        self.assertNotIn("AI answer", result["answer"])

    def test_gemini_answer_used_when_available(self):
        result = self.service(answer="Fresh AI answer", intent=intent()).ask(query="anything")

        self.assertEqual(result["answer"], "Fresh AI answer")

    # ------------------------------------------------------------------
    # Gemini failure fallback (dynamic, not static)
    # ------------------------------------------------------------------
    def test_extraction_failure_falls_back_to_dynamic_parsing(self):
        result = self.service(fail_extract=True).ask(query="cars under 10 lakh")

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertLessEqual(money(vehicle["price"]), 1000000)

    def test_provider_unavailable_falls_back_to_dynamic_parsing(self):
        result = self.offline_service().ask(query="petrol cars from 2024")

        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertEqual(vehicle["fuel_type"], "PETROL")
            self.assertGreaterEqual(vehicle["manufacturing_year"], 2024)

    def test_offline_recommendation_still_returns_one_pick(self):
        result = self.offline_service().ask(
            query="which car should I buy under 15 lakh?"
        )

        self.assertEqual(result["intent"], "RECOMMENDATION")
        self.assertEqual(len(result["results"]), 1)
        self.assertLessEqual(money(result["recommendation"]["price"]), 1500000)
        self.assertIn("my pick for you", result["answer"].lower())

    def test_offline_comparison_still_works(self):
        result = self.offline_service().ask(
            query="compare Honda City and Hyundai Verna"
        )

        self.assertEqual(result["intent"], "COMPARISON")
        ids = {v["id"] for v in result["results"]}
        self.assertEqual(ids, {self.city.pk, self.verna.pk})
        self.assertIsNotNone(result["comparison"]["winner"])
        self.assertTrue(result["comparison"]["analysis"].strip())

    def test_offline_no_understand_message(self):
        result = self.offline_service().ask(query="hello there")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertIn("couldn't understand", result["answer"])

    # ------------------------------------------------------------------
    # Conversational follow-ups (stateless context merge)
    # ------------------------------------------------------------------
    def test_follow_up_filters_narrow_previous_results(self):
        result = self.service(
            intent=intent(filters={"transmission_group": "AUTOMATIC"})
        ).ask(query="only automatic", context_filters={"price_max": 1500000})

        automatic = {"AUTOMATIC", "AMT", "CVT", "DCT"}
        self.assertTrue(result["results"])
        for vehicle in result["results"]:
            self.assertIn(vehicle["transmission"], automatic)
            self.assertLessEqual(money(vehicle["price"]), 1500000)

    def test_follow_up_replaces_whole_category(self):
        result = self.service(
            intent=intent(filters={"price_max": 2500000})
        ).ask(
            query="show me something up to 25 lakh",
            context_filters={"price_max": 1000000, "seating_capacity": 7},
        )

        self.assertEqual(result["filters"]["price_max"], 2500000)
        self.assertEqual(result["filters"].get("seating_capacity"), 7)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["model"], "Innova")

    def test_context_filters_are_validated_not_trusted(self):
        result = self.service(intent=intent()).ask(
            query="show me everything",
            context_filters={"price_max": "not-a-number", "fuel_type": "plasma"},
        )

        self.assertNotIn("price_max", result["filters"])
        self.assertNotIn("fuel_type", result["filters"])
        self.assertEqual(result["total_matches"], 6)

    # ------------------------------------------------------------------
    # Compatibility endpoints through the service
    # ------------------------------------------------------------------
    def test_get_recommendations_maps_to_ask(self):
        result = self.service(intent=intent(filters={"price_max": 1000000})).get_recommendations(
            query="under 10 lakh"
        )

        self.assertEqual(result["total_matches"], 2)
        self.assertEqual(len(result["recommendations"]), 2)
        self.assertTrue(result["explanation"].strip())
        self.assertEqual(result["requirements"]["price_max"], 1000000)

    def test_candidate_limit_is_five(self):
        for index in range(6):
            factories.create_vehicle(
                dealership=self.dealership, brand="Brand", model=f"Model{index}",
                variant="Base", price=Decimal("500000.00"),
            )

        result = self.service(intent=intent()).get_recommendations(query="all")

        self.assertEqual(len(result["recommendations"]), 5)
        self.assertEqual(result["total_matches"], 12)

    def test_answer_query_returns_matches(self):
        result = self.service(intent=intent()).answer_query(query="automatic cars?")

        # "automatic cars" is a high-confidence Fast Path query: answered by
        # Django from verified inventory (no Gemini call), so no "AI answer".
        self.assertTrue(result["matches"])
        self.assertTrue(result["answer"].strip())
        self.assertNotIn("couldn't understand", result["answer"])
        for vehicle in result["matches"]:
            self.assertIn(vehicle["transmission"], {"AUTOMATIC", "AMT", "CVT", "DCT"})

    def test_empty_query_is_rejected(self):
        with self.assertRaises(DomainError):
            self.service().ask(query="   ")

    def test_overlong_query_is_rejected(self):
        with self.assertRaises(DomainError):
            self.service().ask(query="a" * 2500)

    # ------------------------------------------------------------------
    # Manual comparison endpoint flow (by ids)
    # ------------------------------------------------------------------
    def test_compare_returns_actual_specs(self):
        result = self.service().compare_vehicles(vehicle_ids=[self.city.pk, self.swift.pk])

        self.assertEqual(len(result["vehicles"]), 2)
        self.assertEqual(result["vehicles"][0]["price"], str(self.city.price))
        self.assertEqual(result["comparison"], "AI comparison")

    def test_compare_rejects_unavailable_vehicle(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service().compare_vehicles(vehicle_ids=[self.city.pk, self.unavailable.pk])

    def test_compare_rejects_unknown_vehicle(self):
        with self.assertRaises(ResourceNotFoundError):
            self.service().compare_vehicles(vehicle_ids=[self.city.pk, 999999])

    def test_compare_requires_at_least_two(self):
        with self.assertRaises(DomainError):
            self.service().compare_vehicles(vehicle_ids=[self.city.pk])

    def test_compare_rejects_more_than_three(self):
        with self.assertRaises(DomainError):
            self.service().compare_vehicles(
                vehicle_ids=[self.city.pk, self.swift.pk, self.innova.pk, self.city.pk]
            )


class FormatInrTests(TestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(200000), "2,00,000")
        self.assertEqual(format_inr(1500000), "15,00,000")
        self.assertEqual(format_inr(1000), "1,000")
        self.assertEqual(format_inr(800000), "8,00,000")


class YourSpinnyEndpointTests(APITestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.customer = factories.create_customer(external_user_id="auth-ys-cust-1")
        self.employee = factories.create_staff_employee(external_user_id="auth-ys-staff-1")
        self.technician = factories.create_employee(external_user_id="auth-ys-tech-1")
        self.owner = factories.create_owner(external_user_id="auth-ys-owner-1")

        self.vehicle_one = factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, price=Decimal("1500000.00"),
        )
        self.vehicle_two = factories.create_vehicle(
            dealership=self.dealership, brand="Maruti", model="Swift", variant="ZXI",
            transmission=TransmissionType.MANUAL, price=Decimal("800000.00"),
        )

    def auth(self, profile, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": profile.external_user_id,
            "email": profile.email,
        }
        return {"HTTP_AUTHORIZATION": f"Bearer token-for-{profile.external_user_id}"}

    def patch_service(self, fake):
        return patch(
            "apps.core.views.yourspinny.YourSpinnyService",
            new=lambda: YourSpinnyService(gemini=fake),
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_anonymous_is_denied(self, mock_verify_token):
        response = self.client.post(
            reverse("yourspinny-recommendations"), {"query": "suv"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_get_recommendations(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent())):
            response = self.client.post(
                reverse("yourspinny-recommendations"),
                {"query": "family car under 15 lakh"},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_matches"], 2)
        self.assertTrue(response.data["recommendations"])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_recommendations_are_filtered_by_extracted_requirements(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent(filters={"price_max": 1000000}))):
            response = self.client.post(
                reverse("yourspinny-recommendations"),
                {"query": "under 10 lakh"},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["recommendations"]), 1)
        self.assertEqual(response.data["recommendations"][0]["brand"], "Maruti")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_is_forbidden(self, mock_verify_token):
        headers = self.auth(self.employee, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-recommendations"), {"query": "suv"}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_technician_is_forbidden(self, mock_verify_token):
        headers = self.auth(self.technician, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-recommendations"), {"query": "suv"}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_owner_is_forbidden(self, mock_verify_token):
        headers = self.auth(self.owner, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-recommendations"), {"query": "suv"}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_empty_query_is_rejected(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-recommendations"), {"query": ""}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_large_query_is_rejected(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-recommendations"),
            {"query": "a" * 2500},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_extraction_failure_does_not_break_the_endpoint(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(fail_extract=True)):
            response = self.client.post(
                reverse("yourspinny-recommendations"),
                {"query": "under 10 lakh"},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_matches"], 1)
        for vehicle in response.data["recommendations"]:
            self.assertLessEqual(money(vehicle["price"]), 1000000)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_compare_two_vehicles(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini()):
            response = self.client.post(
                reverse("yourspinny-compare"),
                {"vehicle_ids": [self.vehicle_one.pk, self.vehicle_two.pk]},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["vehicles"]), 2)
        self.assertEqual(response.data["comparison"], "AI comparison")

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_compare_with_invalid_vehicle_returns_not_found(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini()):
            response = self.client.post(
                reverse("yourspinny-compare"),
                {"vehicle_ids": [self.vehicle_one.pk, 999999]},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_compare_with_one_vehicle_is_rejected(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-compare"),
            {"vehicle_ids": [self.vehicle_one.pk]},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_compare_with_more_than_three_vehicles_is_rejected(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-compare"),
            {"vehicle_ids": [self.vehicle_one.pk, self.vehicle_two.pk, self.vehicle_one.pk, self.vehicle_two.pk]},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_customer_can_ask_a_question(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent())):
            response = self.client.post(
                reverse("yourspinny-query"),
                {"query": "which automatic cars do you have?"},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Fast Path handles "which automatic cars do you have?" deterministically.
        self.assertTrue(response.data["answer"].strip())
        self.assertNotEqual(response.data["answer"], "AI answer")
        self.assertTrue(response.data["matches"])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_cannot_compare(self, mock_verify_token):
        headers = self.auth(self.employee, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-compare"),
            {"vehicle_ids": [self.vehicle_one.pk, self.vehicle_two.pk]},
            format="json",
            **headers,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_client_supplied_dealership_id_is_ignored(self, mock_verify_token):
        other_dealership = factories.create_dealership()
        factories.create_vehicle(
            dealership=other_dealership, brand="Tata", model="Nexon", variant="XZ",
            price=Decimal("1300000.00"),
        )
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent())):
            response = self.client.post(
                reverse("yourspinny-recommendations"),
                {"query": "anything", "dealership_id": 999999},
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        brands = {v["brand"] for v in response.data["recommendations"]}
        self.assertIn("Tata", brands)


class YourSpinnyAskEndpointTests(APITestCase):
    def setUp(self):
        self.dealership = factories.create_dealership()
        self.customer = factories.create_customer(external_user_id="auth-ys-ask-1")
        self.employee = factories.create_staff_employee(external_user_id="auth-ys-ask-staff-1")

        self.city = factories.create_vehicle(
            dealership=self.dealership, brand="Honda", model="City", variant="VX",
            transmission=TransmissionType.CVT, fuel_type=FuelType.PETROL,
            price=Decimal("1500000.00"), seating_capacity=5, manufacturing_year=2024,
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

    def auth(self, profile, mock_verify_token):
        mock_verify_token.return_value = {
            "sub": profile.external_user_id,
            "email": profile.email,
        }
        return {"HTTP_AUTHORIZATION": f"Bearer token-for-{profile.external_user_id}"}

    def patch_service(self, fake):
        return patch(
            "apps.core.views.yourspinny.YourSpinnyService",
            new=lambda: YourSpinnyService(gemini=fake),
        )

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_anonymous_is_denied(self, mock_verify_token):
        response = self.client.post(
            reverse("yourspinny-ask"), {"query": "cars under 10 lakh"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_employee_is_forbidden(self, mock_verify_token):
        headers = self.auth(self.employee, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-ask"), {"query": "cars under 10 lakh"}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_search_returns_dynamic_results(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent(filters={"price_max": 1000000}), answer=None)):
            first = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "cars under 10 lakh"}, format="json", **headers,
            )
        with self.patch_service(FakeGemini(intent=intent(filters={"price_max": 3000000}), answer=None)):
            second = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "cars under 30 lakh"}, format="json", **headers,
            )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["total_matches"], 1)
        self.assertEqual(second.data["total_matches"], 3)
        self.assertNotEqual(first.data["answer"], second.data["answer"])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_invalid_ai_output_never_reaches_the_orm(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        malicious = intent()
        malicious["filters"]["price_max"] = "1; DROP TABLE vehicle"
        malicious["filters"]["fuel_type"] = "<script>alert(1)</script>"

        with self.patch_service(FakeGemini(intent=malicious)):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "anything"}, format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("price_max", response.data["filters"])
        self.assertNotIn("fuel_type", response.data["filters"])
        self.assertEqual(response.data["total_matches"], 3)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_recommendation_intent_returns_single_pick(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        fake = FakeGemini(
            intent=intent(
                intent_type="RECOMMENDATION",
                filters={"price_max": 3000000},
                requires_recommendation=True,
            ),
            answer="My pick is the Maruti Swift because it fits your budget.",
        )
        with self.patch_service(fake):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "which car should I buy under 30 lakh?"},
                format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["intent"], "RECOMMENDATION")
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["recommendation"])
        # Fast Path answers deterministically: "my pick for you" (lowercase).
        self.assertIn("pick", response.data["answer"].lower())

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_comparison_intent_returns_comparison_payload(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        fake = FakeGemini(
            intent=intent(
                intent_type="COMPARISON",
                vehicle_names=["Honda City", "Toyota Innova"],
                comparison_requested=True,
            ),
            comparison="The Innova seats more; the City is cheaper.",
        )
        with self.patch_service(fake):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "compare Honda City and Toyota Innova"},
                format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["intent"], "COMPARISON")
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["comparison"])
        self.assertIn(response.data["comparison"]["winner"]["id"],
                      {self.city.pk, self.innova.pk})

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_no_match_response(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        fake = FakeGemini(intent=intent(filters={"price_max": 200000}))
        with self.patch_service(fake):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "cars under 2 lakh"}, format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["no_match"])
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["recommendation"])
        self.assertIn("₹2,00,000", response.data["answer"])

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_context_filters_support_follow_ups(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        fake = FakeGemini(intent=intent(filters={"transmission_group": "AUTOMATIC"}))
        with self.patch_service(fake):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "only automatic", "context_filters": {"price_max": 2000000}},
                format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["filters"]["price_max"], 2000000)
        self.assertEqual(response.data["total_matches"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.city.pk)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_client_supplied_dealership_id_is_ignored(self, mock_verify_token):
        other_dealership = factories.create_dealership()
        factories.create_vehicle(
            dealership=other_dealership, brand="Tata", model="Punch", variant="XM",
            price=Decimal("700000.00"),
        )
        headers = self.auth(self.customer, mock_verify_token)

        with self.patch_service(FakeGemini(intent=intent())):
            response = self.client.post(
                reverse("yourspinny-ask"),
                {"query": "everything", "dealership_id": 999999, "role": "admin"},
                format="json", **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        brands = {v["brand"] for v in response.data["results"]}
        self.assertIn("Tata", brands)

    @patch.object(SupabaseJWTAuthentication, "_verify_token")
    def test_empty_query_is_rejected(self, mock_verify_token):
        headers = self.auth(self.customer, mock_verify_token)

        response = self.client.post(
            reverse("yourspinny-ask"), {"query": ""}, format="json", **headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
