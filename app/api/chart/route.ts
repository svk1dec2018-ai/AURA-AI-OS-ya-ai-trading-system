import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") || "XAUUSD";
  const timeframe = searchParams.get("timeframe") || "5m";
  const bars = parseInt(searchParams.get("bars") || "300", 10);

  const snapshot = auraState.generateCandles(symbol, timeframe, isNaN(bars) ? 300 : bars);
  return NextResponse.json(snapshot);
}
