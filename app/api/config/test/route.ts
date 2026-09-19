import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const type = body.type || "mt5";
    const result = auraState.testIntegration(type, body.overrides);
    return NextResponse.json({
      ok: true,
      ...result,
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
