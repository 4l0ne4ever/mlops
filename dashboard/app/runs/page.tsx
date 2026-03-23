import { AutoRefresh } from "@/components/auto-refresh";
import { RunsTable } from "@/components/runs-table";
import { SummaryCard } from "@/components/summary-card";
import { getRunsData } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const runs = await getRunsData();
  const promoteCount = runs.filter(
    (run) => run.decision === "AUTO_PROMOTE",
  ).length;
  const rollbackCount = runs.filter(
    (run) => run.decision === "ROLLBACK",
  ).length;

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Pipeline Runs</p>
          <h2>
            Every evaluation run, with decision reasoning and drill-in detail
          </h2>
        </div>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Run Count"
          value={runs.length}
          detail="Eval results joined to decision logs."
          accent="gold"
        />
        <SummaryCard
          label="Auto Promote"
          value={promoteCount}
          detail="Runs that promoted without manual intervention."
          accent="ink"
        />
        <SummaryCard
          label="Rollback"
          value={rollbackCount}
          detail="Runs that triggered rollback or protective action."
          accent="coral"
        />
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Run ledger</h3>
            <p className="muted">
              Select any run to inspect per-test-case output, scores, and
              comparison reasoning.
            </p>
          </div>
        </div>

        {runs.length ? (
          <RunsTable runs={runs} />
        ) : (
          <div className="empty-state">No runs found.</div>
        )}
      </section>
    </div>
  );
}
