import { NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    corrupt: false,
    items: [...auraState.journal].reverse(),
  });
}
