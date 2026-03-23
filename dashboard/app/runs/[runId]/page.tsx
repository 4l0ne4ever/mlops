import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { StatusPill } from "@/components/status-pill";
import { SummaryCard } from "@/components/summary-card";
import { formatDateTime, formatScore, shortId } from "@/lib/format";
import { getRunDetail } from "@/lib/data";

export const dynamic = "force-dynamic";

type RunDetailPageProps = {
  params: Promise<{ runId: string }>;
};

export default async function RunDetailPage({ params }: RunDetailPageProps) {
  const { runId } = await params;
  const run = await getRunDetail(runId);

  if (!run) {
    return (
      <div className="page-grid">
        <div className="card empty-state">Run {runId} was not found.</div>
      </div>
    );
  }

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Run Detail</p>
          <h2>Run {shortId(run.run_id, 12)}</h2>
        </div>
        <Link href="/runs" className="nav-link">
          Back to runs
        </Link>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Version"
          value={shortId(run.version_id, 12)}
          detail={formatDateTime(run.timestamp)}
          accent="ink"
        />
        <SummaryCard
          label="Quality Score"
          value={formatScore(run.quality_score)}
          detail={`${run.passed_test_cases}/${run.total_test_cases} passed`}
          accent="gold"
        />
        <SummaryCard
          label="Decision"
          value={<StatusPill label={run.decision} />}
          detail={run.action_taken || "No action recorded."}
          accent="coral"
        />
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Decision reasoning</h3>
            <p className="muted">
              Joined from the Phase 3 decision log stream.
            </p>
          </div>
        </div>
        <p>{run.reasoning || "No decision reasoning found for this run."}</p>
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Per-test-case outputs</h3>
            <p className="muted">
              Candidate output, expected reference, and judge score for each
              test case.
            </p>
          </div>
        </div>

        <div className="page-grid">
          {run.details.map((detail) => (
            <article
              key={detail.test_case_id}
              className="card"
              style={{ padding: 18 }}
            >
              <div className="section-heading">
                <div>
                  <h3 style={{ marginBottom: 6 }}>{detail.test_case_id}</h3>
                  <StatusPill label={detail.status} />
                </div>
                <div className="summary-value" style={{ fontSize: "1.4rem" }}>
                  {formatScore(detail.score)}
                </div>
              </div>
              <p>
                <strong>Input:</strong> {detail.input}
              </p>
              <div className="comparison-outputs">
                <div className="comparison-output">
                  <strong>Expected</strong>
                  <br />
                  {detail.expected_output}
                </div>
                <div className="comparison-output">
                  <strong>Actual</strong>
                  <br />
                  {detail.actual_output || "n/a"}
                </div>
              </div>
              <p className="muted" style={{ marginTop: 12 }}>
                {detail.reasoning}
              </p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
