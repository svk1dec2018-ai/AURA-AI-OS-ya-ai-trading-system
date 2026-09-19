"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import MarketChart from "./MarketChart";
import LiveTradingTerminal from "./LiveTradingTerminal";
import { CapabilityExplorer, ExecutionPreview, ResearchStudio, TradeJournal } from "./AdvancedTools";
import { getJson, postJson, tryGetJson } from "../lib/api";
import type { Decision, JsonMap, MT5LiveSnapshot, Workspace } from "../lib/types";

type View =
  | "overview" | "markets" | "charts" | "opportunities" | "trading" | "portfolio"
  | "brain" | "debate" | "risk" | "performance" | "research" | "learning"
  | "news" | "journal" | "studio" | "capabilities" | "system" | "owner";

const NAV: Array<[View, string, string]> = [
  ["overview", "Overview", "OV"],
  ["markets", "Markets", "MK"],
  ["charts", "Live Charts", "CH"],
  ["opportunities", "Opportunities", "OP"],
  ["trading", "Trading Desk", "TR"],
  ["portfolio", "Portfolio", "PF"],
  ["brain", "AI Brain", "AI"],
  ["debate", "Agent Debate", "DB"],
  ["risk", "Risk Center", "RK"],
  ["performance", "Performance", "PA"],
  ["research", "Research Lab", "RL"],
  ["learning", "Learning", "EV"],
  ["news", "News / Macro", "NW"],
  ["journal", "Trade Journal", "TJ"],
  ["studio", "Strategy Studio", "ST"],
  ["capabilities", "All Features", "AZ"],
  ["system", "System Health", "HL"],
  ["owner", "Owner / JARVIS", "JR"],
];

