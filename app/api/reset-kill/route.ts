import { NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST() {
  auraState.killLock = false;
  auraState.killReason = "";
  auraState.recordJournalEvent("KILL_LOCK_RESET", { source: "DASHBOARD_CONTROL" });

  return NextResponse.json({
    ok: true,
    kill_lock: false,
  });
}
