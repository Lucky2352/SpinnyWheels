import os
import json
import logging
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger("autoflow.ai")


class GeminiProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
        self._client: Optional[genai.Client] = None

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("Gemini API key not configured")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def extract_requirements(self, query: str) -> dict:
        if not self.is_available:
            raise RuntimeError("Gemini API key not configured")

        system_prompt = (
            "You are a vehicle requirement extraction assistant for an automotive dealership. "
            "Extract structured requirements from the customer's natural language query. "
            "Return ONLY a JSON object with the following fields (all optional, use null if not specified):\n"
            "{\n"
            "  \"budget_max\": number,  // maximum budget in INR (e.g., 1500000 for 15 lakh)\n"
            "  \"seating_capacity\": number,  // required seats (e.g., 5)\n"
            "  \"transmission\": string,  // one of: MANUAL, AUTOMATIC, AMT, CVT, DCT\n"
            "  \"fuel_type\": string,  // one of: PETROL, DIESEL, CNG, ELECTRIC, HYBRID\n"
            "  \"body_type\": string,  // free text, e.g., SUV, sedan, hatchback\n"
            "  \"usage\": string,  // free text, e.g., city, highway, mixed\n"
            "  \"priorities\": [string],  // array of priorities, e.g., [\"mileage\", \"safety\"]\n"
            "  \"brand_preference\": [string]  // preferred brands, optional\n"
            "}\n"
            "Rules:\n"
            "- If a requirement is not mentioned, use null.\n"
            "- Budget: convert 'lakh' to actual INR (1 lakh = 100000).\n"
            "- Transmission: normalize to exact enum values.\n"
            "- Fuel type: normalize to exact enum values.\n"
            "- Priorities: extract from context (mileage, safety, performance, comfort, space, features, value).\n"
            "- Do not invent requirements not in the query.\n"
            "- Return only valid JSON, no extra text."
        )

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                    types.Content(role="user", parts=[types.Part(text=query)]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
            data = json.loads(text)
            return self._sanitize_requirements(data)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini returned invalid JSON: %s", exc)
            raise ValueError("Failed to parse Gemini response as JSON") from exc
        except Exception as exc:
            logger.exception("Gemini requirement extraction failed")
            raise RuntimeError(f"Gemini extraction failed: {exc}") from exc

    def extract_intent(self, query: str, context: Optional[dict] = None) -> dict:
        """Extract a structured vehicle intent from natural language.

        Returns the raw parsed JSON only; Django validates the structure via
        apps.core.services.intent_parser.validate_intent before any ORM use.
        Raises on transport/JSON failures so callers can fall back.
        """
        if not self.is_available:
            raise RuntimeError("Gemini API key not configured")

        system_prompt = (
            "You are the intent extraction component of YourSpinny, an expert Automobile AI Assistant for spinnyWheels car showroom.\n"
            "Read the customer's natural-language automotive question (English or informal Hinglish) and extract structured intent.\n"
            "Return ONLY a JSON object with this exact shape:\n"
            "{\n"
            "  \"intent\": \"SEARCH\" | \"RECOMMENDATION\" | \"COMPARISON\" | \"INFO\" | \"UNKNOWN\",\n"
            "  \"query_type\": \"INVENTORY_SEARCH\" | \"INVENTORY_RECOMMENDATION\" | \"INVENTORY_COMPARISON\" | \"INVENTORY_AVAILABILITY\" | \"VEHICLE_INFO\" | \"GENERAL_INFO\" | \"GENERAL_COMPARISON\" | \"TROUBLESHOOTING\" | \"CLARIFICATION\" | \"OUT_OF_SCOPE\",\n"
            "  \"scope\": \"automotive\" | \"non_automotive\",\n"
            "  \"normalized_question\": string,\n"
            "  \"context_mode\": \"NONE\" | \"NEW_SEARCH\" | \"FOLLOW_UP\",\n"
            "  \"confidence\": number,\n"
            "  \"entities\": {\"brands\": [string], \"models\": [string], \"variants\": [string]},\n"
            "  \"filters\": {\n"
            "    \"price_min\": number|null,\n"
            "    \"price_max\": number|null,\n"
            "    \"brand\": string|null,\n"
            "    \"model\": string|null,\n"
            "    \"variant\": string|null,\n"
            "    \"manufacturing_year\": number|null,\n"
            "    \"year_min\": number|null,\n"
            "    \"year_max\": number|null,\n"
            "    \"fuel_type\": string|null,\n"
            "    \"transmission\": string|null,\n"
            "    \"transmission_group\": string|null,\n"
            "    \"seating_capacity\": number|null\n"
            "  },\n"
            "  \"exclusions\": {\"brands\": [string], \"models\": [string], \"fuel_types\": [string], \"transmissions\": [string]},\n"
            "  \"sort\": \"price_asc\" | \"price_desc\" | null,\n"
            "  \"limit\": number|null,\n"
            "  \"vehicle_names\": [string],\n"
            "  \"preferences\": [string],\n"
            "  \"requested_information\": [string],\n"
            "  \"requires_inventory\": boolean,\n"
            "  \"comparison_requested\": boolean,\n"
            "  \"requires_recommendation\": boolean\n"
            "}\n"
            "Semantics:\n"
            "- \"under 2 lakh\" / \"below 5 lakh\" / \"up to 10 lakh\" / \"max 200000\" / \"budget is 2 lakh\" -> price_max.\n"
            "  Convert lakh units: 1 lakh = 100000, 1 crore = 10000000, 1 million = 1000000. Strip commas from numbers.\n"
            "- \"above 10 lakh\" / \"more than 8 lakh\" / \"over 10 lakh\" -> price_min.\n"
            "- \"between 5 and 10 lakh\" / \"5 lakh to 10 lakh\" -> price_min AND price_max.\n"
            "- \"around 20 lakh\" / \"approximately 20 lakh\" is a PREFERENCE, not a hard filter: do NOT\n"
            "  invent a price range. Put \"around 20 lakh\" in preferences and leave price_min/price_max null,\n"
            "  unless the customer also states a hard limit, or answer with query_type CLARIFICATION if the\n"
            "  budget is the only thing asked about.\n"
            "- \"5 seater\" / \"seats for five\" / \"car for 5 people\" -> seating_capacity (exact number).\n"
            "  NEVER infer seating capacity from phrases like \"family car\".\n"
            "- fuel_type: PETROL | DIESEL | CNG | ELECTRIC | HYBRID.\n"
            "- transmission: MANUAL | AUTOMATIC | AMT | CVT | DCT when a specific type is named.\n"
            "  For the generic word 'automatic' use transmission_group=\"AUTOMATIC\"; for generic\n"
            "  'manual' use transmission_group=\"MANUAL\".\n"
            "- manufacturing_year for an exact year (\"2025 cars\"); year_min/year_max for ranges\n"
            "  (\"newer than 2023\" -> year_min 2024, \"before 2022\" -> year_max 2021, \"from 2024\" -> year_min 2024).\n"
            "- \"cheapest\" -> sort \"price_asc\"; \"most expensive\" -> sort \"price_desc\".\n"
            "- exclusions: for \"but not diesel\" / \"excluding Honda\" / \"don't show manual cars\", list the\n"
            "  excluded values under exclusions and do NOT also list them as positive filters.\n"
            "- intent / query_type:\n"
            "  * SEARCH / INVENTORY_SEARCH: customer wants matching vehicles listed.\n"
            "  * RECOMMENDATION / INVENTORY_RECOMMENDATION: \"which one should I buy\", \"best pick\",\n"
            "    \"best <brand>\", \"cheapest <brand>\" (also requires_recommendation=true).\n"
            "  * COMPARISON / INVENTORY_COMPARISON: comparing two or more named vehicles (fill\n"
            "    vehicle_names with the full names as spoken, comparison_requested=true).\n"
            "  * COMPARISON / GENERAL_COMPARISON: comparing vehicles or concepts NOT expected in our\n"
            "    inventory (e.g. \"BMW X5 vs Mercedes GLE\", \"petrol vs diesel as fuel types\").\n"
            "  * INFO / INVENTORY_AVAILABILITY: \"do you have X\", \"is X available\", \"X in stock\" ->\n"
            "    vehicle_names + requested_information [\"availability\"].\n"
            "  * INFO / VEHICLE_INFO: \"tell me about X\", \"details of X\" -> vehicle_names +\n"
            "    requested_information [\"details\", \"specifications\"].\n"
            "  * INFO / GENERAL_INFO: general automotive knowledge questions (\"what is ABS\", \"how does a\n"
            "    CVT work\", \"should I buy an EV\", \"is diesel still worth it\") -> requires_inventory=false,\n"
            "    requested_information [\"general_knowledge\"], filters all null. NEVER turn these into inventory searches.\n"
            "    Automotive scope includes vehicles, buying guidance, inventory, test drives,\n"
            "    servicing, repairs, maintenance, appointments, ownership and dealership services.\n"
            "  * INFO / TROUBLESHOOTING: automotive problems, symptoms, noises, vibrations, sluggishness\n"
            "    (\"why is my car slow\", \"why does my car vibrate\", \"overheating on highway\", \"mileage dropped\") ->\n"
            "    requires_inventory=false, requested_information [\"troubleshooting\"], filters all null.\n"
            "  * UNKNOWN / CLARIFICATION: brief ambiguous queries (\"slow car\", \"good car?\", \"comfortable\")\n"
            "    where intent cannot be determined safely without guessing -> requires_inventory=false, ask clarification.\n"
            "  * UNKNOWN / OUT_OF_SCOPE: greetings, thanks, or anything clearly unrelated to\n"
            "    automobiles, vehicles, dealerships, buying, inventory, test drives, servicing,\n"
            "    repairs, maintenance, appointments or ownership (e.g. capital of France,\n"
            "    cricket results, Python programs, jokes, celebrities, maths, weather).\n"
            "    OUT_OF_SCOPE needs scope=\"non_automotive\", requires_inventory=false, empty filters and empty vehicle_names.\n"
            "- constraints vs preferences: only state-stated facts become filters (constraints);\n"
            "  comfort, style, \"good mileage\", \"family friendly\" etc. go into preferences — they are NOT\n"
            "  database fields and must never become filters.\n"
            "- context_mode: FOLLOW_UP when the utterance refines the previous message (\"make it under\n"
            "  10 lakh\", \"only automatic\"); NEW_SEARCH when it fully re-describes a request (\"show me\n"
            "  electric cars\"); NONE when there is no prior message.\n"
            "- normalized_question: one clear English sentence restating the request (for display only).\n"
            "- confidence: 0.0-1.0 how certain you are of this interpretation.\n"
            "- requires_inventory: true only when the answer must come from our showroom database;\n"
            "  false for general knowledge / greetings / clarification.\n"
            "- vehicle_names: only full vehicle names actually mentioned (e.g. [\"Honda City\", \"Hyundai Verna\"]).\n"
            "- NEVER invent inventory: no fake vehicles, prices, stock levels, vehicle IDs, SQL,\n"
            "  database fields (mileage, horsepower, colour, owner count...) or schema. If asked about\n"
            "  data we do not have, keep requires_inventory=false and put it in requested_information.\n"
            "- Never invent filters that are not stated. Use null/false/[] for anything unspecified.\n"
            "- Return only valid JSON, no markdown, no commentary."
        )

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                    types.Content(role="user", parts=[types.Part(text=query)]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini returned invalid intent JSON: %s", exc)
            raise ValueError("Failed to parse Gemini intent response as JSON") from exc
        except Exception as exc:
            logger.warning("Gemini intent extraction failed: %s", exc)
            raise RuntimeError(f"Gemini intent extraction failed: {exc}") from exc

    def generate_answer(
        self,
        query: str,
        intent: dict,
        payload: dict,
    ) -> str:
        """Write a descriptive answer from the verified Django/Neon result only."""
        if not self.is_available:
            raise RuntimeError("Gemini API key not configured")

        if payload.get("no_match_message"):
            return str(payload["no_match_message"])

        def fmt(vehicle: dict) -> str:
            name = " ".join(
                p for p in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("variant")] if p
            )
            lines = [
                f"- {name} ({vehicle.get('manufacturing_year')})",
                f"  Price: ₹{vehicle.get('price')}",
                f"  Fuel: {vehicle.get('fuel_type')}, Transmission: {vehicle.get('transmission')}, "
                f"Seats: {vehicle.get('seating_capacity')}",
                f"  Stock: {vehicle.get('stock_quantity')}",
            ]
            return "\n".join(lines)

        results = payload.get("results") or []
        vehicle_block = "\n".join(fmt(v) for v in results) if results else "(none)"

        system_prompt = (
            "You are YourSpinny, a helpful AI vehicle assistant for a car dealership showroom.\n"
            "Write a concise, natural-language answer to the customer's question.\n"
            "STRICT RULES:\n"
            "- Use ONLY the verified query result below. Never invent vehicles, prices, stock,\n"
            "  brands, models, variants, seating, fuel, transmission or years.\n"
            "- The structured filters were already applied to the database: every listed vehicle\n"
            "  genuinely satisfies them. Say how many vehicles matched and summarise them.\n"
            "- If a specification the customer asked about (e.g. mileage) is not present in the\n"
            "  data, say that this information is not available in the current showroom inventory.\n"
            f"- Intent: {intent.get('intent')}. "
            + (
                "Pick exactly ONE best vehicle and explain why it fits their requirements.\n"
                if intent.get("intent") == "RECOMMENDATION"
                else "List the matching vehicles without singling one out.\n"
            )
            + "- Plain text only, no markdown tables, no JSON. Maximum 8 sentences."
        )

        user_content = (
            f"Customer question: {query}\n"
            f"Applied filters: {json.dumps(intent.get('filters') or {}, default=str)}\n"
            f"Total matches in inventory: {payload.get('total_matches', len(results))}\n"
            f"Verified vehicles from Neon:\n{vehicle_block}"
        )

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=[
                types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                types.Content(role="user", parts=[types.Part(text=user_content)]),
            ],
            config=types.GenerateContentConfig(temperature=0.3),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty answer")
        return text

    def answer_general(self, query: str, context: str = "", query_type: str = "GENERAL_INFO") -> str:
        """Answer a general automotive knowledge question.

        Used only for GENERAL_INFO / TROUBLESHOOTING / GENERAL_COMPARISON / not-in-inventory
        vehicle questions. This is content generation, never intent parsing:
        it must not claim showroom availability or invent database records.
        """
        if not self.is_available:
            raise RuntimeError("Gemini API key not configured")

        troubleshooting_instruction = (
            "If the customer is asking about an automotive problem, symptom, or troubleshooting (e.g. car slow, vibrating/shaking, noise, overheating, mileage drop):\n"
            "- Understand the symptom.\n"
            "- Explain common possible causes clearly and objectively.\n"
            "- Explain what the owner can safely check.\n"
            "- Explain when professional inspection is needed.\n"
            "- Avoid declaring a definitive diagnosis without an in-person physical inspection.\n"
            "- SAFETY FIRST: For dangerous issues (brake problems, severe overheating, smoke, fuel leaks, loss of steering, highway emergencies), prioritize safety and urgently recommend safely stopping and seeking professional roadside assistance.\n\n"
        )
        system_prompt = (
            "You are YourSpinny, an expert Automobile AI Assistant for spinnyWheels.\n"
            "Answer the customer's question thoroughly and accurately using GENERAL automotive knowledge.\n"
            + (troubleshooting_instruction if query_type == "TROUBLESHOOTING" else "")
            + "STRICT RULES:\n"
            "- Never claim a vehicle is in stock, available, or reserved — you have no\n"
            "  access to the showroom database in this mode.\n"
            "- Never invent showroom database fields.\n"
            "- If exact figures vary by variant, say so instead of guessing.\n"
            "- Plain text only, friendly, clear, and professional. Maximum 8 sentences."
        )
        user_content = f"Question: {query}"
        if context:
            user_content += f"\nContext: {context}"

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=[
                types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                types.Content(role="user", parts=[types.Part(text=user_content)]),
            ],
            config=types.GenerateContentConfig(temperature=0.2),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty general answer")
        return text

    def _sanitize_requirements(self, data: dict) -> dict:
        valid_transmissions = {"MANUAL", "AUTOMATIC", "AMT", "CVT", "DCT"}
        valid_fuels = {"PETROL", "DIESEL", "CNG", "ELECTRIC", "HYBRID"}

        result = {
            "budget_max": None,
            "seating_capacity": None,
            "transmission": None,
            "fuel_type": None,
            "body_type": None,
            "usage": None,
            "priorities": [],
            "brand_preference": [],
        }

        if data.get("budget_max") is not None:
            try:
                result["budget_max"] = int(data["budget_max"])
            except (ValueError, TypeError):
                pass

        if data.get("seating_capacity") is not None:
            try:
                val = int(data["seating_capacity"])
                if 1 <= val <= 10:
                    result["seating_capacity"] = val
            except (ValueError, TypeError):
                pass

        trans = data.get("transmission")
        if trans and isinstance(trans, str):
            trans_upper = trans.upper()
            if trans_upper in valid_transmissions:
                result["transmission"] = trans_upper

        fuel = data.get("fuel_type")
        if fuel and isinstance(fuel, str):
            fuel_upper = fuel.upper()
            if fuel_upper in valid_fuels:
                result["fuel_type"] = fuel_upper

        if data.get("body_type") and isinstance(data["body_type"], str):
            result["body_type"] = data["body_type"][:50]

        if data.get("usage") and isinstance(data["usage"], str):
            result["usage"] = data["usage"][:50]

        priorities = data.get("priorities")
        if isinstance(priorities, list):
            result["priorities"] = [str(p)[:30] for p in priorities if p][:5]

        brands = data.get("brand_preference")
        if isinstance(brands, list):
            result["brand_preference"] = [str(b)[:50] for b in brands if b][:5]

        return result

    def generate_explanation(
        self,
        query: str,
        candidates: list[dict],
    ) -> str:
        if not self.is_available:
            return "AI explanation temporarily unavailable."

        if not candidates:
            return "No matching vehicles found."

        candidate_summaries = []
        for i, v in enumerate(candidates, 1):
            parts = [
                f"{i}. {v.get('brand', '')} {v.get('model', '')} {v.get('variant', '')}".strip(),
                f"Price: ₹{v.get('price', 0):,.0f}",
                f"Fuel: {v.get('fuel_type', 'N/A')}",
                f"Transmission: {v.get('transmission', 'N/A')}",
                f"Seats: {v.get('seating_capacity', 'N/A')}",
            ]
            if v.get("variant"):
                parts.append(f"Variant: {v['variant']}")
            candidate_summaries.append(" | ".join(parts))

        system_prompt = (
            "You are an automotive sales assistant explaining vehicle recommendations to a customer. "
            "Given the customer's original query and a list of candidate vehicles from the dealership's actual inventory, "
            "write a concise, helpful explanation for each vehicle.\n"
            "For each vehicle:\n"
            "- Explain why it matches the customer's needs\n"
            "- Highlight key strengths\n"
            "- Note any trade-offs or limitations\n"
            "- Keep it practical and honest\n"
            "- If a specification is not available, say 'Not available' — do not guess\n"
            "- Do not invent specifications not in the provided data\n"
            "- Use a friendly, professional tone\n"
            "Format as a numbered list matching the candidate order."
        )

        user_content = (
            f"Customer query: {query}\n\n"
            f"Candidate vehicles:\n"
            + "\n".join(candidate_summaries)
        )

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                    types.Content(role="user", parts=[types.Part(text=user_content)]),
                ],
                config=types.GenerateContentConfig(temperature=0.3),
            )
            return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini explanation generation failed: %s", exc)
            return "AI explanation temporarily unavailable."

    def generate_comparison(
        self,
        vehicles: list[dict],
    ) -> str:
        if not self.is_available:
            return "AI comparison temporarily unavailable."

        if len(vehicles) < 2:
            return "Need at least 2 vehicles to compare."

        vehicle_summaries = []
        for i, v in enumerate(vehicles, 1):
            parts = [
                f"{i}. {v.get('brand', '')} {v.get('model', '')} {v.get('variant', '')}".strip(),
                f"Price: ₹{v.get('price', 0):,.0f}",
                f"Fuel: {v.get('fuel_type', 'N/A')}",
                f"Transmission: {v.get('transmission', 'N/A')}",
                f"Seats: {v.get('seating_capacity', 'N/A')}",
            ]
            if v.get("variant"):
                parts.append(f"Variant: {v['variant']}")
            vehicle_summaries.append(" | ".join(parts))

        system_prompt = (
            "You are an automotive expert comparing vehicles for a customer. "
            "Given the actual specifications of 2-3 vehicles from a dealership's inventory, "
            "provide a clear, practical comparison.\n"
            "Cover:\n"
            "- Key differences in specifications\n"
            "- Strengths and weaknesses of each\n"
            "- Best for city driving\n"
            "- Best for family use\n"
            "- Best for performance/enthusiasts\n"
            "- Best value for money (if data supports)\n"
            "- Main trade-offs\n"
            "- Final practical recommendation\n"
            "Use only the provided data. If a spec is missing, say 'Not available'. "
            "Do not invent specifications. Be concise and practical."
        )

        user_content = "Vehicles to compare:\n" + "\n".join(vehicle_summaries)

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                    types.Content(role="user", parts=[types.Part(text=user_content)]),
                ],
                config=types.GenerateContentConfig(temperature=0.3),
            )
            return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini comparison generation failed: %s", exc)
            return "AI comparison temporarily unavailable."

    def generate_info_response(
        self,
        query: str,
        vehicles: list[dict],
    ) -> str:
        if not self.is_available:
            return "AI assistant temporarily unavailable."

        if not vehicles:
            return "No matching vehicles found in current inventory."

        system_prompt = (
            "You are a helpful automotive assistant answering customer questions about a dealership's current inventory. "
            "Answer the customer's question using ONLY the vehicle data provided. "
            "If the question asks about vehicles not in the provided data, say so. "
            "Do not use general knowledge about vehicles not in the current inventory. "
            "If a specification is missing, say 'Not available'. Do not guess. "
            "Be concise and practical."
        )

        vehicle_summaries = []
        for v in vehicles:
            parts = [
                f"- {v.get('brand', '')} {v.get('model', '')} {v.get('variant', '')}".strip(),
                f"  Price: ₹{v.get('price', 0):,.0f}",
                f"  Fuel: {v.get('fuel_type', 'N/A')}, Transmission: {v.get('transmission', 'N/A')}, Seats: {v.get('seating_capacity', 'N/A')}",
            ]
            if v.get("variant"):
                parts.append(f"  Variant: {v['variant']}")
            vehicle_summaries.append("\n".join(parts))

        user_content = (
            f"Customer question: {query}\n\n"
            f"Current inventory:\n" + "\n".join(vehicle_summaries)
        )

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=system_prompt)]),
                    types.Content(role="user", parts=[types.Part(text=user_content)]),
                ],
                config=types.GenerateContentConfig(temperature=0.2),
            )
            return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini info response failed: %s", exc)
            return "AI assistant temporarily unavailable."