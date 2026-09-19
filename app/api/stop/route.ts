import { NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST() {
  auraState.isRunning = false;
  auraState.recordJournalEvent("RUNTIME_STOPPED", { source: "DASHBOARD_CONTROL" });
  return NextResponse.json({
    ok: true,
    stopped: true,
    runtime_running: false,
  });
}
