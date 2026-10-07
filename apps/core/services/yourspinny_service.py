import logging
from dataclasses import dataclass
from typing import Optional

from apps.core.exceptions import DomainError, ResourceNotFoundError
from apps.core.repositories.vehicle_repository import VehicleRepository
from apps.core.services.gemini_provider import GeminiProvider
from apps.core.services.intent_parser import fallback_intent, validate_intent
from apps.core.services.query_matcher import classify_context, faq_lookup, match_query

logger = logging.getLogger("autoflow.ai")

UNKNOWN_MESSAGE = (
    "I couldn't understand that vehicle request. Try something like "
    "'cars under ₹10 lakh', '5-seater automatic cars', or "
    "'compare Honda City and Hyundai Verna'."
)

CLARIFICATION_MESSAGE = (
    "Could you clarify that? I don't want to guess your budget. You can say "
    "'cars under ₹10 lakh', 'cars between ₹10 and ₹15 lakh', or "
    "'cars above ₹8 lakh'."
)

GENERAL_UNAVAILABLE_MESSAGE = (
    "I don't have an answer for that right now: it isn't part of the showroom "
    "inventory data, and the AI assistant is temporarily unavailable."
)

AUTOMATIC_TRANSMISSIONS = {"AUTOMATIC", "AMT", "CVT", "DCT"}

# Filter categories used for stateless conversational follow-ups: when a new
# utterance sets any filter in a category, it replaces that category from the
# previous turn instead of merging with it.
FILTER_CATEGORIES = {
    "price": ("price_min", "price_max"),
    "identity": ("brand", "model", "variant"),
    "year": ("manufacturing_year", "year_min", "year_max"),
    "fuel": ("fuel_type",),
    "transmission": ("transmission", "transmission_group"),
    "seating": ("seating_capacity",),
}


@dataclass
class RecommendationCandidate:
    vehicle: object
    score: float
    match_reasons: list[str]


