#!/usr/bin/env python3
"""
End-to-end test: start MCP servers and (optionally) dashboard, then verify APIs.
Run from project root with: python scripts/e2e_test.py [--with-dashboard]
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (socket.error, OSError):
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E test: MCP servers + optional dashboard")
    parser.add_argument("--with-dashboard", action="store_true", help="Start Next.js and hit /api/overview")
    parser.add_argument("--dashboard-timeout", type=float, default=60.0, help="Seconds to wait for dashboard")
    args = parser.parse_args()

    mcp_scripts = [
        PROJECT_ROOT / "mcp-servers" / "storage" / "server.py",
        PROJECT_ROOT / "mcp-servers" / "monitor" / "server.py",
        PROJECT_ROOT / "mcp-servers" / "deploy" / "server.py",
    ]
    mcp_procs = []
    for script in mcp_scripts:
        p = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        mcp_procs.append(p)

    time.sleep(3)
    for i, p in enumerate(mcp_procs):
        if p.poll() is not None:
            print(f"FAIL: MCP server {mcp_scripts[i].parent.name} exited early")
            for pp in mcp_procs:
                if pp.poll() is None:
                    pp.terminate()
            return 1

    print("MCP servers (8000, 8001, 8002) running.")

    if not args.with_dashboard:
        print("E2E (MCP only) OK. Use --with-dashboard to test dashboard API.")
        for p in mcp_procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        return 0

    env = {
        "MCP_STORAGE_URL": "http://127.0.0.1:8000",
        "MCP_MONITOR_URL": "http://127.0.0.1:8001",
        "MCP_DEPLOY_URL": "http://127.0.0.1:8002",
        **os.environ,
    }
    dash = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(PROJECT_ROOT / "dashboard"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if not wait_for_port("127.0.0.1", 3000, timeout=args.dashboard_timeout):
        stderr = dash.stderr.read() if dash.stderr else ""
        print(f"FAIL: Dashboard did not bind to 3000 within {args.dashboard_timeout}s")
        if stderr:
            print(stderr[-800:])
        dash.terminate()
        for p in mcp_procs:
            p.terminate()
        return 1

    print("Dashboard listening on 3000.")

    failed = False
    for label, url in [("overview", "http://127.0.0.1:3000/api/overview"), ("versions", "http://127.0.0.1:3000/api/versions")]:
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                data = json.loads(body)
            print(f"  GET {url} -> 200 OK (valid JSON)")
        except HTTPError as e:
            print(f"  GET {url} -> HTTP {e.code}")
            failed = True
        except (URLError, json.JSONDecodeError, OSError) as e:
            print(f"  GET {url} -> error: {e}")
            failed = True

    dash.terminate()
    try:
        dash.wait(timeout=10)
    except subprocess.TimeoutExpired:
        dash.kill()
    for p in mcp_procs:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()

    if failed:
        print("E2E FAIL: one or more dashboard API checks failed.")
        return 1
    print("E2E OK: MCP + dashboard APIs passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
