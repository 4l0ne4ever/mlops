"""
Storage backend abstraction — local filesystem implementation.

This module provides a local filesystem backend that simulates S3 + DynamoDB
for development. In production (EC2), swap to AWSStorageBackend by setting
STORAGE_BACKEND=aws in .env.

Data layout under .local-data/:
    versions/{version_id}/
        metadata.json       # DynamoDB-like record
        prompt_template.json
        model_config.json
    eval-results/{run_id}/
        result.json          # Full eval result record
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VersionStatus(str, Enum):
    """Version status values (str subclass; backward-compatible with plain strings)."""
    ACTIVE = "active"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    PENDING = "pending"
    COMPLETED = "completed"


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (tmp file + os.replace)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class LocalStorageBackend:
    """Local filesystem backend simulating S3 + DynamoDB for development."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._versions_dir = self._data_dir / "versions"
        self._eval_results_dir = self._data_dir / "eval-results"
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._eval_results_dir.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageBackend initialized at %s", self._data_dir)

    # ── Prompt Version Operations ──────────────────────────────────────────

    def save_prompt_version(
        self,
        prompt_content: str,
        version_label: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Save a prompt version — simulates S3 upload + DynamoDB put_item."""
        version_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        prompt_hash = hashlib.sha256(prompt_content.encode()).hexdigest()

        version_dir = self._versions_dir / version_id
        version_dir.mkdir(parents=True, exist_ok=True)

        # Save prompt content (simulates S3)
        prompt_path = version_dir / "prompt_template.json"
        _atomic_write(prompt_path, prompt_content)

        # Save model config if provided in metadata
        if "model_config" in metadata:
            model_config_path = version_dir / "model_config.json"
            _atomic_write(
                model_config_path,
                json.dumps(metadata["model_config"], indent=2, ensure_ascii=False),
            )

        # Save metadata record (simulates DynamoDB)
        record = {
            "version_id": version_id,
            "version_label": version_label,
            "s3_path": f"versions/{version_id}/prompt_template.json",
            "prompt_hash": prompt_hash,
            "model_name": metadata.get("model_name", ""),
            "temperature": metadata.get("temperature", 0.0),
            "status": VersionStatus.ACTIVE,
            "created_at": timestamp,
            "created_by": metadata.get("created_by", "system"),
            "commit_sha": metadata.get("commit_sha", ""),
        }
        metadata_path = version_dir / "metadata.json"
        _atomic_write(
            metadata_path,
            json.dumps(record, indent=2, ensure_ascii=False),
        )

        logger.info("Saved prompt version %s (%s)", version_id, version_label)
        return {
            "version_id": version_id,
            "s3_path": record["s3_path"],
            "timestamp": timestamp,
        }

    def get_prompt_version(self, version_id: str) -> dict[str, Any]:
        """Get a prompt version by ID — simulates S3 download + DynamoDB get_item."""
        version_dir = self._versions_dir / version_id
        if not version_dir.exists():
            raise FileNotFoundError(f"Version {version_id} not found")

        metadata_path = version_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        prompt_path = version_dir / "prompt_template.json"
        prompt_content = prompt_path.read_text(encoding="utf-8")

        return {
            "prompt_content": prompt_content,
            "metadata": metadata,
            "created_at": metadata["created_at"],
        }

    def list_versions(
        self,
        limit: int = 20,
        status_filter: str = "all",
    ) -> list[dict[str, Any]]:
        """List all versions, sorted by creation time (newest first)."""
        versions: list[dict[str, Any]] = []

        for version_dir in self._versions_dir.iterdir():
            if not version_dir.is_dir():
                continue
            metadata_path = version_dir / "metadata.json"
            if not metadata_path.exists():
                continue
            record = json.loads(metadata_path.read_text(encoding="utf-8"))
            if status_filter != "all" and record.get("status") != status_filter:
                continue
            versions.append({
                "version_id": record["version_id"],
                "version_label": record.get("version_label", ""),
                "created_at": record["created_at"],
                "status": record.get("status", "unknown"),
            })

        # Sort by created_at descending (newest first)
        versions.sort(key=lambda v: v["created_at"], reverse=True)
        return versions[:limit]

    def update_version_status(self, version_id: str, status: str) -> None:
        """Update the status of a version (e.g., promoted, rolled_back)."""
        version_dir = self._versions_dir / version_id
        metadata_path = version_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Version {version_id} not found")

        record = json.loads(metadata_path.read_text(encoding="utf-8"))
        record["status"] = status
        _atomic_write(
            metadata_path,
            json.dumps(record, indent=2, ensure_ascii=False),
        )

    # ── Eval Result Operations ─────────────────────────────────────────────

    def save_eval_result(
        self,
        run_id: str,
        version_id: str,
        scores: dict[str, Any],
        details: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Save evaluation results — simulates DynamoDB put_item."""
        result_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        run_dir = self._eval_results_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        record = {
            "result_id": result_id,
            "run_id": run_id,
            "version_id": version_id,
            "quality_score": scores.get("quality_score", 0.0),
            "score_breakdown": scores.get("breakdown", {}),
            "total_test_cases": len(details),
            "passed_test_cases": sum(
                1 for d in details if d.get("passed", False)
            ),
            "status": VersionStatus.COMPLETED,
            "timestamp": timestamp,
            "details": details,
        }

        result_path = run_dir / "result.json"
        _atomic_write(
            result_path,
            json.dumps(record, indent=2, ensure_ascii=False),
        )

        logger.info(
            "Saved eval result %s for version %s (score: %.2f)",
            result_id,
            version_id,
            record["quality_score"],
        )
        return {"result_id": result_id, "timestamp": timestamp}

    def get_eval_results(
        self,
        version_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get eval results filtered by version_id or run_id."""
        results: list[dict[str, Any]] = []

        for run_dir in self._eval_results_dir.iterdir():
            if not run_dir.is_dir():
                continue
            result_path = run_dir / "result.json"
            if not result_path.exists():
                continue

            record = json.loads(result_path.read_text(encoding="utf-8"))

            # Filter by run_id if specified
            if run_id and record.get("run_id") != run_id:
                continue
            # Filter by version_id if specified
            if version_id and record.get("version_id") != version_id:
                continue

            results.append(record)

        # Sort by timestamp descending
        results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return results
