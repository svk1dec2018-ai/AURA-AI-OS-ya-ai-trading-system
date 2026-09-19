import { NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    service: "aura-web-v3",
    ui_version: 2,
    demo_only: true,
    real_money_enabled: false,
    runtime_running: auraState.isRunning && !auraState.killLock,
    runtime_exit_code: null,
    recovery_error: null,
    owner_auth_required: false,
  });
}
