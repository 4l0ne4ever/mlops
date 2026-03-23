from .interfaces import StorageBackend, MonitorBackend, DeployBackend

__all__ = ["StorageBackend", "MonitorBackend", "DeployBackend", "LocalStorageBackend", "LocalMonitorBackend", "LocalDeployBackend"]


def __getattr__(name: str):
    # Lazy backend loading so `import agentops` works from source without
    # setuptools `package_dir` alias being active.
    if name == "LocalStorageBackend":
        from .storage_local import LocalStorageBackend

        return LocalStorageBackend
    if name == "LocalMonitorBackend":
        from .monitor_local import LocalMonitorBackend

        return LocalMonitorBackend
    if name == "LocalDeployBackend":
        from .deploy_local import LocalDeployBackend

        return LocalDeployBackend
    raise AttributeError(f"module 'agentops.backends' has no attribute {name!r}")

