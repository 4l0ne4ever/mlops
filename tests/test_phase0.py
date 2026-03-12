#!/usr/bin/env python3
"""
Phase 0 — Verification Tests.

Run from project root:
    source .venv/bin/activate
    python tests/test_phase0.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "target-app"))

PASSED = 0
FAILED = 0


def test(name: str, passed: bool, detail: str = ""):
    global PASSED, FAILED
    if passed:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}: {detail}")


# =========================================================================
print("=" * 60)
print("Phase 0 — Verification Tests")
print("=" * 60)

# --- Test 1: Config files exist ---
print("\n[1/7] Config files")
config_files = [
    "configs/prompt_template.json",
    "configs/model_config.json",
    "configs/thresholds.json",
    "configs/local.json",
    "configs/production.json",
]
for f in config_files:
    path = PROJECT_ROOT / f
    test(f, path.exists(), "File not found")

# --- Test 2: Config loading ---
print("\n[2/7] Config module")
try:
    from config import AppConfig
    config = AppConfig()
    test("Config loads", True)
    # Load expected values directly from config files — no hardcoding
    _mc_path = PROJECT_ROOT / "configs" / "model_config.json"
    _pt_path = PROJECT_ROOT / "configs" / "prompt_template.json"
    _mc = json.loads(_mc_path.read_text(encoding="utf-8"))
    _pt = json.loads(_pt_path.read_text(encoding="utf-8"))
    test(f"Model = {config.model_name}", config.model_name == _mc["model_name"],
         f"Got: {config.model_name}")
    test(f"Prompt version = {config.prompt_version}", config.prompt_version == _pt["version"],
         f"Got: {config.prompt_version}")
    test(f"Temperature = {config.temperature}", config.temperature == _mc["temperature"],
         f"Got: {config.temperature}")
    test(f"Few-shot examples = {len(config.few_shot_examples)}",
         len(config.few_shot_examples) == len(_pt.get("few_shot_examples", [])),
         f"Got: {len(config.few_shot_examples)}")
    test(f"Environment = {config.environment}", config.environment == "local",
         f"Got: {config.environment}")
except Exception as e:
    test("Config loads", False, str(e))

# --- Test 3: Pydantic models ---
print("\n[3/7] Pydantic models")
try:
    from models import (
        TranslateRequest, TranslateResponse, BatchTranslateRequest,
        HealthResponse, ConfigInfoResponse, ErrorResponse,
        SupportedLanguage,
    )
    test("Models import", True)

    # Valid request
    req = TranslateRequest(text="Hello", source_lang="en", target_lang="vi")
    test("Valid TranslateRequest", req.text == "Hello")

    # Empty text should fail
    try:
        TranslateRequest(text="", source_lang="en", target_lang="vi")
        test("Rejects empty text", False, "Should have raised")
    except Exception:
        test("Rejects empty text", True)

    # Oversized text should fail
    try:
        TranslateRequest(text="x" * 10001, source_lang="en", target_lang="vi")
        test("Rejects >10000 chars", False, "Should have raised")
    except Exception:
        test("Rejects >10000 chars", True)

    # Supported languages
    test("Languages enum", len(SupportedLanguage) >= 8,
         f"Got {len(SupportedLanguage)}")

except Exception as e:
    test("Models import", False, str(e))

# --- Test 4: Translator module ---
print("\n[4/7] Translator module")
try:
    from translator import TranslationService, TranslationError, TranslationResult
    test("Translator import", True)

    # TranslationError is an Exception
    test("TranslationError is Exception",
         issubclass(TranslationError, Exception))

    # TranslationResult has correct slots
    expected_slots = {"translated_text", "latency_ms", "token_count",
                      "estimated_cost_usd", "model_name"}
    test("TranslationResult slots",
         set(TranslationResult.__slots__) == expected_slots,
         f"Got: {TranslationResult.__slots__}")

except Exception as e:
    test("Translator import", False, str(e))

# --- Test 5: FastAPI app ---
print("\n[5/7] FastAPI app")
try:
    from app import app
    test("App import", True)

    routes = {r.path for r in app.routes if hasattr(r, "methods")}
    expected = {"/health", "/config", "/config/reload",
                "/translate", "/translate/batch"}
    for route in sorted(expected):
        test(f"Route {route}", route in routes, "Missing")

    test("App title", app.title == "AgentOps Translation Agent",
         f"Got: {app.title}")

except Exception as e:
    test("App import", False, str(e))

# --- Test 6: Eval dataset ---
print("\n[6/7] Eval dataset")
dataset_path = PROJECT_ROOT / "eval-datasets" / "baseline_v1.json"
test("baseline_v1.json exists", dataset_path.exists())
if dataset_path.exists():
    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)
    test(f"Test cases count = {len(data)}", len(data) == 10, f"Got: {len(data)}")

    # Check structure
    required_fields = {"id", "category", "source_lang", "target_lang",
                       "input", "expected_output"}
    for tc in data:
        if not required_fields.issubset(tc.keys()):
            test("Test case structure", False,
                 f"Missing fields in {tc.get('id', '?')}")
            break
    else:
        test("Test case structure", True)

    # Check categories
    categories = {tc["category"] for tc in data}
    test("Categories coverage",
         categories == {"simple_sentence", "complex_paragraph", "technical"},
         f"Got: {categories}")

# --- Test 7: Thresholds config ---
print("\n[7/7] Thresholds config")
thresholds_path = PROJECT_ROOT / "configs" / "thresholds.json"
if thresholds_path.exists():
    with open(thresholds_path, encoding="utf-8") as f:
        thresholds = json.load(f)

    weights = thresholds.get("per_dimension_weights", {})
    total_weight = sum(weights.values())
    test(f"Weights sum = {total_weight}", abs(total_weight - 1.0) < 0.001,
         f"Got: {total_weight}")
    test("No tool_call_accuracy", "tool_call_accuracy" not in weights,
         "Should have been removed")
    test(f"task_completion = {weights.get('task_completion')}",
         weights.get("task_completion") == 0.35)
    test(f"output_quality = {weights.get('output_quality')}",
         weights.get("output_quality") == 0.35)
    test(f"latency = {weights.get('latency')}",
         weights.get("latency") == 0.20)
    test(f"cost_efficiency = {weights.get('cost_efficiency')}",
         weights.get("cost_efficiency") == 0.10)
    test(f"judge_temperature = {thresholds.get('judge_temperature')}",
         thresholds.get("judge_temperature") == 0.0)
    test(f"judge_passes = {thresholds.get('judge_passes')}",
         thresholds.get("judge_passes") == 2)

# =========================================================================
print("\n" + "=" * 60)
print(f"Results: {PASSED} passed, {FAILED} failed, {PASSED + FAILED} total")
if FAILED == 0:
    print("🎉 ALL TESTS PASSED")
else:
    print(f"⚠️  {FAILED} test(s) failed — fix before proceeding")
print("=" * 60)
sys.exit(0 if FAILED == 0 else 1)
