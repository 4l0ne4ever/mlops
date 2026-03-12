"""Quick integration test: start all 3 MCP servers, discover tools via MCP client."""

import asyncio
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def main():
    # Start all 3 MCP servers
    scripts = [
        PROJECT_ROOT / "mcp-servers" / "storage" / "server.py",
        PROJECT_ROOT / "mcp-servers" / "monitor" / "server.py",
        PROJECT_ROOT / "mcp-servers" / "deploy" / "server.py",
    ]

    procs = []
    for script in scripts:
        p = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append(p)

    time.sleep(4)

    # Check all started
    for i, p in enumerate(procs):
        if p.poll() is not None:
            out = p.stdout.read()
            print(f"FAIL: Server {scripts[i].parent.name} exited early:\n{out[-300:]}")
            # Cleanup others
            for pp in procs:
                if pp.poll() is None:
                    pp.send_signal(signal.SIGINT)
            sys.exit(1)

    print("All 3 MCP servers running.")

    # Discover tools
    async def discover():
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {
                "storage": {"url": "http://localhost:8000/sse", "transport": "sse"},
                "monitor": {"url": "http://localhost:8001/sse", "transport": "sse"},
                "deploy": {"url": "http://localhost:8002/sse", "transport": "sse"},
            }
        )
        tools = await client.get_tools()
        return tools

    tools = asyncio.run(discover())
    print(f"\nDiscovered {len(tools)} tools:")
    for t in sorted(tools, key=lambda x: x.name):
        print(f"  - {t.name}: {t.description[:70]}")

    expected = {
        "save_prompt_version",
        "get_prompt_version",
        "list_versions",
        "save_eval_result",
        "get_eval_results",
        "push_metric",
        "get_metrics",
        "get_logs",
        "check_health",
        "deploy_version",
        "rollback_version",
        "get_deployment_status",
    }
    found = {t.name for t in tools}
    missing = expected - found
    extra = found - expected

    print()
    if missing:
        print(f"MISSING tools: {missing}")
    if extra:
        print(f"EXTRA tools: {extra}")
    if not missing:
        print(f"ALL {len(expected)} expected tools discovered!")

    # Cleanup
    for p in procs:
        p.send_signal(signal.SIGINT)
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()

    sys.exit(0 if not missing else 1)


if __name__ == "__main__":
    main()
