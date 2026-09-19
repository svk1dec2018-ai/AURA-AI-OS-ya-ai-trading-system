import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") || "XAUUSD";
  const quote = auraState.getLiveQuote(symbol);
  return NextResponse.json(quote);
}
