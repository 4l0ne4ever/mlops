# Quality Score Specification

> **Mục đích:** Định nghĩa chi tiết Quality Score — composite metric dùng để đánh giá chất lượng LLM application sau mỗi thay đổi. Document này là nguồn sự thật duy nhất cho cách tính Quality Score.  
> **Sử dụng tại:** Phase 2 (Eval Pipeline) — module Quality Score Calculator.  
> **Chuẩn bị trước Phase 2** — hội đồng sẽ hỏi kỹ về phần này.

---

## 1. Tổng Quan

**Quality Score** là một giá trị **0–10** tổng hợp từ nhiều chiều đánh giá, phản ánh chất lượng tổng thể của LLM application tại một version cụ thể.

```
QualityScore = Σ(weight_i × normalized_score_i)
```

Giá trị này được dùng bởi:
- **Version Comparator Agent** — so sánh 2 versions
- **Promotion Decision Agent** — quyết định promote/rollback
- **Dashboard** — visualize drift theo thời gian

---

## 2. Các Dimensions

> **Lưu ý:** Đã loại bỏ "Tool-Call Accuracy" vì target app (translation agent) là hệ thống text-in → text-out thuần túy, không có tool calls. Nếu sau này target app có tool calls (ví dụ: glossary lookup), dimension này có thể được thêm lại bằng cách cập nhật config file.

### 2.1 Task Completion Rate — Weight: 0.35

| Item | Detail |
|------|--------|
| **Đo gì** | Tỷ lệ test cases mà output đạt above threshold |
| **Raw value** | 0–100% (số test cases pass / tổng test cases) |
| **Pass threshold cho mỗi test case** | LLM-as-judge score ≥ 6.0/10 |
| **Normalization** | `score = raw_percentage / 10` |
| **Ví dụ** | 85% test cases pass → score = 8.5 |
| **Lý do weight cao (0.35)** | Đây là signal quan trọng nhất — nếu agent fail nhiều tasks, quality rõ ràng kém. Tham khảo: RAGAS framework cũng đặt task success rate là metric hàng đầu. |

### 2.2 Output Quality — Weight: 0.35

| Item | Detail |
|------|--------|
| **Đo gì** | Chất lượng output trung bình của tất cả test cases |
| **Raw value** | 0–10 (average LLM-as-judge score across all test cases) |
| **Evaluator** | Gemini Flash (LLM-as-judge) chấm theo 3 criteria: Accuracy, Fluency, Completeness |
| **Normalization** | Direct use (đã trong range 0-10) |
| **Ví dụ** | Average judge score = 7.2 → score = 7.2 |
| **Lý do weight cao (0.35)** | Output quality phản ánh trực tiếp trải nghiệm người dùng. Kết hợp với Task Completion (task hoàn thành hay không) tạo thành cặp metric bổ trợ: "bao nhiêu tasks pass" + "quality của output tốt đến đâu". |

### 2.3 Latency — Weight: 0.20

| Item | Detail |
|------|--------|
| **Đo gì** | Thời gian phản hồi trung bình của target app |
| **Raw value** | Milliseconds (average response time) |
| **Normalization** | `score = 10 - min(avg_latency_ms / 1000, 10)` |
| **Ví dụ** | 2500ms average → 10 - 2.5 = 7.5 |
| **Interpretation** | < 1s → score 9-10 (excellent), 1-3s → 7-9 (good), 3-5s → 5-7 (acceptable), > 5s → < 5 (poor), > 10s → 0 |
| **Lý do weight 0.20** | Latency ảnh hưởng UX nhưng không critical bằng correctness. Model swap (ví dụ Flash → Pro) có thể tăng latency đáng kể — metric này bắt được regression loại đó. |

### 2.4 Cost Efficiency — Weight: 0.10

