from __future__ import annotations

"""
Entry point: `python -m agentops.mcp.deploy`

This reuses the existing MCP deploy server implementation.
"""

def main() -> None:
    from mcp_servers.deploy.server import mcp

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

