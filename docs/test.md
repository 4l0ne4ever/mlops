# AgentOps Testing Guide

## Tổng quan

Project có 3 tầng test, làm theo thứ tự từ dưới lên:

```
Tầng 3 — Manual / E2E      chạy toàn bộ hệ thống thật
Tầng 2 — Integration       test pipeline, mock external services
Tầng 1 — Unit              test từng function, không cần server
```

Quy tắc: **không có unit tests thì đừng làm integration tests**.

---

## Tầng 1 — Unit Tests

### Mục đích

Test từng function độc lập. Không cần chạy server, không cần AWS, không cần Gemini API. Chạy trong vài giây.

### Cấu trúc thư mục

```
tests/
└── unit/
    ├── test_quality_score.py
    ├── test_evaluator.py
    ├── test_audit_logger.py
    └── test_settings.py
```

---

### `test_quality_score.py`

Đây là file quan trọng nhất — `quality_score.py` là core logic của toàn bộ hệ thống, mọi quyết định deploy/rollback đều phụ thuộc vào nó.

**Các test cần có:**

| Test                              | Mô tả                                                                          | Tại sao quan trọng                          |
| --------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| `test_perfect_score`              | 10 test cases đều score 10, latency thấp, cost thấp → Quality Score phải > 9.0 | Verify happy path                           |
| `test_app_down_score`             | Không có test cases nào chạy được (lists rỗng) → Quality Score phải < 1.0      | Bug đã biết: hiện tại trả về 3.0 thay vì ~0 |
| `test_known_calculation`          | Input cố định → verify output khớp với tính tay từ spec                        | Đảm bảo math không bị drift                 |
| `test_weights_must_sum_to_one`    | Truyền weights tổng ≠ 1.0 → phải raise ValueError                              | Catch config lỗi sớm                        |
| `test_pass_threshold_boundary`    | Score đúng bằng threshold (6.0) → phải tính là pass                            | Boundary condition                          |
| `test_all_cases_fail`             | Tất cả scores = 0 → task completion = 0, output quality = 0                    | Worst case                                  |
| `test_from_config_file`           | Load từ `thresholds.json` → weights và threshold đúng                          | Config loading                              |
| `test_from_config_file_missing`   | File không tồn tại → dùng defaults, không crash                                | Graceful fallback                           |
| `test_skipped_cases_metadata`     | Truyền `skipped_cases=10` → metadata phản ánh đúng                             | Audit accuracy                              |
| `test_warning_insufficient_cases` | Chỉ 20% test cases chạy được → warnings không rỗng                             | Early warning system                        |

---

### `test_evaluator.py`

Test `LLMJudgeEvaluator` **mà không gọi Gemini API thật**. Dùng `pytest-mock` để mock API call.

**Các test cần có:**

| Test                            | Mô tả                                                     | Tại sao quan trọng        |
| ------------------------------- | --------------------------------------------------------- | ------------------------- |
| `test_parse_valid_json`         | JSON hợp lệ từ judge → parse ra đúng fields               | Happy path                |
| `test_parse_json_in_markdown`   | JSON bọc trong `json ... ` → vẫn parse được               | Model hay trả về markdown |
| `test_parse_missing_fields`     | JSON thiếu field `score` → trả về None, không crash       | Defensive parsing         |
| `test_parse_scores_clamped`     | Score = 15 (ngoài range) → bị clamp về 10.0               | Data validation           |
| `test_anomaly_detected`         | Pass 1 = 9.0, Pass 2 = 3.0, delta > 2.0 → `anomaly=True`  | Reliability signal        |
| `test_no_anomaly`               | Pass 1 = 8.0, Pass 2 = 8.5, delta < 2.0 → `anomaly=False` | Normal case               |
| `test_all_passes_fail`          | Mock API luôn raise exception → score=0, `anomaly=True`   | Total failure             |
| `test_average_across_passes`    | Pass 1 = 7.0, Pass 2 = 9.0 → final score = 8.0            | Averaging logic           |
| `test_prompt_variant_selection` | Variant không tồn tại → fallback về default variant A     | Config safety             |

