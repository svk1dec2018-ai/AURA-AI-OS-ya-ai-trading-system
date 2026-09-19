"use client";

import MarketChart from "./MarketChart";
import type { Decision, JsonMap, MT5LiveSnapshot } from "../lib/types";

function n(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function cash(value: unknown, currency = ""): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return (currency ? currency + " " : "") +
    parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function pct(value: unknown): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  const normalized = parsed <= 1 ? parsed * 100 : parsed;
  return normalized.toFixed(1) + "%";
}

function price(value: unknown, digits = 2): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed !== 0 ? parsed.toFixed(digits) : "—";
}

export default function LiveTradingTerminal({
  live,
  liveError,
  decision,
  runtime,
  readiness,
  busy,
  onStart,
  onStop,
  onKill,
}: {
  live: MT5LiveSnapshot | null;
  liveError: string;
  decision: Decision | null;
  runtime: JsonMap;
  readiness: JsonMap | null;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
  onKill: () => void;
}) {
  const currency = live?.account?.currency || "";
  const positions = live?.positions || [];
  const orders = live?.orders || [];
  const watch = (live?.watchlist || []).filter((item) => item.ok);
  const confidence = n(decision?.confidence);
  const mt5Connected = Boolean(live?.terminal?.connected);
  const runtimeRunning = Boolean(runtime?.runtime_running);
  const riskLocked = Boolean(runtime?.app_kill_locked || runtime?.status?.risk_kill_switch);

  return (
    <div className="terminal-overview">
      <section className="terminal-head">
        <div className="terminal-identity">
          <div className={mt5Connected ? "live-dot good" : "live-dot"} />
          <div>
            <div className="terminal-title-row">
              <h2>AURA LIVE TERMINAL</h2>
              <span className={mt5Connected ? "terminal-badge live" : "terminal-badge offline"}>
                {mt5Connected ? "MT5 DEMO LIVE" : "MT5 OFFLINE"}
              </span>
              <span className={runtimeRunning ? "terminal-badge live" : "terminal-badge"}>
                ENGINE {runtimeRunning ? "RUNNING" : "STOPPED"}
              </span>
            </div>
            <p>
              {live
                ? (live.account.server || "MT5") + " · Account ••••" + (live.account.login_last4 || "—") +
                  " · 1:" + (live.account.leverage || "—")
                : liveError || "Waiting for MetaTrader 5 DEMO session..."}
            </p>
          </div>
        </div>
        <div className="terminal-actions">
          <button className="primary" disabled={busy || !mt5Connected || riskLocked} onClick={onStart}>
            ▶ Start AURA DEMO
          </button>
          <button disabled={busy || !runtimeRunning} onClick={onStop}>■ Stop</button>
          <button className="danger" disabled={busy} onClick={onKill}>Emergency Lock</button>
        </div>
      </section>

      <section className="terminal-account-strip">
        <AccountCell label="BALANCE" value={cash(live?.account.balance, currency)} />
        <AccountCell label="EQUITY" value={cash(live?.account.equity, currency)} />
        <AccountCell
          label="FLOATING P&L"
          value={cash(live?.account.profit, currency)}
          tone={n(live?.account.profit) > 0 ? "up" : n(live?.account.profit) < 0 ? "down" : ""}
        />
        <AccountCell label="FREE MARGIN" value={cash(live?.account.margin_free, currency)} />
        <AccountCell label="MARGIN LEVEL" value={live?.account.margin_level ? n(live.account.margin_level).toFixed(1) + "%" : "—"} />
        <AccountCell label="OPEN POSITIONS" value={String(live?.position_count ?? 0)} />
        <AccountCell label="PENDING ORDERS" value={String(live?.order_count ?? 0)} />
        <AccountCell
          label="RISK STATE"
          value={riskLocked ? "LOCKED" : readiness?.mt5_runtime_ready ? "READY" : "CHECK"}
          tone={riskLocked ? "down" : readiness?.mt5_runtime_ready ? "up" : ""}
        />
      </section>

      <section className="terminal-ticker">
        {watch.length ? watch.map((item) => {
          const change = n(item.change_pct);
          const digits = item.digits ?? 2;
          return (
            <div className="ticker-item" key={item.symbol}>
              <div><b>{item.symbol}</b><span>{item.description || item.requested_symbol}</span></div>
              <strong>{price(item.mid || item.last || item.bid, digits)}</strong>
              <em className={change > 0 ? "up" : change < 0 ? "down" : ""}>
                {item.change_pct == null ? "LIVE" : (change >= 0 ? "+" : "") + change.toFixed(2) + "%"}
              </em>
            </div>
          );
        }) : (
          <div className="ticker-empty">Market Watch will populate directly from the connected MT5 DEMO terminal.</div>
        )}
      </section>

      <section className="terminal-main-grid">
        <div className="terminal-chart-card">
          <header className="terminal-panel-head">
            <div><b>MARKET CHART</b><span>Broker candles + technical overlays</span></div>
            <span className="terminal-badge">{runtimeRunning ? "AURA SCANNING" : "MANUAL VIEW"}</span>
          </header>
          <MarketChart />
        </div>

        <aside className="terminal-right">
          <section className="terminal-side-card ai-verdict-card">
            <header><b>AURA AI VERDICT</b><span>{decision?.created_at ? new Date(decision.created_at).toLocaleTimeString() : "No live round"}</span></header>
            <div className="verdict-core">
              <div className={"verdict-intent " + (
                String(decision?.intent || "").includes("LONG") || String(decision?.intent || "").includes("BUY")
                  ? "up" : String(decision?.intent || "").includes("SHORT") || String(decision?.intent || "").includes("SELL")
                  ? "down" : ""
              )}>
                {decision?.intent || "WAIT"}
              </div>
              <div className="verdict-confidence">
                <span>Confidence</span><strong>{pct(decision?.confidence)}</strong>
              </div>
            </div>
            <div className="terminal-meter"><i style={{ width: Math.min(100, confidence * 100) + "%" }} /></div>
            <p>{decision?.thesis || "AURA runtime has not produced a governed trading decision yet."}</p>
            <div className="verdict-stats">
              <span>Support <b>{decision?.support ?? "—"}</b></span>
              <span>Oppose <b>{decision?.opposition ?? "—"}</b></span>
              <span>Abstain <b>{decision?.abstentions ?? "—"}</b></span>
            </div>
          </section>

          <section className="terminal-side-card">
            <header><b>MARKET WATCH</b><span>{watch.length} live</span></header>
            <div className="watch-table">
              <div className="watch-row head"><span>Symbol</span><span>Bid</span><span>Ask</span><span>Spr</span></div>
              {watch.slice(0, 8).map((item) => (
                <div className="watch-row" key={item.symbol}>
                  <span><b>{item.symbol}</b></span>
                  <span>{price(item.bid, item.digits ?? 2)}</span>
                  <span>{price(item.ask, item.digits ?? 2)}</span>
                  <span>{item.spread_points == null ? "—" : n(item.spread_points).toFixed(1)}</span>
                </div>
              ))}
              {!watch.length ? <div className="terminal-empty">No broker quotes yet.</div> : null}
            </div>
          </section>

          <section className="terminal-side-card">
            <header><b>AI COUNCIL</b><span>{decision?.evidence?.length || 0} agents</span></header>
            <div className="mini-agent-list">
              {(decision?.evidence || []).slice(0, 7).map((item: JsonMap, index: number) => (
                <div key={item.agent_id || index}>
                  <span>{item.role || item.agent_id || "Agent"}</span>
                  <b>{pct(item.confidence)}</b>
                </div>
              ))}
              {!decision?.evidence?.length ? <div className="terminal-empty">Start AURA DEMO to populate specialist evidence.</div> : null}
            </div>
          </section>
        </aside>
      </section>

      <section className="terminal-bottom-grid">
        <section className="terminal-table-card">
          <header className="terminal-panel-head">
            <div><b>OPEN POSITIONS</b><span>Direct MT5 account snapshot · updates without starting AURA</span></div>
            <span className="terminal-badge">{positions.length}</span>
          </header>
          <div className="terminal-table-wrap">
            <table className="terminal-table">
              <thead><tr><th>Symbol</th><th>Side</th><th>Volume</th><th>Open</th><th>Current</th><th>SL</th><th>TP</th><th>P&L</th></tr></thead>
              <tbody>
                {positions.length ? positions.map((position) => (
                  <tr key={position.ticket}>
                    <td><b>{position.symbol}</b></td>
                    <td className={position.side === "BUY" ? "up" : "down"}>{position.side}</td>
                    <td>{position.volume}</td>
                    <td>{position.price_open}</td>
                    <td>{position.price_current}</td>
                    <td>{position.sl || "—"}</td>
                    <td>{position.tp || "—"}</td>
                    <td className={position.profit > 0 ? "up" : position.profit < 0 ? "down" : ""}>
                      {cash(position.profit, currency)}
                    </td>
                  </tr>
                )) : <tr><td colSpan={8} className="terminal-empty">No open MT5 positions.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <section className="terminal-table-card compact">
          <header className="terminal-panel-head">
            <div><b>EXECUTION STATUS</b><span>Safety boundary</span></div>
          </header>
          <div className="execution-status-grid">
            <StatusItem label="MT5 connection" value={mt5Connected ? "CONNECTED" : "OFFLINE"} good={mt5Connected} />
            <StatusItem label="Trading runtime" value={runtimeRunning ? "RUNNING" : "STOPPED"} good={runtimeRunning} />
            <StatusItem label="API trading" value={live?.terminal?.tradeapi_disabled ? "DISABLED" : "AVAILABLE"} good={!live?.terminal?.tradeapi_disabled} />
            <StatusItem label="Real money" value="LOCKED" good={false} />
          </div>
          {orders.length ? <div className="pending-order-note">{orders.length} pending MT5 order(s) detected.</div> : null}
        </section>
      </section>
    </div>
  );
}

function AccountCell({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return <div className="account-cell"><span>{label}</span><strong className={tone}>{value}</strong></div>;
}

function StatusItem({ label, value, good }: { label: string; value: string; good: boolean }) {
  return <div className="execution-status"><span>{label}</span><b className={good ? "up" : "down"}>{value}</b></div>;
}
