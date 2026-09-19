import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function GET() {
  return NextResponse.json({
    ok: true,
    positions: auraState.positions,
    equity: auraState.equity,
    pnl: auraState.pnl,
    submitted_orders: auraState.submittedOrders,
    fills: auraState.fills,
  });
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const symbol = (body.symbol || "XAUUSD").toUpperCase();
    const side = (body.side || "BUY").toUpperCase() as "BUY" | "SELL";
    const volume = Number(body.volume) || 0.1;
    const sl = body.sl ? Number(body.sl) : undefined;
    const tp = body.tp ? Number(body.tp) : undefined;

    if (auraState.killLock) {
      return NextResponse.json(
        { ok: false, error: "Cannot execute orders: Kill lock is engaged." },
        { status: 403 }
      );
    }

    const pos = auraState.openDemoPosition({ symbol, side, volume, sl, tp });

    return NextResponse.json({
      ok: true,
      message: `DEMO ${side} order executed for ${volume} lots of ${symbol} at $${pos.entryPrice}`,
      position: pos,
      positions: auraState.positions,
      equity: auraState.equity,
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
