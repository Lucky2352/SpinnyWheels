import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("autoflow.ai")

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class GroqProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL
        self.base_url = base_url or os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1/chat/completions"
        self.timeout = int(os.getenv("GROQ_TIMEOUT", "30"))

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _make_request(self, messages: list, temperature: float = 0.1, response_format: Optional[dict] = None) -> str:
        if not self.is_available:
            raise RuntimeError("Groq API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.base_url, headers=headers, json=payload)
                if response.status_code == 429:
                    raise RuntimeError("Rate limit exceeded (429)")
                if response.status_code >= 500:
                    raise RuntimeError(f"Groq server error: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return str(content).strip()
        except httpx.TimeoutException as exc:
            logger.warning("Groq request timeout: %s", exc)
            raise RuntimeError("Groq request timeout") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Groq HTTP error: %s", exc)
            raise RuntimeError(f"Groq API error: {exc.response.status_code}") from exc
        except Exception as exc:
            logger.warning("Groq request failed: %s", exc)
            raise RuntimeError(f"Groq request failed: {exc}") from exc

    def extract_requirements(self, query: str) -> dict:
        system_prompt = (
            "You are a vehicle requirement extraction assistant for an automotive dealership. "
            "Extract structured requirements from the customer's natural language query. "
            "Return ONLY a JSON object with the following fields (all optional, use null if not specified):\n"
            "{\n"
            '  "budget_max": number,\n'
            '  "seating_capacity": number,\n'
            '  "transmission": string,\n'
            '  "fuel_type": string,\n'
            '  "body_type": string,\n'
            '  "usage": string,\n'
            '  "priorities": [string],\n'
            '  "brand_preference": [string]\n'
            "}\n"
            "Rules:\n"
            "- If a requirement is not mentioned, use null.\n"
            "- Budget: convert 'lakh' to actual INR (1 lakh = 100000).\n"
            "- Transmission: normalize to MANUAL, AUTOMATIC, AMT, CVT, DCT.\n"
            "- Fuel type: normalize to PETROL, DIESEL, CNG, ELECTRIC, HYBRID.\n"
            "- Priorities: extract from context (mileage, safety, performance, comfort, space, features, value).\n"
            "- Do not invent requirements not in the query.\n"
            "- Return only valid JSON, no extra text."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]
        try:
            text = self._make_request(messages, temperature=0.1, response_format={"type": "json_object"})
            data = json.loads(text)
            return self._sanitize_requirements(data)
        except json.JSONDecodeError as exc:
            logger.warning("Groq returned invalid JSON: %s", exc)
            raise ValueError("Failed to parse Groq response as JSON") from exc
        except Exception as exc:
            logger.exception("Groq requirement extraction failed")
            raise

    def extract_intent(self, query: str, context: Optional[dict] = None) -> dict:
        system_prompt = (
            "You are the intent extraction component of YourSpinny, an expert Automobile AI Assistant for spinnyWheels car showroom.\n"
            "Analyze the customer's natural-language query and extract structured intent.\n"
            "Return ONLY a JSON object with this shape:\n"
            "{\n"
            '  "intent": "SEARCH" | "RECOMMENDATION" | "COMPARISON" | "INFO" | "UNKNOWN",\n'
            '  "query_type": "INVENTORY_SEARCH" | "INVENTORY_RECOMMENDATION" | "INVENTORY_COMPARISON" | "INVENTORY_AVAILABILITY" | "VEHICLE_INFO" | "GENERAL_INFO" | "GENERAL_COMPARISON" | "TROUBLESHOOTING" | "CLARIFICATION" | "OUT_OF_SCOPE",\n'
            '  "scope": "automotive" | "non_automotive",\n'
            '  "normalized_question": string,\n'
            '  "context_mode": "NONE" | "NEW_SEARCH" | "FOLLOW_UP",\n'
            '  "confidence": number,\n'
            '  "entities": {"brands": [string], "models": [string], "variants": [string]},\n'
            '  "filters": {\n'
            '    "price_min": number|null,\n'
            '    "price_max": number|null,\n'
            '    "brand": string|null,\n'
            '    "model": string|null,\n'
            '    "variant": string|null,\n'
            '    "manufacturing_year": number|null,\n'
            '    "year_min": number|null,\n'
            '    "year_max": number|null,\n'
            '    "fuel_type": string|null,\n'
            '    "transmission": string|null,\n'
            '    "transmission_group": string|null,\n'
            '    "seating_capacity": number|null\n'
            '  },\n'
            '  "exclusions": {"brands": [string], "models": [string], "fuel_types": [string], "transmissions": [string]},\n'
            '  "sort": "price_asc" | "price_desc" | null,\n'
            '  "limit": number|null,\n'
            '  "vehicle_names": [string],\n'
            '  "preferences": [string],\n'
            '  "requested_information": [string],\n'
            '  "requires_inventory": boolean,\n'
            '  "comparison_requested": boolean,\n'
            '  "requires_recommendation": boolean\n'
            "}\n"
            "CRITICAL RULES FOR TWO KNOWLEDGE SOURCES:\n"
            "1. SOURCE A: GENERAL AUTOMOTIVE KNOWLEDGE (requires_inventory=false, filters all null):\n"
            "   - Automotive concepts & technology: 'What is a CVT?', 'What is torque?', 'How does turbo work?', 'How does ABS work?' -> query_type='GENERAL_INFO', intent='INFO'.\n"
            "   - General driving/fuel/tech advice: 'Should I buy an EV?', 'Petrol vs diesel for city?', 'Automatic vs manual?' -> query_type='GENERAL_INFO', intent='INFO'.\n"
            "   - General recommendations (not asking for showroom inventory): 'Suggest me a family car', 'What car should I buy for city commute?' -> query_type='GENERAL_INFO', intent='INFO'.\n"
            "   - General comparisons: 'Swift vs Punch', 'CVT vs DCT', 'SUV vs sedan' -> query_type='GENERAL_COMPARISON', intent='COMPARISON'.\n"
            "   - Vehicle impressions: 'Is Fortuner good for long trips?', 'What do you think of Honda City?' -> query_type='GENERAL_INFO', intent='INFO'.\n"
            "   - Troubleshooting & problems: 'Why does my car feel slow?', 'Car shaking when braking', 'Overheating on highway', 'Brakes squeaking', 'Mileage dropped' -> query_type='TROUBLESHOOTING', intent='INFO'.\n"
            "   - Ambiguous phrases: 'slow car', 'good car?', 'comfortable', 'worth it?' -> query_type='CLARIFICATION' (or GENERAL_INFO), intent='UNKNOWN'. NEVER treat ambiguous phrases as inventory searches!\n"
            "2. SOURCE B: SHOWROOM INVENTORY (requires_inventory=true):\n"
            "   - ONLY when user explicitly asks about available cars, showroom stock, prices, or dealership inventory: 'What automatic cars do you have under 15 lakh?', 'Show me Honda cars in your showroom', 'Do you have any 7 seaters?', 'Show me something cheap from your showroom', 'Suggest a family car from your showroom'.\n"
            "   - Convert lakh: 1 lakh = 100000, 1 crore = 10000000.\n"
            "   - Normalize transmission: MANUAL, AUTOMATIC, AMT, CVT, DCT. Fuel: PETROL, DIESEL, CNG, ELECTRIC, HYBRID.\n"
            "3. OUT OF DOMAIN (requires_inventory=false, scope='non_automotive', intent='UNKNOWN', query_type='OUT_OF_SCOPE'):\n"
            "   - Questions clearly unrelated to automobiles: cooking, sports scores, jokes, weather, general history, programming.\n"
            "   - Automotive questions are NEVER out of domain ('Should I buy an EV?' is automotive, scope='automotive').\n"
            "4. CONTEXT / FOLLOW-UPS:\n"
            "   - If previous context is provided, resolve pronouns like 'that one', 'anything cheaper', 'what about automatic' relative to previously discussed vehicles or filters.\n"
            "Return only valid JSON, no markdown, no commentary."
        )
        user_content = f"Question: {query}"
        if context:
            user_content = f"Previous Conversation Context: {json.dumps(context, default=str)}\nQuestion: {query}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            text = self._make_request(messages, temperature=0.1, response_format={"type": "json_object"})
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Groq returned invalid intent JSON: %s", exc)
            raise ValueError("Failed to parse Groq intent response as JSON") from exc
        except Exception as exc:
            logger.warning("Groq intent extraction failed: %s", exc)
            raise RuntimeError(f"Groq intent extraction failed: {exc}") from exc

    def generate_answer(self, query: str, intent: dict, payload: dict) -> str:
        if payload.get("no_match_message"):
            return str(payload["no_match_message"])

        def fmt(vehicle: dict) -> str:
            name = " ".join(p for p in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("variant")] if p)
            lines = [
                f"- {name} ({vehicle.get('manufacturing_year')})",
                f"  Price: ₹{vehicle.get('price')}",
                f"  Fuel: {vehicle.get('fuel_type')}, Transmission: {vehicle.get('transmission')}, Seats: {vehicle.get('seating_capacity')}",
                f"  Stock: {vehicle.get('stock_quantity')}",
            ]
            return "\n".join(lines)

        results = payload.get("results") or []
        vehicle_block = "\n".join(fmt(v) for v in results) if results else "(none)"

        system_prompt = (
            "You are YourSpinny, a helpful AI vehicle assistant for a car dealership showroom.\n"
            "Write a concise, natural-language answer to the customer's question.\n"
            "STRICT RULES:\n"
            "- Use ONLY the verified query result below. Never invent vehicles, prices, stock, brands, models, variants, seating, fuel, transmission or years.\n"
            "- The structured filters were already applied to the database: every listed vehicle genuinely satisfies them. Say how many vehicles matched and summarise them.\n"
            "- If a specification the customer asked about is not present in the data, say that this information is not available in the current showroom inventory.\n"
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        text = self._make_request(messages, temperature=0.3)
        if not text:
            raise RuntimeError("Groq returned an empty answer")
        return text

    def answer_general(self, query: str, context: str = "", query_type: str = "GENERAL_INFO") -> str:
        troubleshooting_instruction = (
            "If the customer is asking about an automotive problem, symptom, or troubleshooting (e.g. car slow, vibrating/shaking, noise, overheating, mileage drop, warning light, hard steering):\n"
            "- Understand the symptom.\n"
            "- Explain common possible causes clearly and objectively.\n"
            "- Explain what the owner can safely check.\n"
            "- Explain when professional inspection is needed.\n"
            "- Avoid declaring a definitive diagnosis without an in-person physical inspection.\n"
            "- SAFETY FIRST: For potentially dangerous situations (such as brake problems, severe overheating, smoke, fuel leaks, loss of steering, highway emergencies), prioritize safety and urgently recommend safely stopping and seeking professional roadside assistance.\n\n"
        )
        system_prompt = (
            "You are YourSpinny, an expert Automobile AI Assistant for spinnyWheels showroom.\n"
            "Answer the customer's question thoroughly and accurately using GENERAL automotive knowledge.\n"
            + (troubleshooting_instruction if query_type == "TROUBLESHOOTING" else "")
            + "STRICT RULES:\n"
            "- Never claim a vehicle is in stock, available, or reserved — you have no access to the showroom database in this mode.\n"
            "- Never invent showroom database fields.\n"
            "- If exact figures vary by variant or model year, clarify that instead of guessing.\n"
            "- Provide a clear, natural, and helpful automotive answer. Plain text only."
        )
        user_content = f"Question: {query}"
        if context:
            user_content += f"\nContext: {context}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        text = self._make_request(messages, temperature=0.2)
        if not text:
            raise RuntimeError("Groq returned an empty general answer")
        return text

    def generate_explanation(self, query: str, candidates: list[dict]) -> str:
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
        user_content = f"Customer query: {query}\n\nCandidate vehicles:\n" + "\n".join(candidate_summaries)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            text = self._make_request(messages, temperature=0.3)
            return text
        except Exception as exc:
            logger.warning("Groq explanation generation failed: %s", exc)
            return "AI explanation temporarily unavailable."

    def generate_comparison(self, vehicles: list[dict]) -> str:
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            text = self._make_request(messages, temperature=0.3)
            return text
        except Exception as exc:
            logger.warning("Groq comparison generation failed: %s", exc)
            return "AI comparison temporarily unavailable."

    def generate_info_response(self, query: str, vehicles: list[dict]) -> str:
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
            vehicle_summaries.append("\n".join(parts))
        user_content = f"Customer question: {query}\n\nCurrent inventory:\n" + "\n".join(vehicle_summaries)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            text = self._make_request(messages, temperature=0.2)
            return text
        except Exception as exc:
            logger.warning("Groq info response failed: %s", exc)
            return "AI assistant temporarily unavailable."

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
