from __future__ import annotations

from typing import Any

from .contract import (
    HealthResponse,
    TranslateRequest,
    TranslateResponse,
    BatchTranslateRequest,
    BatchTranslateResponse,
    ConfigReloadResponse,
)


def create_app() -> Any:
    """
    Return the bundled reference target app (FastAPI instance).
    """
    from target_app.app import app

    return app


def get_translation_service(*args: Any, **kwargs: Any) -> Any:
    from target_app.translator import TranslationService

    return TranslationService(*args, **kwargs)


__all__ = [
    "create_app",
    "get_translation_service",
    "HealthResponse",
    "TranslateRequest",
    "TranslateResponse",
    "BatchTranslateRequest",
    "BatchTranslateResponse",
    "ConfigReloadResponse",
]

