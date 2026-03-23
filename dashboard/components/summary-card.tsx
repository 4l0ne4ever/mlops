import { ReactNode } from "react";

export function SummaryCard({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: ReactNode;
  detail: string;
  accent?: "gold" | "ink" | "coral";
}) {
  return (
    <section className={`card summary-card accent-${accent ?? "gold"}`}>
      <p className="card-label">{label}</p>
      <div className="summary-value">{value}</div>
      <p className="card-detail">{detail}</p>
    </section>
  );
}
