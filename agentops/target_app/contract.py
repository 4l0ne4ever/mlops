from __future__ import annotations

from typing import NotRequired, TypedDict


class HealthResponse(TypedDict):
    status: str  # usually "healthy"
    version: str
    model_name: str
    uptime_seconds: float


class TranslateRequest(TypedDict):
    text: str
    # Language codes as strings (e.g. "en", "vi"). The reference app also
    # supports enum-backed values, but over HTTP it is JSON strings.
    source_lang: str
    target_lang: str


class TranslateResponse(TypedDict):
    translated_text: str
    source_lang: str
    target_lang: str
    model_name: str
    latency_ms: float
    token_count: int | None
    estimated_cost_usd: float | None


class BatchItem(TypedDict):
    text: str
    source_lang: str
    target_lang: str


class BatchTranslateRequest(TypedDict):
    items: list[BatchItem]


class BatchTranslateResponse(TypedDict):
    results: list[TranslateResponse]
    total_items: int
    total_latency_ms: float


class ConfigReloadResponse(TypedDict):
    status: str  # "reloaded"
    prompt_version: str
    model_name: str


__all__ = [
    "HealthResponse",
    "TranslateRequest",
    "TranslateResponse",
    "BatchTranslateRequest",
    "BatchTranslateResponse",
    "ConfigReloadResponse",
]

