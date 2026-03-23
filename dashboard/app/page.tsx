import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { RunsTable } from "@/components/runs-table";
import { StatusPill } from "@/components/status-pill";
import { SummaryCard } from "@/components/summary-card";
import { formatDateTime, formatScore, shortId } from "@/lib/format";
import { getOverviewData } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const overview = await getOverviewData();

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Phase 4 Dashboard</p>
          <h2>
            Operational overview across storage, evaluation, and deployment
          </h2>
        </div>
        <p className="muted">
          Auto-refreshing every 30 seconds via server refresh.
        </p>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Production Version"
          value={
            overview.currentVersion
              ? shortId(overview.currentVersion.version_id, 12)
              : "none"
          }
          detail={
            overview.currentVersion?.version_label ||
            "No active production version discovered."
          }
          accent="ink"
        />
        <SummaryCard
          label="Current Quality"
          value={formatScore(overview.currentVersion?.latest_quality_score)}
          detail={`Latest eval at ${formatDateTime(overview.currentVersion?.latest_run_timestamp)}`}
          accent="gold"
        />
        <SummaryCard
          label="Production Health"
          value={
            <StatusPill
              label={overview.productionHealth?.status ?? "unknown"}
            />
          }
          detail={`Response ${overview.productionHealth?.response_time_ms ?? 0} ms`}
          accent="coral"
        />
        <SummaryCard
          label="Version Inventory"
          value={overview.totalVersions}
          detail={`${overview.promotedVersions} promoted, ${overview.pendingVersions} pending`}
          accent="ink"
        />
      </div>

      <div className="split-grid">
        <section className="card">
          <div className="section-heading">
            <div>
              <h3>Deployment state</h3>
              <p className="muted">
                Current production and staging control-plane status.
              </p>
            </div>
          </div>

          <div className="comparison-grid">
            <div className="card" style={{ padding: 18 }}>
              <p className="card-label">Production</p>
              <p>
                <strong>Version:</strong>{" "}
                {shortId(overview.productionDeployment.current_version_id, 12)}
              </p>
              <p>
                <strong>Status:</strong>{" "}
                <StatusPill
                  label={overview.productionDeployment.status || "unknown"}
                />
              </p>
              <p>
                <strong>Deployed:</strong>{" "}
                {formatDateTime(overview.productionDeployment.deployed_at)}
              </p>
            </div>
            <div className="card" style={{ padding: 18 }}>
              <p className="card-label">Staging</p>
              <p>
                <strong>Version:</strong>{" "}
                {shortId(overview.stagingDeployment.current_version_id, 12)}
              </p>
              <p>
                <strong>Status:</strong>{" "}
                <StatusPill
                  label={overview.stagingDeployment.status || "unknown"}
                />
              </p>
              <p>
                <strong>Deployed:</strong>{" "}
                {formatDateTime(overview.stagingDeployment.deployed_at)}
              </p>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="section-heading">
            <div>
              <h3>Latest decision</h3>
              <p className="muted">
                Most recent decision record from monitor logs.
              </p>
            </div>
          </div>

          {overview.latestDecision ? (
            <div>
              <p>
                <strong>Decision:</strong>{" "}
                <StatusPill
                  label={overview.latestDecision.decision ?? "pending"}
                />
              </p>
              <p>
                <strong>Run:</strong>{" "}
                {shortId(overview.latestDecision.run_id, 12)}
              </p>
              <p>
                <strong>Time:</strong>{" "}
                {formatDateTime(overview.latestDecision.timestamp)}
              </p>
              <p className="muted">
                {overview.latestDecision.reasoning ||
                  overview.latestDecision.message}
              </p>
              <p>
                <strong>Action:</strong>{" "}
                {overview.latestDecision.action_taken || "n/a"}
              </p>
            </div>
          ) : (
            <div className="empty-state">No decisions found yet.</div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Recent pipeline runs</h3>
            <p className="muted">
              Latest evaluation runs merged with decision outcomes.
            </p>
          </div>
          <Link href="/runs" className="nav-link">
            Open full run history
          </Link>
        </div>

        {overview.recentRuns.length ? (
          <RunsTable runs={overview.recentRuns} />
        ) : (
          <div className="empty-state">No eval runs available.</div>
        )}
      </section>
    </div>
  );
}
