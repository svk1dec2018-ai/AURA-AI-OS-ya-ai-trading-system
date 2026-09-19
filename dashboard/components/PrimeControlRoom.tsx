"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import MarketChart from "./MarketChart";
import styles from "./PrimeControlRoom.module.css";
import { postJson, tryGetJson } from "../lib/api";
import type { Decision, JsonMap, MT5LiveSnapshot, Workspace } from "../lib/types";

type PrimeProvider = {
  provider_id: string;
  display_name: string;
  markets: string[];
  free_first: boolean;
  public_no_key: boolean;
  configured: boolean;
  missing_env: string[];
  readiness: string;
  data_supported: boolean;
  demo_execution_supported: boolean;
  live_execution_certified: boolean;
  notes: string[];
};

type PrimeStatus = {
  ok: boolean;
  architecture: string;
  software_production_ready: boolean;
  live_money_eligible: boolean;
  optional_capabilities: Record<string, boolean>;
  providers: PrimeProvider[];
  hard_boundaries: Record<string, boolean>;
};

type FleetStatus = {
  ok?: boolean;
  event_transport?: string;
  services?: Array<{
    service_id: string;
    role: string;
    port: number;
    financial_authority: boolean;
  }>;
};

type View = "trade" | "ai" | "risk" | "research" | "system";

const NAV: Array<[View, string, string]> = [
  ["trade", "Live Desk", "◎"],
  ["ai", "AI Council", "✦"],
  ["risk", "Risk", "◈"],
  ["research", "Research", "⌁"],
  ["system", "System", "⚙"],
];

function numberValue(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value: unknown, currency = ""): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return (currency ? currency + " " : "") +
    parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function confidence(value: unknown): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  const normalized = parsed <= 1 ? parsed * 100 : parsed;
  return normalized.toFixed(1) + "%";
}

function latestDecision(workspace: Workspace | null): Decision | null {
  return workspace?.decisions?.items?.[0] || null;
}

function statusClass(value: boolean): string {
  return value ? styles.good : styles.bad;
}

