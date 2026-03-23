from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import agentops


def _load_config(path: str) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path
    data = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in {".json", ""}:
        return json.loads(data)
    raise ValueError(f"Unsupported config format: {cfg_path.suffix}. Use JSON for now.")


def _config_get(cfg: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def init_config(output: str) -> None:
    out_path = Path(output)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path

    sample = {
        "target_app": {"url": "http://localhost:9000"},
        "test_suite": "eval-datasets/baseline_v1.json",
        "backend": "local",
        "mcp": {
            "storage_url": "http://localhost:8000",
            "monitor_url": "http://localhost:8001",
            "deploy_url": "http://localhost:8002",
        },
    }
    out_path.write_text(json.dumps(sample, indent=2), encoding="utf-8")
    print(f"Wrote config to: {out_path}")


def cmd_run_eval(config_path: str, version_id: str) -> int:
    cfg = _load_config(config_path)

    target_url = _config_get(cfg, "target_app", "url", default="http://localhost:9000")
    test_suite = _config_get(cfg, "test_suite", default="eval-datasets/baseline_v1.json")
    backend = _config_get(cfg, "backend", default="local")

    mcp = cfg.get("mcp", {}) if isinstance(cfg.get("mcp"), dict) else {}
    storage_url = _config_get(mcp, "storage_url", default="http://localhost:8000")
    monitor_url = _config_get(mcp, "monitor_url", default="http://localhost:8001")
    deploy_url = _config_get(mcp, "deploy_url", default="http://localhost:8002")

    agentops.configure(
        target_app_url=target_url,
        test_suite_path=test_suite,
        backend=backend,
        mcp_storage_url=storage_url,
        mcp_monitor_url=monitor_url,
        mcp_deploy_url=deploy_url,
    )

    runner = agentops.EvalRunner()
    result = runner.run_eval(version_id=version_id)

    print(json.dumps({"run_id": result.run_id, "quality_score": result.quality_score.quality_score, "status": result.status}, indent=2))
    return 0


def cmd_run_orchestrator(config_path: str, run_id: str | None) -> int:
    cfg = _load_config(config_path)

    target_url = _config_get(cfg, "target_app", "url", default="http://localhost:9000")
    test_suite = _config_get(cfg, "test_suite", default="eval-datasets/baseline_v1.json")
    backend = _config_get(cfg, "backend", default="local")

    mcp = cfg.get("mcp", {}) if isinstance(cfg.get("mcp"), dict) else {}
    storage_url = _config_get(mcp, "storage_url", default="http://localhost:8000")
    monitor_url = _config_get(mcp, "monitor_url", default="http://localhost:8001")
    deploy_url = _config_get(mcp, "deploy_url", default="http://localhost:8002")

    agentops.configure(
        target_app_url=target_url,
        test_suite_path=test_suite,
        backend=backend,
        mcp_storage_url=storage_url,
        mcp_monitor_url=monitor_url,
        mcp_deploy_url=deploy_url,
    )

    orch = agentops.Orchestrator()
    result = orch.run_pipeline(run_id=run_id or "")
    print(json.dumps({"run_id": result.run_id, "quality_score": result.quality_score, "status": result.status}, indent=2))
    return 0


def cmd_run_mcp(server: str) -> int:
    if server == "storage":
        from agentops.mcp.storage import main
        main()
        return 0
    if server == "monitor":
        from agentops.mcp.monitor import main
        main()
        return 0
    if server == "deploy":
        from agentops.mcp.deploy import main
        main()
        return 0
    raise ValueError(f"Unknown MCP server: {server}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agentops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-config", help="Write a sample agentops config (JSON).")
    p_init.add_argument("--output", default="agentops.json")

    p_eval = sub.add_parser("run-eval", help="Run an eval run via EvalRunner.")
    p_eval.add_argument("--config", default="agentops.json")
    p_eval.add_argument("--version-id", default="v0")

    p_orch = sub.add_parser("run-orchestrator", help="Run the full orchestrator pipeline.")
    p_orch.add_argument("--config", default="agentops.json")
    p_orch.add_argument("--run-id", default=None)

    p_mcp = sub.add_parser("run-mcp", help="Start an MCP server (blocking).")
    p_mcp.add_argument("server", choices=["storage", "monitor", "deploy"])

    args = parser.parse_args(argv)

    if args.command == "init-config":
        init_config(args.output)
        return
    if args.command == "run-eval":
        sys.exit(cmd_run_eval(args.config, args.version_id))
    if args.command == "run-orchestrator":
        sys.exit(cmd_run_orchestrator(args.config, args.run_id))
    if args.command == "run-mcp":
        sys.exit(cmd_run_mcp(args.server))


if __name__ == "__main__":
    main()

