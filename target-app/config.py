"""
Configuration loader for Translation Agent.

Loads prompt template, model config, and app settings from JSON files.
Supports hot-reloading config without restarting the server.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults / fallbacks
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PROMPT_TEMPLATE_PATH = _PROJECT_ROOT / "configs" / "prompt_template.json"
DEFAULT_MODEL_CONFIG_PATH = _PROJECT_ROOT / "configs" / "model_config.json"
DEFAULT_APP_CONFIG_PATH = _PROJECT_ROOT / "configs" / "local.json"


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

class AppConfig:
    """Holds all runtime configuration loaded from JSON files."""

    def __init__(self) -> None:
        self._prompt_template: dict[str, Any] = {}
        self._model_config: dict[str, Any] = {}
        self._app_config: dict[str, Any] = {}
        self.reload()

    # -- public properties ---------------------------------------------------

    @property
    def system_prompt(self) -> str:
        return self._prompt_template.get("system_prompt", "You are a translator.")

    @property
    def user_prompt_template(self) -> str:
        return self._prompt_template.get(
            "user_prompt_template",
            "Translate from {source_lang} to {target_lang}:\n\n{text}",
        )

    @property
    def few_shot_examples(self) -> list[dict[str, str]]:
        return self._prompt_template.get("few_shot_examples", [])

    @property
    def prompt_version(self) -> str:
        return self._prompt_template.get("version", "unknown")

    @property
    def model_name(self) -> str:
        return self._model_config.get("model_name", "gemini-2.5-flash")

    @property
    def temperature(self) -> float:
        return self._model_config.get("temperature", 0.3)

    @property
    def max_tokens(self) -> int:
        return self._model_config.get("max_tokens", 2048)

    @property
    def top_p(self) -> float:
        return self._model_config.get("top_p", 0.95)

    @property
    def top_k(self) -> int:
        return self._model_config.get("top_k", 40)

    @property
    def environment(self) -> str:
        return self._app_config.get("environment", "local")

    @property
    def log_level(self) -> str:
        return self._app_config.get("logging", {}).get("level", "INFO")

    @property
    def target_app_production_url(self) -> str:
        return self._app_config.get("target_app", {}).get(
            "production_url", "http://localhost:9000"
        )

    @property
    def target_app_staging_url(self) -> str:
        return self._app_config.get("target_app", {}).get(
            "staging_url", "http://localhost:9001"
        )

    # -- loader methods ------------------------------------------------------

    def reload(self) -> None:
        """Reload all config files from disk. Safe to call at runtime."""
        self._prompt_template = self._load_json(
            os.environ.get("PROMPT_TEMPLATE_PATH", str(DEFAULT_PROMPT_TEMPLATE_PATH))
        )
        self._model_config = self._load_json(
            os.environ.get("MODEL_CONFIG_PATH", str(DEFAULT_MODEL_CONFIG_PATH))
        )
        self._app_config = self._load_json(
            os.environ.get("APP_CONFIG", str(DEFAULT_APP_CONFIG_PATH))
        )
        logger.info(
            "Config loaded",
            extra={
                "prompt_version": self.prompt_version,
                "model_name": self.model_name,
                "environment": self.environment,
            },
        )

    @staticmethod
    def _load_json(path: str) -> dict[str, Any]:
        """Load a JSON file, return empty dict on failure."""
        file_path = Path(path)
        if not file_path.exists():
            logger.warning("Config file not found: %s — using defaults", path)
            return {}
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load config %s: %s", path, exc)
            return {}
