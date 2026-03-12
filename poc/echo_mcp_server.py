"""
POC Spike — Echo MCP Server.

Minimal MCP server with a single 'echo' tool to validate:
- MCP Python SDK (FastMCP) works
- SSE transport works
- Tool discovery (tools/list) works
- Tool invocation (tools/call) works

Run: python poc/echo_mcp_server.py
SSE endpoint: http://localhost:8000/sse

Test with MCP Inspector:
    npx @modelcontextprotocol/inspector sse http://localhost:8000/sse
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Port must be set in constructor (mcp >= 1.26.0)
_port = int(os.environ.get("MCP_STORAGE_PORT", "8000"))
mcp = FastMCP("echo-server", port=_port)


@mcp.tool()
def echo(text: str) -> str:
    """Echo back the input text. Used to validate MCP tool call round-trip."""
    return f"Echo: {text}"


@mcp.tool()
def echo_with_metadata(text: str, metadata: str = "") -> dict:
    """
    Echo back the input text with optional metadata.
    Returns structured response to validate complex return types.
    """
    return {
        "echoed_text": text,
        "metadata": metadata,
        "server": "echo-mcp-server",
        "status": "success",
    }


if __name__ == "__main__":
    # Run with SSE transport — validates that SSE works end-to-end
    mcp.run(transport="sse")
