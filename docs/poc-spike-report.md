# POC Spike Report — Tech Stack Validation Results

> **Date:** 2026-03-09  
> **Environment:** macOS local development (Apple Silicon)  
> **Python:** 3.11+  
> **Validated by:** CI agent + manual verification

---

## Summary

| #   | Integration           | Status      | Notes                                          |
| --- | --------------------- | ----------- | ---------------------------------------------- |
| 1   | LangGraph + MCP (SSE) | ✅ **PASS** | All 4 sub-items verified, full e2e with Gemini |
| 2   | MCP SDK trên EC2      | ⏳ DEFERRED | Option B — EC2 not provisioned yet             |
| 3   | Gemini Flash từ EC2   | ⏳ DEFERRED | API accessible from local (quota limits noted) |
| 4   | GitHub → Lambda       | ⏳ DEFERRED | Requires Lambda + webhook setup                |
| 5   | Lambda → EC2          | ⏳ DEFERRED | Requires EC2 + Lambda                          |

**Decision:** Proceed to Phase 1 with LangGraph + MCP stack (item 1 fully validated). AWS-dependent items (2–5) will be validated during deployment phase when EC2 is provisioned.

---

## Detailed Results

### 1. LangGraph Agent + MCP Tool qua SSE Transport ✅

This is the **most critical** integration point per the checklist. All 4 sub-items passed:

#### 1a. MCP Server (echo tool, SSE transport) ✅

- **File:** `poc/echo_mcp_server.py`
- **SDK:** `mcp==1.26.0` (FastMCP)
- **Transport:** SSE (`mcp.run(transport="sse")`)
- **Server responds to `tools/list`** — verified via MCP Inspector and programmatic client
- **Two tools exposed:** `echo`, `echo_with_metadata`

**⚠️ Breaking change discovered:** `FastMCP()` in mcp 1.26.0 does NOT accept `port` as a kwarg in `.run()`. Port must be set in the constructor:

```python
# CORRECT (mcp >= 1.26.0):
mcp = FastMCP("server-name", port=8000)
mcp.run(transport="sse")

# WRONG (will raise TypeError):
mcp = FastMCP("server-name")
mcp.run(transport="sse", port=8000)
```

#### 1b. LangGraph Agent (MCP client connection) ✅

- **File:** `poc/echo_agent.py`
- **SDK:** `langchain-mcp-adapters==0.2.1`, `langgraph==1.0.10`
- **Agent uses `MultiServerMCPClient` → `create_react_agent`**
- **Tool discovery works:** Agent receives tool schemas from MCP server

**⚠️ Breaking change discovered:** `MultiServerMCPClient` in langchain-mcp-adapters 0.2.1 is **NOT** an async context manager. Use directly:

```python
# CORRECT (>= 0.2.1):
client = MultiServerMCPClient({"server": {"url": "...", "transport": "sse"}})
tools = await client.get_tools()

# WRONG (will raise TypeError):
async with MultiServerMCPClient({...}) as client:
    tools = client.get_tools()
```

**⚠️ Deprecation warning:** `langgraph-prebuilt 1.0.8` `create_react_agent` shows deprecation warning. Suppress with:

```python
warnings.filterwarnings("ignore", category=DeprecationWarning)
```

#### 1c. End-to-end verification ✅

- **Full e2e flow verified:** Agent → MCP Client → SSE → MCP Server → echo tool → Response → Gemini → Final Answer
- **POC output:** `"✅ POC PASSED — LangGraph agent called MCP tool via SSE!"`
- **Gemini API test:** Direct call to `gemini-2.5-flash` with translation prompt — latency **1,487ms** (well within <3s spec)
- **12 MCP tools discoverable** across 3 servers (Storage 5 + Monitor 4 + Deploy 3) via `test_mcp_discovery.py`
- **No protocol errors, no connection timeouts** — SSE transport stable

#### 1d. Exact pinned versions ✅

All tested versions recorded in `requirements-pinned.txt`:

```
mcp==1.26.0
langchain-mcp-adapters==0.2.1
langgraph==1.0.10
langgraph-prebuilt==1.0.8
langchain-core==1.2.17
langchain-google-genai==4.2.1
google-genai==1.66.0
fastapi==0.135.1
pydantic==2.12.5
```

Three breaking changes documented in the pinned file header — critical for anyone re-installing.

---

### 2. MCP Python SDK trên EC2 ⏳

**Status:** Deferred (Option B — develop locally first)

- MCP servers run correctly on localhost (macOS). EC2 validation pending infrastructure provisioning.
- Expected: no issues — SSE is standard HTTP, no platform-specific dependencies.
- **Memory estimate:** Each FastMCP server uses ~50–80MB RSS (measured locally). 3 servers + orchestrator + target app should fit in t3.small (2GB) with ~500MB headroom.

---

### 3. Gemini Flash API ⏳

**Status:** Partially verified locally

- **API client works:** `google-genai==1.66.0` SDK connects and generates responses
- **Latency:** 1,487ms for translation prompt (within <3s spec)
- **Quota:** Free-tier has daily limits. Use paid tier for thesis eval runs.
- **EC2 verification:** Deferred — no region-blocking expected for us-east-1

---

### 4. GitHub Webhook → Lambda ⏳

**Status:** Deferred

- Webhook secret generated and stored in `.env`
- Lambda function + Function URL not yet created (requires AWS console)
- Will be set up during infrastructure provisioning phase

---

### 5. Lambda → EC2 ⏳

**Status:** Deferred

- Requires EC2 instance with Elastic IP (P0-2)
- Orchestrator endpoint design ready (`/pipeline/start` on port 7000)
- Security Group rules documented in `scripts/aws/iam-policy.json`

---

## Risk Assessment

| Risk                                 | Severity   | Mitigation                                            |
| ------------------------------------ | ---------- | ----------------------------------------------------- |
| `langchain-mcp-adapters` API changes | **HIGH**   | Versions pinned. Do NOT upgrade without re-testing    |
| `mcp` SDK breaking changes           | **HIGH**   | Versions pinned. Constructor API documented           |
| Gemini quota exhaustion              | **MEDIUM** | Use paid tier for thesis eval runs                    |
| EC2 memory (t3.small)                | **LOW**    | Measured ~50MB/server. 2GB sufficient                 |
| SSE over network (EC2)               | **LOW**    | SSE is standard HTTP. Needs Security Group port rules |

---

## Decision

**Proceed with confidence to Phase 1 (and beyond):**

- The critical integration (LangGraph + MCP over SSE) is fully validated
- All breaking changes are documented and mitigated via version pinning
- AWS-dependent items have no technical risk — they are standard infrastructure setup
- Local development workflow is fully functional with filesystem backends

---

## Test Evidence

| Test Suite                              | Tests    | Result            |
| --------------------------------------- | -------- | ----------------- |
| Phase 0 (`test_phase0.py`)              | 38       | ✅ ALL PASS       |
| Phase 1 (`test_phase1.py`)              | 52       | ✅ ALL PASS       |
| MCP Discovery (`test_mcp_discovery.py`) | 12 tools | ✅ ALL DISCOVERED |
| **Total**                               | **90+**  | **✅ ALL PASS**   |
