"""
POC Spike — LangGraph Agent connecting to MCP Server via SSE.

Validates the critical integration: LangGraph → langchain-mcp-adapters → MCP Server (SSE).

Usage:
    1. Start echo MCP server in terminal 1:
       python poc/echo_mcp_server.py

    2. Run this agent in terminal 2:
       python poc/echo_agent.py

Expected output:
    - Agent discovers echo tools from MCP server
    - Agent calls echo tool with test message
    - Agent receives correct response
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()


async def run_poc():
    """Run the POC spike agent with MCP tool integration."""

    # Dynamic imports — check if dependencies are installed
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langgraph.prebuilt import create_react_agent
    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}")
        print("Install: pip install langchain-mcp-adapters langgraph")
        sys.exit(1)

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        print("ERROR: Missing langchain-google-genai")
        print("Install: pip install langchain-google-genai")
        sys.exit(1)

    # --- Configuration — load from config files, allow env var overrides ---
    import json as _json
    _root = Path(__file__).resolve().parent.parent

    _model_config = _json.loads((_root / "configs" / "model_config.json").read_text(encoding="utf-8"))
    _local_config = _json.loads((_root / "configs" / "local.json").read_text(encoding="utf-8"))

    MODEL_NAME = os.environ.get("GEMINI_MODEL") or _model_config["model_name"]
    MCP_SERVER_URL = os.environ.get("MCP_ECHO_URL") or _local_config["mcp_servers"]["storage"]
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print("POC Spike — LangGraph + MCP (SSE) Integration")
    print("=" * 60)
    print(f"  MCP Server: {MCP_SERVER_URL}")
    print(f"  Model:      {MODEL_NAME}")
    print()

    # --- Step 1: Connect to MCP server via SSE ---
    print("[1/4] Connecting to MCP server via SSE...")

    client = MultiServerMCPClient(
        {
            "echo-server": {
                "url": MCP_SERVER_URL,
                "transport": "sse",
            }
        }
    )
    if True:
        # --- Step 2: Discover tools ---
        print("[2/4] Discovering tools...")
        tools = await client.get_tools()

        if not tools:
            print("  FAIL: No tools discovered!")
            sys.exit(1)

        print(f"  Found {len(tools)} tool(s):")
        for tool in tools:
            print(f"    - {tool.name}: {tool.description[:80]}")

        # --- Step 3: Create LangGraph agent with MCP tools ---
        print("[3/4] Creating LangGraph agent with MCP tools...")

        llm = ChatGoogleGenerativeAI(
            model=MODEL_NAME,
            google_api_key=GEMINI_API_KEY,
            temperature=0,
        )

        agent = create_react_agent(llm, tools)

        # --- Step 4: Run agent with a test prompt ---
        print("[4/4] Running agent with test prompt...")
        print()

        test_message = "Use the echo tool to echo 'Hello from AgentOps POC!'"
        print(f"  Prompt: {test_message}")
        print()

        result = await agent.ainvoke({"messages": [("user", test_message)]})

        # Extract and display result
        messages = result.get("messages", [])
        print("  Agent messages:")
        for msg in messages:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", str(msg))
            if isinstance(content, list):
                content = str(content)
            preview = content[:200] if isinstance(content, str) else str(content)[:200]
            print(f"    [{role}] {preview}")

        # --- Validation ---
        print()
        print("=" * 60)

        # Check if echo tool was called
        tool_calls_found = any(
            getattr(msg, "type", "") == "tool" for msg in messages
        )

        if tool_calls_found:
            print("✅ POC PASSED — LangGraph agent called MCP tool via SSE!")
        else:
            print("⚠️  POC WARNING — Agent responded but may not have used the tool")
            print("     Check messages above for tool call evidence")

        print("=" * 60)

        # --- Print versions for pinning ---
        print()
        print("Installed versions (PIN THESE in requirements-pinned.txt):")
        import importlib.metadata as meta

        for pkg in ["mcp", "langchain-mcp-adapters", "langgraph", "langchain-core",
                     "langchain-google-genai"]:
            try:
                ver = meta.version(pkg)
                print(f"  {pkg}=={ver}")
            except meta.PackageNotFoundError:
                print(f"  {pkg}: NOT INSTALLED")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    asyncio.run(run_poc())
