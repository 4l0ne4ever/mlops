from __future__ import annotations

"""
Entry point: `python -m agentops.mcp.storage`

This reuses the existing MCP storage server implementation.
"""

def main() -> None:
    from mcp_servers.storage.server import mcp

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

