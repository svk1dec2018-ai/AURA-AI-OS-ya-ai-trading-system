import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    config: auraState.config,
  });
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const updated = auraState.updateConfig(body);
    return NextResponse.json({
      ok: true,
      message: "Configuration & credentials saved successfully",
      config: updated,
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
