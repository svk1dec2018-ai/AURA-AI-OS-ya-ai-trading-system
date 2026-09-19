"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { getJson, postJson } from "../lib/api";
import type { JsonMap } from "../lib/types";

export function ExecutionPreview() {
  const [symbol, setSymbol] = useState("XAUUSD");
  const [side, setSide] = useState("BUY");
  const [result, setResult] = useState<JsonMap | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const data = await getJson<JsonMap>(
        "/api/mt5/execution-check?symbol=" + encodeURIComponent(symbol) + "&side=" + side
      );
      setResult(data);
      setError("");
    } catch (exc) {
      setResult(null);
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tool-box">
      <div className="tool-title"><b>Protected DEMO order preview</b><span>NO SEND</span></div>
      <form className="tool-form" onSubmit={run}>
        <label>Symbol<input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
        <label>Side<select value={side} onChange={(e) => setSide(e.target.value)}><option>BUY</option><option>SELL</option></select></label>
        <button className="primary" disabled={busy}>{busy ? "Checking..." : "Check broker acceptance"}</button>
      </form>
      {error ? <div className="tool-error">{error}</div> : null}
      {result ? (
        <div className="preview-grid">
          <ToolStat label="Resolved symbol" value={String(result.symbol || symbol)} />
          <ToolStat label="Minimum volume" value={String(result.minimum_volume ?? "—")} />
          <ToolStat label="Entry" value={String(result.entry_price ?? "—")} />
          <ToolStat label="SL" value={String(result.native_stop ?? "—")} />
          <ToolStat label="TP" value={String(result.native_target ?? "—")} />
          <ToolStat label="Margin" value={String(result.margin_required ?? "—")} />
          <ToolStat label="order_check" value={result.execution_ready ? "ACCEPTED" : "BLOCKED"} />
          <ToolStat label="order_send" value={result.order_submission_attempted ? "ATTEMPTED" : "NOT SENT"} />
        </div>
      ) : <p className="tool-copy">This uses MT5 broker order_check only. It cannot submit a trade.</p>}
    </div>
  );
}

export function TradeJournal() {
  const [items, setItems] = useState<any[]>([]);
  const [status, setStatus] = useState("Loading...");
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await getJson<JsonMap>("/api/journal");
        if (active) {
          setItems(data.items || []);
          setStatus(data.corrupt ? "Journal integrity warning" : "Append-only financial journal");
        }
      } catch (exc) {
        if (active) setStatus(exc instanceof Error ? exc.message : String(exc));
      }
    }
    load();
    const timer = window.setInterval(load, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  return (
    <div>
      <div className="tool-subhead">{status}</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Seq</th><th>Event</th><th>Time</th><th>Payload</th></tr></thead>
          <tbody>
            {items.length ? items.slice(0, 150).map((item) => (
              <tr key={item.event_id || item.sequence}>
                <td>{item.sequence}</td><td>{item.event_type}</td>
                <td>{item.created_at ? new Date(item.created_at).toLocaleString() : "—"}</td>
                <td className="journal-payload">{JSON.stringify(item.payload)}</td>
              </tr>
            )) : <tr><td colSpan={4} className="empty">No financial journal events yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ResearchStudio() {
  const [options, setOptions] = useState<JsonMap | null>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [selected, setSelected] = useState("");
  const [backtest, setBacktest] = useState<JsonMap | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [o, c] = await Promise.all([
        getJson<JsonMap>("/api/algo/options"),
        getJson<JsonMap>("/api/algo/candidates"),
      ]);
      setOptions(o);
      setCandidates(c.items || []);
      if (!selected && c.items?.[0]?.candidate_id) setSelected(c.items[0].candidate_id);
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    }
  }

  useEffect(() => { refresh(); }, []);

  async function buildTemplate(template: any) {
    setBusy(true);
    try {
      const payload = { ...template, name: template.name + " AURA2" };
      const built = await postJson<JsonMap>("/api/algo/build", payload);
      setMessage("Candidate built: " + built.candidate_id + " · " + built.stage);
      await refresh();
      setSelected(built.candidate_id);
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
  }

  async function runBacktest() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await postJson<JsonMap>("/api/backtest/run", {
        candidate_id: selected,
        symbol: "XAUUSD",
        timeframe: "5m",
        bars: 1000,
      });
      setBacktest(result);
      setMessage("Causal backtest completed. Candidate remains research-only.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
  }

  const templates = options?.templates || [];
  return (
    <div className="studio">
      <div className="studio-banner">
        <b>Strategy Factory + causal backtest</b>
        <span>Research only · no risk/broker authority · no automatic live deployment</span>
      </div>
      <div className="template-grid">
        {templates.map((template: any) => (
          <button key={template.name} className="template-card" disabled={busy} onClick={() => buildTemplate(template)}>
            <b>{template.name}</b><span>{template.thesis}</span>
            <small>{(template.entries || []).join(", ")} · {(template.confirmations || []).join(", ")}</small>
          </button>
        ))}
      </div>
      <div className="studio-run">
        <label>Candidate
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">Select candidate</option>
            {candidates.map((item) => <option key={item.candidate_id} value={item.candidate_id}>{item.owner_name || item.candidate_id}</option>)}
          </select>
        </label>
        <button className="primary" disabled={busy || !selected} onClick={runBacktest}>{busy ? "Working..." : "Run XAUUSD M5 causal backtest"}</button>
      </div>
      {message ? <div className="safety-note">{message}</div> : null}
      {backtest ? (
        <div className="preview-grid">
          <ToolStat label="Return" value={String(backtest.metrics?.total_return_pct ?? "—") + "%"} />
          <ToolStat label="Max drawdown" value={String(backtest.metrics?.max_drawdown_pct ?? "—")} />
          <ToolStat label="Orders" value={String(backtest.metrics?.orders ?? 0)} />
          <ToolStat label="Fills" value={String(backtest.metrics?.fills ?? 0)} />
          <ToolStat label="Rejected" value={String(backtest.metrics?.rejected_signals ?? 0)} />
          <ToolStat label="Next gate" value={String(backtest.validation?.next_required ?? "walk-forward")} />
        </div>
      ) : null}
    </div>
  );
}

export function CapabilityExplorer({ items }: { items: any[] }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(() => items.filter((item) => {
    const matchText = (item.name + " " + item.group + " " + item.description).toLowerCase().includes(query.toLowerCase());
    return matchText && (filter === "all" || item.status === filter);
  }), [items, query, filter]);

  return (
    <div>
      <div className="cap-tools">
        <input placeholder="Search AURA capabilities..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All states</option><option value="ui_connected">UI connected</option>
          <option value="backend_ready">Backend ready</option><option value="partial">Partial</option>
          <option value="external_gate">External gate</option><option value="pending">Pending</option>
          <option value="blocked">Blocked</option>
        </select>
      </div>
      <div className="cap-cards">
        {filtered.map((item) => (
          <article key={item.id}>
            <header><div><small>{item.group}</small><b>{item.name}</b></div><span className={item.status}>{item.status}</span></header>
            <p>{item.description}</p>
            <code>{(item.evidence || []).join(" · ") || "No repository evidence listed"}</code>
          </article>
        ))}
      </div>
    </div>
  );
}

function ToolStat({ label, value }: { label: string; value: string }) {
  return <div className="tool-stat"><span>{label}</span><b>{value}</b></div>;
}
