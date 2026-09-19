import { NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET() {
  const ws = auraState.getWorkspace();
  return NextResponse.json({
    ok: true,
    runtime_running: auraState.isRunning && !auraState.killLock,
    status: ws.runtime?.status,
  });
}