function num(value: any, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function pct(value: any) {
  const parsed = num(value, NaN);
  if (!Number.isFinite(parsed)) return "—";
  const normalized = parsed <= 1 ? parsed * 100 : parsed;
  return normalized.toFixed(1) + "%";
}

function money(value: any, currency = "") {
  const parsed = num(value, NaN);
  if (!Number.isFinite(parsed)) return "—";
  const formatted = parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return (currency ? currency + " " : "") + formatted;
}

function latestDecision(workspace: Workspace | null): Decision | null {
  return workspace?.decisions?.items?.[0] || null;
}

export default function AuraControlRoom() {
  const [view, setView] = useState<View>("overview");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [readiness, setReadiness] = useState<JsonMap | null>(null);
  const [liveMt5, setLiveMt5] = useState<MT5LiveSnapshot | null>(null);
  const [liveMt5Error, setLiveMt5Error] = useState("");
  const [candidates, setCandidates] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [serviceState, setServiceState] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [jarvisOpen, setJarvisOpen] = useState(false);
  const [jarvisInput, setJarvisInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: "user" | "aura"; text: string }>>([
    {
      role: "aura",
      text: "AURA ready. Ask about MT5, risk, P&L, agents, opportunities, research or system status.",
    },
  ]);
  const [ownerToken, setOwnerToken] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  async function refresh() {
    const [healthResult, workspaceResult, readinessResult, algoResult] = await Promise.all([
      tryGetJson<JsonMap>("/api/health"),
      tryGetJson<Workspace>("/api/workspace"),
      tryGetJson<JsonMap>("/api/readiness"),
      tryGetJson<JsonMap>("/api/algo/candidates"),
    ]);

    const nextState: Record<string, { ok: boolean; detail: string }> = {
      backend: healthResult.ok
        ? { ok: true, detail: "Backend connected" }
        : { ok: false, detail: "error" in healthResult ? healthResult.error : "Backend unavailable" },
      workspace: workspaceResult.ok
        ? { ok: true, detail: "Workspace loaded" }
        : { ok: false, detail: "error" in workspaceResult ? workspaceResult.error : "Workspace unavailable" },
      mt5: readinessResult.ok
        ? {
            ok: Boolean(readinessResult.data.mt5_runtime_ready),
            detail: readinessResult.data.mt5_runtime_ready
              ? "MT5 DEMO ready"
              : readinessResult.data.demo_state || "MT5 runtime not ready",
          }
        : { ok: false, detail: "error" in readinessResult ? readinessResult.error : "MT5 readiness unavailable" },
      research: algoResult.ok
        ? { ok: true, detail: "Research catalog loaded" }
        : { ok: false, detail: "error" in algoResult ? algoResult.error : "Research catalog unavailable" },
    };
    setServiceState(nextState);

    if (workspaceResult.ok) setWorkspace(workspaceResult.data);
    if (readinessResult.ok) setReadiness(readinessResult.data);
    if (algoResult.ok) setCandidates(algoResult.data.items || []);

    const hardErrors = Object.entries(nextState)
      .filter(([key, value]) => key !== "mt5" && !value.ok)
      .map(([key, value]) => key.toUpperCase() + ": " + value.detail);
    setError(hardErrors.join(" | "));
  }

  useEffect(() => {
    setOwnerToken(sessionStorage.getItem("aura-owner-token") || "");
    refresh();
    const timer = window.setInterval(refresh, 8000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    async function refreshLiveMt5() {
      const result = await tryGetJson<MT5LiveSnapshot>(
        "/api/mt5/live?symbols=XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,USOIL"
      );
      if (!active) return;
      if (result.ok) {
        setLiveMt5(result.data);
        setLiveMt5Error("");
        setServiceState((current) => ({
          ...current,
          mt5: { ok: true, detail: "MT5 DEMO live account + market data" },
        }));
      } else {
        const detail = "error" in result ? result.error : "MT5 live snapshot unavailable";
        setLiveMt5(null);
        setLiveMt5Error(detail);
        setServiceState((current) => ({
          ...current,
          mt5: { ok: false, detail },
        }));
      }
    }
    refreshLiveMt5();
    const timer = window.setInterval(refreshLiveMt5, 1500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const runtime = workspace?.runtime || {};
  const status = runtime.status || {};
  const baseline = runtime.baseline || {};
  const brain = runtime.brain || {};
  const decision = latestDecision(workspace);
  const decisions = workspace?.decisions?.items || [];
  const intelligence = workspace?.intelligence?.items || [];
  const learning = workspace?.learning || {};
  const capabilityItems = workspace?.capabilities?.items || [];
  const currency = liveMt5?.account?.currency || baseline.currency || "";
  const mtf = brain.aura2_mtf?.latest || {};
  const firstMtf = Object.values(mtf)[0] as JsonMap | undefined;

  const stats = useMemo(() => ({
    equity: status.equity ?? status.portfolio?.equity ?? baseline.starting_balance,
    pnl: status.realized_pnl ?? status.pnl ?? 0,
    drawdown: status.drawdown_pct ?? status.max_drawdown_pct,
    opportunities: status.opportunities ?? status.counters?.opportunities ?? decisions.length,
    orders: status.submitted_orders ?? status.counters?.submitted_orders ?? 0,
    fills: status.fills ?? status.counters?.fills ?? 0,
  }), [status, baseline, decisions.length]);

  async function runtimeAction(path: string, body: JsonMap = {}) {
    setActionBusy(true);
    try {
      await postJson(path, body);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setActionBusy(false);
    }
  }

  async function sendJarvis(event: FormEvent) {
    event.preventDefault();
    const text = jarvisInput.trim();
    if (!text) return;
    setJarvisInput("");
    setMessages((items) => items.concat({ role: "user", text }));
    try {
      const result = await postJson<JsonMap>("/api/command", { text });
      setMessages((items) => items.concat({ role: "aura", text: result.answer || "Command handled." }));
    } catch (exc) {
      const detail = exc instanceof Error ? exc.message : String(exc);
      setMessages((items) => items.concat({ role: "aura", text: "Blocked: " + detail }));
    }
  }

  function saveToken(value: string) {
    setOwnerToken(value);
    if (value) sessionStorage.setItem("aura-owner-token", value);
    else sessionStorage.removeItem("aura-owner-token");
  }

  const pageName = NAV.find((item) => item[0] === view)?.[1] || "AURA 2";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-orb">A</div>
          <div><b>AURA 2</b><span>AI Trading OS</span></div>
        </div>
        <div className="mode-card">
          <small>Execution boundary</small>
          <strong>MT5 DEMO / RESEARCH</strong>
          <span className={runtime.runtime_running ? "pulse good" : "pulse"} />
        </div>
        <nav>
          {NAV.map(([id, label, icon]) => (
            <button
              key={id}
              className={view === id ? "nav active" : "nav"}
              onClick={() => setView(id)}
            >
              <span className="nav-icon">{icon}</span><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div>RiskEngine <b>INDEPENDENT</b></div>
          <div>Real money <b className="red">LOCKED</b></div>
          <div>Fund movement <b className="red">BLOCKED</b></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p>AURA OWNER CONTROL ROOM</p>
            <h1>{pageName}</h1>
          </div>
          <div className="top-actions">
            <span className={liveMt5?.terminal?.connected ? "chip good" : "chip"}>
              MT5 {liveMt5?.terminal?.connected ? "LIVE" : "WAITING"}
            </span>
            <span className={runtime.runtime_running ? "chip good" : "chip"}>
              ENGINE {runtime.runtime_running ? "RUNNING" : "STOPPED"}
            </span>
            <button className="jarvis-button" onClick={() => setJarvisOpen(true)}>✦ AURA</button>
          </div>
        </header>

        <div className="content">
          <ServiceStrip state={serviceState} />
          {error ? (
            <div className="alert error">
              <b>AURA service problem:</b> {error}
              <div className="alert-help">Backend/MT5 failure no longer blanks the whole dashboard. Open System Health for the exact failing service.</div>
            </div>
          ) : null}

          {view === "overview" && (
            <LiveTradingTerminal
              live={liveMt5}
              liveError={liveMt5Error}
              decision={decision}
              runtime={runtime}
              readiness={readiness}
              busy={actionBusy}
              onStart={() => runtimeAction("/api/start", { max_symbols: 25, max_batches: 0 })}
              onStop={() => runtimeAction("/api/stop")}
              onKill={() => runtimeAction("/api/kill", { reason: "Emergency lock from AURA 2 live terminal" })}
            />
          )}

          {view === "charts" && <Panel title="Professional MT5 chart" badge="Live quote + closed candles"><MarketChart /></Panel>}

          {(view === "markets" || view === "opportunities") && (
            <Panel title={view === "markets" ? "Market scanner" : "Ranked opportunities"} badge="Evidence">
              <DecisionTable items={decisions} />
            </Panel>
          )}

          {view === "brain" && (
            <section className="grid two">
              <Panel title="CEO decision" badge="Explainable"><DecisionDetail decision={decision} /></Panel>
              <Panel title="Specialist evidence" badge="Live"><AgentEvidence decision={decision} detailed /></Panel>
            </section>
          )}

          {view === "debate" && (
            <Panel title="Bull / Bear / Counterfactual debate" badge="Adversarial"><Debate decision={decision} /></Panel>
          )}

          {view === "risk" && (
            <section className="grid two">
              <Panel title="Release readiness" badge={readiness?.demo_state || "CHECK"}><ReadinessList readiness={readiness} /></Panel>
              <Panel title="Permanent authority boundaries" badge="Fail closed">
                <div className="guard-grid">
                  <Guard good text="Independent RiskEngine" />
                  <Guard good text="Native SL/TP required" />
                  <Guard good text="DEMO account guard" />
                  <Guard good text="AI cannot bypass risk" />
                  <Guard text="Real money locked" />
                  <Guard text="Withdrawal blocked" />
                  <Guard text="Fund transfer blocked" />
                  <Guard text="External agents cannot submit orders" />
                </div>
              </Panel>
            </section>
          )}

          {view === "trading" && (
            <section className="grid two">
              <Panel title="Protected execution controls" badge="DEMO">
                <div className="control-stack">
                  <button className="primary" disabled={actionBusy} onClick={() => runtimeAction("/api/start", { max_symbols: 25, max_batches: 0 })}>Start continuous DEMO</button>
                  <button disabled={actionBusy} onClick={() => runtimeAction("/api/stop")}>Stop runtime</button>
                  <button className="danger" disabled={actionBusy} onClick={() => runtimeAction("/api/kill", { reason: "Owner emergency lock" })}>Emergency lock</button>
                </div>
                <div className="safety-note">Manual direct order submission is intentionally not exposed here. Autonomous orders still pass CEO → RiskEngine → protected MT5 adapter.</div>
              </Panel>
              <Panel title="Execution telemetry" badge="Broker">
                <KeyValue label="Runtime" value={runtime.runtime_running ? "RUNNING" : "STOPPED"} />
                <KeyValue label="Orders" value={String(stats.orders)} />
                <KeyValue label="Fills" value={String(stats.fills)} />
                <KeyValue label="Reconciliations" value={String(status.reconciliations ?? status.counters?.reconciliations ?? 0)} />
                <KeyValue label="Kill switch" value={runtime.app_kill_locked || status.risk_kill_switch ? "LOCKED" : "CLEAR"} />
              </Panel>
              <Panel title="Broker-safe order preview" badge="NO SEND">
                <ExecutionPreview />
              </Panel>
            </section>
          )}

          {view === "portfolio" && (
            <section className="metrics">
              <Metric label="Balance" value={money(liveMt5?.account?.balance ?? baseline.starting_balance, currency)} sub="Direct MT5 account" />
              <Metric label="Equity" value={money(liveMt5?.account?.equity ?? stats.equity, currency)} sub="Direct MT5 account" />
              <Metric label="Floating P&L" value={money(liveMt5?.account?.profit, currency)} sub="Direct MT5 positions" />
              <Metric label="Gross exposure" value={money(status.gross_exposure, currency)} sub="Risk-aware" />
              <Metric label="Open Positions" value={String(liveMt5?.position_count ?? 0)} sub="Direct MT5 account" />
              <Metric label="Pending Orders" value={String(liveMt5?.order_count ?? 0)} sub="Direct MT5 account" />
              <Metric label="Currency" value={currency || "—"} sub="Account" />
            </section>
          )}

          {view === "performance" && (
            <section className="grid two">
              <Panel title="Measured runtime metrics" badge="No fabricated stats">
                <KeyValue label="Equity" value={money(stats.equity, currency)} />
                <KeyValue label="P&L" value={money(stats.pnl, currency)} />
                <KeyValue label="Drawdown" value={pct(stats.drawdown)} />
                <KeyValue label="Opportunities" value={String(stats.opportunities)} />
                <KeyValue label="Orders" value={String(stats.orders)} />
                <KeyValue label="Fills" value={String(stats.fills)} />
              </Panel>
              <Panel title="Validation policy" badge="Research">
                <p className="copy">AURA does not invent win-rate, Sharpe or profit factor when forward evidence is absent. Strategy claims must come from causal backtest, walk-forward, Monte Carlo and paper/DEMO results.</p>
              </Panel>
            </section>
          )}

          {view === "research" && (
            <section className="grid two">
              <Panel title="Open-source research fusion" badge="AURA2">
                <div className="source-grid">
                  {["Microsoft Qlib", "RD-Agent", "TradingAgents", "FinRL-X", "FreqAI reference", "Nexus reference"].map((name) => (
                    <div key={name} className="source-card"><b>{name}</b><span>Research-only sidecar / architecture source</span></div>
                  ))}
                </div>
              </Panel>
              <Panel title="Strategy candidates" badge={String(candidates.length)}>
                <div className="candidate-list">
                  {candidates.length ? candidates.slice(0, 8).map((item) => (
                    <div className="candidate" key={item.candidate_id}>
                      <b>{item.owner_name || item.candidate_id}</b>
                      <span>{item.stage} · next {item.validation?.next_required || "validation"}</span>
                    </div>
                  )) : <div className="empty">No research candidates yet.</div>}
                </div>
              </Panel>
            </section>
          )}

          {view === "learning" && (
            <section className="grid two">
              <Panel title="Self-learning status" badge="Forward-only"><LearningCard learning={learning} detailed /></Panel>
              <Panel title="AURA2 multi-timeframe memory" badge="Bounded"><pre className="json-box">{JSON.stringify(brain.aura2_mtf || {}, null, 2)}</pre></Panel>
            </section>
          )}

          {view === "news" && (
            <Panel title="News / macro intelligence" badge="Provenance-aware">
              <div className="news-list">
                {intelligence.length ? intelligence.map((item, index) => (
                  <article key={item.event_id || index}>
                    <div><b>{item.title || item.kind || "Intelligence event"}</b><p>{item.summary || "No summary."}</p></div>
                    <span>{item.sentiment ?? "neutral"}</span>
                  </article>
                )) : <div className="empty">No persisted live intelligence yet.</div>}
              </div>
            </Panel>
          )}

          {view === "journal" && (
            <Panel title="Append-only Trade Journal" badge="WAL">
              <TradeJournal />
            </Panel>
          )}

          {view === "studio" && (
            <Panel title="Strategy Studio" badge="Research only">
              <ResearchStudio />
            </Panel>
          )}

          {view === "capabilities" && (
            <Panel title="A → Z Capability Explorer" badge={String(capabilityItems.length) + " modules"}>
              <CapabilityExplorer items={capabilityItems} />
            </Panel>
          )}

          {view === "system" && (
            <section className="grid two">
              <Panel title="System health" badge={readiness?.demo_state || "CHECK"}><ReadinessList readiness={readiness} /></Panel>
              <Panel title="Runtime log" badge="Tail"><pre className="log-box">{runtime.log_tail || "No runtime log yet."}</pre></Panel>
              <Panel title="Capability matrix" badge={String(capabilityItems.length) + " modules"}>
                <div className="capability-list">
                  {capabilityItems.map((item: any) => (
                    <div key={item.id}><span>{item.name}</span><b className={item.status}>{item.status}</b></div>
                  ))}
                </div>
              </Panel>
            </section>
          )}

          {view === "owner" && (
            <section className="grid two">
              <Panel title="Owner access" badge="Local">
                <label className="field-label">Owner token (session-only)</label>
                <input
                  className="owner-input"
                  type="password"
                  value={ownerToken}
                  onChange={(event) => saveToken(event.target.value)}
                  placeholder="Only required if AURA_OWNER_TOKEN is enabled"
                />
                <div className="safety-note">Token stays in browser sessionStorage and is not stored by the dashboard source.</div>
                <div className="control-stack">
                  <button onClick={() => setJarvisOpen(true)}>Open AURA assistant</button>
                  <button onClick={() => runtimeAction("/api/reset-kill")}>Reset local emergency lock</button>
                </div>
              </Panel>
              <Panel title="JARVIS-style command examples" badge="AURA">
                <div className="command-examples">
                  {["Gold analyse karo", "Aaj ka P&L dikhao", "Why did you skip the last trade?", "Agent debate explain karo", "System health check", "Latest opportunities batao"].map((item) => (
                    <button key={item} onClick={() => { setJarvisInput(item); setJarvisOpen(true); }}>{item}</button>
                  ))}
                </div>
              </Panel>
            </section>
          )}
        </div>
      </main>

      {jarvisOpen && (
        <aside className="jarvis">
          <div className="jarvis-head">
            <div><b>✦ AURA</b><span>Owner intelligence assistant</span></div>
            <button onClick={() => setJarvisOpen(false)}>×</button>
          </div>
          <div className="chat">
            {messages.map((message, index) => <div key={index} className={"bubble " + message.role}>{message.text}</div>)}
          </div>
          <form onSubmit={sendJarvis}>
            <input value={jarvisInput} onChange={(event) => setJarvisInput(event.target.value)} placeholder="Ask AURA..." />
            <button>Send</button>
          </form>
        </aside>
      )}
    </div>
  );
}

function ServiceStrip({ state }: { state: Record<string, { ok: boolean; detail: string }> }) {
  const items = [
    ["Backend", state.backend],
    ["Workspace", state.workspace],
    ["MT5", state.mt5],
    ["Research", state.research],
  ] as const;
  return (
    <div className="service-strip">
      {items.map(([label, item]) => (
        <div key={label} className={item?.ok ? "service-pill good" : "service-pill bad"}>
          <i />
          <div><b>{label}</b><span>{item?.detail || "Checking..."}</span></div>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{sub}</small></div>;
}

function Panel({ title, badge, children }: { title: string; badge?: string; children: React.ReactNode }) {
  return <section className="panel"><header><div><h3>{title}</h3></div>{badge ? <span className="badge">{badge}</span> : null}</header><div className="panel-body">{children}</div></section>;
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return <div className="kv"><span>{label}</span><b>{value}</b></div>;
}

function Guard({ text, good = false }: { text: string; good?: boolean }) {
  return <div className={good ? "guard good" : "guard bad"}><i />{text}</div>;
}

function ReadinessList({ readiness, limit }: { readiness: JsonMap | null; limit?: number }) {
  const checks = (readiness?.checks || []).slice(0, limit || 99);
  return <div className="check-list">{checks.length ? checks.map((item: any) => (
    <div className={item.passed ? "check good" : "check bad"} key={item.id}>
      <i/><div><b>{item.name}</b><span>{item.detail}</span></div>
    </div>
  )) : <div className="empty">Readiness data unavailable.</div>}</div>;
}

function DecisionTable({ items }: { items: Decision[] }) {
  return <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>TF</th><th>Intent</th><th>Confidence</th><th>Risk flags</th><th>Time</th></tr></thead><tbody>{items.length ? items.map((item, index) => (
    <tr key={item.event_id || index}>
      <td><b>{item.symbol || "—"}</b></td>
      <td>{item.timeframe || "—"}</td>
      <td className={String(item.intent).includes("LONG") ? "green" : String(item.intent).includes("SHORT") ? "red" : ""}>{item.intent || "FLAT"}</td>
      <td>{pct(item.confidence)}</td>
      <td>{(item.risk_flags || []).join(", ") || "—"}</td>
      <td>{item.created_at ? new Date(item.created_at).toLocaleTimeString() : "—"}</td>
    </tr>
  )) : <tr><td colSpan={6} className="empty">No agent rounds yet.</td></tr>}</tbody></table></div>;
}

function DecisionDetail({ decision }: { decision: Decision | null }) {
  if (!decision) return <div className="empty">No CEO decision yet.</div>;
  return <div className="decision-detail">
    <div className="big-intent">{decision.intent || "FLAT"} <span>{pct(decision.confidence)}</span></div>
    <p>{decision.thesis}</p>
    <KeyValue label="Support" value={String(decision.support ?? "—")} />
    <KeyValue label="Opposition" value={String(decision.opposition ?? "—")} />
    <KeyValue label="Abstentions" value={String(decision.abstentions ?? "—")} />
    <KeyValue label="Opposing view" value={decision.opposing_view || "—"} />
    <div className="tag-row">{(decision.risk_flags || []).map((flag) => <span key={flag}>{flag}</span>)}</div>
  </div>;
}

function AgentEvidence({ decision, detailed = false }: { decision: Decision | null; detailed?: boolean }) {
  const evidence = decision?.evidence || [];
  return <div className="agent-list">{evidence.length ? evidence.slice(0, detailed ? 20 : 8).map((item: any, index) => (
    <div className="agent" key={item.agent_id || index}>
      <div><b>{item.role || item.agent_id || "Agent"}</b><span>{item.thesis || item.intent || "Evidence"}</span></div>
      <strong>{pct(item.confidence)}</strong>
    </div>
  )) : <div className="empty">Agent evidence will appear after live scans.</div>}</div>;
}

function Debate({ decision }: { decision: Decision | null }) {
  const d: any = decision?.deliberation;
  if (!d) return <div className="empty">No persisted deliberation yet. Start the agent runtime to populate Bull/Bear/Counterfactual review.</div>;
  return <div className="debate-grid">
    <div className="debate bull"><span>BULL</span><p>{d.bull_thesis || d.bull || "No bull summary."}</p></div>
    <div className="debate bear"><span>BEAR</span><p>{d.bear_thesis || d.bear || "No bear summary."}</p></div>
    <div className="debate counter"><span>COUNTERFACTUAL</span><p>{d.counterfactual || d.challenge || "No counterfactual summary."}</p></div>
    <pre className="json-box">{JSON.stringify(d, null, 2)}</pre>
  </div>;
}

function LearningCard({ learning, detailed = false }: { learning: JsonMap; detailed?: boolean }) {
  const status = learning?.status || {};
  const challenger = learning?.latest_research_challenger;
  return <div>
    <KeyValue label="State" value={status.state || "idle"} />
    <KeyValue label="Replay samples" value={String(status.replay_samples ?? 0)} />
    <KeyValue label="Live samples" value={String(status.live_replay_samples ?? 0)} />
    <KeyValue label="Agent observations" value={String(status.agent_reliability_observations ?? 0)} />
    <KeyValue label="Challenger" value={challenger?.genome_id || "none"} />
    {detailed && challenger ? <pre className="json-box">{JSON.stringify(challenger, null, 2)}</pre> : null}
  </div>;
}
