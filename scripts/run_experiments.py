#!/usr/bin/env python3
"""
Phase 5 — Experiment Runner

Runs a set of predefined scenarios through the full AgentOps pipeline and
produces detailed result files for offline analysis (for the thesis report).

Scenarios are implemented as *config mutations* on top of the current local
config; each scenario:
  1) Adjusts prompt/model settings by editing JSON config files
  2) Hot-reloads the target app config via /config/reload
  3) Invokes the orchestrator pipeline (manual trigger)
  4) Records timing, scores, comparator verdict, and decision outcome

Outputs:
  - .local-data/experiments/experiments_<timestamp>.jsonl
      One JSON record per scenario run, including:
        * scenario_id, scenario_type, description
        * run_id, version_id
        * quality_score (v_new, v_current, delta)
        * comparator verdict + dimension deltas
        * decision (AUTO_PROMOTE / ROLLBACK / ESCALATE / NO_ACTION)
        * action_taken
        * started_at, completed_at, wall_clock_seconds
        * config_diff (fields changed vs baseline)
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

# Ensure agents package is importable
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agents"))

from agents.orchestrator.agent import run_pipeline  # noqa: E402


DATA_DIR = Path(os.environ.get("STORAGE_DATA_DIR", str(PROJECT_ROOT / ".local-data")))
EXPERIMENTS_DIR = DATA_DIR / "experiments"
EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "configs" / "prompt_template.json"
MODEL_CONFIG_PATH = PROJECT_ROOT / "configs" / "model_config.json"
APP_CONFIG_PATH = Path(
    os.environ.get("APP_CONFIG", str(PROJECT_ROOT / "configs" / "local.json"))
)
VALIDATION_SUITE_PATH = PROJECT_ROOT / "eval-datasets" / "validation_suite_v1.json"


@dataclass
class Scenario:
    id: str
    kind: str
    description: str
    apply: Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _reload_target_app_config(app_config: dict[str, Any]) -> None:
    """
    Call /config/reload on the target app so that prompt/model changes take effect.

    Uses CONFIG_RELOAD_API_KEY if set; skips reload silently if the endpoint
    is unreachable so that experiments can still run against a static config.
    """
    target_app = app_config.get("target_app", {})
    staging_url = target_app.get("staging_url", "http://localhost:9001").rstrip("/")
    reload_url = f"{staging_url}/config/reload"
    api_key = os.environ.get("CONFIG_RELOAD_API_KEY", "")

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                reload_url,
                headers={"X-API-Key": api_key} if api_key else {},
            )
        if resp.status_code != 200:
            print(f"  ⚠️  /config/reload returned HTTP {resp.status_code}: {resp.text[:200]}")
        else:
            data = resp.json()
            print(
                f"  ↪  Config reloaded: prompt_version={data.get('prompt_version')}, "
                f"model_name={data.get('model_name')}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  Could not call /config/reload ({exc}); continuing with current app config.")


def _ensure_validation_suite() -> None:
    if not VALIDATION_SUITE_PATH.exists():
        raise SystemExit(
            f"validation_suite_v1.json not found at {VALIDATION_SUITE_PATH}. "
            "Phase 5 requires this suite."
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_scenarios() -> list[Scenario]:
    """
    Define experiment scenarios as config mutations.

    We keep changes simple and numeric where possible so that:
      - Scenario 1: Baseline (no change) — reference run on validation suite
      - Scenario 2: Lower temperature (more conservative outputs)
      - Scenario 3: Higher temperature (more diverse outputs, potential regression)
      - Scenario 4: Model swap (if supported by provider account)
      - Scenario 5: Bad prompt (weaken system prompt to induce regression)
    """

    def s1_baseline(prompt_cfg: dict[str, Any], model_cfg: dict[str, Any]):
        return prompt_cfg, model_cfg

    def s2_lower_temp(prompt_cfg: dict[str, Any], model_cfg: dict[str, Any]):
        cfg = copy.deepcopy(model_cfg)
        cfg["temperature"] = max(0.0, float(cfg.get("temperature", 0.3)) - 0.2)
        return prompt_cfg, cfg

    def s3_higher_temp(prompt_cfg: dict[str, Any], model_cfg: dict[str, Any]):
        cfg = copy.deepcopy(model_cfg)
        base = float(cfg.get("temperature", 0.3))
        cfg["temperature"] = min(1.0, base + 0.4)
        return prompt_cfg, cfg

    def s4_model_swap(prompt_cfg: dict[str, Any], model_cfg: dict[str, Any]):
        cfg = copy.deepcopy(model_cfg)
        # Swap to a different (potentially slower / higher quality) model name.
        # Adjust this to whatever alternative is available in your Gemini account.
        cfg["model_name"] = cfg.get("alt_model_name", "gemini-2.0-flash")
        return prompt_cfg, cfg

    def s5_bad_prompt(prompt_cfg: dict[str, Any], model_cfg: dict[str, Any]):
        pcfg = copy.deepcopy(prompt_cfg)
        pcfg["system_prompt"] = "You translate very roughly. Do not worry about accuracy."
        pcfg["version"] = f"{pcfg.get('version', 'unknown')}-bad"
        return pcfg, model_cfg

    return [
        Scenario(
            id="scenario_1_baseline",
            kind="baseline",
            description="Baseline config on validation_suite_v1.json",
            apply=s1_baseline,
        ),
        Scenario(
            id="scenario_2_lower_temp",
            kind="temperature",
            description="Lower temperature than baseline (more deterministic outputs).",
            apply=s2_lower_temp,
        ),
        Scenario(
            id="scenario_3_higher_temp",
            kind="temperature",
            description="Higher temperature than baseline (more diverse outputs, risk of regression).",
            apply=s3_higher_temp,
        ),
        Scenario(
            id="scenario_4_model_swap",
            kind="model",
            description="Swap model_name to an alternative (if available).",
            apply=s4_model_swap,
        ),
        Scenario(
            id="scenario_5_bad_prompt",
            kind="prompt",
            description="Intentionally weak system prompt to induce quality regression.",
            apply=s5_bad_prompt,
        ),
    ]


def run_scenario(scenario: Scenario, dry_run: bool = False) -> dict[str, Any]:
    """
    Apply scenario-specific config changes, reload target app, run pipeline,
    and return a detailed result record.
    """
    print("\n" + "=" * 80)
    print(f"{scenario.id} — {scenario.description}")
    print("=" * 80)

    # Load current configs
    prompt_cfg = _read_json(PROMPT_TEMPLATE_PATH)
    model_cfg = _read_json(MODEL_CONFIG_PATH)
    app_cfg = _read_json(APP_CONFIG_PATH)

    original_prompt = copy.deepcopy(prompt_cfg)
    original_model = copy.deepcopy(model_cfg)

    # Apply scenario mutation
    new_prompt_cfg, new_model_cfg = scenario.apply(prompt_cfg, model_cfg)

    # Compute simple config diff for logging
    config_diff: dict[str, Any] = {
        "prompt_changed": new_prompt_cfg != original_prompt,
        "model_changed": new_model_cfg != original_model,
        "original_temperature": original_model.get("temperature"),
        "new_temperature": new_model_cfg.get("temperature"),
        "original_model_name": original_model.get("model_name"),
        "new_model_name": new_model_cfg.get("model_name"),
        "prompt_version_before": original_prompt.get("version"),
        "prompt_version_after": new_prompt_cfg.get("version"),
    }

    if dry_run:
        print("  [dry-run] Would apply config changes and run pipeline.")
        return {
            "scenario_id": scenario.id,
            "kind": scenario.kind,
            "description": scenario.description,
            "dry_run": True,
            "config_diff": config_diff,
        }

    # Write mutated configs; always restore in finally so failure/interrupt doesn't leave configs mutated
    _write_json(PROMPT_TEMPLATE_PATH, new_prompt_cfg)
    _write_json(MODEL_CONFIG_PATH, new_model_cfg)
    print("  ↪  Updated prompt_template.json and model_config.json")

    try:
        _reload_target_app_config(app_cfg)

        run_id = f"{scenario.id}-{_timestamp()}"
        print(f"  ↪  Running pipeline: run_id={run_id}")
        t0 = time.perf_counter()
        result = run_pipeline(
            trigger_type="manual",
            webhook_payload={},
            run_id=run_id,
            test_suite_path=str(VALIDATION_SUITE_PATH),
        )
        elapsed = time.perf_counter() - t0

        quality_score = float(result.get("quality_score", 0.0))
        comparison_report = result.get("comparison_report", {})
        decision = result.get("decision", {})

        record = {
            "scenario_id": scenario.id,
            "kind": scenario.kind,
            "description": scenario.description,
            "run_id": run_id,
            "wall_clock_seconds": round(elapsed, 3),
            "pipeline_status": result.get("status", "unknown"),
            "version_id": result.get("version_id", ""),
            "quality_score": quality_score,
            "comparison": {
                "verdict": comparison_report.get("verdict"),
                "v_new_score": comparison_report.get("v_new_score"),
                "v_current_score": comparison_report.get("v_current_score"),
                "delta": comparison_report.get("delta"),
                "dimension_deltas": comparison_report.get("dimension_deltas"),
            },
            "decision": {
                "decision": decision.get("decision"),
                "reasoning": decision.get("reasoning"),
                "confidence": decision.get("confidence"),
                "action_taken": decision.get("action_taken"),
            },
            "started_at": result.get("started_at"),
            "completed_at": result.get("completed_at"),
            "errors": result.get("errors", []),
            "config_diff": config_diff,
        }

        print(
            f"  ✓ Completed: status={record['pipeline_status']}, "
            f"score={record['quality_score']:.3f}, "
            f"delta={record['comparison']['delta']}, "
            f"decision={record['decision']['decision']}"
        )
        return record
    finally:
        _write_json(PROMPT_TEMPLATE_PATH, original_prompt)
        _write_json(MODEL_CONFIG_PATH, original_model)
        print("  ↪  Restored original configs\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 5 experiments.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not mutate configs or call pipeline; just print planned scenarios.",
    )
    parser.add_argument(
        "--only",
        metavar="SCENARIO_ID",
        help="Run a single scenario by id (e.g. scenario_3_higher_temp).",
    )
    args = parser.parse_args()

    _ensure_validation_suite()

    scenarios = _build_scenarios()
    if args.only:
        scenarios = [s for s in scenarios if s.id == args.only]
        if not scenarios:
            raise SystemExit(f"Unknown scenario id: {args.only}")

    outfile = EXPERIMENTS_DIR / f"experiments_{_timestamp()}.jsonl"
    print(f"Writing experiment results to: {outfile}")

    records: list[dict[str, Any]] = []
    for scenario in scenarios:
        rec = run_scenario(scenario, dry_run=args.dry_run)
        records.append(rec)
        if not args.dry_run:
            with outfile.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\nSummary:")
    for rec in records:
        print(
            f"  - {rec['scenario_id']}: "
            f"status={rec.get('pipeline_status', 'n/a')}, "
            f"score={rec.get('quality_score', 0.0):.3f} "
            f"decision={rec.get('decision', {}).get('decision')}"
        )
    print(f"\nDone. Detailed records: {outfile if not args.dry_run else '(dry-run, no file written)'}")


if __name__ == "__main__":
    main()