def format_inr(amount) -> str:
    """Format an amount with Indian digit grouping (200000 -> 2,00,000)."""
    try:
        value = int(amount)
    except (TypeError, ValueError):
        return str(amount)
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if len(digits) <= 3:
        return f"{sign}{digits}"
    last_three = digits[-3:]
    rest = digits[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return sign + ",".join(groups) + "," + last_three


class YourSpinnyService:
    MAX_CANDIDATES = 5
    MAX_COMPARISON_VEHICLES = 3
    MAX_ANSWER_VEHICLES = 8

    def __init__(
        self,
        vehicle_repo: Optional[VehicleRepository] = None,
        gemini: Optional[GeminiProvider] = None,
    ):
        self._vehicles = vehicle_repo or VehicleRepository()
        self._gemini = gemini or GeminiProvider()
        # Per-instance cache of distinct brands/models: at most two cheap
        # DISTINCT queries per request, only when the matcher actually needs
        # to resolve brand/model tokens.
        self._lookup_cache: Optional[dict] = None

    # ------------------------------------------------------------------
    # Unified dynamic query flow
    # ------------------------------------------------------------------
    def ask(
        self,
        *,
        query: str,
        dealership_id: Optional[int] = None,
        context_filters: Optional[dict] = None,
    ) -> dict:
        self._validate_query(query)

        intent, meta = self._resolve_intent(query, context_filters)
        intent_name = intent["intent"]
        query_type = intent["query_type"]

        logger.info(
            "yourspinny ask processing_path=%s intent_source=%s query_type=%s intent=%s",
            meta["processing_path"],
            meta["intent_source"],
            query_type,
            intent_name,
        )

        if intent_name == "UNKNOWN":
            answer = (
                CLARIFICATION_MESSAGE if query_type == "CLARIFICATION" else UNKNOWN_MESSAGE
            )
            return self._response(
                query, intent, answer=answer, results=[], total_matches=0, meta=meta
            )

        if query_type == "GENERAL_INFO":
            # Never queries the database: general automotive knowledge only.
            return self._response(
                query,
                intent,
                answer=self._general_answer(query),
                results=[],
                total_matches=0,
                meta=meta,
            )

        if intent_name == "COMPARISON":
            return self._handle_comparison(query, intent, dealership_id, meta)

        if intent_name == "INFO" and intent["vehicle_names"]:
            # Named-vehicle questions are answered from the named records only.
            # When a name is not in stock we must answer about that name
            # truthfully (general knowledge / availability "no") — never fall
            # back to silently listing every other vehicle.
            vehicles = self._vehicles.find_by_names(
                intent["vehicle_names"], dealership_id=dealership_id
            )
        else:
            vehicles = self._vehicles.search(
                dealership_id=dealership_id,
                filters=intent["filters"],
                sort=intent["sort"],
                limit=intent["limit"],
                exclusions=intent.get("exclusions"),
            )

        total_matches = len(vehicles)

        if total_matches == 0:
            if query_type == "VEHICLE_INFO" and intent["vehicle_names"]:
                # "Tell me about X" must never answer "no vehicles found" when
                # X simply isn't stocked: answer from general knowledge.
                label = " and ".join(intent["vehicle_names"])
                return self._response(
                    query,
                    intent,
                    answer=self._general_answer(
                        f"{query} (note: {label} is not in the current showroom inventory)"
                    ),
                    results=[],
                    total_matches=0,
                    meta=meta,
                )
            if query_type == "INVENTORY_AVAILABILITY" and intent["vehicle_names"]:
                label = " and ".join(intent["vehicle_names"])
                return self._response(
                    query,
                    intent,
                    answer=(
                        f"No — {label} is not currently available in our showroom "
                        "inventory. Would you like me to find something similar?"
                    ),
                    results=[],
                    total_matches=0,
                    no_match=True,
                    meta=meta,
                )
            answer, closest = self._no_match_response(intent, dealership_id)
            return self._response(
                query,
                intent,
                answer=answer,
                results=[],
                total_matches=0,
                no_match=True,
                closest_above=closest,
                meta=meta,
            )

        recommendation = None
        results = vehicles
        if intent_name == "RECOMMENDATION":
            ranked = self._rank(vehicles, intent["filters"], intent.get("sort"))
            recommendation = ranked[0].vehicle
            results = [recommendation]

        answer = self._generate_answer(
            query, intent, results, total_matches, recommendation, meta
        )
        return self._response(
            query,
            intent,
            answer=answer,
            results=results,
            total_matches=total_matches,
            recommendation=recommendation,
            meta=meta,
        )

    def get_recommendations(
        self,
        *,
        query: str,
        dealership_id: Optional[int] = None,
    ) -> dict:
        result = self.ask(query=query, dealership_id=dealership_id)
        return {
            "query": query,
            "requirements": result["filters"],
            "recommendations": result["results"][: self.MAX_CANDIDATES],
            "explanation": result["answer"],
            "total_matches": result["total_matches"],
        }

    def answer_query(
        self,
        *,
        query: str,
        dealership_id: Optional[int] = None,
    ) -> dict:
        result = self.ask(query=query, dealership_id=dealership_id)
        return {
            "query": query,
            "matches": result["results"],
            "answer": result["answer"],
            "total_matches": result["total_matches"],
            "intent": result["intent"],
            "filters": result["filters"],
        }

    def compare_vehicles(
        self,
        *,
        vehicle_ids: list[int],
        dealership_id: Optional[int] = None,
    ) -> dict:
        if len(vehicle_ids) < 2:
            raise DomainError("At least 2 vehicles are required for comparison.")
        if len(vehicle_ids) > self.MAX_COMPARISON_VEHICLES:
            raise DomainError(f"Maximum {self.MAX_COMPARISON_VEHICLES} vehicles can be compared.")

        vehicles = self._vehicles.list_available(dealership_id=dealership_id)
        vehicle_map = {v.pk: v for v in vehicles}

        selected = []
        for vid in vehicle_ids:
            if vid not in vehicle_map:
                raise ResourceNotFoundError(f"Vehicle {vid} not found or not available.")
            selected.append(vehicle_map[vid])

        vehicle_data = [self._vehicle_to_dict(v, 1.0, []) for v in selected]

        comparison = ""
        if self._gemini.is_available:
            try:
                comparison = self._gemini.generate_comparison(vehicle_data)
            except Exception:
                comparison = "AI comparison temporarily unavailable."

        return {
            "vehicles": vehicle_data,
            "comparison": comparison,
        }

    # ------------------------------------------------------------------
    # Intent resolution: Fast Path first, Gemini fallback second.
    # Both paths emit the same canonical intent and both pass through the
    # same validation layer before anything reaches the ORM.
    # ------------------------------------------------------------------
    def _validate_query(self, query: str) -> None:
        if not query or not query.strip():
            raise DomainError("Query cannot be empty.")
        if len(query) > 2000:
            raise DomainError("Query is too long. Please keep it under 2000 characters.")

    def _resolve_intent(self, query: str, context_filters: Optional[dict]) -> tuple[dict, dict]:
        # Deterministic context classification applies to both paths: the
        # previous turn only carries over for explicit follow-up fragments.
        context_mode = classify_context(query, context_filters)

        meta = {"processing_path": "gemini_fallback", "intent_source": "local"}

        # 1. Fast Path: high-confidence local match, no Gemini call.
        match = match_query(
            query,
            known_context=context_filters,
            inventory_lookup=self._inventory_lookup,
        )

        intent = None
        if match.get("matched"):
            raw = match.get("intent")
            intent = validate_intent(raw) if isinstance(raw, dict) else None
            if intent is not None:
                meta = {"processing_path": "fast_path", "intent_source": "local"}

        # 2. Gemini fallback: strict structured JSON into the SAME validator.
        if intent is None and self._gemini.is_available:
            try:
                raw = self._gemini.extract_intent(query)
                if isinstance(raw, dict):
                    intent = validate_intent(raw)
                    if intent["intent"] == "UNKNOWN" and not raw.get("intent"):
                        intent = None
                    else:
                        meta = {
                            "processing_path": "gemini_fallback",
                            "intent_source": "gemini",
                        }
            except Exception as exc:
                logger.warning("Gemini intent extraction failed, using fallback: %s", exc)
                intent = None

        # 3. Deterministic last resort when Gemini is unavailable/unusable.
        if intent is None:
            intent = self._fallback_intent(query)

        # Context policy is owned by Django, never by the model: re-apply the
        # locally classified mode after validation.
        intent["context_mode"] = context_mode
        if context_mode == "FOLLOW_UP" and context_filters:
            intent = self._merge_context(intent, context_filters)

        return intent, meta

    def _inventory_lookup(self) -> dict:
        """Distinct brands/models, memoised per service instance."""
        if self._lookup_cache is None:
            self._lookup_cache = {
                "brands": tuple(self._vehicles.distinct_brands()),
                "models": tuple(self._vehicles.distinct_models()),
            }
        return self._lookup_cache

    def _fallback_intent(self, query: str) -> dict:
        lookup = {"brands": (), "models": ()}
        try:
            lookup = self._inventory_lookup()
        except Exception:  # pragma: no cover - DB unavailable during fallback
            pass
        return fallback_intent(
            query, brands=lookup["brands"], models=lookup["models"]
        )

    def _merge_context(self, intent: dict, context_filters: dict) -> dict:
        """Apply previous-turn filters for conversational follow-ups.

        A new utterance replaces whole filter categories it mentions; anything
        it does not mention carries over from the previous turn.
        """
        context = validate_intent({"filters": context_filters})
        if intent["intent"] not in {"SEARCH", "RECOMMENDATION", "INFO"}:
            return intent

        context_filters_valid = context["filters"]
        touched = set()
        for category, keys in FILTER_CATEGORIES.items():
            if any(intent["filters"].get(key) is not None for key in keys):
                touched.add(category)

        for category, keys in FILTER_CATEGORIES.items():
            if category in touched:
                continue
            for key in keys:
                value = context_filters_valid.get(key)
                if value is not None and intent["filters"].get(key) is None:
                    intent["filters"][key] = value

        if intent["sort"] is None and context["sort"]:
            intent["sort"] = context["sort"]
        return intent

    # ------------------------------------------------------------------
    # Comparison intent (inventory-backed and general)
    # ------------------------------------------------------------------
    def _handle_comparison(
        self, query: str, intent: dict, dealership_id, meta: Optional[dict] = None
    ) -> dict:
        meta = meta or {}
        names = intent["vehicle_names"]
        label = " and ".join(names) if names else "those vehicles"

        # Resolve each name separately so we can tell showroom facts apart
        # from vehicles that simply are not in our inventory.
        unique: list = []
        seen: set = set()
        missing: list[str] = []
        for name in names:
            found = self._vehicles.find_by_names([name], dealership_id=dealership_id) or []
            if not found:
                missing.append(name)
            for vehicle in found:
                if vehicle.pk not in seen:
                    seen.add(vehicle.pk)
                    unique.append(vehicle)

        # CASE B: nothing in inventory -> general automotive comparison.
        if not unique:
            if self._gemini.is_available:
                intent = dict(intent)
                intent["query_type"] = "GENERAL_COMPARISON"
                answer = self._general_answer(
                    f"{query} (neither vehicle is in the current showroom inventory; "
                    "answer with general automotive knowledge)"
                )
                return self._response(
                    query,
                    intent,
                    answer=answer,
                    results=[],
                    total_matches=0,
                    meta=meta,
                )
            answer = f"I couldn't find {label} in our current showroom inventory."
            return self._response(
                query,
                intent,
                answer=answer,
                results=[],
                total_matches=0,
                no_match=True,
                meta=meta,
            )

        # CASE C: at least one name is not stocked — clearly distinguish the
        # verified showroom facts from general information about the rest.
        if missing:
            vehicles = unique[: self.MAX_COMPARISON_VEHICLES]
            vehicle_data = [self._vehicle_to_dict(v, 1.0, []) for v in vehicles]
            ranked = self._rank(vehicles, {})
            winner = ranked[0]
            analysis = self._comparison_template(vehicles, winner.vehicle)
            missing_label = " and ".join(missing)
            analysis += (
                f" {missing_label} is not part of our current showroom inventory, "
                "so no showroom specifications are shown for it."
            )
            general_note = ""
            if self._gemini.is_available:
                general_note = self._general_answer(
                    f"In two or three sentences, describe how {missing_label} "
                    "generally compares in this segment (general automotive "
                    "knowledge only, no showroom claims)."
                )
            if general_note:
                analysis += f" General information about {missing_label}: {general_note}"
            answer = (
                f"Comparing {label}. Verified showroom data covers the vehicles we "
                f"actually stock. {analysis}"
            )
            comparison = {
                "vehicles": vehicle_data,
                "analysis": analysis,
                "winner": None,
            }
            return self._response(
                query,
                intent,
                answer=answer,
                results=vehicle_data,
                total_matches=len(vehicles),
                comparison=comparison,
                meta=meta,
            )

        if len(unique) < 2:
            name = self._vehicle_name(unique[0])
            answer = (
                f"I found only {name} in our current showroom inventory. "
                "A comparison needs at least two available vehicles."
            )
            return self._response(
                query,
                intent,
                answer=answer,
                results=unique,
                total_matches=len(unique),
                meta=meta,
            )

        vehicles = unique[: self.MAX_COMPARISON_VEHICLES]
        vehicle_data = [self._vehicle_to_dict(v, 1.0, []) for v in vehicles]
        ranked = self._rank(vehicles, {})
        winner = ranked[0]

        # CASE A: all vehicles verified from inventory.
        analysis = ""
        if meta.get("processing_path") != "fast_path" and self._gemini.is_available:
            try:
                analysis = self._gemini.generate_comparison(vehicle_data)
            except Exception:
                analysis = ""
        if not analysis:
            analysis = self._comparison_template(vehicles, winner.vehicle)

        answer = (
            f"Comparing {label} using verified data from our current showroom inventory. "
            f"{analysis}"
        )

        comparison = {
            "vehicles": vehicle_data,
            "analysis": analysis,
            "winner": {
                "id": winner.vehicle.pk,
                "name": self._vehicle_name(winner.vehicle),
                "reason": (winner.match_reasons[0] if winner.match_reasons else
                           f"Best overall value at ₹{format_inr(winner.vehicle.price)}"),
            },
        }

        return self._response(
            query,
            intent,
            answer=answer,
            results=vehicle_data,
            total_matches=len(vehicles),
            comparison=comparison,
            meta=meta,
        )

    def _comparison_template(self, vehicles, winner) -> str:
        lines = []
        for v in vehicles:
            lines.append(
                f"{self._vehicle_name(v)} is priced at ₹{format_inr(v.price)} with "
                f"{v.fuel_type.lower()} fuel, {v.transmission.lower()} transmission and "
                f"{v.seating_capacity} seats."
            )
        body = " ".join(lines)
        return (
            f"{body} The strongest overall pick is {self._vehicle_name(winner)} — "
            f"it offers the best fit for the requirements in question at "
            f"₹{format_inr(winner.price)}."
        )

    # ------------------------------------------------------------------
    # Answers
    # ------------------------------------------------------------------
    def _generate_answer(
        self,
        query: str,
        intent: dict,
        results: list,
        total_matches: int,
        recommendation=None,
        meta: Optional[dict] = None,
    ) -> str:
        meta = meta or {}
        payload = {
            "results": [
                self._vehicle_to_dict(v, 1.0, []) for v in results[: self.MAX_ANSWER_VEHICLES]
            ],
            "total_matches": total_matches,
            "filters": intent["filters"],
        }
        # Fast-path queries get deterministic Django-generated text: no Gemini
        # answer call, no extra latency. Gemini-backed intents may ask for a
        # richer explanation; if it fails, the same template still works.
        if meta.get("processing_path") != "fast_path" and self._gemini.is_available:
            try:
                answer = self._gemini.generate_answer(query, intent, payload)
                if answer and str(answer).strip():
                    return str(answer).strip()
            except Exception as exc:
                logger.warning("Gemini answer generation failed, using template: %s", exc)
        return self._template_answer(intent, results, total_matches, recommendation)

    def _general_answer(self, query: str) -> str:
        """General automotive knowledge answer: FAQ first, then Gemini.

        Never touches inventory: if neither source can answer, say so
        truthfully instead of inventing facts or database results.
        """
        faq = faq_lookup(query)
        if faq:
            return faq
        if self._gemini.is_available:
            try:
                answer = self._gemini.answer_general(query)
                if answer and str(answer).strip():
                    return str(answer).strip()
            except Exception as exc:
                logger.warning("Gemini general answer failed: %s", exc)
        return GENERAL_UNAVAILABLE_MESSAGE

    def _template_answer(
        self, intent: dict, results: list, total_matches: int, recommendation=None
    ) -> str:
        desc = self._describe_filters(intent["filters"])

        if recommendation is not None:
            reasons = "; ".join(
                r for r in self._rank([recommendation], intent["filters"])[0].match_reasons
            ) or f"priced at ₹{format_inr(recommendation.price)}"
            return (
                f"Based on the available vehicles{desc}, my pick for you is "
                f"{self._vehicle_name(recommendation)} at ₹{format_inr(recommendation.price)}. "
                f"It matches your requirements ({reasons}). Among the {total_matches} "
                f"matching vehicles, it is the strongest overall fit."
            )

        if intent["sort"] == "price_asc" and results:
            first = results[0]
            return (
                f"The cheapest vehicle{desc} is {self._vehicle_name(first)} at "
                f"₹{format_inr(first.price)}. I found {total_matches} matching "
                f"{'vehicle' if total_matches == 1 else 'vehicles'} in our showroom."
            )

        if intent["sort"] == "price_desc" and results:
            first = results[0]
            return (
                f"The most expensive vehicle{desc} is {self._vehicle_name(first)} at "
                f"₹{format_inr(first.price)}. I found {total_matches} matching "
                f"{'vehicle' if total_matches == 1 else 'vehicles'} in our showroom."
            )

        if intent["intent"] == "INFO" and results:
            first = results[0]
            detail = (
                f"{self._vehicle_name(first)} is currently available in our showroom at "
                f"₹{format_inr(first.price)} — {first.fuel_type.lower()} fuel, "
                f"{first.transmission.lower()} transmission, {first.seating_capacity} seats, "
                f"{first.manufacturing_year}."
            )
            if total_matches > 1:
                return (
                    f"I found {total_matches} matching vehicles in our inventory. {detail} "
                    f"See the full list below."
                )
            return detail

        names = [self._vehicle_name(v) for v in results[: self.MAX_ANSWER_VEHICLES]]
        listing = ", ".join(names)
        return (
            f"I found {total_matches} {'vehicle' if total_matches == 1 else 'vehicles'} "
            f"currently available{desc} in our showroom inventory: {listing}."
        )

    def _no_match_response(self, intent: dict, dealership_id) -> tuple[str, Optional[object]]:
        filters = intent["filters"]
        desc = self._describe_filters(filters).strip()
        active_count = sum(1 for v in filters.values() if v is not None)

        if active_count == 0:
            answer = "I couldn't find any available vehicles in our current showroom inventory."
        elif filters.get("price_max") is not None and active_count == 1:
            answer = (
                "I couldn't find any vehicles under "
                f"₹{format_inr(filters['price_max'])} in our current showroom inventory."
            )
        elif filters.get("seating_capacity") is not None and active_count == 1:
            seats = filters["seating_capacity"]
            answer = (
                f"I couldn't find a {seats}-seater vehicle in our current inventory."
            )
        else:
            answer = (
                f"I couldn't find any vehicles matching {desc or 'your requirements'} "
                "in our current showroom inventory."
            )

        closest = None
        if filters.get("price_max") is not None:
            above_filters = {
                k: v for k, v in filters.items() if k not in ("price_min", "price_max")
            }
            above_filters["price_min"] = filters["price_max"] + 1
            above = self._vehicles.search(
                dealership_id=dealership_id,
                filters=above_filters,
                sort="price_asc",
                exclusions=intent.get("exclusions"),
            )
            if above:
                closest = above[0]
                answer += " If you'd like, I can find the closest available option above your budget."

        return answer, closest

    # ------------------------------------------------------------------
    # Ranking for recommendations
    # ------------------------------------------------------------------
    def _rank(
        self, vehicles: list, filters: dict, sort: Optional[str] = None
    ) -> list[RecommendationCandidate]:
        filters = filters or {}
        scored = []
        for vehicle in vehicles:
            score = 0.0
            reasons: list[str] = []

            if filters.get("price_max") is not None and vehicle.price <= filters["price_max"]:
                budget = float(filters["price_max"])
                if budget > 0:
                    score += (1 - float(vehicle.price) / budget) * 0.3
                reasons.append(
                    f"Within budget (₹{format_inr(vehicle.price)} ≤ ₹{format_inr(filters['price_max'])})"
                )
            if filters.get("price_min") is not None and vehicle.price >= filters["price_min"]:
                score += 0.1
                reasons.append(f"Above your minimum price (₹{format_inr(vehicle.price)})")
            if filters.get("seating_capacity") is not None:
                if vehicle.seating_capacity == filters["seating_capacity"]:
                    score += 0.2
                    reasons.append(f"Seats exactly {vehicle.seating_capacity}")
            if filters.get("transmission") and vehicle.transmission == filters["transmission"]:
                score += 0.2
                reasons.append(f"{vehicle.transmission} transmission")
            if filters.get("transmission_group") == "AUTOMATIC":
                if vehicle.transmission in AUTOMATIC_TRANSMISSIONS:
                    score += 0.2
                    reasons.append(f"{vehicle.transmission} automatic transmission")
            if filters.get("transmission_group") == "MANUAL" and vehicle.transmission == "MANUAL":
                score += 0.2
                reasons.append("Manual transmission")
            if filters.get("fuel_type") and vehicle.fuel_type == filters["fuel_type"]:
                score += 0.15
                reasons.append(f"{vehicle.fuel_type} fuel")
            if filters.get("brand") and filters["brand"].lower() in vehicle.brand.lower():
                score += 0.1
                reasons.append(f"{vehicle.brand} brand")
            if filters.get("model") and filters["model"].lower() in vehicle.model.lower():
                score += 0.1
                reasons.append(f"{vehicle.model} model")
            if filters.get("manufacturing_year") is not None:
                if vehicle.manufacturing_year == filters["manufacturing_year"]:
                    score += 0.1
                    reasons.append(f"Manufactured {vehicle.manufacturing_year}")
            if filters.get("year_min") is not None and vehicle.manufacturing_year >= filters["year_min"]:
                score += 0.1
                reasons.append(f"Year {vehicle.manufacturing_year}")
            if filters.get("year_max") is not None and vehicle.manufacturing_year <= filters["year_max"]:
                score += 0.1
                reasons.append(f"Year {vehicle.manufacturing_year}")
            if vehicle.is_in_stock:
                score += 0.05
                reasons.append("In stock")

            scored.append((vehicle, score, reasons))

        if sort == "price_asc":
            # Cheapest-first must survive ranking ("cheapest Honda").
            scored.sort(key=lambda item: (float(item[0].price), -item[1]))
        elif sort == "price_desc":
            scored.sort(key=lambda item: (-float(item[0].price), -item[1]))
        else:
            scored.sort(key=lambda item: (item[1], -float(item[0].price)))
        return [
            RecommendationCandidate(vehicle=v, score=s, match_reasons=r)
            for v, s, r in scored
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _response(
        self,
        query: str,
        intent: dict,
        *,
        answer: str,
        results: list,
        total_matches: int,
        no_match: bool = False,
        recommendation=None,
        comparison=None,
        closest_above=None,
        meta: Optional[dict] = None,
    ) -> dict:
        if results and isinstance(results[0], object) and not isinstance(results[0], dict):
            result_data = [self._vehicle_to_dict(v, 1.0, []) for v in results]
        else:
            result_data = results

        recommendation_data = None
        if recommendation is not None:
            if isinstance(recommendation, dict):
                recommendation_data = recommendation
            else:
                ranked = self._rank(
                    [recommendation], intent.get("filters") or {}, intent.get("sort")
                )
                candidate = ranked[0]
                recommendation_data = self._vehicle_to_dict(
                    candidate.vehicle, candidate.score, candidate.match_reasons
                )

        closest_data = None
        if closest_above is not None:
            closest_data = self._vehicle_to_dict(closest_above, 0.0, [])

        applied_filters = {
            k: v for k, v in intent["filters"].items() if v is not None
        }

        response = {
            "query": query,
            "intent": intent["intent"],
            "answer": answer,
            "filters": applied_filters,
            "results": result_data,
            "recommendation": recommendation_data,
            "comparison": comparison,
            "total_matches": total_matches,
            "no_match": no_match,
            "closest_above": closest_data,
        }
        # Observability: which pipeline answered (never API keys, tokens or PII).
        if meta is not None:
            response["processing_path"] = meta.get("processing_path", "unknown")
            response["intent_source"] = meta.get("intent_source", "unknown")
        response["query_type"] = intent.get("query_type", "UNKNOWN")
        response["context_mode"] = intent.get("context_mode", "NONE")
        if any(bool(v) for v in (intent.get("exclusions") or {}).values()):
            response["exclusions"] = intent["exclusions"]
        return response

    def _describe_filters(self, filters: dict) -> str:
        parts: list[str] = []
        if filters.get("price_min") is not None and filters.get("price_max") is not None:
            parts.append(
                f"priced between ₹{format_inr(filters['price_min'])} and ₹{format_inr(filters['price_max'])}"
            )
        elif filters.get("price_max") is not None:
            parts.append(f"under ₹{format_inr(filters['price_max'])}")
        elif filters.get("price_min") is not None:
            parts.append(f"above ₹{format_inr(filters['price_min'])}")

        if filters.get("brand") and filters.get("model"):
            parts.append(f"{filters['brand']} {filters['model']}")
        elif filters.get("brand"):
            parts.append(f"{filters['brand']}")
        elif filters.get("model"):
            parts.append(f"{filters['model']}")
        if filters.get("variant"):
            parts.append(f"{filters['variant']} variant")

        if filters.get("manufacturing_year") is not None:
            parts.append(f"from {filters['manufacturing_year']}")
        elif filters.get("year_min") is not None and filters.get("year_max") is not None:
            parts.append(f"from {filters['year_min']} to {filters['year_max']}")
        elif filters.get("year_min") is not None:
            parts.append(f"from {filters['year_min']} onwards")
        elif filters.get("year_max") is not None:
            parts.append(f"up to {filters['year_max']}")

        if filters.get("fuel_type"):
            parts.append(filters["fuel_type"].lower())
        if filters.get("transmission"):
            parts.append(filters["transmission"].lower())
        elif filters.get("transmission_group") == "AUTOMATIC":
            parts.append("automatic")
        elif filters.get("transmission_group") == "MANUAL":
            parts.append("manual")
        if filters.get("seating_capacity") is not None:
            parts.append(f"{filters['seating_capacity']}-seater")

        if not parts:
            return ""
        return " " + ", ".join(parts)

    def _vehicle_name(self, vehicle) -> str:
        return " ".join(
            p for p in [vehicle.brand, vehicle.model, vehicle.variant] if p
        ).strip()

    def _vehicle_to_dict(self, vehicle, score: float, reasons: list[str]) -> dict:
        return {
            "id": vehicle.pk,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "variant": vehicle.variant or "",
            "manufacturing_year": vehicle.manufacturing_year,
            "fuel_type": vehicle.fuel_type,
            "transmission": vehicle.transmission,
            "seating_capacity": vehicle.seating_capacity,
            "price": str(vehicle.price),
            "description": vehicle.description or "",
            "stock_quantity": vehicle.stock_quantity,
            "is_available": vehicle.is_available,
            "is_in_stock": vehicle.is_in_stock,
            "dealership": vehicle.dealership_id,
            "dealership_name": vehicle.dealership.name if vehicle.dealership else None,
            "match_score": round(score, 3),
            "match_reasons": reasons,
        }
