"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DriftPoint } from "@/lib/types";

export function DimensionTrendChart({ points }: { points: DriftPoint[] }) {
  return (
    <div className="chart-shell">
      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={points}>
          <CartesianGrid stroke="rgba(34,34,34,0.12)" strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" tick={false} />
          <YAxis domain={[0, 10]} />
          <Tooltip />
          <Legend />
          <Line
            type="monotone"
            dataKey="task_completion"
            stroke="#1f3a5f"
            dot={false}
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="output_quality"
            stroke="#cf5c36"
            dot={false}
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="latency"
            stroke="#6b8f71"
            dot={false}
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="cost_efficiency"
            stroke="#b68d40"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
