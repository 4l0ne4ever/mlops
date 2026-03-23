import { NextResponse } from "next/server";

import { getComparisonData } from "@/lib/data";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const left = searchParams.get("left") ?? undefined;
    const right = searchParams.get("right") ?? undefined;
    return NextResponse.json(await getComparisonData(left, right));
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 },
    );
  }
}