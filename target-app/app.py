"""
AgentOps Target App — Translation Agent API.

FastAPI application providing translation services via Google Gemini Flash.
Designed to be evaluated by the AgentOps eval pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

# ---------------------------------------------------------------------------
# Load .env file — must be before any os.environ.get() calls at module level
# ---------------------------------------------------------------------------

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # fallback: search cwd + parents


from config import AppConfig
from models import (
    BatchTranslateRequest,
    BatchTranslateResponse,
    ConfigInfoResponse,
    ErrorResponse,
    HealthResponse,
    TranslateRequest,
    TranslateResponse,
)
from translator import TranslationError, TranslationService

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        import json as _json

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields
        if hasattr(record, "__dict__"):
            for key in ("source_lang", "target_lang", "latency_ms", "model",
                        "error", "input_length", "output_length", "token_count",
                        "estimated_cost_usd", "prompt_version", "model_name",
                        "environment", "status_code", "method", "path"):
                if key in record.__dict__:
                    log_entry[key] = record.__dict__[key]
        return _json.dumps(log_entry, ensure_ascii=False)


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

_start_time: float = 0.0
_config: AppConfig | None = None
_translator: TranslationService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    global _start_time, _config, _translator

    _setup_logging()
    logger = logging.getLogger("agentops.target-app")

    # Load config
    _config = AppConfig()
    logging.root.setLevel(_config.log_level)

    # Validate API key from env (.env is already loaded at module level)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error(
            "GEMINI_API_KEY not set — add it to .env file. "
            "Translation requests will return 502."
        )

    # Initialize translator
    _translator = TranslationService(_config, api_key)
    _start_time = time.monotonic()

    logger.info(
        "Target app started",
        extra={
            "model_name": _config.model_name,
            "prompt_version": _config.prompt_version,
            "environment": _config.environment,
        },
    )
    yield

    logger.info("Target app shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# Disable API docs in production (security)
_docs_url = "/docs" if os.environ.get("APP_CONFIG", "").endswith("local.json") else None
_redoc_url = "/redoc" if _docs_url else None

app = FastAPI(
    title="AgentOps Translation Agent",
    description=(
        "Translation API powered by Google Gemini Flash. "
        "Part of the AgentOps platform — designed to be evaluated "
        "by the automated eval pipeline."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# CORS — restrict origins from env var (default: localhost:3000 only)
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# API key header for protected endpoints
_reload_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

logger = logging.getLogger("agentops.target-app")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(TranslationError)
async def translation_error_handler(
    request: Request, exc: TranslationError
) -> JSONResponse:
    logger.error("Translation error", extra={"error": str(exc)})
    return JSONResponse(
        status_code=502,
        content=ErrorResponse(
            error="translation_error",
            detail=str(exc),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error("Unhandled error", extra={"error": str(exc)})
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail="An unexpected error occurred. Check server logs.",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": round(elapsed_ms, 2),
        },
    )
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    """Returns service health status, current config version, and uptime."""
    if _config is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return HealthResponse(
        status="healthy",
        version=_config.prompt_version,
        model_name=_config.model_name,
        uptime_seconds=round(time.monotonic() - _start_time, 2),
    )


@app.get(
    "/config",
    response_model=ConfigInfoResponse,
    tags=["system"],
    summary="Current configuration (non-sensitive)",
)
async def get_config() -> ConfigInfoResponse:
    """Returns current non-sensitive configuration for debugging."""
    if _config is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return ConfigInfoResponse(
        version=_config.prompt_version,
        model_name=_config.model_name,
        temperature=_config.temperature,
        max_tokens=_config.max_tokens,
        prompt_template_version=_config.prompt_version,
        environment=_config.environment,
    )


@app.post(
    "/config/reload",
    tags=["system"],
    summary="Hot-reload configuration (requires X-API-Key header)",
)
async def reload_config(
    api_key: str | None = Security(_reload_api_key_header),
) -> dict:
    """Reload config from JSON files without restarting. Requires auth."""
    # Verify API key
    expected_key = os.environ.get("CONFIG_RELOAD_API_KEY", "")
    if expected_key and api_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")

    if _config is None or _translator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    _config.reload()
    _translator.reconfigure()
    logging.root.setLevel(_config.log_level)
    return {
        "status": "reloaded",
        "prompt_version": _config.prompt_version,
        "model_name": _config.model_name,
    }


@app.post(
    "/translate",
    response_model=TranslateResponse,
    responses={502: {"model": ErrorResponse}},
    tags=["translation"],
    summary="Translate a single text",
)
async def translate(request: TranslateRequest) -> TranslateResponse:
    """
    Translate a single text from source language to target language.

    Uses Google Gemini Flash API with the current prompt template and model
    configuration. Returns the translated text along with latency and cost
    metrics for the eval pipeline.
    """
    if _translator is None or _config is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    if request.source_lang == request.target_lang:
        raise HTTPException(
            status_code=400,
            detail="source_lang and target_lang must be different.",
        )

    result = await asyncio.to_thread(
        _translator.translate,
        text=request.text,
        source_lang=request.source_lang.value,
        target_lang=request.target_lang.value,
    )

    return TranslateResponse(
        translated_text=result.translated_text,
        source_lang=request.source_lang.value,
        target_lang=request.target_lang.value,
        model_name=result.model_name,
        latency_ms=result.latency_ms,
        token_count=result.token_count,
        estimated_cost_usd=result.estimated_cost_usd,
    )


@app.post(
    "/translate/batch",
    response_model=BatchTranslateResponse,
    responses={502: {"model": ErrorResponse}},
    tags=["translation"],
    summary="Translate a batch of texts",
)
async def translate_batch(request: BatchTranslateRequest) -> BatchTranslateResponse:
    """
    Translate multiple texts. Each item can have its own language pair.
    Maximum 50 items per batch.

    Uses asyncio.to_thread for concurrent execution.
    Handles partial failures — failed items get error info, successful items
    are still returned.
    """
    if _translator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate language pairs first (fast, no API calls)
    for item in request.items:
        if item.source_lang == item.target_lang:
            raise HTTPException(
                status_code=400,
                detail=f"source_lang and target_lang must be different (item: '{item.text[:50]}...').",
            )

    batch_start = time.perf_counter()

    async def _translate_one(item: TranslateRequest) -> TranslateResponse:
        """Translate a single item via thread pool to avoid blocking event loop."""
        result = await asyncio.to_thread(
            _translator.translate,
            text=item.text,
            source_lang=item.source_lang.value,
            target_lang=item.target_lang.value,
        )
        return TranslateResponse(
            translated_text=result.translated_text,
            source_lang=item.source_lang.value,
            target_lang=item.target_lang.value,
            model_name=result.model_name,
            latency_ms=result.latency_ms,
            token_count=result.token_count,
            estimated_cost_usd=result.estimated_cost_usd,
        )

    # Run all translations concurrently via thread pool
    tasks = [_translate_one(item) for item in request.items]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[TranslateResponse] = []
    errors: list[str] = []
    for i, outcome in enumerate(settled):
        if isinstance(outcome, Exception):
            errors.append(f"Item {i}: {outcome}")
            logger.warning("Batch item %d failed: %s", i, outcome)
        else:
            results.append(outcome)

    if not results and errors:
        # All items failed — raise so the error handler returns 502
        raise TranslationError(
            f"All {len(errors)} batch items failed. First error: {errors[0]}"
        )

    batch_elapsed = (time.perf_counter() - batch_start) * 1000

    return BatchTranslateResponse(
        results=results,
        total_items=len(results),
        total_latency_ms=round(batch_elapsed, 2),
    )
