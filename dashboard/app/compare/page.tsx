import { AutoRefresh } from "@/components/auto-refresh";
import { StatusPill } from "@/components/status-pill";
import { SummaryCard } from "@/components/summary-card";
import { formatScore, shortId } from "@/lib/format";
import { getComparisonData } from "@/lib/data";

export const dynamic = "force-dynamic";

type ComparePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function ComparePage({ searchParams }: ComparePageProps) {
  const params = (await searchParams) ?? {};
  const left = typeof params.left === "string" ? params.left : undefined;
  const right = typeof params.right === "string" ? params.right : undefined;
  const comparison = await getComparisonData(left, right);
  const scoreDelta =
    (comparison.leftRun?.quality_score ?? 0) -
    (comparison.rightRun?.quality_score ?? 0);

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Comparison View</p>
          <h2>Side-by-side version comparison down to test-case outputs</h2>
        </div>
      </section>

      <section className="card">
        <form method="get" className="form-row">
          <label className="field">
            <span>Left version</span>
            <select name="left" defaultValue={comparison.selectedLeft}>
              {comparison.versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.version_label || shortId(version.version_id, 12)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Right version</span>
            <select name="right" defaultValue={comparison.selectedRight}>
              {comparison.versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.version_label || shortId(version.version_id, 12)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>&nbsp;</span>
            <button type="submit">Compare</button>
          </label>
        </form>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Left Score"
          value={formatScore(comparison.leftRun?.quality_score)}
          detail={
            comparison.leftVersion?.version_label ||
            shortId(comparison.selectedLeft, 12)
          }
          accent="ink"
        />
        <SummaryCard
          label="Right Score"
          value={formatScore(comparison.rightRun?.quality_score)}
          detail={
            comparison.rightVersion?.version_label ||
            shortId(comparison.selectedRight, 12)
          }
          accent="gold"
        />
        <SummaryCard
          label="Score Delta"
          value={
            scoreDelta >= 0
              ? `+${formatScore(scoreDelta)}`
              : formatScore(scoreDelta)
          }
          detail="Left minus right"
          accent="coral"
        />
      </div>

      <div className="comparison-grid">
        <section className="card">
          <p className="card-label">Left version</p>
          <h3>
            {comparison.leftVersion?.version_label ||
              shortId(comparison.selectedLeft, 12)}
          </h3>
          <p>
            <StatusPill
              label={String(comparison.leftVersion?.status || "unknown")}
            />
          </p>
          <p className="muted">
            Run {shortId(comparison.leftRun?.run_id, 12)} ·{" "}
            {comparison.leftRun?.passed_test_cases ?? 0}/
            {comparison.leftRun?.total_test_cases ?? 0} passed
          </p>
        </section>
        <section className="card">
          <p className="card-label">Right version</p>
          <h3>
            {comparison.rightVersion?.version_label ||
              shortId(comparison.selectedRight, 12)}
          </h3>
          <p>
            <StatusPill
              label={String(comparison.rightVersion?.status || "unknown")}
            />
          </p>
          <p className="muted">
            Run {shortId(comparison.rightRun?.run_id, 12)} ·{" "}
            {comparison.rightRun?.passed_test_cases ?? 0}/
            {comparison.rightRun?.total_test_cases ?? 0} passed
          </p>
        </section>
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Per-test-case comparison</h3>
            <p className="muted">
              Outputs and judge scores aligned by test_case_id.
            </p>
          </div>
        </div>

        {comparison.rows.length ? (
          <div className="page-grid">
            {comparison.rows.map((row) => (
              <article
                key={row.test_case_id}
                className="card"
                style={{ padding: 18 }}
              >
                <div className="section-heading">
                  <div>
                    <h3 style={{ marginBottom: 6 }}>{row.test_case_id}</h3>
                    <p className="muted" style={{ margin: 0 }}>
                      {row.input}
                    </p>
                  </div>
                  <div>
                    <StatusPill
                      label={row.delta >= 0 ? "left_ahead" : "right_ahead"}
                    />
                  </div>
                </div>
                <p>
                  <strong>Expected:</strong> {row.expected_output}
                </p>
                <div className="comparison-outputs">
                  <div className="comparison-output">
                    <strong>Left</strong>
                    <br />
                    {row.left_output || "n/a"}
                    <br />
                    <br />
                    <span className="muted">
                      Score {formatScore(row.left_score)} · {row.left_status}
                    </span>
                  </div>
                  <div className="comparison-output">
                    <strong>Right</strong>
                    <br />
                    {row.right_output || "n/a"}
                    <br />
                    <br />
                    <span className="muted">
                      Score {formatScore(row.right_score)} · {row.right_status}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            No comparable test-case data available for the selected versions.
          </div>
        )}
      </section>
    </div>
  );
}
