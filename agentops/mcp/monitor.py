from __future__ import annotations

"""
Entry point: `python -m agentops.mcp.monitor`

This reuses the existing MCP monitor server implementation.
"""

def main() -> None:
    from mcp_servers.monitor.server import mcp

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

