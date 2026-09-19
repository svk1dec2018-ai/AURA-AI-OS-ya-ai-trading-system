import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  auraState.isRunning = false;
  auraState.killLock = true;
  auraState.killReason = body.reason || "Emergency lock from AURA 2 dashboard";
  auraState.recordJournalEvent("KILL_LOCK_ENGAGED", { reason: auraState.killReason });

  return NextResponse.json({
    ok: true,
    kill_lock: true,
    reason: auraState.killReason,
  });
}
