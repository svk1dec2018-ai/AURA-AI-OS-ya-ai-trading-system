import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const positionId = body.position_id;
    if (!positionId) {
      return NextResponse.json({ ok: false, error: "Missing position_id" }, { status: 400 });
    }

    const res = auraState.closeDemoPosition(positionId);
    if (!res.ok) {
      return NextResponse.json({ ok: false, error: "Position not found or already closed" }, { status: 404 });
    }

    return NextResponse.json({
      ok: true,
      message: `Position closed. Realized PnL: ${res.realizedPnl >= 0 ? "+" : ""}$${res.realizedPnl.toFixed(2)}`,
      positions: auraState.positions,
      equity: auraState.equity,
      realized_pnl: res.realizedPnl,
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