| Item | Detail |
|------|--------|
| **Đo gì** | Chi phí trung bình mỗi request (LLM API cost) |
| **Raw value** | USD per request |
| **Normalization** | `score = 10 - min(cost_per_request × 100, 10)` |
| **Ví dụ** | $0.003/request → 10 - 0.3 = 9.7 |
| **Interpretation** | < $0.01 → score 9-10, $0.01-$0.05 → 5-9, $0.05-$0.10 → 0-5, > $0.10 → 0 |
| **Lý do weight thấp (0.10)** | Cost quan trọng trong production nhưng ở thesis scope, focus chính là quality và speed. Weight thấp nhưng vẫn cần theo dõi để phát hiện khi swap sang expensive model. |

### 2.5 LLM-as-Judge Protocol — Cách Judge Đánh Giá

> ⚠️ **Quan trọng cho hội đồng:** Dịch thuật có **nhiều bản dịch đúng** cho cùng 1 câu. Nếu judge so khớp string với `expected_output`, bản dịch đúng nhưng diễn đạt khác sẽ bị chấm thấp sai. Phải document rõ cách judge hoạt động.

**Nguyên tắc cốt lõi:**

| Rule | Chi tiết |
|------|---------|
| `expected_output` chỉ là **reference**, không phải ground truth duy nhất | Judge dùng expected_output như tham chiếu để hiểu ý nghĩa đúng, KHÔNG so khớp string |
| Judge đánh giá theo **criteria**, không phải string matching | 3 criteria: Accuracy (giữ nghĩa), Fluency (tự nhiên), Completeness (đầy đủ) |
| Dùng `temperature=0` | Đảm bảo output deterministic — cùng input → cùng score |
| **2-pass averaging** | Chạy mỗi test case qua judge **2 lần**, lấy average score → giảm variance |
| Judge phải output structured JSON | Enforce JSON schema, retry nếu output không đúng format |

**Tại sao 2-pass averaging?**
- LLM judge khi `temperature=0` vẫn có variance nhỏ (do top-p sampling, batch effects)
- 2 passes đủ để giảm variance mà không tốn quá nhiều API cost
- Nếu 2 scores chênh lệch > 2.0 → flag anomaly, có thể cần human review

**Judge prompt phải ghi rõ:**
```
IMPORTANT: Do NOT compare the actual translation word-by-word with the expected translation.
The expected translation is provided as a REFERENCE for meaning only.
A translation that conveys the same meaning with different wording should still receive a high score.
Evaluate based on: Accuracy, Fluency, and Completeness.
```

---

## 3. Bảng Tóm Tắt

| Dimension | Weight | Raw Value | Normalization Formula | Score Range |
|-----------|--------|-----------|----------------------|-------------|
| Task Completion Rate | **0.35** | 0–100% | `raw / 10` | 0–10 |
| Output Quality | **0.35** | 0–10 | Direct | 0–10 |
| Latency | **0.20** | ms | `10 - min(ms/1000, 10)` | 0–10 |
| Cost Efficiency | **0.10** | $/req | `10 - min($×100, 10)` | 0–10 |
| **Total** | **1.00** | | | **0–10** |

---

## 4. Ví Dụ Tính Toán Chi Tiết

### Case A: Version chạy tốt

```
Input:
  - 50 test cases, 43 passed (≥ 6.0) → Task Completion = 86%
  - Average LLM judge score = 7.8
  - Average latency = 1800ms
  - Average cost = $0.002/request

Calculation:
  Task Completion: 86% → 8.6 × 0.35 = 3.010
  Output Quality:  7.8  → 7.8 × 0.35 = 2.730
  Latency:      1800ms → 8.2 × 0.20 = 1.640
  Cost:        $0.002  → 9.8 × 0.10 = 0.980
                                       ──────
                         Quality Score = 8.360
```

### Case B: Version bị regression (bad prompt)

```
Input:
  - 50 test cases, 28 passed → Task Completion = 56%
  - Average LLM judge score = 4.9
  - Average latency = 2200ms
  - Average cost = $0.002/request

Calculation:
  Task Completion: 56% → 5.6 × 0.35 = 1.960
  Output Quality:  4.9  → 4.9 × 0.35 = 1.715
  Latency:      2200ms → 7.8 × 0.20 = 1.560
  Cost:        $0.002  → 9.8 × 0.10 = 0.980
                                       ──────
                         Quality Score = 6.215

  Delta vs Case A: 6.215 - 8.360 = -2.145 → CRITICAL REGRESSION
```

