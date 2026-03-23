from __future__ import annotations

import json
from typing import Any, Literal

import httpx


MCP_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SESSION_HEADER = "mcp-session-id"


_MCP_CLIENT_INFO = {
    "name": "agentops-framework",
    "version": "0.1.0",
}


McpServerName = Literal["storage", "monitor", "deploy"]


def _json_rpc_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _parse_mcp_content(data: Any) -> Any:
    """
    Extract parsed content from MCP responses.

    Supports:
      - JSON-RPC with `result.content` blocks of `{type:"text", text:"..."}`
      - direct `result` payloads
    """
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    result = data.get("result", data) if isinstance(data, dict) else data
    if not isinstance(result, dict):
        return result

    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
    return result


def _parse_mcp_http_response(resp: httpx.Response) -> Any:
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        return resp.json()

    body = resp.text
    if "text/event-stream" in content_type:
        # streamable-http may wrap MCP result as SSE with `data:` lines.
        data_lines = [
            line[5:].strip() for line in body.splitlines() if line.startswith("data:")
        ]
        if not data_lines:
            return None
        return json.loads(data_lines[-1])

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _initialize_session(client: httpx.Client, server_url: str, label: str) -> str:
    url = f"{server_url}/mcp"
    init_resp = client.post(
        url,
        json={
            "jsonrpc": MCP_VERSION,
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _MCP_CLIENT_INFO,
            },
        },
        headers=_json_rpc_headers(),
    )
    init_resp.raise_for_status()

    session_id = init_resp.headers.get(MCP_SESSION_HEADER)
    if not session_id:
        raise RuntimeError(f"{label} initialize: missing {MCP_SESSION_HEADER}")

    _parse_mcp_content(_parse_mcp_http_response(init_resp))

    notif_resp = client.post(
        url,
        json={
            "jsonrpc": MCP_VERSION,
            "method": "notifications/initialized",
            "params": {},
        },
        headers={**_json_rpc_headers(), MCP_SESSION_HEADER: session_id},
    )
    notif_resp.raise_for_status()

    return session_id


def call_tool(
    server: McpServerName,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    storage_url: str = "http://localhost:8000",
    monitor_url: str = "http://localhost:8001",
    deploy_url: str = "http://localhost:8002",
    timeout: float = 15.0,
) -> Any:
    """
    Call an MCP tool over streamable-http JSON-RPC.

    This hides session initialization from framework users.
    """
    if server == "storage":
        base = storage_url
    elif server == "monitor":
        base = monitor_url
    elif server == "deploy":
        base = deploy_url
    else:
        raise ValueError(f"Unknown server: {server}")

    url = f"{base}/mcp"
    headers = _json_rpc_headers()

    with httpx.Client(timeout=timeout) as client:
        label = f"MCP {server}.{tool_name}"
        session_id = _initialize_session(client, base, label)

        resp = client.post(
            url,
            json={
                "jsonrpc": MCP_VERSION,
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers={**headers, MCP_SESSION_HEADER: session_id},
        )

        if resp.status_code == 400:
            # Some servers require re-initialize on session-related errors.
            session_id = _initialize_session(client, base, label)
            resp = client.post(
                url,
                json={
                    "jsonrpc": MCP_VERSION,
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers={**headers, MCP_SESSION_HEADER: session_id},
            )

        resp.raise_for_status()
        parsed = _parse_mcp_http_response(resp)
        return _parse_mcp_content(parsed)

