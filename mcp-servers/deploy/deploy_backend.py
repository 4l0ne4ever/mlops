"""
Deploy backend abstraction — local filesystem implementation.

Simulates deploy/rollback operations for local development.
In production (EC2), this would actually restart target app services
via systemctl and update config files.

Data layout under .local-data/:
    deployments/
        staging.json         # Current staging deployment state
        production.json      # Current production deployment state
        history.jsonl        # Deployment history (append-only)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DeployEnvironment(str, Enum):
    """Deployment environment (str subclass; backward-compatible with plain strings)."""
    STAGING = "staging"
    PRODUCTION = "production"


class DeployStatus(str, Enum):
    """Deployment status (str subclass; backward-compatible with plain strings)."""
    IDLE = "idle"
    DEPLOYED = "deployed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (tmp file + os.replace)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class LocalDeployBackend:
    """Local filesystem backend simulating EC2 deploy operations."""

    def __init__(self, data_dir: str | Path, local_config: dict[str, Any]) -> None:
        self._data_dir = Path(data_dir)
        self._deploy_dir = self._data_dir / "deployments"
        self._deploy_dir.mkdir(parents=True, exist_ok=True)
        self._local_config = local_config

        # Initialize deployment state files if they don't exist
        for env in (DeployEnvironment.STAGING, DeployEnvironment.PRODUCTION):
            state_file = self._deploy_dir / f"{env.value}.json"
            if not state_file.exists():
                _atomic_write(
                    state_file,
                    json.dumps(
                        {
                            "current_version_id": "",
                            "status": DeployStatus.IDLE,
                            "deployed_at": "",
                            "deployment_id": "",
                        },
                        indent=2,
                    ),
                )

        logger.info("LocalDeployBackend initialized at %s", self._data_dir)

    def _get_endpoint_url(self, environment: str) -> str:
        """Get endpoint URL for environment from config."""
        target_app = self._local_config.get("target_app", {})
        if environment == "staging":
            return target_app.get("staging_url", "http://localhost:9001")
        return target_app.get("production_url", "http://localhost:9000")

    def _check_health(self, endpoint_url: str, retries: int = 3) -> bool:
        """Run health check with retries."""
        health_url = f"{endpoint_url.rstrip('/')}/health"
        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(health_url)
                if response.status_code == 200:
                    logger.info(
                        "Health check passed (attempt %d): %s",
                        attempt,
                        health_url,
                    )
                    return True
            except Exception as exc:
                logger.warning(
                    "Health check failed (attempt %d/%d): %s — %s",
                    attempt,
                    retries,
                    health_url,
                    exc,
                )
            if attempt < retries:
                time.sleep(2)
        return False

    def _write_history(self, record: dict[str, Any]) -> None:
        """Append a deployment record to history."""
        history_file = self._deploy_dir / "history.jsonl"
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── Deploy Operations ──────────────────────────────────────────────────

    def deploy_version(
        self,
        version_id: str,
        environment: str,
    ) -> dict[str, Any]:
        """
        Deploy a version to staging or production.

        In local dev, this updates the deployment state file.
        On EC2, this would pull config from S3, restart services, and health check.
        """
        if environment not in (DeployEnvironment.STAGING, DeployEnvironment.PRODUCTION):
            return {
                "deployment_id": "",
                "status": DeployStatus.FAILED,
                "error": f"Invalid environment: {environment}. Must be 'staging' or 'production'.",
            }

        deployment_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        endpoint_url = self._get_endpoint_url(environment)

        # Save previous state for potential rollback
        state_file = self._deploy_dir / f"{environment}.json"
        previous_state = json.loads(state_file.read_text(encoding="utf-8"))

        # Update deployment state
        new_state = {
            "current_version_id": version_id,
            "status": DeployStatus.DEPLOYED,
            "deployed_at": timestamp,
            "deployment_id": deployment_id,
            "previous_version_id": previous_state.get("current_version_id", ""),
        }
        _atomic_write(
            state_file,
            json.dumps(new_state, indent=2),
        )

        # Record in history
        self._write_history(
            {
                "deployment_id": deployment_id,
                "version_id": version_id,
                "environment": environment,
                "action": "deploy",
                "status": DeployStatus.DEPLOYED,
                "timestamp": timestamp,
                "endpoint_url": endpoint_url,
                "previous_version_id": previous_state.get("current_version_id", ""),
            }
        )

        logger.info(
            "Deployed %s to %s (deployment_id: %s)",
            version_id,
            environment,
            deployment_id,
        )

        return {
            "deployment_id": deployment_id,
            "status": DeployStatus.DEPLOYED,
            "endpoint_url": endpoint_url,
        }

    def rollback_version(
        self,
        target_version_id: str,
    ) -> dict[str, Any]:
        """
        Rollback production to a specific version.

        In local dev, updates the deployment state file.
        On EC2, would restore config files and restart services.
        """
        deployment_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        environment = "production"

        state_file = self._deploy_dir / f"{environment}.json"
        previous_state = json.loads(state_file.read_text(encoding="utf-8"))

        new_state = {
            "current_version_id": target_version_id,
            "status": DeployStatus.ROLLED_BACK,
            "deployed_at": timestamp,
            "deployment_id": deployment_id,
            "rolled_back_from": previous_state.get("current_version_id", ""),
        }
        _atomic_write(
            state_file,
            json.dumps(new_state, indent=2),
        )

        self._write_history(
            {
                "deployment_id": deployment_id,
                "version_id": target_version_id,
                "environment": environment,
                "action": "rollback",
                "status": DeployStatus.ROLLED_BACK,
                "timestamp": timestamp,
                "rolled_back_from": previous_state.get("current_version_id", ""),
            }
        )

        logger.info(
            "Rolled back production to %s (from %s)",
            target_version_id,
            previous_state.get("current_version_id", ""),
        )

        return {
            "deployment_id": deployment_id,
            "status": DeployStatus.ROLLED_BACK,
        }

    def get_deployment_status(
        self,
        deployment_id: str = "",
        environment: str = "",
    ) -> dict[str, Any]:
        """
        Get current deployment status.

        Can query by deployment_id (search history) or environment (current state).
        """
        # If environment specified, return current state
        if environment:
            if environment not in ("staging", "production"):
                return {"error": f"Invalid environment: {environment}"}
            state_file = self._deploy_dir / f"{environment}.json"
            if not state_file.exists():
                return {
                    "current_version_id": "",
                    "status": "no_deployment",
                    "environment": environment,
                }
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["environment"] = environment
            return state

        # If deployment_id specified, search history
        if deployment_id:
            history_file = self._deploy_dir / "history.jsonl"
            if not history_file.exists():
                return {"error": f"Deployment {deployment_id} not found"}
            with open(history_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("deployment_id") == deployment_id:
                        return record
            return {"error": f"Deployment {deployment_id} not found"}

        return {"error": "Must specify deployment_id or environment"}
