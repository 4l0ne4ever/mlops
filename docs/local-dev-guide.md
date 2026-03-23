# Local Development Guide

> **Mục đích:** Hướng dẫn chạy từng component locally trên máy dev mà không cần EC2. Phát triển và debug local trước, test xong mới deploy lên EC2.

---

## Prerequisites

| Tool    | Version | Cài đặt                    |
| ------- | ------- | -------------------------- |
| Python  | 3.11+   | `brew install python@3.11` |
| Node.js | 18+     | `brew install node`        |
| AWS CLI | 2.x     | `brew install awscli`      |
| Git     | latest  | `brew install git`         |

**AWS Credentials (local dev):**

```bash
# Dùng credentials từ IAM user (Phase 0)
aws configure
# Hoặc set environment variables:
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
export AWS_DEFAULT_REGION=us-east-1
```

**API Keys:**

```bash
export GEMINI_API_KEY=xxx
# Copy từ .env.example và fill vào .env
cp .env.example .env
```

---

## Repo Structure & Venvs

```bash
# Clone repo
git clone <repo-url>
cd agentops-platform

# Tạo venv cho mỗi service
python3.11 -m venv target-app/venv
python3.11 -m venv mcp-servers/storage/venv
python3.11 -m venv mcp-servers/monitor/venv
python3.11 -m venv mcp-servers/deploy/venv
python3.11 -m venv agents/orchestrator/venv

# Install dependencies cho mỗi service
source target-app/venv/bin/activate && pip install -r target-app/requirements.txt && deactivate
source mcp-servers/storage/venv/bin/activate && pip install -r mcp-servers/storage/requirements.txt && deactivate
# ... tương tự cho các services khác
```

> **Shortcut:** Dùng `scripts/setup-local.sh` (sẽ tạo ở Phase 0) để tự động tạo tất cả venvs + install deps.

---

## Chạy Từng Component

### 1. Target App (Translation Agent)

```bash
cd target-app
source venv/bin/activate
uvicorn app:app --port 9000 --reload

# Test:
curl -X POST http://localhost:9000/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world!", "source_lang": "en", "target_lang": "vi"}'

# Health check:
curl http://localhost:9000/health
```

### 2. MCP Server: Storage

```bash
cd mcp-servers/storage
source venv/bin/activate

# Chạy MCP server (port được set trong server.py hoặc qua env var)
# MCP Python SDK KHÔNG có CLI flags --transport hay --port
# Transport và port được config trong code (mcp.run(transport="streamable-http")) hoặc uvicorn
python server.py
# Hoặc: uvicorn server:app --port 8000

# Server sẽ expose MCP endpoint tại: http://localhost:8000/mcp
# Verify endpoint exists:
curl -i http://localhost:8000/mcp
```

### 3. MCP Server: Monitor

```bash
cd mcp-servers/monitor
source venv/bin/activate
python server.py
# Hoặc: uvicorn server:app --port 8001
# MCP endpoint: http://localhost:8001/mcp
```

### 4. MCP Server: Deploy

```bash
cd mcp-servers/deploy
source venv/bin/activate
python server.py
# Hoặc: uvicorn server:app --port 8002
# MCP endpoint: http://localhost:8002/mcp
```

> **Lưu ý:** Deploy server ở local sẽ trỏ đến **local target app** (localhost:9000) thay vì EC2. Config endpoint trong `.env` hoặc `configs/local.json`.

### 5. Orchestrator Agent

```bash
cd agents/orchestrator
source venv/bin/activate

# Set LangSmith tracing (recommended cho debugging):
export LANGSMITH_API_KEY=xxx
export LANGSMITH_TRACING=true
export LANGSMITH_PROJECT=agentops-local

python server.py
# Hoặc: uvicorn server:app --port 7000
```

### 6. Dashboard

```bash
cd dashboard
npm install
npm run dev
# → http://localhost:3000
```

> **Lưu ý:** Dashboard local hiện đọc data qua MCP servers và `APP_CONFIG`, không cần AWS credentials trực tiếp nếu bạn đang dùng local backends:
>
> ```bash
> # dashboard/.env.local
> MCP_STORAGE_URL=http://127.0.0.1:8000
> MCP_MONITOR_URL=http://127.0.0.1:8001
> MCP_DEPLOY_URL=http://127.0.0.1:8002
> APP_CONFIG=configs/local.json
> ```
>
> Dashboard sẽ dùng target app URLs từ `configs/local.json` để check production/staging health.

