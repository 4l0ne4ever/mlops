#!/usr/bin/env python3
"""
Seed baseline v_current into LOCAL storage (.local-data/).

This is the local-dev counterpart to `seed-baseline.py` (which uses AWS).
Uses LocalStorageBackend directly — no boto3/AWS credentials needed.

Solves the "first-run problem": when the pipeline runs for the first time,
there is no v_current to compare against. This script creates the initial
version record + baseline eval results so the Comparator has a baseline.

Usage:
    python scripts/seed-baseline-local.py

    # Force re-seed (wipe existing data):
    python scripts/seed-baseline-local.py --force
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project root & env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

from mcp_servers.storage.storage_backend import LocalStorageBackend

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get(
    "STORAGE_DATA_DIR", str(PROJECT_ROOT / ".local-data")
)
BASELINE_DATASET_PATH = PROJECT_ROOT / "eval-datasets" / "baseline_v1.json"
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "configs" / "prompt_template.json"
MODEL_CONFIG_PATH = PROJECT_ROOT / "configs" / "model_config.json"
THRESHOLDS_PATH = PROJECT_ROOT / "configs" / "thresholds.json"

SEED_MARKER = Path(DATA_DIR) / ".seeded"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Seed baseline v_current into local storage."""

    force = "--force" in sys.argv

    print("=" * 60)
    print("AgentOps — Seed Baseline v_current (Local)")
    print("=" * 60)

    # Check if already seeded
    if SEED_MARKER.exists() and not force:
        print("\n⚠️  Already seeded. Use --force to re-seed.")
        existing = json.loads(SEED_MARKER.read_text(encoding="utf-8"))
        print(f"   v_current = {existing.get('version_id', 'unknown')}")
        print(f"   Seeded at = {existing.get('seeded_at', 'unknown')}")
        sys.exit(0)

    # Validate required files
    for path in (BASELINE_DATASET_PATH, PROMPT_TEMPLATE_PATH, MODEL_CONFIG_PATH):
        if not path.exists():
            print(f"ERROR: File not found: {path}")
            sys.exit(1)

    # Load configs
    with open(PROMPT_TEMPLATE_PATH, encoding="utf-8") as f:
        prompt_template = json.load(f)
    with open(MODEL_CONFIG_PATH, encoding="utf-8") as f:
        model_config = json.load(f)
    with open(BASELINE_DATASET_PATH, encoding="utf-8") as f:
        baseline_data = json.load(f)

    print(f"\n  Data dir:       {DATA_DIR}")
    print(f"  Baseline cases: {len(baseline_data)}")
    print(f"  Model:          {model_config['model_name']}")

    # --- Initialize backend ---
    backend = LocalStorageBackend(data_dir=DATA_DIR)

    # --- Step 1: Save baseline prompt version ---
    print("\n[1/3] Saving baseline prompt version...")

    save_result = backend.save_prompt_version(
        prompt_content=json.dumps(prompt_template, ensure_ascii=False, indent=2),
        version_label="v1-baseline (seeded)",
        metadata={
            "model_name": model_config["model_name"],
            "temperature": model_config["temperature"],
            "created_by": "seed-script",
            "commit_sha": "initial-seed",
            "model_config": model_config,
        },
    )
    version_id = save_result["version_id"]
    print(f"  ✅ Version saved: {version_id}")
    print(f"     Path: {save_result['s3_path']}")

    # Promote to "promoted" status (this is v_current)
    backend.update_version_status(version_id, "promoted")
    print("  ✅ Status set to: promoted")

    # --- Step 2: Save baseline eval results ---
    print("\n[2/3] Saving baseline eval results...")

    # Conservative baseline scores — will be replaced after first real eval
    baseline_scores = {
        "quality_score": 7.5,
        "breakdown": {
            "task_completion": {"score": 8.0, "weight": 0.35},
            "output_quality": {"score": 7.5, "weight": 0.35},
            "latency": {"score": 7.0, "weight": 0.20},
            "cost_efficiency": {"score": 9.5, "weight": 0.10},
        },
    }

    # Generate placeholder details for each test case
    baseline_details = [
        {
            "test_case_id": tc["id"],
            "category": tc["category"],
            "score": 7.5,
            "passed": True,
            "input_preview": tc["input"][:80],
            "note": "Baseline placeholder — run real eval to update",
        }
        for tc in baseline_data
    ]

    eval_result = backend.save_eval_result(
        run_id="run-baseline-seed",
        version_id=version_id,
        scores=baseline_scores,
        details=baseline_details,
    )
    print(f"  ✅ Eval result saved: {eval_result['result_id']}")
    print(f"     Quality Score: {baseline_scores['quality_score']}")
    print(f"     Test cases:    {len(baseline_details)} passed / {len(baseline_details)} total")

    # --- Step 3: Write deployment record ---
    print("\n[3/3] Setting production deployment...")

    # We use the deploy backend to record this
    _local_config_path = os.environ.get(
        "APP_CONFIG", str(PROJECT_ROOT / "configs" / "local.json")
    )
    _local_config = json.loads(Path(_local_config_path).read_text(encoding="utf-8"))

    from mcp_servers.deploy.deploy_backend import LocalDeployBackend

    deploy_backend = LocalDeployBackend(data_dir=DATA_DIR, local_config=_local_config)
    deploy_result = deploy_backend.deploy_version(version_id, "production")
    print(f"  ✅ Production deployed: {deploy_result['deployment_id']}")
    print(f"     Endpoint: {deploy_result.get('endpoint_url', 'N/A')}")

    # --- Write seed marker ---
    from datetime import datetime, timezone

    marker = {
        "version_id": version_id,
        "run_id": "run-baseline-seed",
        "seeded_at": datetime.now(timezone.utc).isoformat(),
        "baseline_quality_score": baseline_scores["quality_score"],
        "test_cases_count": len(baseline_data),
    }
    SEED_MARKER.write_text(
        json.dumps(marker, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("✅ Baseline seeded successfully!")
    print(f"   v_current       = {version_id}")
    print(f"   Quality Score   = {baseline_scores['quality_score']}")
    print(f"   Marker file     = .local-data/.seeded")
    print("   Comparator will use this as baseline for first eval run.")
    print("=" * 60)


if __name__ == "__main__":
    main()
