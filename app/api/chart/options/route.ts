import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    ok: true,
    timeframes: ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
    symbols: ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD", "SPX500"],
  });
}
