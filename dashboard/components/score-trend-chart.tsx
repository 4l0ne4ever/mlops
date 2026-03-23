"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DriftPoint } from "@/lib/types";

export function ScoreTrendChart({ points }: { points: DriftPoint[] }) {
  return (
    <div className="chart-shell">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={points}>
          <CartesianGrid stroke="rgba(34,34,34,0.12)" strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" tick={false} />
          <YAxis domain={[0, 10]} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="quality_score"
            stroke="#cf5c36"
            strokeWidth={3}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
