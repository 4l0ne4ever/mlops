# MCP Integration Guide

This document describes how services in this repository communicate with the MCP layer in the current production-oriented implementation.

## Transport

The MCP servers use FastMCP with `streamable-http` transport, not the older SSE handshake flow.

Endpoints:

- Storage: `http://<host>:8000/mcp`
- Monitor: `http://<host>:8001/mcp`
- Deploy: `http://<host>:8002/mcp`

FastMCP streamable-http requires a short session handshake before calling tools:

1. POST `initialize` to `/mcp`
2. Read the `mcp-session-id` response header
3. POST `notifications/initialized` with that session header
4. POST `tools/call` with the same session header

Tool calls are then sent as JSON-RPC 2.0 payloads:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_versions",
    "arguments": {
      "limit": 20,
      "status_filter": "all"
    }
  }
}
```

## Available Tools

### Storage Server

- `save_prompt_version`
- `get_prompt_version`
- `list_versions`
- `update_version_status`
- `save_eval_result`
- `get_eval_results`

### Monitor Server

- `push_metric`
- `get_metrics`
- `get_logs`
- `check_health`

### Deploy Server

- `deploy_version`
- `rollback_version`
- `get_deployment_status`

## Python Client Pattern

The repository clients in [agents/mcp_client.py](/Users/duongcongthuyet/Downloads/workspace/AI%20/agentic%20mlops/agents/mcp_client.py) and [dashboard/lib/mcp.ts](/Users/duongcongthuyet/Downloads/workspace/AI%20/agentic%20mlops/dashboard/lib/mcp.ts) follow this pattern:

1. POST `initialize` to `/mcp`
2. Capture `mcp-session-id`
3. POST `notifications/initialized`
4. POST JSON-RPC 2.0 `tools/call`
5. Parse the returned `result.content[]` blocks
6. Fail closed in production unless `MCP_ALLOW_FALLBACK=true`

Minimal example:

```python
import httpx

with httpx.Client(timeout=10.0) as client:
  initialize = client.post(
        "http://localhost:8000/mcp",
    json={
      "jsonrpc": "2.0",
      "id": 1,
      "method": "initialize",
      "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "example-client", "version": "0.1.0"},
      },
    },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
  initialize.raise_for_status()
  session_id = initialize.headers["mcp-session-id"]

  client.post(
    "http://localhost:8000/mcp",
    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    headers={
      "Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
      "mcp-session-id": session_id,
    },
  ).raise_for_status()

  response = client.post(
    "http://localhost:8000/mcp",
    json={
      "jsonrpc": "2.0",
      "id": 1,
      "method": "tools/call",
      "params": {
        "name": "get_eval_results",
        "arguments": {"version_id": "", "run_id": ""},
      },
    },
    headers={
      "Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
      "mcp-session-id": session_id,
    },
  )
  response.raise_for_status()
```

## Operational Notes

- Use `MCP_STORAGE_URL`, `MCP_MONITOR_URL`, and `MCP_DEPLOY_URL` to point clients at non-local hosts.
- For HTTPS (e.g. TLS at nginx or ALB), set these to the base paths **without** `/mcp`; the client appends `/mcp`. Example: `https://<domain>/storage`, `https://<domain>/monitor`, `https://<domain>/deploy`.
- In production, do not rely on silent local fallback. The client code is configured to fail closed by default.
- The dashboard should read through MCP or the same authoritative storage sources, not through mock JSON embedded in the frontend.

## Troubleshooting

- `405` or `406` on `GET /mcp`: the endpoint exists; use `POST /mcp` for session setup and tool calls.
- `400 Missing session ID`: the client skipped `initialize` or did not forward the `mcp-session-id` header.
- `404` on `/call-tool`: client is using an outdated transport assumption.
- Empty dashboard data: verify MCP URLs, server health, and that eval runs or decisions have actually been persisted.
