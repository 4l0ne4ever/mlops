"""
LLM-as-Judge Evaluator — uses Gemini Flash to score translation quality.

Protocol (from configs/quality_score_spec.md):
    - expected_output is a REFERENCE, not ground truth — no string matching
    - Evaluates on 3 criteria: Accuracy, Fluency, Completeness
    - temperature=0 for deterministic output
    - 2-pass averaging to reduce variance
    - Structured JSON output enforced
    - Anomaly detection: if 2 passes differ by > threshold → flag

Returns structured results per test case:
    {"score": 0-10, "reasoning": "...", "issues": [...], "criteria": {...}}
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Judge prompt templates — 3 variants per P2-4 requirement
# ---------------------------------------------------------------------------

# Variant A: Default structured prompt (most explicit instructions)
_JUDGE_SYSTEM_PROMPT_A = """\
You are an expert translation quality evaluator. You evaluate machine translations \
by comparing the actual translation against a reference translation.

IMPORTANT RULES:
1. Do NOT compare the actual translation word-by-word with the expected translation.
2. The expected translation is provided as a REFERENCE for meaning only.
3. A translation that conveys the same meaning with different wording should still receive a high score.
4. Evaluate based on three criteria: Accuracy, Fluency, and Completeness.

SCORING GUIDE (0-10 scale):
- 9-10: Excellent — accurate, fluent, complete, natural sounding
- 7-8: Good — minor issues that don't affect meaning
- 5-6: Acceptable — some inaccuracies or awkward phrasing
- 3-4: Poor — significant meaning errors or missing content
- 0-2: Very poor — largely incorrect or incomprehensible

You MUST respond with valid JSON only. No other text."""

_JUDGE_USER_PROMPT_A = """\
Evaluate the following translation:

Source text ({source_lang}):
{input_text}

Expected translation ({target_lang}) — USE AS REFERENCE ONLY:
{expected_output}

Actual translation:
{actual_output}

Rate the translation on these criteria (0-10 each):
1. **Accuracy**: Does the translation preserve the original meaning?
2. **Fluency**: Is the translation natural and grammatically correct?
3. **Completeness**: Does the translation include all information from the source?

Respond with this exact JSON format:
{{
  "accuracy": <0-10>,
  "fluency": <0-10>,
  "completeness": <0-10>,
  "score": <overall 0-10>,
  "reasoning": "<brief explanation>",
  "issues": ["<issue1>", "<issue2>"]
}}"""

# Variant B: Rubric-based prompt (more structured scoring rubric)
_JUDGE_SYSTEM_PROMPT_B = """\
You are a professional translation quality assessor. Your task is to evaluate \
machine-translated text against a reference translation using a precise rubric.

You must output ONLY valid JSON — no explanations outside the JSON object."""

_JUDGE_USER_PROMPT_B = """\
Assess this translation using the rubric below.

SOURCE ({source_lang}): {input_text}
REFERENCE ({target_lang}): {expected_output}
CANDIDATE: {actual_output}

RUBRIC (score each 0-10):
• Accuracy (semantic fidelity to source — ignore stylistic differences from reference)
• Fluency (grammar, natural phrasing, readability in target language)
• Completeness (no omissions or hallucinated additions)

Overall score = weighted impression considering all three criteria.

Output JSON:
{{
  "accuracy": <0-10>,
  "fluency": <0-10>,
  "completeness": <0-10>,
  "score": <overall 0-10>,
  "reasoning": "<one-line justification>",
  "issues": []
}}"""

# Variant C: Chain-of-thought prompt (reason first, then score)
_JUDGE_SYSTEM_PROMPT_C = """\
You evaluate translation quality. Think step-by-step about accuracy, fluency, \
and completeness, then provide scores. Output valid JSON only."""

_JUDGE_USER_PROMPT_C = """\
Translation evaluation task:

Original ({source_lang}): {input_text}
Reference ({target_lang}): {expected_output}
To evaluate: {actual_output}

Step 1: Does the candidate preserve the meaning of the original? (accuracy 0-10)
Step 2: Is the candidate natural and grammatical? (fluency 0-10)
Step 3: Is all information from the original included? (completeness 0-10)
Step 4: What is the overall quality? (score 0-10)

Important: The reference is for meaning guidance only. Different wording is acceptable.

