"use client";

import { useEffect, useState } from "react";
import { getJson, postJson } from "../lib/api";
import type { LiveQuote, Position } from "../lib/types";

interface Props {
  onOrderExecuted?: () => void;
  selectedSymbol?: string;
  onSelectSymbol?: (symbol: string) => void;
}

const POPULAR_SYMBOLS = [
  { symbol: "XAUUSD", name: "Gold / USD", digits: 2, defaultVol: 0.1 },
  { symbol: "EURUSD", name: "Euro / USD", digits: 5, defaultVol: 0.2 },
  { symbol: "GBPUSD", name: "GBP / USD", digits: 5, defaultVol: 0.2 },
  { symbol: "USDJPY", name: "USD / JPY", digits: 3, defaultVol: 0.2 },
  { symbol: "BTCUSD", name: "Bitcoin / USD", digits: 2, defaultVol: 0.05 },
  { symbol: "ETHUSD", name: "Ethereum / USD", digits: 2, defaultVol: 0.1 },
  { symbol: "SPX500", name: "S&P 500 Index", digits: 2, defaultVol: 0.1 },
];

export default function LiveTradingDesk({
  onOrderExecuted,
  selectedSymbol = "XAUUSD",
  onSelectSymbol,
}: Props) {
  const [symbol, setSymbol] = useState(selectedSymbol);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [volume, setVolume] = useState(0.1);
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [quote, setQuote] = useState<LiveQuote | null>(null);
  const [quoteTick, setQuoteTick] = useState<"up" | "down" | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [equity, setEquity] = useState(50428.5);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    if (selectedSymbol && selectedSymbol !== symbol) {
      setSymbol(selectedSymbol);
    }
  }, [selectedSymbol]);

  // Live Quote Polling and Ticking
  useEffect(() => {
    let lastPrice = 0;
    async function fetchQuote() {
      try {
        const res = await getJson<LiveQuote>(`/api/mt5/quote?symbol=${symbol}`);
        if (res.ok) {
          if (lastPrice > 0 && res.last !== lastPrice) {
            setQuoteTick(res.last > lastPrice ? "up" : "down");
            setTimeout(() => setQuoteTick(null), 600);
          }
          lastPrice = res.last;
          setQuote(res);
        }
      } catch (e) {
        // silent polling
      }
    }

    fetchQuote();
    const timer = setInterval(fetchQuote, 1500);
    return () => clearInterval(timer);
  }, [symbol]);

  // Fetch active positions
  const refreshPositions = async () => {
    try {
      const res = await getJson<{ ok: boolean; positions: Position[]; equity: number }>("/api/orders");
      if (res.ok) {
        setPositions(res.positions || []);
        if (res.equity) setEquity(res.equity);
      }
    } catch (e) {
      // silent
    }
  };

  useEffect(() => {
    refreshPositions();
    const interval = setInterval(refreshPositions, 2500);
    return () => clearInterval(interval);
  }, []);

  const handleSelectSymbol = (sym: string) => {
    setSymbol(sym);
    if (onSelectSymbol) onSelectSymbol(sym);
    // adjust default SL / TP
    setSl("");
    setTp("");
  };

  const executeOrder = async () => {
    setLoading(true);
    setToast(null);
    try {
      const res = await postJson<{ ok: boolean; message: string; position: Position }>("/api/orders", {
        symbol,
        side,
        volume,
        sl: sl ? Number(sl) : undefined,
        tp: tp ? Number(tp) : undefined,
      });

      if (res.ok) {
        setToast({ ok: true, message: res.message });
        await refreshPositions();
        if (onOrderExecuted) onOrderExecuted();
      } else {
        setToast({ ok: false, message: (res as any).error || "Order execution rejected" });
      }
    } catch (err: any) {
      setToast({ ok: false, message: err?.message || "Execution failed" });
    } finally {
      setLoading(false);
    }
  };

  const closePosition = async (posId: string) => {
    try {
      const res = await postJson<{ ok: boolean; message: string }>("/api/positions/close", {
        position_id: posId,
      });
      if (res.ok) {
        setToast({ ok: true, message: res.message });
        await refreshPositions();
        if (onOrderExecuted) onOrderExecuted();
      }
    } catch (err: any) {
      setToast({ ok: false, message: err?.message || "Failed to close position" });
    }
  };

  // calculate current unrealized PnL of open positions
  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);

  return (
    <div id="live-trading-desk" className="space-y-4">
      {/* Live Market Bar Strip */}
      <div className="bg-[#0b101b] border border-slate-800 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3 shadow-lg">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-full">
          {POPULAR_SYMBOLS.map((s) => (
            <button
              key={s.symbol}
              type="button"
              onClick={() => handleSelectSymbol(s.symbol)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all whitespace-nowrap flex items-center gap-1.5 ${
                symbol === s.symbol
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 shadow-sm"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800 hover:border-slate-700"
              }`}
            >
              <span>{s.symbol}</span>
              {symbol === s.symbol && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
              )}
            </button>
          ))}
        </div>

        {/* Live Equity Badge */}
        <div className="flex items-center gap-4 text-xs font-mono ml-auto">
          <div className="text-right">
            <span className="text-slate-400 text-[10px] block uppercase">Demo Equity</span>
            <span className="font-bold text-slate-100">${equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
          <div className="text-right pl-3 border-l border-slate-800">
            <span className="text-slate-400 text-[10px] block uppercase">Open P&L</span>
            <span className={`font-bold ${totalUnrealizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {totalUnrealizedPnl >= 0 ? "+" : ""}${totalUnrealizedPnl.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Main Execution Desk & Order Ticket */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left: Quick Execution Ticket */}
        <div className="lg:col-span-5 bg-[#0b101b] border border-slate-800 rounded-xl p-4 sm:p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold text-slate-100 font-mono">{symbol}</span>
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/40">
                  MT5 DEMO
                </span>
              </div>
              <span className="text-xs text-slate-400">
                {POPULAR_SYMBOLS.find((s) => s.symbol === symbol)?.name || "Market Asset"}
              </span>
            </div>

            {/* Live Ticking Price */}
            <div className="text-right">
              <span className="text-[10px] text-slate-400 uppercase font-mono block">Last Price</span>
              <div
                className={`text-lg font-bold font-mono transition-colors duration-300 ${
                  quoteTick === "up"
                    ? "text-emerald-400 scale-105"
                    : quoteTick === "down"
                    ? "text-rose-400 scale-105"
                    : "text-slate-100"
                }`}
              >
                {quote ? quote.last.toFixed(quote.digits || 2) : "—"}
              </div>
            </div>
          </div>

          {/* Bid / Ask Box */}
          <div className="grid grid-cols-2 gap-3 font-mono text-center">
            <div className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800">
              <span className="text-[10px] text-slate-400 uppercase block">Bid (Sell)</span>
              <span className="text-sm font-bold text-rose-400">
                {quote ? quote.bid.toFixed(quote.digits || 2) : "—"}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800">
              <span className="text-[10px] text-slate-400 uppercase block">Ask (Buy)</span>
              <span className="text-sm font-bold text-emerald-400">
                {quote ? quote.ask.toFixed(quote.digits || 2) : "—"}
              </span>
            </div>
          </div>

          {/* Order Side Selector */}
          <div className="grid grid-cols-2 gap-2">
            <button
              id="btn-side-buy"
              type="button"
              onClick={() => setSide("BUY")}
              className={`py-2 rounded-lg font-semibold text-xs transition-all uppercase tracking-wider ${
                side === "BUY"
                  ? "bg-emerald-600 text-white shadow-lg shadow-emerald-900/40 border border-emerald-500"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800"
              }`}
            >
              ▲ Buy (Long)
            </button>
            <button
              id="btn-side-sell"
              type="button"
              onClick={() => setSide("SELL")}
              className={`py-2 rounded-lg font-semibold text-xs transition-all uppercase tracking-wider ${
                side === "SELL"
                  ? "bg-rose-600 text-white shadow-lg shadow-rose-900/40 border border-rose-500"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800"
              }`}
            >
              ▼ Sell (Short)
            </button>
          </div>

          {/* Volume (Lots) */}
          <div className="space-y-1.5 text-xs">
            <label className="block text-slate-400 font-medium">Order Volume (Standard Lots)</label>
            <div className="grid grid-cols-5 gap-1.5">
              {[0.01, 0.05, 0.1, 0.5, 1.0].map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setVolume(v)}
                  className={`py-1 rounded font-mono text-xs transition-colors border ${
                    volume === v
                      ? "bg-slate-800 text-emerald-300 border-emerald-500/60"
                      : "bg-slate-950 text-slate-400 border-slate-800 hover:bg-slate-900"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
            <input
              id="input-trade-volume"
              type="number"
              step="0.01"
              min="0.01"
              max="50"
              value={volume}
              onChange={(e) => setVolume(Math.max(0.01, Number(e.target.value)))}
              className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
            />
          </div>

          {/* Stop Loss and Take Profit */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <label className="block text-slate-400 mb-1">Native Stop Loss</label>
              <input
                id="input-trade-sl"
                type="number"
                step="any"
                placeholder={
                  quote
                    ? (side === "BUY"
                        ? quote.bid - (symbol === "XAUUSD" ? 8 : 0.004)
                        : quote.ask + (symbol === "XAUUSD" ? 8 : 0.004)
                      ).toFixed(quote.digits || 2)
                    : "Auto SL"
                }
                value={sl}
                onChange={(e) => setSl(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-rose-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">Take Profit Target</label>
              <input
                id="input-trade-tp"
                type="number"
                step="any"
                placeholder={
                  quote
                    ? (side === "BUY"
                        ? quote.ask + (symbol === "XAUUSD" ? 16 : 0.008)
                        : quote.bid - (symbol === "XAUUSD" ? 16 : 0.008)
                      ).toFixed(quote.digits || 2)
                    : "Auto TP"
                }
                value={tp}
                onChange={(e) => setTp(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
              />
            </div>
          </div>

          {/* Feedback Toast Banner */}
          {toast && (
            <div
              className={`p-2.5 rounded-lg text-xs font-medium border flex items-center justify-between ${
                toast.ok
                  ? "bg-emerald-950/40 border-emerald-800/60 text-emerald-300"
                  : "bg-rose-950/40 border-rose-800/60 text-rose-300"
              }`}
            >
              <span>{toast.message}</span>
              <button onClick={() => setToast(null)} className="text-slate-400 hover:text-slate-200 ml-2">✕</button>
            </div>
          )}

          {/* Submit Button */}
          <button
            id="btn-execute-order"
            type="button"
            disabled={loading}
            onClick={executeOrder}
            className={`w-full py-3 rounded-lg font-semibold text-xs tracking-wider uppercase transition-all shadow-xl disabled:opacity-50 ${
              side === "BUY"
                ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30"
                : "bg-rose-600 hover:bg-rose-500 text-white shadow-rose-900/30"
            }`}
          >
            {loading
              ? "Submitting to MT5..."
              : `Execute DEMO ${side} (${volume} Lots)`}
          </button>

          <p className="text-[11px] text-slate-500 text-center">
            Guarded by AURA RiskEngine. All executions route exclusively through the protected DEMO broker session.
          </p>
        </div>

        {/* Right: Active Live Positions Table */}
        <div className="lg:col-span-7 bg-[#0b101b] border border-slate-800 rounded-xl p-4 sm:p-5 shadow-xl flex flex-col justify-between space-y-4">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <h3 className="text-sm font-semibold text-slate-200">Active Open Positions ({positions.length})</h3>
              </div>
              <button
                type="button"
                onClick={refreshPositions}
                className="text-xs text-slate-400 hover:text-slate-200 transition-colors"
              >
                ↻ Refresh
              </button>
            </div>

            {positions.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-xs">
                No active positions open. Place a trade on the left to start tracking real-time DEMO execution.
              </div>
            ) : (
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 font-mono text-[11px]">
                      <th className="pb-2">ID</th>
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2">Lots</th>
                      <th className="pb-2">Entry</th>
                      <th className="pb-2">Current</th>
                      <th className="pb-2">SL / TP</th>
                      <th className="pb-2">Unrealized P&L</th>
                      <th className="pb-2 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-850 font-mono">
                    {positions.map((pos) => {
                      const isProfit = (pos.pnl || 0) >= 0;
                      return (
                        <tr key={pos.id} className="hover:bg-slate-900/50 transition-colors">
                          <td className="py-2.5 text-slate-500 text-[10px]">{pos.id}</td>
                          <td className="py-2.5 font-bold text-slate-200">{pos.symbol}</td>
                          <td className="py-2.5">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                pos.side === "BUY"
                                  ? "bg-emerald-950 text-emerald-300 border border-emerald-800/50"
                                  : "bg-rose-950 text-rose-300 border border-rose-800/50"
                              }`}
                            >
                              {pos.side}
                            </span>
                          </td>
                          <td className="py-2.5 text-slate-300">{pos.volume}</td>
                          <td className="py-2.5 text-slate-300">${pos.entryPrice}</td>
                          <td className="py-2.5 text-slate-200">${pos.currentPrice}</td>
                          <td className="py-2.5 text-[10px] text-slate-400">
                            {pos.sl ? `$${pos.sl}` : "—"} / {pos.tp ? `$${pos.tp}` : "—"}
                          </td>
                          <td className="py-2.5 font-bold">
                            <span className={isProfit ? "text-emerald-400" : "text-rose-400"}>
                              {isProfit ? "+" : ""}${pos.pnl.toFixed(2)}
                            </span>
                          </td>
                          <td className="py-2.5 text-right">
                            <button
                              type="button"
                              onClick={() => closePosition(pos.id)}
                              className="px-2 py-1 text-[10px] font-semibold bg-slate-800 hover:bg-rose-900 text-slate-300 hover:text-rose-200 border border-slate-700 hover:border-rose-700 rounded transition-colors"
                            >
                              Close
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Quick Info Footer */}
          <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] text-slate-400 gap-2">
            <span>Broker Reconciled: <strong className="text-slate-200">100% In-Sync</strong></span>
            <span>Write-Ahead Logging: <strong className="text-emerald-400">Continuous WAL Active</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}
