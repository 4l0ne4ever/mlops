import { AutoRefresh } from "@/components/auto-refresh";
import { DimensionTrendChart } from "@/components/dimension-trend-chart";
import { ScoreTrendChart } from "@/components/score-trend-chart";
import { SummaryCard } from "@/components/summary-card";
import { formatScore, shortId } from "@/lib/format";
import { getDriftData } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function DriftPage() {
  const { points } = await getDriftData();
  const latest = points[points.length - 1];
  const earliest = points[0];
  const drift =
    latest && earliest ? latest.quality_score - earliest.quality_score : 0;

  return (
    <div className="page-grid">
      <AutoRefresh intervalMs={30000} />

      <section className="section-heading">
        <div>
          <p className="eyebrow">Metric Drift</p>
          <h2>Quality trend and per-dimension movement across eval history</h2>
        </div>
      </section>

      <div className="metrics-grid">
        <SummaryCard
          label="Latest Version"
          value={shortId(latest?.version_id, 12)}
          detail="Newest run on record."
          accent="ink"
        />
        <SummaryCard
          label="Latest Score"
          value={formatScore(latest?.quality_score)}
          detail="Composite quality score."
          accent="gold"
        />
        <SummaryCard
          label="Total Points"
          value={points.length}
          detail="Eval results included in this trend."
          accent="coral"
        />
        <SummaryCard
          label="Net Drift"
          value={drift >= 0 ? `+${formatScore(drift)}` : formatScore(drift)}
          detail="Latest minus earliest visible point."
          accent="ink"
        />
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Quality Score drift</h3>
            <p className="muted">
              Pulled from stored eval results. This remains accurate even before
              dedicated score metrics are emitted.
            </p>
          </div>
        </div>
        {points.length ? (
          <ScoreTrendChart points={points} />
        ) : (
          <div className="empty-state">No drift data available.</div>
        )}
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h3>Dimension drill-down</h3>
            <p className="muted">
              Task completion, output quality, latency, and cost efficiency over
              time.
            </p>
          </div>
        </div>
        {points.length ? (
          <DimensionTrendChart points={points} />
        ) : (
          <div className="empty-state">No dimension data available.</div>
        )}
      </section>
    </div>
  );
}