---

### `test_audit_logger.py`

| Test                      | Mô tả                                                       |
| ------------------------- | ----------------------------------------------------------- |
| `test_log_and_read_back`  | Log một record → đọc lại → fields khớp                      |
| `test_filter_by_run_id`   | Log nhiều run_ids → filter chỉ lấy 1 run_id                 |
| `test_daily_rotation`     | Log hôm nay → file tên đúng format `YYYY-MM-DD.jsonl`       |
| `test_get_summary_empty`  | Không có logs → summary trả về `{"total_calls": 0}`         |
| `test_get_summary_stats`  | 10 calls, 8 success → `success_rate=0.8`                    |
| `test_log_failure_silent` | Audit dir không có write permission → không crash app chính |

---

### `test_settings.py`

| Test                   | Mô tả                                                    |
| ---------------------- | -------------------------------------------------------- | ------------------------------ |
| `test_defaults_loaded` | Không có env vars → defaults hợp lý                      |
| `test_env_override`    | Set `GEMINI_API_KEY=test123` → settings phản ánh đúng    |
| `test_paths_absolute`  | Tất cả paths trong settings đều absolute, không relative | Prevent working directory bugs |

---

## Tầng 2 — Integration Tests

### Mục đích

Test pipeline hoạt động đúng end-to-end, nhưng **mock các external services** (Gemini API, AWS). Chạy trong 30–60 giây.

### Cấu trúc thư mục

```
tests/
└── integration/
    ├── test_eval_pipeline.py
    ├── test_mcp_storage.py
    └── test_decision_logic.py
```

### Nguyên tắc mock

```
Thật:    LangGraph graph execution, quality_score.py, audit_logger.py
Mock:    Gemini API, AWS S3/DynamoDB, Target app HTTP endpoint
```

Lý do: muốn test logic orchestration, không muốn phụ thuộc vào network hay credentials.

---

### `test_eval_pipeline.py`

Test toàn bộ flow từ `load_test_suite` → `run_test_cases` → `evaluate_outputs` → `aggregate_results` → `save_results`.

**Các test cần có:**

| Test                        | Setup                                                                       | Kiểm tra                                                                                         |
| --------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `test_happy_path`           | Mock target app trả về translations tốt, mock Gemini judge trả về score 8.0 | Quality Score > 7.0, status = "completed", result_id không rỗng                                  |
| `test_target_app_down`      | Mock target app trả về HTTP 503 cho tất cả requests                         | Tất cả test cases có status "failed", Quality Score < 1.0, pipeline vẫn hoàn thành (không crash) |
| `test_partial_failures`     | 40/50 cases thành công, 10 bị timeout                                       | `completed_test_cases=40`, `skipped=10`, warnings không rỗng                                     |
| `test_judge_api_error`      | Mock Gemini raise exception                                                 | Cases bị judge fail → skipped=True, score=0, pipeline không crash                                |
| `test_empty_test_suite`     | File test suite rỗng (0 cases)                                              | Pipeline exit sớm, status="error", không crash                                                   |
| `test_test_suite_not_found` | Path trỏ đến file không tồn tại                                             | status="error", errors có message rõ ràng                                                        |

---

### `test_mcp_storage.py`

Test MCP Storage client — cả MCP server path lẫn fallback direct file write.

| Test                             | Mô tả                                                              |
| -------------------------------- | ------------------------------------------------------------------ |
| `test_save_and_load_eval_result` | Save result → load lại → data khớp                                 |
| `test_fallback_when_mcp_down`    | MCP server không chạy → fallback về direct file write, không crash |
| `test_load_test_cases_from_file` | File JSON hợp lệ → parse đúng format                               |
| `test_concurrent_saves`          | 5 threads cùng save → không có data corruption                     |

---

### `test_decision_logic.py`

