#!/usr/bin/env python3
"""
Read all experiments_*.jsonl in .local-data/experiments/, pick the latest run
(by file mtime) with the most scenarios, and write a summary table to
.local-data/experiments/experiments_summary.md.
Run from project root: python scripts/summarize_experiments.py
"""
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = PROJECT_ROOT / ".local-data" / "experiments"


def main() -> None:
    if not EXPERIMENTS_DIR.exists():
        print(f"Missing: {EXPERIMENTS_DIR}")
        return

    files = sorted(EXPERIMENTS_DIR.glob("experiments_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("No experiments_*.jsonl files found.")
        return

    # Use the most recent file; prefer one that has at least one record with quality_score > 0
    all_records: list[dict] = []
    fallback: list[dict] = []
    for f in files:
        recs = []
        for line in f.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if recs:
            if not fallback:
                fallback = recs
            if any(r.get("quality_score", 0) > 0 for r in recs):
                all_records = recs
                break
    if not all_records:
        all_records = fallback

    if not all_records:
        print("No valid records in any file.")
        return

    out = []
    out.append("# Phase 5 experiments summary")
    out.append("")
    out.append("Generated from `.local-data/experiments/experiments_*.jsonl` (latest run with data).")
    out.append("")
    out.append("| Scenario | Kind | Status | Quality score | Delta | Verdict | Decision | Wall (s) |")
    out.append("|----------|------|--------|---------------|-------|---------|----------|----------|")

    for r in all_records:
        scenario = r.get("scenario_id", "")
        kind = r.get("kind", "")
        status = r.get("pipeline_status", "")
        score = r.get("quality_score", 0)
        comp = r.get("comparison") or {}
        delta = comp.get("delta")
        delta_str = f"{delta:+.2f}" if delta is not None else "—"
        verdict = comp.get("verdict") or "—"
        decision = (r.get("decision") or {}).get("decision") or "—"
        wall = r.get("wall_clock_seconds", 0)
        out.append(f"| {scenario} | {kind} | {status} | {score:.3f} | {delta_str} | {verdict} | {decision} | {wall:.1f} |")

    out.append("")
    out.append("## Notes")
    out.append("")
    out.append("- **Quality score**: 0–10 composite (task completion, output quality, latency, cost efficiency).")
    out.append("- **Delta**: v_new_score − v_current_score (seeded baseline 7.5).")
    out.append("- **Verdict**: IMPROVED | NO_SIGNIFICANT_CHANGE | REGRESSION_DETECTED | CRITICAL_REGRESSION.")
    out.append("- **Decision**: AUTO_PROMOTE | NO_ACTION | ESCALATE | ROLLBACK.")
    out.append("")
    err_counts = [len(r.get("errors") or []) for r in all_records]
    if any(err_counts):
        out.append("### Error counts per scenario")
        out.append("")
        for r in all_records:
            n = len(r.get("errors") or [])
            out.append(f"- {r.get('scenario_id', '?')}: {n} error(s)")
        out.append("")

    summary_path = EXPERIMENTS_DIR / "experiments_summary.md"
    summary_path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
