"""
Eval Orchestrator Agent — LangGraph StateGraph that coordinates the full eval pipeline.

State Graph nodes:
    1. receive_trigger  — parse incoming trigger (webhook payload or manual)
    2. parse_change     — determine change type (prompt/code/config)
    3. check_lock       — concurrent pipeline locking (only 1 run at a time)
    4. prepare_eval     — select test suite, configure parameters
    5. run_eval         — invoke Eval Runner Agent
    6. route_result     — forward results to Decision Layer (Phase 3)

The Orchestrator:
    - Receives triggers from Lambda webhook or manual invocation
    - Prevents concurrent pipeline runs via lock file
    - Delegates actual evaluation to Eval Runner Agent
    - Stores pipeline run metadata for dashboard visibility
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (tmp file + os.replace)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class ChangeType(str, Enum):
    """Change type values from parse_change (str subclass; backward-compatible)."""
    PROMPT = "prompt"
    CODE = "code"
    CONFIG = "config"
    UNKNOWN = "unknown"
    IRRELEVANT = "irrelevant"


# ---------------------------------------------------------------------------
# Lock file for concurrent pipeline prevention
# ---------------------------------------------------------------------------

_LOCK_DIR = Path(
    os.environ.get("STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data"))
)


def _acquire_lock(run_id: str) -> bool:
    """
    Try to acquire pipeline lock. Returns True if acquired.

    Uses atomic file creation (O_CREAT | O_EXCL) to prevent TOCTOU races.
    In production, this would be a DynamoDB conditional write.
    """
    lock_file = _LOCK_DIR / "pipeline.lock"
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)

    # Check for stale lock first
    if lock_file.exists():
        try:
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            lock_time = datetime.fromisoformat(lock_data.get("started_at", ""))
            age_seconds = (
                datetime.now(timezone.utc) - lock_time
            ).total_seconds()
            if age_seconds < 1800:  # 30 minutes
                logger.warning(
                    "Pipeline lock held by run %s (age: %.0fs)",
                    lock_data.get("run_id", "unknown"),
                    age_seconds,
                )
                return False
            else:
                logger.warning(
                    "Stale lock detected (age: %.0fs), removing",
                    age_seconds,
                )
                lock_file.unlink(missing_ok=True)
        except Exception:
            # Corrupt lock file, remove and re-try
            lock_file.unlink(missing_ok=True)

    # Atomic creation — O_CREAT|O_EXCL fails if file already exists
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Another process created the lock between our check and open
        logger.warning("Pipeline lock contention — another run won the race")
        return False

    lock_data = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    try:
        os.write(fd, json.dumps(lock_data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)

    logger.info("Pipeline lock acquired: run_id=%s", run_id)
    return True


def _release_lock(run_id: str) -> None:
    """Release pipeline lock."""
    lock_file = _LOCK_DIR / "pipeline.lock"
    if lock_file.exists():
        try:
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            if lock_data.get("run_id") == run_id:
                lock_file.unlink()
                logger.info("Pipeline lock released: run_id=%s", run_id)
            else:
                logger.warning(
                    "Lock held by different run %s, not releasing",
                    lock_data.get("run_id"),
                )
        except Exception:
            lock_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class OrchestratorState(TypedDict, total=False):
    """State passed between Orchestrator nodes."""
    # Input / trigger
    run_id: str
    trigger_type: str  # "webhook" | "manual"
    webhook_payload: dict[str, Any]
    # After parse_change
    change_type: str  # "prompt" | "code" | "config" | "unknown"
    changed_files: list[str]
    commit_sha: str
    branch: str
    # After check_lock
    lock_acquired: bool
    # After prepare_eval
    version_id: str
    test_suite_path: str
    target_app_url: str
    # After run_eval
    eval_result: dict[str, Any]
    quality_score: float
    # After compare_versions (Phase 3)
    comparison_report: dict[str, Any]
    # After make_decision (Phase 3)
    decision: dict[str, Any]
    # Pipeline metadata
    status: str  # "running" | "completed" | "skipped" | "error"
    started_at: str
    completed_at: str
    errors: list[str]


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def receive_trigger(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 1: Parse incoming trigger and initialize pipeline run.
    """
    run_id = state.get("run_id", str(uuid.uuid4()))
    trigger_type = state.get("trigger_type", "manual")
    started_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Pipeline triggered: run_id=%s, type=%s", run_id, trigger_type
    )

    return {
        "run_id": run_id,
        "trigger_type": trigger_type,
        "started_at": started_at,
        "status": "running",
        "errors": [],
    }


