import { NextResponse } from "next/server";
import { STRATEGY_TEMPLATES } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    templates: STRATEGY_TEMPLATES,
    entries: ["ema_cross", "liquidity_sweep", "rsi_oversold", "breakout", "bollinger_reversion", "keltner_breakout", "macd_momentum"],
    confirmations: ["volume_expansion", "higher_timeframe_trend", "delta_divergence", "chop_regime", "premium_discount"],
    exits: ["trailing_atr", "fixed_rr", "regime_change"],
  });
}