JSON output:
{{
  "accuracy": <0-10>,
  "fluency": <0-10>,
  "completeness": <0-10>,
  "score": <overall 0-10>,
  "reasoning": "<your step-by-step reasoning>",
  "issues": ["<issue if any>"]
}}"""

# Variant registry
PROMPT_VARIANTS: dict[str, tuple[str, str]] = {
    "A": (_JUDGE_SYSTEM_PROMPT_A, _JUDGE_USER_PROMPT_A),
    "B": (_JUDGE_SYSTEM_PROMPT_B, _JUDGE_USER_PROMPT_B),
    "C": (_JUDGE_SYSTEM_PROMPT_C, _JUDGE_USER_PROMPT_C),
}

# Default variant — selected after consistency testing
# Variant A provides the most explicit scoring guidelines
DEFAULT_PROMPT_VARIANT = "A"

# Legacy aliases for backward compat
_JUDGE_SYSTEM_PROMPT = _JUDGE_SYSTEM_PROMPT_A
_JUDGE_USER_PROMPT = _JUDGE_USER_PROMPT_A


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class JudgeResult:
    """Result from a single LLM-as-judge evaluation."""
    score: float
    accuracy: float
    fluency: float
    completeness: float
    reasoning: str
    issues: list[str]
    raw_passes: list[dict[str, Any]] = field(default_factory=list)
    anomaly: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "accuracy": round(self.accuracy, 2),
            "fluency": round(self.fluency, 2),
            "completeness": round(self.completeness, 2),
            "reasoning": self.reasoning,
            "issues": self.issues,
            "passes": len(self.raw_passes),
            "anomaly": self.anomaly,
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class LLMJudgeEvaluator:
    """
    Evaluates translation quality using Gemini Flash as LLM-as-judge.

    Follows the 2-pass averaging protocol from quality_score_spec.md.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.0,
        num_passes: int = 2,
        anomaly_threshold: float = 2.0,
        max_retries: int = 3,
        prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model_name = model_name
        self._temperature = temperature
        self._num_passes = num_passes
        self._anomaly_threshold = anomaly_threshold
        self._max_retries = max_retries
        self._prompt_variant = prompt_variant
        self._client = None
        self._audit_logger = None

        # Resolve prompt templates for selected variant
        if prompt_variant in PROMPT_VARIANTS:
            self._system_prompt, self._user_prompt_template = PROMPT_VARIANTS[prompt_variant]
        else:
            logger.warning(
                "Unknown prompt variant '%s', falling back to '%s'",
                prompt_variant, DEFAULT_PROMPT_VARIANT,
            )
            self._system_prompt, self._user_prompt_template = PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT]
            self._prompt_variant = DEFAULT_PROMPT_VARIANT

    def _ensure_client(self):
        """Lazy-initialize Gemini client and audit logger."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            logger.info(
                "LLM Judge initialized with model=%s, passes=%d, variant=%s",
                self._model_name,
                self._num_passes,
                self._prompt_variant,
            )
        if not hasattr(self, "_audit_logger") or self._audit_logger is None:
            from .audit_logger import JudgeAuditLogger
            self._audit_logger = JudgeAuditLogger()

    @classmethod
    def from_config(
        cls,
        thresholds_path: str | Path | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        prompt_variant: str | None = None,
    ) -> "LLMJudgeEvaluator":
        """Create evaluator from thresholds.json config."""
        config: dict[str, Any] = {}
        if thresholds_path:
            path = Path(thresholds_path)
            if path.exists():
                config = json.loads(path.read_text(encoding="utf-8"))

        return cls(
            api_key=api_key,
            model_name=model_name or "gemini-2.5-flash",
            temperature=config.get("judge_temperature", 0.0),
            num_passes=config.get("judge_passes", 2),
            anomaly_threshold=config.get("judge_anomaly_threshold", 2.0),
            prompt_variant=prompt_variant or config.get(
                "judge_prompt_variant", DEFAULT_PROMPT_VARIANT
            ),
        )

    # -- Core evaluation -----------------------------------------------------

    def evaluate(
        self,
        input_text: str,
        expected_output: str,
        actual_output: str,
        source_lang: str = "auto",
        target_lang: str = "auto",
        run_id: str = "",
        test_case_id: str = "",
    ) -> JudgeResult:
        """
        Evaluate a single translation using 2-pass LLM-as-judge.

        Args:
            input_text: The original source text.
            expected_output: Reference translation (not ground truth).
            actual_output: The translation to evaluate.
            source_lang: Source language code.
            target_lang: Target language code.
            run_id: Eval run ID (for audit logging).
            test_case_id: Test case ID (for audit logging).

        Returns:
            JudgeResult with averaged score and criteria breakdown.
        """
        self._ensure_client()

        user_prompt = self._user_prompt_template.format(
            source_lang=source_lang,
            target_lang=target_lang,
            input_text=input_text,
            expected_output=expected_output,
            actual_output=actual_output,
        )

        # Run multiple passes
        passes: list[dict[str, Any]] = []
        for pass_num in range(1, self._num_passes + 1):
            result = self._single_pass(
                user_prompt, pass_num,
                run_id=run_id,
                test_case_id=test_case_id,
                input_text=input_text,
                expected_output=expected_output,
                actual_output=actual_output,
            )
            if result is not None:
                passes.append(result)

        if not passes:
            logger.error("All judge passes failed — returning zero score")
            return JudgeResult(
                score=0.0,
                accuracy=0.0,
                fluency=0.0,
                completeness=0.0,
                reasoning="Judge evaluation failed — all passes returned errors",
                issues=["judge_failure"],
                raw_passes=[],
                anomaly=True,
            )

        # Average across passes
        avg_score = sum(p["score"] for p in passes) / len(passes)
        avg_accuracy = sum(p["accuracy"] for p in passes) / len(passes)
        avg_fluency = sum(p["fluency"] for p in passes) / len(passes)
        avg_completeness = sum(p["completeness"] for p in passes) / len(passes)

        # Anomaly detection: if passes differ by > threshold
        anomaly = False
        if len(passes) >= 2:
            score_range = max(p["score"] for p in passes) - min(p["score"] for p in passes)
            if score_range > self._anomaly_threshold:
                anomaly = True
                logger.warning(
                    "Judge anomaly detected: score range %.1f > threshold %.1f",
                    score_range,
                    self._anomaly_threshold,
                )

        # Use reasoning from the first successful pass
        reasoning = passes[0].get("reasoning", "")
        issues = passes[0].get("issues", [])

        return JudgeResult(
            score=avg_score,
            accuracy=avg_accuracy,
            fluency=avg_fluency,
            completeness=avg_completeness,
            reasoning=reasoning,
            issues=issues,
            raw_passes=passes,
            anomaly=anomaly,
        )

    def _single_pass(
        self,
        user_prompt: str,
        pass_num: int,
        *,
        run_id: str = "",
        test_case_id: str = "",
        input_text: str = "",
        expected_output: str = "",
        actual_output: str = "",
    ) -> dict[str, Any] | None:
        """Execute a single judge pass with retry logic and audit logging."""
        from google.genai import types

        for attempt in range(1, self._max_retries + 1):
            call_start = time.perf_counter()
            try:
                config = types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    temperature=self._temperature,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                )
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=user_prompt,
                    config=config,
                )
                text = response.text.strip()
                call_latency = (time.perf_counter() - call_start) * 1000
                parsed = self._parse_json_response(text)

                # Audit log — success or parse failure
                if hasattr(self, "_audit_logger") and self._audit_logger:
                    self._audit_logger.log_call(
                        run_id=run_id,
                        test_case_id=test_case_id,
                        prompt_variant=self._prompt_variant,
                        model_name=self._model_name,
                        temperature=self._temperature,
                        pass_num=pass_num,
                        attempt_num=attempt,
                        input_text=input_text,
                        expected_output=expected_output,
                        actual_output=actual_output,
                        raw_response=text,
                        parsed_result=parsed,
                        latency_ms=call_latency,
                        success=parsed is not None,
                        error="" if parsed else "invalid JSON response",
                    )

                if parsed is not None:
                    logger.debug(
                        "Judge pass %d attempt %d: score=%.1f",
                        pass_num,
                        attempt,
                        parsed["score"],
                    )
                    return parsed
                else:
                    logger.warning(
                        "Judge pass %d attempt %d: invalid JSON response",
                        pass_num,
                        attempt,
                    )
            except Exception as exc:
                call_latency = (time.perf_counter() - call_start) * 1000
                # Audit log — exception
                if hasattr(self, "_audit_logger") and self._audit_logger:
                    self._audit_logger.log_call(
                        run_id=run_id,
                        test_case_id=test_case_id,
                        prompt_variant=self._prompt_variant,
                        model_name=self._model_name,
                        temperature=self._temperature,
                        pass_num=pass_num,
                        attempt_num=attempt,
                        input_text=input_text,
                        expected_output=expected_output,
                        actual_output=actual_output,
                        raw_response="",
                        parsed_result=None,
                        latency_ms=call_latency,
                        success=False,
                        error=str(exc),
                    )
                logger.warning(
                    "Judge pass %d attempt %d failed: %s",
                    pass_num,
                    attempt,
                    exc,
                )

        logger.error("Judge pass %d: all %d retries exhausted", pass_num, self._max_retries)
        return None

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any] | None:
        """Parse and validate judge JSON response."""
        try:
            # Try direct parse first
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code block
            # This is a safety net: response_mime_type="application/json" should
            # prevent this path. If triggered, it means the model ignored the
            # mime type constraint — worth investigating.
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                logger.warning(
                    "Judge response was not valid JSON; falling back to "
                    "markdown code block extraction. This indicates the model "
                    "ignored response_mime_type='application/json'."
                )
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return None
            else:
                return None

        # Validate required fields
        required = {"score", "accuracy", "fluency", "completeness"}
        if not required.issubset(data.keys()):
            return None

        # Clamp scores to 0-10
        for key in ("score", "accuracy", "fluency", "completeness"):
            val = data[key]
            if not isinstance(val, (int, float)):
                return None
            data[key] = min(max(float(val), 0.0), 10.0)

        # Ensure optional fields
        data.setdefault("reasoning", "")
        data.setdefault("issues", [])
        if isinstance(data["issues"], str):
            data["issues"] = [data["issues"]] if data["issues"] else []

        return data

# ---------------------------------------------------------------------------
# Prompt Variant Consistency Tester (P2-4 requirement)
# ---------------------------------------------------------------------------

def test_prompt_variants(
    test_cases: list[dict[str, Any]],
    api_key: str = "",
    model_name: str = "gemini-2.5-flash",
    num_runs: int = 3,
) -> dict[str, Any]:
    """
    Test all prompt variants for consistency and select the best one.

    Per P2-4: "thử 2-3 prompt variants, chọn variant cho kết quả consistent nhất"

    Runs each variant `num_runs` times on the given test cases and computes:
    - Mean score per variant
    - Score standard deviation (lower = more consistent)
    - Anomaly rate

    Args:
        test_cases: List of dicts with input, expected_output, source_lang, target_lang.
        api_key: Gemini API key.
        model_name: Model to use.
        num_runs: Number of evaluation runs per variant.

    Returns:
        Dict with variant results and recommended variant.
    """
    import statistics

    results: dict[str, dict[str, Any]] = {}

    for variant_name in PROMPT_VARIANTS:
        all_scores: list[float] = []
        anomaly_count = 0

        for run_num in range(num_runs):
            evaluator = LLMJudgeEvaluator(
                api_key=api_key,
                model_name=model_name,
                prompt_variant=variant_name,
            )

            run_scores: list[float] = []
            for tc in test_cases:
                actual = tc.get("actual_output")
                if not actual:
                    logger.warning(
                        "Skipping test case without actual_output in variant %s test",
                        variant_name,
                    )
                    continue
                try:
                    result = evaluator.evaluate(
                        input_text=tc["input"],
                        expected_output=tc.get("expected_output", ""),
                        actual_output=actual,
                        source_lang=tc.get("source_lang", "auto"),
                        target_lang=tc.get("target_lang", "auto"),
                    )
                    run_scores.append(result.score)
                    if result.anomaly:
                        anomaly_count += 1
                except Exception as exc:
                    logger.warning(
                        "Variant %s run %d failed for test case: %s",
                        variant_name, run_num + 1, exc,
                    )

            all_scores.extend(run_scores)

        if all_scores:
            mean_score = statistics.mean(all_scores)
            std_dev = statistics.stdev(all_scores) if len(all_scores) > 1 else 0.0
            results[variant_name] = {
                "mean_score": round(mean_score, 3),
                "std_dev": round(std_dev, 3),
                "total_evaluations": len(all_scores),
                "anomaly_count": anomaly_count,
                "consistency": round(10.0 - std_dev, 3),  # Higher = more consistent
            }
        else:
            results[variant_name] = {
                "mean_score": 0.0,
                "std_dev": 0.0,
                "total_evaluations": 0,
                "anomaly_count": 0,
                "consistency": 0.0,
            }

    # Select best variant: highest consistency (lowest std_dev), break ties by mean score
    best_variant = max(
        results.keys(),
        key=lambda v: (results[v]["consistency"], results[v]["mean_score"]),
    )

    return {
        "variants": results,
        "recommended": best_variant,
        "reason": (
            f"Variant {best_variant} selected: "
            f"consistency={results[best_variant]['consistency']:.3f}, "
            f"mean_score={results[best_variant]['mean_score']:.3f}, "
            f"std_dev={results[best_variant]['std_dev']:.3f}"
        ),
    }