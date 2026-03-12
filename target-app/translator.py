"""
Translation service — integrates with Google Gemini Flash API.

Uses the new `google.genai` SDK (replaces deprecated `google.generativeai`).
Handles prompt construction, API calls, error handling, and cost estimation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from google import genai
from google.genai import types

from config import AppConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost estimation (approximate, Gemini Flash pricing as of 2025)
# ---------------------------------------------------------------------------

# Gemini 2.0 Flash: $0.10 / 1M input tokens, $0.40 / 1M output tokens
_INPUT_COST_PER_TOKEN = 0.10 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.40 / 1_000_000


class TranslationService:
    """Handles text translation using Google Gemini API."""

    def __init__(self, config: AppConfig, api_key: str) -> None:
        self._config = config
        self._api_key = api_key
        self._client: genai.Client | None = None
        self._configure_client()

    def _configure_client(self) -> None:
        """Configure the Gemini API client."""
        self._client = genai.Client(api_key=self._api_key)
        logger.info(
            "Gemini client configured",
            extra={"model": self._config.model_name},
        )

    def reconfigure(self) -> None:
        """Re-read config and reconfigure. Called after config reload."""
        self._configure_client()

    # -- public API ----------------------------------------------------------

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> TranslationResult:
        """
        Translate text from source_lang to target_lang.

        Returns a TranslationResult with the translated text, latency, and
        cost estimation.

        Raises:
            TranslationError: If the Gemini API call fails after retries.
        """
        if self._client is None:
            raise TranslationError(
                "Gemini client not configured — check GEMINI_API_KEY in .env"
            )

        prompt = self._build_prompt(text, source_lang, target_lang)

        config = types.GenerateContentConfig(
            system_instruction=self._config.system_prompt,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_tokens,
            top_p=self._config.top_p,
            top_k=self._config.top_k,
        )

        start_time = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._config.model_name,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Gemini API call failed",
                extra={
                    "error": str(exc),
                    "model": self._config.model_name,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            raise TranslationError(f"Gemini API error: {exc}") from exc

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Extract text from response
        translated_text = self._extract_text(response)

        # Token usage and cost estimation
        token_count: Optional[int] = None
        estimated_cost: Optional[float] = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            token_count = input_tokens + output_tokens
            estimated_cost = (
                input_tokens * _INPUT_COST_PER_TOKEN
                + output_tokens * _OUTPUT_COST_PER_TOKEN
            )

        logger.info(
            "Translation completed",
            extra={
                "source_lang": source_lang,
                "target_lang": target_lang,
                "input_length": len(text),
                "output_length": len(translated_text),
                "latency_ms": round(elapsed_ms, 2),
                "token_count": token_count,
                "estimated_cost_usd": round(estimated_cost, 6) if estimated_cost else None,
                "model": self._config.model_name,
            },
        )

        return TranslationResult(
            translated_text=translated_text,
            latency_ms=round(elapsed_ms, 2),
            token_count=token_count,
            estimated_cost_usd=round(estimated_cost, 6) if estimated_cost else None,
            model_name=self._config.model_name,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_prompt(
        self, text: str, source_lang: str, target_lang: str
    ) -> str:
        """Build the full prompt from template + few-shot examples."""
        parts: list[str] = []

        # Few-shot examples
        for example in self._config.few_shot_examples:
            parts.append(f"Example input: {example['input']}")
            parts.append(f"Example output: {example['output']}")
            parts.append("")

        # User prompt from template
        user_prompt = self._config.user_prompt_template.format(
            source_lang=source_lang,
            target_lang=target_lang,
            text=text,
        )
        parts.append(user_prompt)

        return "\n".join(parts)

    @staticmethod
    def _extract_text(response) -> str:
        """Safely extract text from Gemini response."""
        try:
            # New google.genai SDK — .text property
            if hasattr(response, "text") and response.text:
                return response.text.strip()
            # Fallback: access candidates directly
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    return candidate.content.parts[0].text.strip()
            raise TranslationError("Empty response from Gemini API")
        except (AttributeError, IndexError, ValueError) as exc:
            raise TranslationError(
                f"Failed to extract text from Gemini response: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Result and error types
# ---------------------------------------------------------------------------

class TranslationResult:
    """Immutable result of a translation operation."""

    __slots__ = (
        "translated_text",
        "latency_ms",
        "token_count",
        "estimated_cost_usd",
        "model_name",
    )

    def __init__(
        self,
        translated_text: str,
        latency_ms: float,
        token_count: Optional[int],
        estimated_cost_usd: Optional[float],
        model_name: str,
    ) -> None:
        self.translated_text = translated_text
        self.latency_ms = latency_ms
        self.token_count = token_count
        self.estimated_cost_usd = estimated_cost_usd
        self.model_name = model_name


class TranslationError(Exception):
    """Raised when translation fails."""
