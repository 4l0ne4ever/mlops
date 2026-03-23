import { AutoRefresh } from "@/components/auto-refresh";
import { StatusPill } from "@/components/status-pill";
import { SummaryCard } from "@/components/summary-card";
import { VersionsTable } from "@/components/versions-table";
import { formatDateTime, formatScore, shortId } from "@/lib/format";
import { getVersionsData } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function VersionsPage() {
  const versions = await getVersionsData();
  const latest = versions[0];

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Version History</p>
          <h2>Prompt versions with score and deployment state</h2>
        </div>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Total Versions"
          value={versions.length}
          detail="Discovered from MCP Storage list_versions."
          accent="gold"
        />
        <SummaryCard
          label="Latest Version"
          value={shortId(latest?.version_id, 12)}
          detail={latest?.version_label || "n/a"}
          accent="ink"
        />
        <SummaryCard
          label="Latest Score"
          value={formatScore(latest?.latest_quality_score)}
          detail={formatDateTime(latest?.latest_run_timestamp)}
          accent="coral"
        />
      </div>

      <div className="split-grid">
        <section className="card">
          <div className="section-heading">
            <div>
              <h3>Timeline</h3>
              <p className="muted">
                Newest versions first with real status and latest score.
              </p>
            </div>
          </div>

          <ol className="timeline">
            {versions.slice(0, 8).map((version) => (
              <li key={version.version_id} className="timeline-item">
                <p style={{ margin: 0 }}>
                  <strong>
                    {version.version_label || shortId(version.version_id, 12)}
                  </strong>
                </p>
                <p className="muted" style={{ margin: "6px 0" }}>
                  {formatDateTime(version.created_at)}
                </p>
                <p style={{ margin: 0 }}>
                  <StatusPill label={String(version.status)} />
                  <span style={{ marginLeft: 10 }}>
                    score {formatScore(version.latest_quality_score)}
                  </span>
                </p>
              </li>
            ))}
          </ol>
        </section>

        <section className="card">
          <div className="section-heading">
            <div>
              <h3>Status distribution</h3>
              <p className="muted">
                Operational snapshot of the version catalog.
              </p>
            </div>
          </div>

          <div className="page-grid">
            {["promoted", "pending", "rolled_back", "active", "failed"].map(
              (status) => {
                const count = versions.filter(
                  (version) => String(version.status) === status,
                ).length;
                return (
                  <div key={status} className="card" style={{ padding: 16 }}>
                    <p className="card-label">{status}</p>
                    <div className="summary-value">{count}</div>
                    <StatusPill label={status} />
                  </div>
                );
              },
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Full catalog</h3>
            <p className="muted">
              Table view for fast scanning and filtering outside the MCP CLI.
            </p>
          </div>
        </div>

        {versions.length ? (
          <VersionsTable versions={versions} />
        ) : (
          <div className="empty-state">No versions stored yet.</div>
        )}
      </section>
    </div>
  );
}
