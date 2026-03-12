"""
AgentOps — GitHub Webhook Lambda Handler.

Receives GitHub push events and triggers the orchestrator pipeline on EC2.

Deployment:
    1. Zip this file: zip lambda.zip lambda_handler.py
    2. Upload to Lambda (runtime: python3.11)
    3. Set environment variables:
       - EC2_ENDPOINT: http://<elastic-ip>:7000
       - GITHUB_WEBHOOK_SECRET: <same as in GitHub webhook settings>
    4. Enable Lambda Function URL (auth type: NONE for testing)
    5. Set GitHub webhook URL to the Lambda Function URL

Architecture:
    GitHub Push → Webhook → Lambda Function URL → This handler → HTTP POST → EC2 Orchestrator
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.request
import urllib.error
from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle GitHub webhook events delivered via Lambda Function URL."""

    # --- Extract request info ---
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body", "")
    is_base64 = event.get("isBase64Encoded", False)

    if is_base64:
        import base64
        body = base64.b64decode(body).decode("utf-8")

    github_event = headers.get("x-github-event", "unknown")
    delivery_id = headers.get("x-github-delivery", "unknown")

    print(f"[AgentOps] Received event: {github_event}, delivery: {delivery_id}")

    # --- Verify webhook signature ---
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        signature = headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(
            secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            print("[AgentOps] ❌ Signature verification failed")
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid signature"}),
            }
        print("[AgentOps] ✅ Signature verified")
    else:
        print("[AgentOps] ⚠️ No webhook secret configured — skipping verification")

    # --- Only process push events ---
    if github_event == "ping":
        print("[AgentOps] Ping event — responding OK")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "pong", "delivery_id": delivery_id}),
        }

    if github_event != "push":
        print(f"[AgentOps] Ignoring event type: {github_event}")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": f"Ignored event: {github_event}"}),
        }

    # --- Parse push payload ---
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON payload"}),
        }

    ref = payload.get("ref", "")
    commit_sha = payload.get("after", "")[:7]
    pusher = payload.get("pusher", {}).get("name", "unknown")
    commit_msg = (payload.get("head_commit") or {}).get("message", "")[:100]

    # Get list of changed files
    changed_files: list[str] = []
    for commit in payload.get("commits", []):
        changed_files.extend(commit.get("added", []))
        changed_files.extend(commit.get("modified", []))
        changed_files.extend(commit.get("removed", []))
    changed_files = list(set(changed_files))

    print(f"[AgentOps] Push to {ref} by {pusher} ({commit_sha})")
    print(f"[AgentOps] Message: {commit_msg}")
    print(f"[AgentOps] Changed files: {len(changed_files)}")

    # --- Check if relevant files changed ---
    # Only trigger pipeline for config/prompt/model changes
    relevant_patterns = [
        "configs/prompt_template",
        "configs/model_config",
        "target-app/",
        "eval-datasets/",
    ]
    relevant_changes = [
        f for f in changed_files
        if any(f.startswith(p) for p in relevant_patterns)
    ]

    if not relevant_changes:
        print(f"[AgentOps] No relevant file changes — skipping pipeline trigger")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "No relevant changes detected",
                "changed_files": changed_files,
            }),
        }

    # --- Trigger EC2 orchestrator ---
    ec2_endpoint = os.environ.get("EC2_ENDPOINT", "http://localhost:7000")
    trigger_url = f"{ec2_endpoint}/trigger"

    # Send the full GitHub webhook payload so the orchestrator can parse changes
    trigger_payload = json.dumps(payload).encode("utf-8")

    print(f"[AgentOps] Triggering pipeline at {trigger_url}")

    try:
        req = urllib.request.Request(
            trigger_url,
            data=trigger_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8")
            print(f"[AgentOps] ✅ Pipeline triggered: {resp.status}")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Pipeline triggered",
                    "ec2_response": json.loads(response_body) if response_body else {},
                    "commit_sha": commit_sha,
                    "changed_files": relevant_changes,
                }),
            }
    except urllib.error.URLError as exc:
        print(f"[AgentOps] ❌ Failed to trigger pipeline: {exc}")
        return {
            "statusCode": 502,
            "body": json.dumps({
                "error": f"Failed to reach EC2: {exc}",
                "endpoint": trigger_url,
            }),
        }
    except Exception as exc:
        print(f"[AgentOps] ❌ Unexpected error: {exc}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }
