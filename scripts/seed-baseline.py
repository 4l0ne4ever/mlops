#!/usr/bin/env python3
"""
Seed baseline results into DynamoDB as v_current.

Solves the "first-run problem": when the pipeline runs for the first time,
there is no v_current to compare against. This script creates the initial
version record and eval results in DynamoDB so the Comparator has a baseline.

Usage:
    # Ensure AWS credentials are configured
    python scripts/seed-baseline.py

    # With custom config
    APP_CONFIG=configs/production.json python scripts/seed-baseline.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "agentops-storage")
DYNAMODB_VERSIONS_TABLE = os.environ.get("DYNAMODB_TABLE_VERSIONS", "agentops-versions")
DYNAMODB_EVAL_RUNS_TABLE = os.environ.get("DYNAMODB_TABLE_EVAL_RUNS", "agentops-eval-runs")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

BASELINE_DATASET_PATH = PROJECT_ROOT / "eval-datasets" / "baseline_v1.json"
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "configs" / "prompt_template.json"
MODEL_CONFIG_PATH = PROJECT_ROOT / "configs" / "model_config.json"


def main() -> None:
    """Seed baseline v_current into DynamoDB + S3."""

    print("=" * 60)
    print("AgentOps — Seed Baseline v_current")
    print("=" * 60)

    # Validate files exist
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

    # Generate IDs
    version_id = f"v1-baseline-{uuid.uuid4().hex[:8]}"
    run_id = f"run-baseline-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    print(f"  Version ID: {version_id}")
    print(f"  Run ID:     {run_id}")
    print(f"  Timestamp:  {now}")

    # --- S3: Upload config files ---
    print("\n[1/3] Uploading configs to S3...")
    s3 = boto3.client("s3", region_name=AWS_REGION)

    s3_prefix = f"versions/{version_id}"

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{s3_prefix}/prompt_template.json",
        Body=json.dumps(prompt_template, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{s3_prefix}/model_config.json",
        Body=json.dumps(model_config, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{s3_prefix}/metadata.json",
        Body=json.dumps({"seeded": True, "seeded_at": now}, indent=2),
        ContentType="application/json",
    )
    print(f"  Uploaded to s3://{S3_BUCKET}/{s3_prefix}/")

    # --- DynamoDB: Create version record ---
    print("\n[2/3] Creating version record in DynamoDB...")
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

    versions_table = dynamodb.Table(DYNAMODB_VERSIONS_TABLE)
    versions_table.put_item(Item={
        "version_id": version_id,
        "version_label": "v1-baseline (seeded)",
        "s3_path": f"s3://{S3_BUCKET}/{s3_prefix}",
        "prompt_hash": "baseline-initial",
        "model_name": model_config["model_name"],
        "temperature": str(model_config["temperature"]),
        "status": "promoted",
        "created_at": now,
        "created_by": "seed-script",
        "commit_sha": "initial-seed",
    })
    print(f"  Created version record: {version_id}")

    # --- DynamoDB: Create baseline eval run ---
    print("\n[3/3] Creating baseline eval run in DynamoDB...")

    # Baseline scores (conservative defaults — will be updated after first real eval)
    baseline_quality_score = 7.5  # Placeholder — run actual eval to update
    baseline_breakdown = {
        "task_completion": {"score": 8.0, "weight": 0.35},
        "output_quality": {"score": 7.5, "weight": 0.35},
        "latency": {"score": 7.0, "weight": 0.20},
        "cost_efficiency": {"score": 9.5, "weight": 0.10},
    }

    eval_runs_table = dynamodb.Table(DYNAMODB_EVAL_RUNS_TABLE)
    eval_runs_table.put_item(Item={
        "run_id": run_id,
        "version_id": version_id,
        "trigger_id": "seed-baseline",
        "quality_score": str(baseline_quality_score),
        "score_breakdown": json.dumps(baseline_breakdown),
        "test_suite_id": "baseline_v1",
        "total_test_cases": len(baseline_data),
        "passed_test_cases": len(baseline_data),
        "avg_latency_ms": 0,
        "total_cost_usd": str(0),
        "status": "completed",
        "started_at": now,
        "completed_at": now,
        "decision": "promoted",
        "decision_reasoning": "Initial baseline — seeded by seed-baseline.py",
    })
    print(f"  Created eval run record: {run_id}")

    # --- Update current deployment record in S3 ---
    s3.put_object(
        Bucket=S3_BUCKET,
        Key="deployments/current/production.json",
        Body=json.dumps({
            "version_id": version_id,
            "deployed_at": now,
            "deployed_by": "seed-script",
        }, indent=2),
        ContentType="application/json",
    )
    print(f"\n  Set production deployment to: {version_id}")

    print("\n" + "=" * 60)
    print("✅ Baseline seeded successfully!")
    print(f"   v_current = {version_id}")
    print("   Comparator will use this as baseline for first eval run.")
    print("=" * 60)


if __name__ == "__main__":
    main()