Test Decision Agent logic — đây là thứ quyết định deploy hay rollback.

| Test                     | Delta                                 | Expected Decision                        |
| ------------------------ | ------------------------------------- | ---------------------------------------- |
| `test_auto_promote`      | +0.5 (vượt threshold +0.3)            | AUTO_PROMOTE                             |
| `test_no_action`         | -0.2 (trong range -0.5 đến +0.3)      | NO_ACTION                                |
| `test_escalate`          | -0.7 (dưới -0.5, trên -1.0)           | ESCALATE                                 |
| `test_rollback`          | -1.5 (dưới -1.0)                      | ROLLBACK                                 |
| `test_boundary_promote`  | Đúng bằng +0.3                        | AUTO_PROMOTE (inclusive)                 |
| `test_boundary_rollback` | Đúng bằng -1.0                        | ROLLBACK (inclusive)                     |
| `test_no_baseline`       | Không có version cũ (first run)       | AUTO_PROMOTE (first run always promotes) |
| `test_invalid_score`     | Quality Score = None (pipeline error) | ESCALATE, không crash                    |

---

## Tầng 3 — Manual / E2E Testing

### Mục đích

Verify toàn bộ hệ thống chạy đúng trên môi trường thật. Chạy trước mỗi lần demo hoặc release.

### Checklist E2E

```
□ 1. Khởi động tất cả services (honcho start)
□ 2. Health check tất cả endpoints
□ 3. Chạy eval pipeline thủ công với 5 test cases
□ 4. Verify kết quả xuất hiện trên dashboard
□ 5. Test AUTO_PROMOTE scenario
□ 6. Test ROLLBACK scenario (inject version xấu)
□ 7. Test app-down scenario (tắt target app, chạy eval)
□ 8. Verify audit logs được ghi đúng
```

### Các scenario quan trọng cần test thủ công

**Scenario 1 — Happy path (15 phút)**
Push một prompt change nhỏ → hệ thống tự chạy → AUTO_PROMOTE → dashboard cập nhật.

**Scenario 2 — Regression detection (15 phút)**
Inject một prompt version cố tình xấu → hệ thống phát hiện → ROLLBACK → production untouched → alert được gửi.

**Scenario 3 — App down (10 phút)**
Tắt staging app → chạy eval → verify pipeline không crash, Quality Score thấp, không trigger false promote.

**Scenario 4 — First run / no baseline (10 phút)**
Xóa DynamoDB records → chạy lần đầu → verify auto-promote baseline, không crash vì thiếu version cũ.

---

## Thứ tự triển khai

```
Tuần 1:   Unit tests — quality_score.py (quan trọng nhất, fix bug app-down trước)
Tuần 2:   Unit tests — evaluator.py, audit_logger.py
Tuần 3:   Integration tests — eval_pipeline.py, decision_logic.py
Tuần 4:   Integration tests — mcp_storage.py
Ongoing:  Manual E2E trước mỗi lần demo
```

---

## Công cụ cần cài

```
pytest              test runner chính
pytest-mock         mock external calls (Gemini, AWS)
pytest-asyncio      nếu có async code
pytest-cov          đo coverage
httpx               mock HTTP server cho target app
```

Coverage target thực tế:

- `quality_score.py` → 90%+ (core logic, không có lý do để bỏ sót)
- `evaluator.py` → 70%+ (phần Gemini call được mock)
- `agent.py` → 60%+ (integration tests cover phần còn lại)
- Overall → 70%+ là đủ cho portfolio

---

## Lưu ý quan trọng

**Không nên test:**

- Gemini API trả về đúng không — đó là responsibility của Google, không phải của bạn
- AWS services hoạt động đúng không — tương tự
- LangGraph internal behavior — đó là thư viện bên ngoài

**Nên test:**

- Logic của bạn khi Gemini trả về đúng
- Logic của bạn khi Gemini fail
- Math trong quality_score.py
- Decision thresholds
- Fallback behavior khi external services down
