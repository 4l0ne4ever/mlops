# POC Spike Checklist — Tech Stack Validation

> **Mục đích:** Validate tất cả integration points trước khi commit vào Phase 1. Phát hiện sớm rủi ro kỹ thuật, tránh surprise ở tuần 6.  
> **Timeline:** 2–3 ngày (cuối Phase 0, sau khi EC2 + target app sẵn sàng)  
> **Nguyên tắc:** Mỗi item test **một integration duy nhất**. Nếu fail → biết chính xác điểm nào cần fallback.

---

## Checklist

### 1. LangGraph Agent + MCP Tool qua SSE Transport ⚡ (Quan trọng nhất)

**Mục tiêu:** Chứng minh LangGraph agent có thể discover và gọi MCP tool qua SSE.

**Bước thực hiện:**

- [ ] **1a.** Tạo MCP server đơn giản (1 tool: `echo` — nhận text, trả lại text đó)
  - Dùng `mcp` Python SDK (`FastMCP`), chạy SSE transport
  - Server code: `mcp.run(transport="sse")`, chạy qua `python server.py` hoặc `uvicorn`
  - Server phải trả về tool schema khi client gọi `tools/list`
- [ ] **1b.** Tạo LangGraph agent đơn giản (1 node gọi MCP tool)
  - Dùng `langchain-mcp-adapters` để kết nối
  - Agent gọi `echo` tool, verify output = input
- [ ] **1c.** Verify end-to-end: Agent → MCP Client → SSE → MCP Server → Tool → Response
- [ ] **1d.** ⚠️ **Ghi lại exact versions đã test thành công:**
  ```
  mcp==X.X.X
  langchain-mcp-adapters==X.X.X
  langgraph==X.X.X
  langchain-core==X.X.X
  ```
  - Tạo `requirements-pinned.txt` ngay sau khi POC pass
  - `langchain-mcp-adapters` đang thay đổi rất nhanh (0.0.x → 0.2.x trong vài tháng), breaking changes xảy ra thường xuyên
  - **Nếu không pin:** Phase 1 install version mới → break → mất 1–2 ngày debug

**Pass criteria:**
- [ ] Agent nhận được tool schema từ MCP server
- [ ] Agent gọi tool thành công và nhận response đúng
- [ ] Không có connection timeout hoặc protocol error
- [ ] `requirements-pinned.txt` created với exact versions

**Nếu FAIL:**
- Check version compatibility: `langchain-mcp-adapters` vs `langgraph` vs `mcp` SDK
- Thử upgrade/downgrade versions
- **Fallback cuối cùng:** giữ MCP server nhưng gọi qua HTTP REST thay vì MCP protocol (mất điểm MCP contribution nhưng vẫn hoạt động)

---

### 2. MCP Python SDK trên EC2

**Mục tiêu:** Verify MCP server chạy được trên EC2 (không chỉ local).

- [ ] **2a.** SSH vào EC2, tạo venv, install `mcp` SDK
- [ ] **2b.** Chạy echo MCP server từ mục 1a trên EC2
- [ ] **2c.** Từ local machine, dùng MCP client kết nối đến EC2 MCP server (qua Elastic IP)
- [ ] **2d.** Verify tool discovery + tool call hoạt động qua network

**Pass criteria:**
- [ ] MCP server chạy ổn định trên EC2 > 30 phút không crash
- [ ] Memory usage < 200MB cho 1 MCP server
- [ ] Response time < 500ms cho tool call (excluding network latency)

**Nếu FAIL:**
- Check memory: `free -h` → nếu thiếu RAM, confirm t3.small đủ
- Check firewall: Security Group cho phép port 8000

---

### 3. Gemini Flash API từ EC2

**Mục tiêu:** Verify Gemini API accessible và latency chấp nhận được từ EC2.

- [ ] **3a.** Setup Gemini API key trên EC2 (environment variable)
- [ ] **3b.** Gọi Gemini Flash API từ EC2 — simple prompt test
- [ ] **3c.** Đo latency: gửi 10 requests, tính average response time

**Pass criteria:**
- [ ] API trả về response thành công (không bị region block)
- [ ] Average latency < 3 giây (cho simple prompt)
- [ ] Không có rate limiting issues ở tần suất test (1 req/giây)

**Nếu FAIL:**
- Thử region khác cho EC2 (us-east-1 thường tốt nhất cho API calls)
- Kiểm tra API key quotas

---

### 4. GitHub Webhook → AWS Lambda

**Mục tiêu:** Verify webhook delivery chain hoạt động.

- [ ] **4a.** Tạo Lambda function đơn giản (log payload, return 200)
- [ ] **4b.** Bật **Lambda Function URL** trong console (đơn giản hơn API Gateway, miễn phí)
  - Không cần API Gateway — Lambda Function URL ra mắt 2022, built-in, zero config
  - API Gateway tốn thêm ~$3.50/million requests và cần config thêm
- [ ] **4c.** Configure GitHub webhook trỏ đến Lambda Function URL
- [ ] **4d.** Push commit → verify Lambda nhận được payload

**Pass criteria:**
- [ ] Lambda triggered trong < 5 giây sau push
- [ ] Payload chứa đầy đủ info: changed files, commit SHA, author
- [ ] Webhook signature validation hoạt động

**Nếu FAIL:**
- Check Lambda Function URL đã enabled (Auth type = NONE cho testing, IAM cho production)
- Check Lambda execution role permissions

---

### 5. Lambda → EC2 Orchestrator Endpoint

**Mục tiêu:** Verify Lambda gọi được EC2 qua Elastic IP.

- [ ] **5a.** Tạo simple HTTP endpoint trên EC2 (FastAPI, port 7000, endpoint `/pipeline/start`)
- [ ] **5b.** Từ Lambda, gửi HTTP POST đến `http://{elastic-ip}:7000/pipeline/start`
- [ ] **5c.** Verify EC2 nhận được request từ Lambda

**Pass criteria:**
- [ ] Lambda → EC2 HTTP call thành công
- [ ] Response time < 2 giây (Lambda → EC2)
- [ ] EC2 Security Group đúng (cho phép inbound từ Lambda IP range)

**Nếu FAIL:**
- Check Security Group inbound rules
- Check Elastic IP đúng
- Xem xét dùng VPC endpoint nếu cần (phức tạp hơn nhưng reliable)

---

## Tổng Kết POC

| # | Integration | Status | Notes |
|---|------------|--------|-------|
| 1 | LangGraph + MCP (SSE) | ⬜ | Quan trọng nhất |
| 2 | MCP SDK trên EC2 | ⬜ | |
| 3 | Gemini Flash từ EC2 | ⬜ | |
| 4 | GitHub → Lambda | ⬜ | |
| 5 | Lambda → EC2 | ⬜ | |

**Quyết định sau POC:**
- ✅ Nếu tất cả pass → proceed avec confidence sang Phase 1
- ⚠️ Nếu item 1 fail → fallback sang REST calls, document lý do trong thesis
- 🔴 Nếu item 2 hoặc 3 fail → xem xét lại infrastructure choice (có thể cần khác EC2)
