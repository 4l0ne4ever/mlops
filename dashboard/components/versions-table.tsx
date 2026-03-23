"use client";

import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";

import { DataGrid } from "@/components/data-grid";
import { StatusPill } from "@/components/status-pill";
import {
  formatDateTime,
  formatRelativeCount,
  formatScore,
  shortId,
} from "@/lib/format";
import type { EnrichedVersionRecord } from "@/lib/types";

const columnHelper = createColumnHelper<EnrichedVersionRecord>();

const columns: ColumnDef<EnrichedVersionRecord, any>[] = [
  columnHelper.accessor("version_label", {
    header: "Label",
    cell: (info) =>
      info.getValue() || shortId(info.row.original.version_id, 12),
  }),
  columnHelper.accessor("version_id", {
    header: "Version ID",
    cell: (info) => shortId(info.getValue(), 12),
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => <StatusPill label={String(info.getValue())} />,
  }),
  columnHelper.accessor("latest_quality_score", {
    header: "Latest Score",
    cell: (info) => formatScore(info.getValue()),
  }),
  columnHelper.display({
    id: "pass-rate",
    header: "Latest Passes",
    cell: (info) => {
      const row = info.row.original;
      return formatRelativeCount(row.passed_test_cases, row.total_test_cases);
    },
  }),
  columnHelper.accessor("created_at", {
    header: "Created",
    cell: (info) => formatDateTime(info.getValue()),
  }),
];

export function VersionsTable({
  versions,
}: {
  versions: EnrichedVersionRecord[];
}) {
  return <DataGrid data={versions} columns={columns} />;
}
