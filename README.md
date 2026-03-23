# AgentOps Platform

Agentic MLOps platform for LLM application lifecycle management: evaluation orchestration, quality scoring (LLM-as-judge), comparison and decision agents, and MCP-backed storage, monitor, and deploy.

## Install

```bash
pip install -e .
# Or from sdist: pip install agentops-platform-*.tar.gz
```

Requires Python 3.11+. See `requirements.txt` for runtime dependencies.

## Run (development)

- **Target app:** `cd target-app && uvicorn app:app --port 9000`
- **MCP servers:** `python mcp-servers/storage/server.py` (8000), `monitor` (8001), `deploy` (8002)
- **Orchestrator:** `python -m agents.orchestrator.agent --serve --port 7000`
- **Dashboard:** `cd dashboard && npm run dev`

Set `APP_CONFIG`, `GEMINI_API_KEY`, and MCP URLs as needed. See `docs/` for architecture and setup.

**Secrets:** Use `.env` for local secrets (see `.env.example`). Never commit `.env`; it is gitignored. If this workspace is ever shared or packaged, rotate all keys (AWS, Gemini, LangSmith, webhooks, reload key).
