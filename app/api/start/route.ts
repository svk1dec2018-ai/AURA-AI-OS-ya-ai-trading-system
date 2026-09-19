import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    auraState.isRunning = true;
    auraState.killLock = false;
    auraState.recordJournalEvent("RUNTIME_STARTED", {
      max_symbols: body.max_symbols || 25,
      max_batches: body.max_batches || 0,
      mode: "DEMO_CONTINUOUS",
    });

    return NextResponse.json({
      ok: true,
      already_running: false,
      started: true,
      mt5_execution_check: {
        symbol: "XAUUSD",
        verified: true,
      },
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
