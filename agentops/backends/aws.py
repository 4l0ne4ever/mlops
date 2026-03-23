from __future__ import annotations

from typing import Any


class AwsStorageBackend:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "AWS storage backend is not implemented in this framework stage yet. "
            "Use the local backend for now."
        )


class AwsMonitorBackend:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "AWS monitor backend is not implemented in this framework stage yet. "
            "Use the local backend for now."
        )


class AwsDeployBackend:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "AWS deploy backend is not implemented in this framework stage yet. "
            "Use the local backend for now."
        )


__all__ = ["AwsStorageBackend", "AwsMonitorBackend", "AwsDeployBackend"]

