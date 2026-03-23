from __future__ import annotations

from typing import Any, Protocol


class StorageBackend(Protocol):
    def save_prompt_version(
        self,
        prompt_content: str,
        version_label: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def get_prompt_version(self, version_id: str) -> dict[str, Any]:
        ...

    def list_versions(self, limit: int = 20, status_filter: str = "all") -> list[dict[str, Any]]:
        ...

    def update_version_status(self, version_id: str, status: str) -> None:
        ...

    def save_eval_result(
        self,
        run_id: str,
        version_id: str,
        scores: dict[str, Any],
        details: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def get_eval_results(
        self,
        version_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


class MonitorBackend(Protocol):
    def push_metric(
        self,
        metric_name: str,
        value: float,
        dimensions: dict[str, str],
    ) -> dict[str, Any]:
        ...

    def get_metrics(self, metric_name: str, version_id: str, time_range: str) -> list[dict[str, Any]]:
        ...

    def get_logs(self, log_group: str, filter_pattern: str, time_range: str) -> list[dict[str, Any]]:
        ...

    def write_log(
        self,
        log_group: str,
        message: str,
        level: str = "INFO",
        extra: dict[str, Any] | None = None,
    ) -> None:
        ...


class DeployBackend(Protocol):
    def deploy_version(self, version_id: str, environment: str) -> dict[str, Any]:
        ...

    def rollback_version(self, target_version_id: str) -> dict[str, Any]:
        ...

    def get_deployment_status(
        self,
        deployment_id: str = "",
        environment: str = "",
    ) -> dict[str, Any]:
        ...

