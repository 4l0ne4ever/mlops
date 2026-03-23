from __future__ import annotations

import importlib
import os
from pathlib import Path

import agentops.settings as settings


def test_paths_are_absolute():
    assert settings.CONFIGS_DIR.is_absolute()
    assert settings.EVAL_DATA_DIR.is_absolute()
    assert Path(settings.DEFAULT_APP_CONFIG_PATH).is_absolute()
    assert settings.STORAGE_DATA_DIR.is_absolute()


def test_env_override_for_app_config(monkeypatch):
    # APP_CONFIG is used at import time, so reload settings.
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    importlib.reload(settings)

    assert str(settings.DEFAULT_APP_CONFIG_PATH).endswith("configs/local.json")

    # Restore module-derived defaults for subsequent tests.
    monkeypatch.delenv("APP_CONFIG", raising=False)
    importlib.reload(settings)

