import { NextResponse } from "next/server";

import { getRunDetail } from "@/lib/data";

export const dynamic = "force-dynamic";

type RouteProps = {
  params: Promise<{ runId: string }>;
};

export async function GET(_: Request, { params }: RouteProps) {
  try {
    const { runId } = await params;
    const run = await getRunDetail(runId);
    if (!run) {
      return NextResponse.json({ error: "Run not found" }, { status: 404 });
    }
    return NextResponse.json(run);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 },
    );
  }
}