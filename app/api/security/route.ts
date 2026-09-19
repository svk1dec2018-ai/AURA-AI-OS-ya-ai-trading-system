import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    ok: true,
    owner_auth_required: false,
    real_money_enabled: false,
    environment: "production_candidate_demo",
  });
}
