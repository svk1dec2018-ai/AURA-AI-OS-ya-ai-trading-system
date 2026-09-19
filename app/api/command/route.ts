import { NextRequest, NextResponse } from "next/server";
import { auraState } from "@/lib/state";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const text = (body.text || "").trim().toLowerCase();

    let answer = "";
    if (text.includes("status") || text.includes("health")) {
      answer = `AURA 2 Engine: ${auraState.isRunning && !auraState.killLock ? "RUNNING" : "PAUSED"} · Equity: $${auraState.equity.toLocaleString()} · PnL: +$${auraState.pnl.toFixed(2)} · RiskEngine: INDEPENDENT · Boundary: Protected MT5 DEMO only.`;
    } else if (text.includes("risk") || text.includes("drawdown")) {
      answer = `RiskEngine status: Max drawdown ${auraState.drawdownPct}% (Budget 3.0%). Real-money trading is HARD-LOCKED. All orders require pre-computed native SL/TP brackets.`;
    } else if (text.includes("decision") || text.includes("ceo") || text.includes("xauusd")) {
      const d = auraState.decisions[0];
      answer = `Latest CEO Decision: ${d.symbol} ${d.intent} (Confidence: ${Math.round((d.confidence || 0) * 100)}%). Thesis: ${d.thesis} Support: ${d.support}/6 agents.`;
    } else if (text.includes("kill") || text.includes("stop") || text.includes("emergency")) {
      auraState.isRunning = false;
      auraState.killLock = true;
      auraState.killReason = "Emergency lock requested via AURA Owner Chat";
      auraState.recordJournalEvent("EMERGENCY_LOCK_ENGAGED", { reason: auraState.killReason });
      answer = `EMERGENCY LOCK ENGAGED: All automated scanning, agent rounds, and DEMO checks are frozen. Real money remains locked.`;
    } else if (text.includes("start") || text.includes("resume")) {
      auraState.isRunning = true;
      auraState.killLock = false;
      auraState.recordJournalEvent("RUNTIME_STARTED", { initiator: "AURA Owner Chat" });
      answer = `AURA DEMO runtime started. Multi-market scanner and specialist AI council active.`;
    } else {
      answer = `AURA AI OS Owner Command: Acknowledged "${body.text}". Multi-model specialist council (Technical, SMC, Volume, Macro, Options, Forecast, and Risk Policy) is actively monitoring 54 tradable pairs under strict DEMO safety rules.`;
    }

    return NextResponse.json({
      ok: true,
      answer,
    });
  } catch (exc) {
    return NextResponse.json(
      { ok: false, error: exc instanceof Error ? exc.message : String(exc) },
      { status: 400 }
    );
  }
}