export default function PrimeControlRoom() {
  const [view, setView] = useState<View>("trade");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [readiness, setReadiness] = useState<JsonMap | null>(null);
  const [prime, setPrime] = useState<PrimeStatus | null>(null);
  const [fleet, setFleet] = useState<FleetStatus | null>(null);
  const [live, setLive] = useState<MT5LiveSnapshot | null>(null);
  const [liveError, setLiveError] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("XAUUSD");
  const [events, setEvents] = useState<JsonMap[]>([]);
  const [streamState, setStreamState] = useState("OFFLINE");
  const [jarvisOpen, setJarvisOpen] = useState(false);
  const [jarvisInput, setJarvisInput] = useState("");
  const [listening, setListening] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [messages, setMessages] = useState<Array<{ role: "owner" | "aura"; text: string }>>([
    {
      role: "aura",
      text: "AURA Prime online. Ask about live MT5, risk, positions, agents, providers or system health.",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refreshControlPlane() {
    const [workspaceResult, readinessResult, primeResult, fleetResult] = await Promise.all([
      tryGetJson<Workspace>("/api/workspace"),
      tryGetJson<JsonMap>("/api/readiness"),
      tryGetJson<PrimeStatus>("/api/prime/status"),
      tryGetJson<FleetStatus>("/api/fleet/status"),
    ]);

    if (workspaceResult.ok) setWorkspace(workspaceResult.data);
    if (readinessResult.ok) setReadiness(readinessResult.data);
    if (primeResult.ok) setPrime(primeResult.data);
    if (fleetResult.ok) setFleet(fleetResult.data);

    const failures = [
      !workspaceResult.ok ? "workspace" : "",
      !readinessResult.ok ? "readiness" : "",
      !primeResult.ok ? "prime" : "",
      !fleetResult.ok ? "fleet" : "",
    ].filter(Boolean);
    setError(failures.length ? "Unavailable services: " + failures.join(", ") : "");
  }

  useEffect(() => {
    refreshControlPlane();
    const timer = window.setInterval(refreshControlPlane, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    async function refreshLive() {
      const result = await tryGetJson<MT5LiveSnapshot>(
        "/api/mt5/live?symbols=XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,USOIL"
      );
      if (!active) return;
      if (result.ok) {
        setLive(result.data);
        setLiveError("");
      } else {
        setLive(null);
        setLiveError("error" in result ? result.error : "MT5 live snapshot unavailable");
      }
    }
    refreshLive();
    const timer = window.setInterval(refreshLive, 1200);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const source = new EventSource("/api/fleet/events");
    setStreamState("CONNECTING");
    source.onopen = () => setStreamState("LIVE");
    source.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data);
        if (payload?.error) {
          setStreamState("ERROR");
          return;
        }
        setEvents((items) => [payload, ...items].slice(0, 60));
      } catch {
        setStreamState("ERROR");
      }
    };
    source.onerror = () => setStreamState("OFFLINE");
    return () => source.close();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setJarvisOpen(true);
      }
      if (event.key === "Escape") setJarvisOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const runtime = workspace?.runtime || {};
  const runtimeStatus = runtime.status || {};
  const decision = latestDecision(workspace);
  const evidence = decision?.evidence || [];
  const watch = (live?.watchlist || []).filter((item) => item.ok);
  const currency = live?.account?.currency || "";
  const positions = live?.positions || [];
  const orders = live?.orders || [];
  const runtimeRunning = Boolean(runtime.runtime_running);
  const riskLocked = Boolean(runtime.app_kill_locked || runtimeStatus.risk_kill_switch);
  const mt5Connected = Boolean(live?.terminal?.connected);
  const softwareReady = Boolean(prime?.software_production_ready);

  const account = useMemo(() => ({
    balance: money(live?.account?.balance, currency),
    equity: money(live?.account?.equity, currency),
    pnl: money(live?.account?.profit, currency),
    freeMargin: money(live?.account?.margin_free, currency),
  }), [live, currency]);

  async function runtimeAction(path: string, body: JsonMap = {}) {
    setBusy(true);
    try {
      await postJson(path, body);
      await refreshControlPlane();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  function speak(text: string) {
    if (!speakReplies || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 500));
    utterance.rate = 1.02;
    window.speechSynthesis.speak(utterance);
  }

  async function sendJarvis(event?: FormEvent) {
    event?.preventDefault();
    const text = jarvisInput.trim();
    if (!text) return;
    setJarvisInput("");
    setMessages((items) => items.concat({ role: "owner", text }));
    try {
      const result = await postJson<JsonMap>("/api/command", { text });
      const answer = String(result.answer || result.message || "Command handled.");
      setMessages((items) => items.concat({ role: "aura", text: answer }));
      speak(answer);
    } catch (exc) {
      const detail = exc instanceof Error ? exc.message : String(exc);
      const answer = "Blocked: " + detail;
      setMessages((items) => items.concat({ role: "aura", text: answer }));
      speak(answer);
    }
  }

  function startVoice() {
    type SpeechCtor = new () => {
      lang: string;
      interimResults: boolean;
      continuous: boolean;
      start: () => void;
      onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null;
      onend: (() => void) | null;
      onerror: (() => void) | null;
    };
    const voiceWindow = window as unknown as {
      SpeechRecognition?: SpeechCtor;
      webkitSpeechRecognition?: SpeechCtor;
    };
    const Ctor = voiceWindow.SpeechRecognition || voiceWindow.webkitSpeechRecognition;
    if (!Ctor) {
      setMessages((items) => items.concat({
        role: "aura",
        text: "Browser speech recognition is unavailable here. Text command remains available.",
      }));
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "en-IN";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const result = event.results[0]?.[0]?.transcript || "";
      setJarvisInput(result);
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    setListening(true);
    recognition.start();
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.rail}>
        <button className={styles.logo} onClick={() => setView("trade")} aria-label="AURA Prime">
          <span>A</span>
        </button>
        <div className={styles.nav}>
          {NAV.map(([id, label, icon]) => (
            <button
              key={id}
              title={label}
              className={view === id ? styles.navActive : styles.navButton}
              onClick={() => setView(id)}
            >
              <span>{icon}</span>
              <small>{label}</small>
            </button>
          ))}
        </div>
        <div className={styles.railBottom}>
          <i className={statusClass(mt5Connected)} />
          <i className={statusClass(runtimeRunning)} />
          <i className={statusClass(!riskLocked)} />
        </div>
      </aside>

      <main className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.identity}>
            <div className={styles.miniOrb}><i /><span /></div>
            <div>
              <b>AURA PRIME</b>
              <small>Autonomous Research · Governed Execution · Owner Control</small>
            </div>
          </div>
          <div className={styles.statusLine}>
            <StatusChip good={softwareReady} label={softwareReady ? "SOFTWARE READY" : "CHECK SYSTEM"} />
            <StatusChip good={mt5Connected} label={mt5Connected ? "MT5 LIVE DATA" : "MT5 OFFLINE"} />
            <StatusChip good={streamState === "LIVE"} label={"FLEET " + streamState} />
            <StatusChip good={!riskLocked} label={riskLocked ? "RISK LOCKED" : "RISK ARMED"} />
            <button className={styles.commandButton} onClick={() => setJarvisOpen(true)}>
              ✦ ASK AURA <kbd>Ctrl K</kbd>
            </button>
          </div>
        </header>

        {error ? <div className={styles.bannerError}>{error}</div> : null}

        {view === "trade" ? (
          <div className={styles.tradeLayout}>
            <section className={styles.leftColumn}>
              <Panel title="MARKET WATCH" badge={mt5Connected ? "LIVE" : "WAITING"}>
                <div className={styles.watchlist}>
                  {watch.length ? watch.map((item) => (
                    <button
                      key={item.symbol}
                      className={selectedSymbol === item.symbol ? styles.watchActive : styles.watchRow}
                      onClick={() => setSelectedSymbol(item.symbol)}
                    >
                      <span>
                        <b>{item.symbol}</b>
                        <small>{item.description || item.requested_symbol}</small>
                      </span>
                      <span>
                        <strong>{numberValue(item.mid || item.last || item.bid).toFixed(item.digits || 2)}</strong>
                        <small className={numberValue(item.change_pct) >= 0 ? styles.positive : styles.negative}>
                          {item.change_pct == null ? "—" : numberValue(item.change_pct).toFixed(2) + "%"}
                        </small>
                      </span>
                    </button>
                  )) : <Empty text={liveError || "Waiting for MT5 market watch..."} />}
                </div>
              </Panel>

              <Panel title="ACCOUNT" badge={live?.account?.server || "MT5"}>
                <Metric label="Balance" value={account.balance} />
                <Metric label="Equity" value={account.equity} />
                <Metric label="Floating P&L" value={account.pnl} accent={numberValue(live?.account?.profit) >= 0} />
                <Metric label="Free Margin" value={account.freeMargin} />
                <Metric label="Leverage" value={"1:" + (live?.account?.leverage || "—")} />
              </Panel>

              <Panel title="PROVIDERS" badge="TRUTH MATRIX">
                <div className={styles.providerMini}>
                  {(prime?.providers || []).slice(0, 10).map((provider) => (
                    <div key={provider.provider_id}>
                      <i className={statusClass(
                        provider.readiness === "PUBLIC_READY" ||
                        provider.readiness === "DEMO_EXECUTION" ||
                        provider.readiness === "DATA_ONLY"
                      )} />
                      <span>{provider.display_name}</span>
                      <small>{provider.readiness.replaceAll("_", " ")}</small>
                    </div>
                  ))}
                </div>
              </Panel>
            </section>

            <section className={styles.centerColumn}>
              <div className={styles.chartHeader}>
                <div>
                  <span>ACTIVE INSTRUMENT</span>
                  <b>{selectedSymbol}</b>
                </div>
                <div className={styles.accountStrip}>
                  <MetricCompact label="BALANCE" value={account.balance} />
                  <MetricCompact label="EQUITY" value={account.equity} />
                  <MetricCompact label="P&L" value={account.pnl} />
                  <MetricCompact label="POSITIONS" value={String(positions.length)} />
                </div>
              </div>
              <div className={styles.chartCard}>
                <MarketChart externalSymbol={selectedSymbol} />
              </div>

              <div className={styles.bottomTerminal}>
                <Panel title="OPEN POSITIONS" badge={String(positions.length)}>
                  <div className={styles.tableWrap}>
                    <table>
                      <thead>
                        <tr><th>Symbol</th><th>Side</th><th>Volume</th><th>Entry</th><th>Current</th><th>P&L</th><th>SL</th><th>TP</th></tr>
                      </thead>
                      <tbody>
                        {positions.map((position) => (
                          <tr key={position.ticket}>
                            <td>{position.symbol}</td>
                            <td className={position.side === "BUY" ? styles.positive : styles.negative}>{position.side}</td>
                            <td>{position.volume}</td>
                            <td>{position.price_open}</td>
                            <td>{position.price_current}</td>
                            <td className={position.profit >= 0 ? styles.positive : styles.negative}>{position.profit.toFixed(2)}</td>
                            <td>{position.sl || "—"}</td>
                            <td>{position.tp || "—"}</td>
                          </tr>
                        ))}
                        {!positions.length ? <tr><td colSpan={8}><Empty text="No open MT5 positions" /></td></tr> : null}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </div>
            </section>

            <section className={styles.rightColumn}>
              <div className={styles.jarvisCore}>
                <div className={styles.orbitOne} />
                <div className={styles.orbitTwo} />
                <div className={styles.orbitThree} />
                <button className={styles.coreButton} onClick={() => setJarvisOpen(true)}>
                  <span>A</span>
                  <i />
                </button>
                <small>{runtimeRunning ? "THINKING LIVE" : "STANDBY"}</small>
              </div>

              <Panel title="AURA VERDICT" badge={decision?.intent || "WAIT"}>
                <div className={styles.verdict}>
                  <strong className={
                    decision?.intent === "LONG" ? styles.positive :
                    decision?.intent === "SHORT" ? styles.negative : ""
                  }>
                    {decision?.intent || "NO SIGNAL"}
                  </strong>
                  <span>{confidence(decision?.confidence)} confidence</span>
                  <div className={styles.confidenceTrack}>
                    <i style={{ width: Math.min(100, numberValue(decision?.confidence) * 100) + "%" }} />
                  </div>
                  <p>{decision?.thesis || "Waiting for point-in-time specialist evidence."}</p>
                </div>
              </Panel>

              <Panel title="RISK CORE" badge={riskLocked ? "LOCKED" : "INDEPENDENT"}>
                <div className={styles.riskGrid}>
                  <Guard good={!riskLocked} label="Kill switch" value={riskLocked ? "ENGAGED" : "CLEAR"} />
                  <Guard good={prime?.hard_boundaries?.risk_bypass === false} label="AI risk bypass" value="BLOCKED" />
                  <Guard good={prime?.hard_boundaries?.fund_movement === false} label="Fund movement" value="BLOCKED" />
                  <Guard good={!prime?.live_money_eligible} label="Real money" value={prime?.live_money_eligible ? "GATED" : "LOCKED"} />
                </div>
              </Panel>

              <Panel title="EXECUTION" badge="OWNER">
                <div className={styles.actions}>
                  <button
                    disabled={busy}
                    className={styles.start}
                    onClick={() => runtimeAction("/api/start", { max_symbols: 25, max_batches: 0 })}
                  >
                    START DEMO
                  </button>
                  <button disabled={busy} onClick={() => runtimeAction("/api/stop")}>STOP</button>
                  <button
                    disabled={busy}
                    className={styles.kill}
                    onClick={() => runtimeAction("/api/kill", { reason: "AURA Prime owner emergency lock" })}
                  >
                    EMERGENCY LOCK
                  </button>
                </div>
                <p className={styles.microcopy}>Orders remain CEO → RiskEngine → protected broker adapter. No direct manual bypass is exposed.</p>
              </Panel>
            </section>
          </div>
        ) : null}

        {view === "ai" ? (
          <div className={styles.pageGrid}>
            <Panel title="SPECIALIST CONSTELLATION" badge={String(evidence.length)}>
              <div className={styles.agentGrid}>
                {evidence.length ? evidence.map((agent, index) => (
                  <article key={String(agent.agent_id || index)}>
                    <div className={styles.agentOrb}>{String(agent.role || "AI").slice(0, 2).toUpperCase()}</div>
                    <div>
                      <b>{String(agent.role || agent.agent_id || "specialist")}</b>
                      <span>{String(agent.intent || "FLAT")} · {confidence(agent.confidence)}</span>
                      <p>{String(agent.thesis || "No thesis")}</p>
                    </div>
                  </article>
                )) : <Empty text="No current agent evidence. Start paper/DEMO analysis to populate the council." />}
              </div>
            </Panel>
            <Panel title="MODEL STACK" badge="OPTIONAL / FREE-FIRST">
              <CapabilityGrid values={prime?.optional_capabilities || {}} />
            </Panel>
            <Panel title="LATEST DECISION TRACE" badge="POINT-IN-TIME">
              <pre className={styles.code}>{JSON.stringify(decision || {}, null, 2)}</pre>
            </Panel>
          </div>
        ) : null}

        {view === "risk" ? (
          <div className={styles.pageGrid}>
            <Panel title="RELEASE READINESS" badge={String(readiness?.demo_state || "CHECK")}>
              <pre className={styles.code}>{JSON.stringify(readiness || {}, null, 2)}</pre>
            </Panel>
            <Panel title="PERMANENT BOUNDARIES" badge="FAIL CLOSED">
              <div className={styles.boundaryGrid}>
                <Guard good label="Independent RiskEngine" value="REQUIRED" />
                <Guard good label="Closed-candle decisions" value="REQUIRED" />
                <Guard good label="Broker reconciliation" value="REQUIRED" />
                <Guard good label="AI execution authority" value="NONE" />
                <Guard good label="Withdrawal/deposit" value="BLOCKED" />
                <Guard good label="Live default" value="OFF" />
              </div>
            </Panel>
          </div>
        ) : null}

        {view === "research" ? (
          <div className={styles.pageGrid}>
            <Panel title="PROVIDER MATRIX" badge="FREE-FIRST">
              <div className={styles.providerGrid}>
                {(prime?.providers || []).map((provider) => (
                  <article key={provider.provider_id}>
                    <header><b>{provider.display_name}</b><span>{provider.readiness.replaceAll("_", " ")}</span></header>
                    <p>{provider.markets.join(" · ")}</p>
                    <footer>
                      <span>{provider.public_no_key ? "NO KEY" : provider.configured ? "CONFIGURED" : "CONFIG NEEDED"}</span>
                      <span>{provider.demo_execution_supported ? "DEMO EXEC" : "DATA"}</span>
                    </footer>
                  </article>
                ))}
              </div>
            </Panel>
            <Panel title="RESEARCH RULES" badge="CHAMPION / CHALLENGER">
              <div className={styles.timeline}>
                {["Hypothesis", "Causal Backtest", "Walk-forward", "Monte Carlo", "Shadow", "Paper / DEMO", "Human Approval", "Smallest Canary"].map((item, index) => (
                  <div key={item}><i>{index + 1}</i><span>{item}</span></div>
                ))}
              </div>
            </Panel>
          </div>
        ) : null}

        {view === "system" ? (
          <div className={styles.pageGrid}>
            <Panel title="DISTRIBUTED FLEET" badge={streamState}>
              <div className={styles.serviceGrid}>
                {(fleet?.services || []).map((service) => (
                  <article key={service.service_id}>
                    <i className={statusClass(streamState === "LIVE")} />
                    <div><b>{service.service_id}</b><span>{service.role} · :{service.port}</span></div>
                    <small>{service.financial_authority ? "FINANCIAL AUTHORITY" : "NO FINANCIAL AUTHORITY"}</small>
                  </article>
                ))}
              </div>
            </Panel>
            <Panel title="LIVE EVENT STREAM" badge={String(events.length)}>
              <div className={styles.eventFeed}>
                {events.map((item, index) => (
                  <article key={String(item.record_id || index)}>
                    <b>{String(item.stream || "event")}</b>
                    <span>{String(item.event?.source || "unknown")}</span>
                    <code>{JSON.stringify(item.event?.payload || {})}</code>
                  </article>
                ))}
                {!events.length ? <Empty text="Waiting for Redis fleet events..." /> : null}
              </div>
            </Panel>
          </div>
        ) : null}
      </main>

      {jarvisOpen ? (
        <div className={styles.jarvisOverlay} onMouseDown={(event) => {
          if (event.target === event.currentTarget) setJarvisOpen(false);
        }}>
          <section className={styles.jarvisPanel}>
            <header>
              <div className={styles.jarvisHeaderOrb}><i /><span /></div>
              <div><b>AURA / JARVIS</b><small>Owner intelligence · advisory commands · financial actions governed</small></div>
              <button onClick={() => setJarvisOpen(false)}>×</button>
            </header>
            <div className={styles.chat}>
              {messages.map((message, index) => (
                <div key={index} className={message.role === "aura" ? styles.auraBubble : styles.ownerBubble}>
                  <small>{message.role === "aura" ? "AURA" : "OWNER"}</small>
                  {message.text}
                </div>
              ))}
            </div>
            <div className={styles.voiceBar}>
              <button className={listening ? styles.listening : ""} onClick={startVoice}>
                {listening ? "● LISTENING" : "◉ VOICE"}
              </button>
              <button onClick={() => setSpeakReplies((value) => !value)}>
                SPEAK {speakReplies ? "ON" : "OFF"}
              </button>
              <span>Try: “What is MT5 status?”, “Explain latest decision”, “Show risk state”.</span>
            </div>
            <form onSubmit={sendJarvis}>
              <input
                autoFocus
                value={jarvisInput}
                onChange={(event) => setJarvisInput(event.target.value)}
                placeholder="Ask AURA or type an owner command..."
              />
              <button type="submit">SEND ↗</button>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Panel({ title, badge, children }: { title: string; badge?: string; children: React.ReactNode }) {
  return (
    <section className={styles.panel}>
      <header><b>{title}</b>{badge ? <span>{badge}</span> : null}</header>
      <div className={styles.panelBody}>{children}</div>
    </section>
  );
}

function StatusChip({ good, label }: { good: boolean; label: string }) {
  return <span className={good ? styles.statusGood : styles.statusBad}><i />{label}</span>;
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={styles.metric}>
      <span>{label}</span>
      <b className={accent === undefined ? "" : accent ? styles.positive : styles.negative}>{value}</b>
    </div>
  );
}

function MetricCompact({ label, value }: { label: string; value: string }) {
  return <div className={styles.metricCompact}><span>{label}</span><b>{value}</b></div>;
}

function Guard({ good, label, value }: { good: boolean; label: string; value: string }) {
  return (
    <div className={styles.guard}>
      <i className={statusClass(good)} />
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function CapabilityGrid({ values }: { values: Record<string, boolean> }) {
  return (
    <div className={styles.capabilityGrid}>
      {Object.entries(values).map(([name, enabled]) => (
        <div key={name}><i className={statusClass(enabled)} /><span>{name}</span><b>{enabled ? "READY" : "OPTIONAL"}</b></div>
      ))}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className={styles.empty}>{text}</div>;
}