---

## Chạy Tất Cả Services Cùng Lúc

Dùng **Honcho** hoặc **tmux** để quản lý multiple processes:

**Option A: Procfile (dùng honcho)**

```bash
# Install honcho
pip install honcho

# Tạo Procfile:
cat > Procfile << 'EOF'
target:    bash -c "cd target-app && . venv/bin/activate && uvicorn app:app --port 9000"
storage:   bash -c "cd mcp-servers/storage && . venv/bin/activate && python server.py"
monitor:   bash -c "cd mcp-servers/monitor && . venv/bin/activate && python server.py"
deploy:    bash -c "cd mcp-servers/deploy && . venv/bin/activate && python server.py"
orch:      bash -c "cd agents/orchestrator && . venv/bin/activate && python server.py"
dashboard: bash -c "cd dashboard && npm run dev"
EOF

honcho start
```

> **Lưu ý:** Dùng `.` thay cho `source` — POSIX compliant, chạy được trên mọi shell.

**Option B: tmux script**

```bash
# scripts/start-local.sh
tmux new-session -d -s agentops
tmux send-keys -t agentops "cd target-app && . venv/bin/activate && uvicorn app:app --port 9000" C-m
tmux split-window -h
tmux send-keys "cd mcp-servers/storage && . venv/bin/activate && python server.py" C-m
# ... thêm panes cho các services khác
tmux attach -t agentops
```

---

## Local vs EC2: Sự Khác Biệt

| Aspect          | Local                      | EC2                                    |
| --------------- | -------------------------- | -------------------------------------- |
| Endpoints       | `localhost:{port}`         | `{elastic-ip}:{port}` hoặc nginx proxy |
| AWS Access      | IAM user credentials       | IAM Instance Role                      |
| Process Manager | honcho / tmux              | systemd                                |
| Config file     | `configs/local.json`       | `configs/production.json`              |
| Dashboard       | `npm run dev` (hot reload) | `npm start` (production build)         |
| MCP transport   | streamable-http            | streamable-http                        |

**Config switching:**

```bash
# Local
export APP_CONFIG=configs/local.json

# EC2
export APP_CONFIG=configs/production.json
```

---

## Debugging Tips

### LangSmith Tracing (Bắt buộc)

- Tất cả LangGraph agent calls đều nên trace
- Xem traces tại: https://smith.langchain.com
- Giúp debug: tool gọi sai, output format sai, agent loop vô hạn

### MCP Endpoint Smoke Test

- Dùng `initialize` để test MCP servers độc lập (không cần agent):
  ```bash
  curl -X POST http://localhost:8000/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{
      "jsonrpc": "2.0",
      "id": 1,
      "method": "initialize",
      "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "0.1.0"}
      }
    }'
  ```
- Expect `HTTP 200` and an `mcp-session-id` header in the response.

### Mock Lambda Trigger (Local Testing)

Khi develop Orchestrator (Phase 2), cần test trigger mà không cần push lên GitHub mỗi lần:

```bash
# Simulate GitHub webhook trigger locally
curl -X POST http://localhost:7000/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{
    "trigger_id": "test-001",
    "repo": "agentops-platform",
    "branch": "main",
    "commit_sha": "abc123",
    "changed_files": ["configs/prompt_template.json"],
    "change_type": "prompt_change",
    "timestamp": "2026-04-15T10:30:00Z",
    "author": "thuyet"
  }'
```

> Payload format giống hệt Change Summary từ Lambda → Orchestrator (xem `system_architecture_design.md` section 2.1).

### Mock AWS (cho unit tests)

- Dùng `moto` library để mock S3, DynamoDB, CloudWatch
- Không tốn AWS cost khi chạy tests local

### Port Conflicts

- Nếu port đã bị chiếm: `lsof -i :{port}` → `kill -9 {pid}`
- Hoặc đổi port trong `server.py` hoặc uvicorn command

---

## Workflow Phát Triển Khuyến Nghị

```
1. Develop local → test local → verify trên LangSmith
2. Push lên GitHub → GitHub Actions lint check (optional)
3. SSH vào EC2 → git pull → restart services
4. Verify trên EC2 → push thêm nếu cần fix
```

> **Không bao giờ** develop trực tiếp trên EC2. EC2 là production-like environment, chỉ dùng để deploy và verify final.