def parse_change(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 2: Determine what changed from the webhook payload.

    For manual triggers, defaults to "config" change type.
    """
    trigger_type = state.get("trigger_type", "manual")
    payload = state.get("webhook_payload", {})

    if trigger_type == "manual":
        return {
            "change_type": ChangeType.CONFIG,
            "changed_files": [],
            "commit_sha": "",
            "branch": "main",
        }

    # Parse GitHub webhook payload
    commits = payload.get("commits", [])
    changed_files: list[str] = []
    for commit in commits:
        changed_files.extend(commit.get("added", []))
        changed_files.extend(commit.get("modified", []))
        changed_files.extend(commit.get("removed", []))

    commit_sha = payload.get("after", "")[:8]
    branch = payload.get("ref", "refs/heads/main").split("/")[-1]

    # Determine change type based on files changed
    change_type: str = ChangeType.UNKNOWN
    has_prompt = any("prompt_template" in f for f in changed_files)
    has_config = any(
        f.startswith("configs/") for f in changed_files
    )
    has_code = any(
        f.startswith("target-app/") for f in changed_files
    )

    if has_prompt:
        change_type = ChangeType.PROMPT
    elif has_code:
        change_type = ChangeType.CODE
    elif has_config:
        change_type = ChangeType.CONFIG

    # Filter: only trigger for relevant changes
    relevant = any(
        f.startswith("configs/")
        or f.startswith("target-app/")
        or f.startswith("eval-datasets/")
        for f in changed_files
    )
    if not relevant and changed_files:
        change_type = ChangeType.IRRELEVANT

    logger.info(
        "Change parsed: type=%s, files=%d, branch=%s, sha=%s",
        change_type,
        len(changed_files),
        branch,
        commit_sha,
    )

    return {
        "change_type": change_type,
        "changed_files": changed_files,
        "commit_sha": commit_sha,
        "branch": branch,
    }


def check_lock(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 3: Try to acquire concurrent pipeline lock.
    """
    run_id = state.get("run_id", "")

    # Skip lock check for irrelevant changes
    if state.get("change_type") == "irrelevant":
        return {"lock_acquired": False, "status": "skipped"}

    acquired = _acquire_lock(run_id)
    if not acquired:
        logger.warning("Pipeline skipped: another run is in progress")
        return {"lock_acquired": False, "status": "skipped"}

    return {"lock_acquired": True}


def prepare_eval(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 4: Select test suite and configure eval parameters.
    """
    change_type = state.get("change_type", "config")
    errors = list(state.get("errors", []))

    # Default test suite — baseline_v1.json for all change types
    test_suite_path = str(_PROJECT_ROOT / "eval-datasets" / "baseline_v1.json")

    # Load target app URL from config
    config_path = os.environ.get(
        "APP_CONFIG", str(_PROJECT_ROOT / "configs" / "local.json")
    )
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        # Eval runs against staging (port 9001)
        target_app_url = config.get("target_app", {}).get(
            "staging_url", "http://localhost:9001"
        )
    except Exception as exc:
        errors.append(f"Config load error: {exc}")
        target_app_url = "http://localhost:9001"

    # Version ID — use commit sha or generate one
    version_id = state.get("commit_sha", "") or str(uuid.uuid4())[:8]

    logger.info(
        "Eval prepared: change=%s, suite=%s, target=%s",
        change_type,
        Path(test_suite_path).name,
        target_app_url,
    )

    return {
        "version_id": version_id,
        "test_suite_path": test_suite_path,
        "target_app_url": target_app_url,
        "errors": errors,
    }


def run_eval_node(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 5: Invoke the Eval Runner Agent.
    """
    from agents.eval_runner.agent import run_eval

    run_id = state.get("run_id", "")
    version_id = state.get("version_id", "")
    test_suite_path = state.get("test_suite_path", "")
    target_app_url = state.get("target_app_url", "")
    errors = list(state.get("errors", []))

    try:
        eval_result = run_eval(
            version_id=version_id,
            test_suite_path=test_suite_path,
            target_app_url=target_app_url,
            run_id=run_id,
        )

        quality_score = eval_result.get("quality_score", {}).get(
            "quality_score", 0.0
        )

        logger.info(
            "Eval completed: run_id=%s, score=%.3f", run_id, quality_score
        )

        return {
            "eval_result": eval_result,
            "quality_score": quality_score,
            "errors": errors + eval_result.get("errors", []),
        }
    except Exception as exc:
        errors.append(f"Eval runner failed: {exc}")
        logger.error("Eval runner failed: %s", exc)
        return {
            "eval_result": {},
            "quality_score": 0.0,
            "status": "error",
            "errors": errors,
        }


def compare_versions_node(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 6: Run Version Comparator Agent — compare v_new vs v_current.

    Fetches the most recent eval result for v_current from storage,
    then compares it against the just-evaluated v_new.
    """
    from agents.comparator.agent import compare_versions

    run_id = state.get("run_id", "")
    version_id = state.get("version_id", "")
    eval_result = state.get("eval_result", {})
    errors = list(state.get("errors", []))

    # Build v_new scores from eval_result.
    # quality_score in EvalRunnerState is a nested dict
    # {quality_score: float, breakdown: {dim: {score, weight, raw_value}}, ...}
    qs_dict = eval_result.get("quality_score", {})
    if isinstance(qs_dict, dict):
        v_new_quality_score = qs_dict.get("quality_score", state.get("quality_score", 0.0))
        v_new_breakdown = qs_dict.get("breakdown", {})
    else:
        v_new_quality_score = float(qs_dict) if qs_dict else state.get("quality_score", 0.0)
        v_new_breakdown = {}
    v_new_scores: dict[str, Any] = {
        "quality_score": v_new_quality_score,
        "score_breakdown": v_new_breakdown,
    }

    # Get v_current — latest promoted version from storage via MCP client
    v_current_id = ""
    v_current_scores: dict[str, Any] = {}
    try:
        from agents.mcp_client import MCPStorageClient
        client = MCPStorageClient()

        versions = client.list_versions(limit=10, status_filter="promoted")
        if versions:
            v_current_id = versions[0].get("version_id", "")
            results = client.get_eval_results(version_id=v_current_id)
            if results:
                v_current_scores = results[0]
        else:
            # No promoted version — first deployment, treat as big improvement
            logger.info("No current promoted version — first deployment")
            v_current_scores = {"quality_score": 0.0, "score_breakdown": {}}
    except Exception as exc:
        logger.warning("Could not fetch v_current scores: %s", exc)
        v_current_scores = {"quality_score": 0.0, "score_breakdown": {}}

    try:
        report = compare_versions(
            v_new_id=version_id,
            v_current_id=v_current_id,
            v_new_scores=v_new_scores,
            v_current_scores=v_current_scores,
        )
        logger.info(
            "Comparison: verdict=%s, delta=%.3f",
            report.get("verdict", ""),
            report.get("delta", 0.0),
        )
        return {
            "comparison_report": report,
            "errors": errors,
        }
    except Exception as exc:
        errors.append(f"Comparator failed: {exc}")
        logger.error("Comparator failed: %s", exc)
        return {
            "comparison_report": {},
            "errors": errors,
        }


def make_decision_node(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 7: Run Promotion Decision Agent — promote / rollback / escalate.
    """
    from agents.decision.agent import make_decision

    run_id = state.get("run_id", "")
    comparison_report = state.get("comparison_report", {})
    errors = list(state.get("errors", []))

    if not comparison_report:
        logger.warning("No comparison report — skipping decision")
        return {
            "decision": {"decision": "NO_ACTION", "reasoning": "No comparison data"},
            "errors": errors,
        }

    try:
        decision_result = make_decision(
            comparison_report=comparison_report,
            run_id=run_id,
        )
        logger.info(
            "Decision: %s (confidence=%s)",
            decision_result.get("decision", ""),
            decision_result.get("confidence", ""),
        )
        return {
            "decision": decision_result,
            "errors": errors + decision_result.get("errors", []),
        }
    except Exception as exc:
        errors.append(f"Decision agent failed: {exc}")
        logger.error("Decision agent failed: %s", exc)
        return {
            "decision": {"decision": "NO_ACTION", "reasoning": f"Error: {exc}"},
            "errors": errors,
        }


def route_result(state: OrchestratorState) -> dict[str, Any]:
    """
    Node 8: Finalize pipeline run — save metadata and release lock.
    """
    run_id = state.get("run_id", "")
    errors = list(state.get("errors", []))
    completed_at = datetime.now(timezone.utc).isoformat()

    # Release lock
    if state.get("lock_acquired", False):
        _release_lock(run_id)

    # Save pipeline run metadata
    try:
        data_dir = Path(
            os.environ.get("STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data"))
        )
        runs_dir = data_dir / "pipeline-runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        run_record = {
            "run_id": run_id,
            "trigger_type": state.get("trigger_type", "manual"),
            "change_type": state.get("change_type", "unknown"),
            "changed_files": state.get("changed_files", []),
            "commit_sha": state.get("commit_sha", ""),
            "branch": state.get("branch", ""),
            "version_id": state.get("version_id", ""),
            "quality_score": state.get("quality_score", 0.0),
            "comparison_report": state.get("comparison_report", {}),
            "decision": state.get("decision", {}),
            "status": state.get("status", "completed")
            if state.get("status") != "error"
            else "error",
            "started_at": state.get("started_at", ""),
            "completed_at": completed_at,
            "errors": errors,
        }

        # If status wasn't already set to error, mark completed
        if run_record["status"] == "running":
            run_record["status"] = "completed"

        run_path = runs_dir / f"{run_id}.json"
        _atomic_write(
            run_path,
            json.dumps(run_record, indent=2, ensure_ascii=False),
        )
        logger.info("Pipeline run saved: %s", run_path.name)
    except Exception as exc:
        errors.append(f"Failed to save pipeline run: {exc}")
        logger.error("Failed to save pipeline run: %s", exc)

    final_status = state.get("status", "completed")
    if final_status == "running":
        final_status = "completed"

    logger.info(
        "Pipeline %s: run_id=%s, score=%.3f",
        final_status,
        run_id,
        state.get("quality_score", 0.0),
    )

    return {
        "status": final_status,
        "completed_at": completed_at,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_orchestrator_graph():
    """
    Build the Eval Orchestrator LangGraph StateGraph.

    Returns a compiled graph that can be invoked with:
        result = graph.invoke({
            "trigger_type": "manual",  # or "webhook"
            "webhook_payload": {...},  # if webhook
        })
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("receive_trigger", receive_trigger)
    graph.add_node("parse_change", parse_change)
    graph.add_node("check_lock", check_lock)
    graph.add_node("prepare_eval", prepare_eval)
    graph.add_node("run_eval", run_eval_node)
    graph.add_node("compare_versions", compare_versions_node)
    graph.add_node("make_decision", make_decision_node)
    graph.add_node("route_result", route_result)

    # Define edges
    graph.set_entry_point("receive_trigger")
    graph.add_edge("receive_trigger", "parse_change")
    graph.add_edge("parse_change", "check_lock")

    # Conditional: skip eval if lock not acquired or irrelevant change
    def should_run_eval(state: OrchestratorState) -> str:
        if not state.get("lock_acquired", False):
            return "route_result"  # skip → finalize
        return "prepare_eval"

    graph.add_conditional_edges(
        "check_lock",
        should_run_eval,
        {"prepare_eval": "prepare_eval", "route_result": "route_result"},
    )

    graph.add_edge("prepare_eval", "run_eval")

    # After eval: compare versions, then decide, then finalize
    # If eval errored, skip comparison/decision and go straight to finalize
    def should_compare(state: OrchestratorState) -> str:
        if state.get("status") == "error":
            return "route_result"
        return "compare_versions"

    graph.add_conditional_edges(
        "run_eval",
        should_compare,
        {"compare_versions": "compare_versions", "route_result": "route_result"},
    )

    graph.add_edge("compare_versions", "make_decision")
    graph.add_edge("make_decision", "route_result")
    graph.add_edge("route_result", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

# Module-level compiled graph — built once on first call.
_ORCHESTRATOR_GRAPH: Any = None


def run_pipeline(
    trigger_type: str = "manual",
    webhook_payload: dict[str, Any] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """
    Run the full orchestrator pipeline synchronously.

    Args:
        trigger_type: "manual" or "webhook".
        webhook_payload: GitHub webhook payload (for webhook triggers).
        run_id: Optional custom run ID.

    Returns:
        Final state dict with quality_score, status, etc.
    """
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_PROJECT_ROOT / ".env")

    # Configure LangSmith tracing
    from agents.tracing import configure_tracing, get_graph_config
    configure_tracing()

    if not run_id:
        run_id = str(uuid.uuid4())

    global _ORCHESTRATOR_GRAPH
    if _ORCHESTRATOR_GRAPH is None:
        _ORCHESTRATOR_GRAPH = build_orchestrator_graph()

    initial_state: OrchestratorState = {
        "run_id": run_id,
        "trigger_type": trigger_type,
        "webhook_payload": webhook_payload or {},
    }

    # Build LangSmith tracing config
    trace_config = get_graph_config(
        run_name=f"orchestrator-{run_id[:8]}",
        tags=["orchestrator", trigger_type],
        metadata={
            "run_id": run_id,
            "trigger_type": trigger_type,
        },
    )

    logger.info("Orchestrator starting: run_id=%s, type=%s", run_id, trigger_type)
    start = time.perf_counter()
    try:
        result = _ORCHESTRATOR_GRAPH.invoke(initial_state, config=trace_config)
    except Exception:
        # Ensure lock is always released even on unhandled errors
        _release_lock(run_id)
        raise
    elapsed = time.perf_counter() - start

    logger.info(
        "Orchestrator finished in %.1fs: status=%s, score=%.3f",
        elapsed,
        result.get("status", "unknown"),
        result.get("quality_score", 0.0),
    )
    return result


# ---------------------------------------------------------------------------
# FastAPI endpoint for Lambda/webhook triggers
# ---------------------------------------------------------------------------


def create_orchestrator_app():
    """
    Create a FastAPI app that serves as the orchestrator HTTP endpoint.

    Lambda function calls POST /trigger with the webhook payload.
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="AgentOps Eval Orchestrator")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestrator"}

    @app.post("/trigger")
    async def trigger(request: Request):
        """Receive trigger from Lambda or manual invocation."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        trigger_type = "webhook" if payload.get("commits") else "manual"

        # Run pipeline (blocking — could be made async in production)
        import asyncio
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: run_pipeline(
                trigger_type=trigger_type,
                webhook_payload=payload,
            ),
        )

        return JSONResponse(
            content={
                "run_id": result.get("run_id", ""),
                "status": result.get("status", "unknown"),
                "quality_score": result.get("quality_score", 0.0),
            },
            status_code=200 if result.get("status") != "error" else 500,
        )

    return app


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_PROJECT_ROOT / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="Run eval orchestrator")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start as HTTP server (for Lambda triggers)",
    )
    parser.add_argument(
        "--port", type=int, default=7000, help="HTTP server port (default: 7000)"
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        default=True,
        help="Run a manual eval pipeline (default)",
    )
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        app = create_orchestrator_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        result = run_pipeline(trigger_type="manual")
        print("\n" + "=" * 60)
        print("ORCHESTRATOR PIPELINE RESULT")
        print("=" * 60)
        print(f"  Run ID:        {result.get('run_id', 'N/A')}")
        print(f"  Status:        {result.get('status', 'unknown')}")
        print(f"  Quality Score: {result.get('quality_score', 0.0):.3f}")
        print(f"  Change Type:   {result.get('change_type', 'N/A')}")
        print(f"  Started:       {result.get('started_at', 'N/A')}")
        print(f"  Completed:     {result.get('completed_at', 'N/A')}")
        if result.get("errors"):
            print(f"  Warnings:      {len(result['errors'])}")
            for err in result["errors"][:5]:
                print(f"    - {err}")
        print("=" * 60)
