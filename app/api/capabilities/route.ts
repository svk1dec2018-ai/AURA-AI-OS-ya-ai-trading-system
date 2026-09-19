import { NextResponse } from "next/server";
import { CAPABILITIES } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    count: CAPABILITIES.length,
    items: CAPABILITIES,
  });
}
