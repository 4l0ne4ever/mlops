#!/usr/bin/env python3
"""
Run the full stack like a real product: start all services, then run health checks,
trigger a pipeline run, and verify the dashboard. Cleans up processes on exit.

Usage (from project root):
  python scripts/run_product_test.py

Requires: .venv, configs, eval-datasets, and APP_CONFIG pointing to configs/local.json.
Staging target app (9001) must be reachable for the pipeline to run evals.
"""
from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Default orchestrator to 7001 for this script to avoid macOS AirPlay on 7000
os.environ.setdefault("ORCHESTRATOR_PORT", "7001")

from agentops.settings import (
    DASHBOARD_PORT,
    MCP_DEPLOY_PORT,
    MCP_MONITOR_PORT,
    MCP_STORAGE_PORT,
    ORCHESTRATOR_PORT,
    TARGET_APP_PROD_PORT,
    TARGET_APP_STAGING_PORT,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _service_definitions() -> list[tuple[str, int, list, str, dict | None]]:
    """Build SERVICE list from agentops.settings so ports/URLs stay in sync with config."""
    return [
        ("target-app prod", TARGET_APP_PROD_PORT, [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", str(TARGET_APP_PROD_PORT)], str(PROJECT_ROOT / "target-app"), None),
        ("target-app staging", TARGET_APP_STAGING_PORT, [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", str(TARGET_APP_STAGING_PORT)], str(PROJECT_ROOT / "target-app"), None),
        ("MCP storage", MCP_STORAGE_PORT, [sys.executable, str(PROJECT_ROOT / "mcp-servers" / "storage" / "server.py")], str(PROJECT_ROOT), None),
        ("MCP monitor", MCP_MONITOR_PORT, [sys.executable, str(PROJECT_ROOT / "mcp-servers" / "monitor" / "server.py")], str(PROJECT_ROOT), None),
        ("MCP deploy", MCP_DEPLOY_PORT, [sys.executable, str(PROJECT_ROOT / "mcp-servers" / "deploy" / "server.py")], str(PROJECT_ROOT), None),
        ("orchestrator", ORCHESTRATOR_PORT, [sys.executable, "-m", "agents.orchestrator.agent", "--serve", "--port", str(ORCHESTRATOR_PORT)], str(PROJECT_ROOT), None),
        ("dashboard", DASHBOARD_PORT, ["npm", "run", "dev"], str(PROJECT_ROOT / "dashboard"), {
            "MCP_STORAGE_URL": f"http://127.0.0.1:{MCP_STORAGE_PORT}",
            "MCP_MONITOR_URL": f"http://127.0.0.1:{MCP_MONITOR_PORT}",
            "MCP_DEPLOY_URL": f"http://127.0.0.1:{MCP_DEPLOY_PORT}",
        }),
    ]


SERVICES = _service_definitions()

PROCS: list[subprocess.Popen] = []


def wait_for_port(host: str, port: int, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (socket.error, OSError):
            time.sleep(0.4)
    return False


def kill_all() -> None:
    for p in PROCS:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()


def free_port(port: int) -> None:
    """Try to free the port by killing any process listening on it."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            for pid in out.stdout.strip().split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, ValueError):
                    pass
            time.sleep(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def main() -> int:
    atexit.register(kill_all)
    env_base = os.environ.copy()
    env_base.setdefault("APP_CONFIG", str(PROJECT_ROOT / "configs" / "local.json"))

    ports = [TARGET_APP_PROD_PORT, TARGET_APP_STAGING_PORT, MCP_STORAGE_PORT, MCP_MONITOR_PORT, MCP_DEPLOY_PORT, ORCHESTRATOR_PORT, DASHBOARD_PORT]
    print("Freeing ports for clean run...")
    for port in ports:
        free_port(port)
    time.sleep(2)

    print("Starting all services (product stack)...")
    for name, port, cmd, cwd, env_add in SERVICES:
        env = {**env_base, **(env_add or {})}
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        PROCS.append(p)
        print(f"  Started {name} (port {port})")
        time.sleep(0.8)

    print("\nWaiting for ports...")
    all_ok = True
    for _name, port, _cmd, _cwd, _env in SERVICES:
        if wait_for_port("127.0.0.1", port):
            print(f"  OK port {port}")
        else:
            print(f"  FAIL port {port}")
            all_ok = False
    if not all_ok:
        kill_all()
        return 1

    print("\n--- Health checks ---")
    checks = [
        ("Target app prod", f"http://127.0.0.1:{TARGET_APP_PROD_PORT}/health"),
        ("Target app staging", f"http://127.0.0.1:{TARGET_APP_STAGING_PORT}/health"),
        ("Orchestrator", f"http://127.0.0.1:{ORCHESTRATOR_PORT}/health"),
    ]
    for label, url in checks:
        try:
            req = Request(url, headers={"User-Agent": "AgentOps-ProductTest/1.0", "Accept": "application/json"})
            with urlopen(req, timeout=5) as r:
                json.loads(r.read().decode())
            print(f"  {label}: OK")
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            print(f"  {label}: FAIL — HTTP {e.code} — {body[:200]}")
            all_ok = False
        except Exception as e:
            print(f"  {label}: FAIL — {e}")
            all_ok = False

    print("\n--- Dashboard API ---")
    for label, url in [("Overview", f"http://127.0.0.1:{DASHBOARD_PORT}/api/overview"), ("Versions", f"http://127.0.0.1:{DASHBOARD_PORT}/api/versions")]:
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as r:
                json.loads(r.read().decode())
            print(f"  GET {url}: 200 OK")
        except Exception as e:
            print(f"  GET {url}: FAIL — {e}")
            all_ok = False

    print("\n--- Trigger pipeline (manual) ---")
    try:
        req = Request(
            f"http://127.0.0.1:{ORCHESTRATOR_PORT}/trigger",
            data=json.dumps({"trigger_type": "manual"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=600) as r:  # pipeline can take several minutes (eval + judge)
            body = json.loads(r.read().decode())
        rid = body.get("run_id", "")
        status = body.get("status", "unknown")
        score = body.get("quality_score", 0)
        print(f"  POST /trigger: 200 — run_id={rid[:12]}..., status={status}, quality_score={score:.3f}")
        if status not in ("completed", "skipped"):
            print(f"  WARNING: status was {status}")
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  POST /trigger: HTTP {e.code} — {body[:300]}")
        all_ok = False
    except URLError as e:
        print(f"  POST /trigger: {e.reason}")
        all_ok = False
    except Exception as e:
        print(f"  POST /trigger: {e}")
        all_ok = False

    print("\n--- Dashboard after run ---")
    try:
        req = Request(f"http://127.0.0.1:{DASHBOARD_PORT}/api/overview", headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as r:
            overview = json.loads(r.read().decode())
        runs = overview.get("recentRuns") or []
        print(f"  Overview: recentRuns count = {len(runs)}")
    except Exception as e:
        print(f"  Overview: {e}")

    kill_all()
    print("\n" + ("Product test PASSED" if all_ok else "Product test FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
