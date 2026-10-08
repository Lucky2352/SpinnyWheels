import os
from typing import Optional

from apps.core.services.gemini_provider import GeminiProvider
from apps.core.services.groq_provider import GroqProvider


class AIProvider:
    def __init__(self, provider: Optional[str] = None, **kwargs):
        provider_name = (provider or os.getenv("AI_PROVIDER") or "groq").lower()
        self.provider_name = provider_name
        if provider_name == "groq":
            self._provider = GroqProvider(**kwargs)
        else:
            self._provider = GeminiProvider(**kwargs)

    @property
    def is_available(self) -> bool:
        return self._provider.is_available

    def extract_requirements(self, query: str) -> dict:
        return self._provider.extract_requirements(query)

    def extract_intent(self, query: str) -> dict:
        return self._provider.extract_intent(query)

    def generate_answer(self, query: str, intent: dict, payload: dict) -> str:
        return self._provider.generate_answer(query, intent, payload)

    def answer_general(self, query: str, context: str = "") -> str:
        return self._provider.answer_general(query, context)

    def generate_explanation(self, query: str, candidates: list[dict]) -> str:
        return self._provider.generate_explanation(query, candidates)

    def generate_comparison(self, vehicles: list[dict]) -> str:
        return self._provider.generate_comparison(vehicles)

    def generate_info_response(self, query: str, vehicles: list[dict]) -> str:
        return self._provider.generate_info_response(query, vehicles)
