import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") || "XAUUSD";
  const side = (searchParams.get("side") || "BUY").toUpperCase();
  const quote = auraState.getLiveQuote(symbol);

  const entry = side === "BUY" ? quote.ask : quote.bid;
  const delta = symbol === "XAUUSD" ? 8.0 : symbol.includes("USD") ? 0.0035 : 45.0;
  const sl = side === "BUY" ? Number((entry - delta).toFixed(2)) : Number((entry + delta).toFixed(2));
  const tp = side === "BUY" ? Number((entry + delta * 2).toFixed(2)) : Number((entry - delta * 2).toFixed(2));

  return NextResponse.json({
    ok: true,
    symbol,
    side,
    execution_ready: true,
    order_check_attempted: true,
    order_submission_attempted: false,
    minimum_volume: 0.01,
    entry_price: entry,
    native_stop: sl,
    native_target: tp,
    margin_required: Number((entry * 0.02).toFixed(2)),
    real_money_enabled: false,
    boundary: "MT5 DEMO ONLY",
  });
}
