import math


from agents.eval_runner.quality_score import QualityScoreCalculator


def test_perfect_score():
    calc = QualityScoreCalculator()
    scores = [10.0] * 10
    latencies_ms = [0.0] * 10
    costs_usd = [0.0] * 10

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=0,
        version_id="v1",
        run_id="r1",
    )

    assert result.is_valid is True
    assert result.quality_score > 9.9
    breakdown = result.breakdown
    assert breakdown["task_completion"]["score"] == 10.0
    assert breakdown["output_quality"]["score"] == 10.0
    assert breakdown["latency"]["score"] == 10.0
    assert breakdown["cost_efficiency"]["score"] == 10.0


def test_app_down_score():
    calc = QualityScoreCalculator()
    result = calc.calculate(
        test_case_scores=[],
        latencies_ms=[],
        costs_usd=[],
        skipped_cases=0,
        version_id="v1",
        run_id="r1",
    )

    assert result.quality_score == 0.0
    assert result.is_valid is False


def test_known_calculation_matches_manual_math():
    calc = QualityScoreCalculator()

    # pass_threshold defaults to 6.0
    scores = [6.0, 6.0, 0.0, 0.0]  # 2/4 pass => 50% pass rate => 5.0 task completion
    latencies_ms = [1000.0] * 4  # normalize_latency(1000ms) = 9.0
    costs_usd = [0.01] * 4  # normalize_cost(0.01) = 9.0

    # avg_judge_score = (6+6+0+0)/4 = 3.0
    # normalize_output_quality(3.0) = 3.0
    # quality_score = 0.35*5.0 + 0.35*3.0 + 0.2*9.0 + 0.1*9.0
    expected = 0.35 * 5.0 + 0.35 * 3.0 + 0.2 * 9.0 + 0.1 * 9.0

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=0,
        version_id="v1",
        run_id="r1",
    )

    assert math.isclose(result.quality_score, expected, rel_tol=1e-9)


def test_weights_must_sum_to_one():
    try:
        QualityScoreCalculator(
            weights={
                "task_completion": 0.3,
                "output_quality": 0.3,
                "latency": 0.2,
                "cost_efficiency": 0.1,
            }
        )
        assert False, "expected ValueError"
    except ValueError:
        assert True


def test_pass_threshold_boundary_inclusive():
    calc = QualityScoreCalculator()
    threshold = calc.pass_threshold
    assert threshold == 6.0

    scores = [threshold, threshold]
    latencies_ms = [1000.0, 1000.0]
    costs_usd = [0.01, 0.01]

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=0,
    )

    assert result.breakdown["task_completion"]["score"] == 10.0


def test_all_cases_fail_sets_task_completion_and_output_quality_to_zero():
    calc = QualityScoreCalculator()
    scores = [0.0, 0.0]
    latencies_ms = [1000.0, 1000.0]
    costs_usd = [0.01, 0.01]

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=0,
        run_id="r1",
    )

    assert result.breakdown["task_completion"]["score"] == 0.0
    assert result.breakdown["output_quality"]["score"] == 0.0


def test_from_config_file_and_missing_fallback(tmp_path):
    # valid config
    calc = QualityScoreCalculator.from_config_file("configs/thresholds.json")
    assert math.isclose(calc.pass_threshold, calc.pass_threshold)

    # missing config => defaults
    missing = tmp_path / "does-not-exist.json"
    calc2 = QualityScoreCalculator.from_config_file(missing)
    assert math.isclose(calc2.pass_threshold, 6.0)


def test_skipped_cases_metadata():
    calc = QualityScoreCalculator()
    scores = [10.0, 0.0]  # 1 pass out of 2 completed
    latencies_ms = [1000.0, 1000.0]
    costs_usd = [0.01, 0.01]

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=8,
        total_cases=10,
        run_id="r1",
        version_id="v1",
    )

    assert result.metadata["total_test_cases"] == 10
    assert result.metadata["completed_test_cases"] == 2
    assert result.metadata["skipped_test_cases"] == 8
    assert result.metadata["passed_test_cases"] == 1


def test_warning_insufficient_cases_emits_warning_and_sets_is_valid_false():
    calc = QualityScoreCalculator()
    # 1 completed out of 3 total => run_fraction=0.333 < min_test_cases_required=0.5
    scores = [7.0]
    latencies_ms = [1000.0]
    costs_usd = [0.01]

    result = calc.calculate(
        test_case_scores=scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        skipped_cases=2,
        total_cases=3,
    )

    assert result.is_valid is False
    assert len(result.warnings) > 0

