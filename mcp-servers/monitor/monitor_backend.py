"""
Monitor backend abstraction — local filesystem implementation.

Simulates CloudWatch Metrics + CloudWatch Logs for local development.

Data layout under .local-data/:
    metrics/{metric_name}/
        datapoints.jsonl     # Append-only, one JSON per line
    logs/{log_group}/
        entries.jsonl        # Append-only, one JSON per line
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Time-range helper ──────────────────────────────────────────────────────

_TIME_RANGE_RE = re.compile(r"^last_(\d+)(h|d)$")


def _cutoff_for_range(time_range: str) -> datetime | None:
    """Return a UTC datetime cutoff for a time_range string like 'last_24h' or 'last_7d'."""
    m = _TIME_RANGE_RE.match(time_range)
    if not m:
        return None  # unknown format → return all data
    amount, unit = int(m.group(1)), m.group(2)
    delta = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    return datetime.now(timezone.utc) - delta


class LocalMonitorBackend:
    """Local filesystem backend simulating CloudWatch for development."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._metrics_dir = self._data_dir / "metrics"
        self._logs_dir = self._data_dir / "logs"
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        logger.info("LocalMonitorBackend initialized at %s", self._data_dir)

    # ── Metrics Operations ─────────────────────────────────────────────────

    def push_metric(
        self,
        metric_name: str,
        value: float,
        dimensions: dict[str, str],
    ) -> dict[str, Any]:
        """Push a custom metric datapoint — simulates CloudWatch PutMetricData."""
        timestamp = datetime.now(timezone.utc).isoformat()

        metric_dir = self._metrics_dir / metric_name
        metric_dir.mkdir(parents=True, exist_ok=True)

        datapoint = {
            "metric_name": metric_name,
            "value": value,
            "dimensions": dimensions,
            "timestamp": timestamp,
        }

        datapoints_file = metric_dir / "datapoints.jsonl"
        with open(datapoints_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(datapoint, ensure_ascii=False) + "\n")

        logger.info(
            "Pushed metric %s = %.4f (dims: %s)",
            metric_name,
            value,
            dimensions,
        )
        return {"status": "ok", "timestamp": timestamp}

    def get_metrics(
        self,
        metric_name: str,
        version_id: str = "",
        time_range: str = "last_24h",
    ) -> list[dict[str, Any]]:
        """Get metric datapoints — simulates CloudWatch GetMetricData."""
        metric_dir = self._metrics_dir / metric_name
        datapoints_file = metric_dir / "datapoints.jsonl"

        if not datapoints_file.exists():
            return []

        datapoints: list[dict[str, Any]] = []
        with open(datapoints_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                dp = json.loads(line)
                # Filter by version_id dimension if specified
                if version_id:
                    dims = dp.get("dimensions", {})
                    if dims.get("version_id") != version_id:
                        continue
                datapoints.append(
                    {"timestamp": dp["timestamp"], "value": dp["value"]}
                )

        # Sort by timestamp ascending
        datapoints.sort(key=lambda d: d["timestamp"])

        # Filter by time_range
        cutoff = _cutoff_for_range(time_range)
        if cutoff is not None:
            cutoff_iso = cutoff.isoformat()
            datapoints = [dp for dp in datapoints if dp["timestamp"] >= cutoff_iso]

        return datapoints

    # ── Logs Operations ────────────────────────────────────────────────────

    def write_log(
        self,
        log_group: str,
        message: str,
        level: str = "INFO",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write a log entry — simulates CloudWatch PutLogEvents."""
        timestamp = datetime.now(timezone.utc).isoformat()

        log_dir = self._logs_dir / log_group
        log_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            **(extra or {}),
        }

        entries_file = log_dir / "entries.jsonl"
        with open(entries_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_logs(
        self,
        log_group: str,
        filter_pattern: str = "",
        time_range: str = "last_24h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get log entries — simulates CloudWatch FilterLogEvents."""
        log_dir = self._logs_dir / log_group
        entries_file = log_dir / "entries.jsonl"

        if not entries_file.exists():
            return []

        entries: list[dict[str, Any]] = []
        with open(entries_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                # Simple filter: check if pattern appears in message
                if filter_pattern and filter_pattern not in entry.get("message", ""):
                    continue
                entries.append(entry)

        # Sort by timestamp descending (newest first)
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        # Filter by time_range
        cutoff = _cutoff_for_range(time_range)
        if cutoff is not None:
            cutoff_iso = cutoff.isoformat()
            entries = [e for e in entries if e.get("timestamp", "") >= cutoff_iso]

        return entries[:limit]