### Case C: Swap model (cheap → expensive, better quality)

```
Input:
  - 50 test cases, 47 passed → Task Completion = 94%
  - Average LLM judge score = 9.1
  - Average latency = 4500ms (slower model)
  - Average cost = $0.045/request (expensive)

Calculation:
  Task Completion: 94% → 9.4 × 0.35 = 3.290
  Output Quality:  9.1  → 9.1 × 0.35 = 3.185
  Latency:      4500ms → 5.5 × 0.20 = 1.100
  Cost:        $0.045  → 5.5 × 0.10 = 0.550
                                       ──────
                         Quality Score = 8.125

  Delta vs Case A: 8.125 - 8.360 = -0.235 → NO SIGNIFICANT CHANGE
  (Quality tăng nhưng latency + cost tăng → gần như offset nhau)
```

---

## 5. Edge Cases

| Situation | Handling |
|-----------|---------|
| Target app timeout (100% test cases fail) | Task Completion = 0%, Output Quality = 0 → QS rất thấp → trigger CRITICAL_REGRESSION |
| LLM-as-judge API error (không chấm được) | Retry 3 lần. Nếu vẫn fail → mark test case as SKIPPED. Nếu > 50% skipped → eval run status = "partial", cần human review |
| Cost = $0 (free model/cached) | Cost score = 10.0 (perfect) — không bị chia cho 0 nhờ formula |
| Latency = 0ms (cached response) | Latency score = 10.0 — bình thường, chỉ có nghĩa response rất nhanh |
| Only 1 test case chạy được (49 skipped) | Task Completion tính trên số cases chạy được. Nhưng nếu < 50% cases chạy → flag warning |

---

## 6. Configurable Parameters

Tất cả parameters nằm trong `configs/thresholds.json`:

```json
{
  "per_dimension_weights": {
    "task_completion": 0.35,
    "output_quality": 0.35,
    "latency": 0.20,
    "cost_efficiency": 0.10
  },
  "test_case_pass_threshold": 6.0,
  "overall_regression_threshold": -0.5,
  "critical_dimension_threshold": -1.0,
  "auto_promote_threshold": 0.3,
  "min_test_cases_required": 0.5
}
```

| Parameter | Ý nghĩa | Default |
|-----------|---------|---------|
| `per_dimension_weights` | Weight cho từng dimension | Xem bảng trên |
| `test_case_pass_threshold` | Score tối thiểu để 1 test case "pass" | 6.0 |
| `overall_regression_threshold` | Delta score → trigger "regression detected" | -0.5 |
| `critical_dimension_threshold` | Delta single dimension → trigger "critical" | -1.0 |
| `auto_promote_threshold` | Delta score → auto promote | +0.3 |
| `min_test_cases_required` | % test cases phải chạy thành công để eval valid | 50% |

---

## 7. Justification Cho Weight Choices

| Dimension | Weight | Justification |
|-----------|--------|---------------|
| Task Completion | 0.35 | RAGAS framework coi task success là metric primary. Correctness là yếu tố quantitative rõ ràng nhất. |
| Output Quality | 0.35 | Bổ trợ Task Completion: "pass" chỉ nói binary, quality cho nuanced view. Research từ DeepEval cho thấy LLM-judge correlate ~0.85 với human evaluation. |
| Latency | 0.20 | Theo Google UX research, response time > 3s giảm user satisfaction đáng kể. Weight đủ để bắt regression khi swap model nhưng không override correctness. |
| Cost | 0.10 | Cost awareness cần có nhưng không nên dominate decision. Tham khảo: MLOps best practices đặt cost ở secondary priority sau quality. |

> **Ablation study (Phase 5):** Sẽ thử bỏ từng dimension, xem impact lên decision accuracy. Kết quả sẽ validate hoặc adjust weights trên.
