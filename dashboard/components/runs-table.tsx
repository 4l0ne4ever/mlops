"use client";

import Link from "next/link";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";

import { DataGrid } from "@/components/data-grid";
import { StatusPill } from "@/components/status-pill";
import {
  formatDateTime,
  formatRelativeCount,
  formatScore,
  shortId,
} from "@/lib/format";
import type { EnrichedRunRecord } from "@/lib/types";

const columnHelper = createColumnHelper<EnrichedRunRecord>();

const columns: ColumnDef<EnrichedRunRecord, any>[] = [
  columnHelper.accessor("run_id", {
    header: "Run",
    cell: (info) => (
      <Link href={`/runs/${info.getValue()}`}>
        {shortId(info.getValue(), 12)}
      </Link>
    ),
  }),
  columnHelper.accessor("version_id", {
    header: "Version",
    cell: (info) => shortId(info.getValue(), 12),
  }),
  columnHelper.accessor("quality_score", {
    header: "Quality",
    cell: (info) => formatScore(info.getValue()),
  }),
  columnHelper.display({
    id: "pass-rate",
    header: "Pass Rate",
    cell: (info) => {
      const row = info.row.original;
      return formatRelativeCount(row.passed_test_cases, row.total_test_cases);
    },
  }),
  columnHelper.accessor("decision", {
    header: "Decision",
    cell: (info) => <StatusPill label={info.getValue()} />,
  }),
  columnHelper.accessor("timestamp", {
    header: "Timestamp",
    cell: (info) => formatDateTime(info.getValue()),
  }),
];

export function RunsTable({ runs }: { runs: EnrichedRunRecord[] }) {
  return <DataGrid data={runs} columns={columns} />;
}
