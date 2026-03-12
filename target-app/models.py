"""
Pydantic models for Translation Agent API — request/response schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SupportedLanguage(str, Enum):
    """Supported languages for translation."""
    ENGLISH = "en"
    VIETNAMESE = "vi"
    JAPANESE = "ja"
    CHINESE = "zh"
    KOREAN = "ko"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    """Single text translation request."""
    text: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="The text to translate.",
        examples=["Trí tuệ nhân tạo đang thay đổi cách chúng ta làm việc."],
    )
    source_lang: SupportedLanguage = Field(
        ...,
        description="ISO 639-1 source language code.",
        examples=["vi"],
    )
    target_lang: SupportedLanguage = Field(
        ...,
        description="ISO 639-1 target language code.",
        examples=["en"],
    )


class BatchTranslateRequest(BaseModel):
    """Batch translation request — multiple texts, same language pair."""
    items: list[TranslateRequest] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of translation requests (max 50).",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TranslateResponse(BaseModel):
    """Single translation result."""
    translated_text: str = Field(
        ..., description="The translated text."
    )
    source_lang: str = Field(
        ..., description="Source language used."
    )
    target_lang: str = Field(
        ..., description="Target language used."
    )
    model_name: str = Field(
        ..., description="Model used for translation."
    )
    latency_ms: float = Field(
        ..., description="Time taken for translation in milliseconds."
    )
    token_count: Optional[int] = Field(
        None, description="Total token count (prompt + completion) if available."
    )
    estimated_cost_usd: Optional[float] = Field(
        None, description="Estimated cost in USD for this request."
    )


class BatchTranslateResponse(BaseModel):
    """Batch translation result."""
    results: list[TranslateResponse] = Field(
        ..., description="List of translation results."
    )
    total_items: int = Field(
        ..., description="Total number of items processed."
    )
    total_latency_ms: float = Field(
        ..., description="Total time for entire batch in milliseconds."
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(
        ..., description="Service status.", examples=["healthy"]
    )
    version: str = Field(
        ..., description="Current config version label."
    )
    model_name: str = Field(
        ..., description="Current model name."
    )
    uptime_seconds: float = Field(
        ..., description="Uptime in seconds since service start."
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Current server time (UTC).",
    )


class ConfigInfoResponse(BaseModel):
    """Current configuration information (non-sensitive)."""
    version: str
    model_name: str
    temperature: float
    max_tokens: int
    prompt_template_version: str
    environment: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type.")
    detail: str = Field(..., description="Detailed error message.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
