"use client";

import { useEffect, useState } from "react";
import { getJson, postJson } from "../lib/api";

interface Props {
  onSaved?: () => void;
  onClose?: () => void;
}

export default function CredentialsManager({ onSaved, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<"brokers" | "ai" | "feeds" | "alerts">("brokers");
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [config, setConfig] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testLog, setTestLog] = useState<{ id: string; ok: boolean; message: string; latency_ms?: number } | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    // Load config from server or localStorage
    async function load() {
      try {
        const res = await getJson<{ ok: boolean; config: Record<string, string> }>("/api/config");
        if (res.ok && res.config) {
          const localSaved = localStorage.getItem("aura_credentials_cache");
          const localParsed = localSaved ? JSON.parse(localSaved) : {};
          setConfig({ ...res.config, ...localParsed });
        }
      } catch (err) {
        console.warn("Could not fetch config from server, falling back to local storage", err);
        const localSaved = localStorage.getItem("aura_credentials_cache");
        if (localSaved) setConfig(JSON.parse(localSaved));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const toggleSecret = (key: string) => {
    setShowSecrets((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const updateField = (key: string, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const saveConfig = async () => {
    setSaving(true);
    setNotification(null);
    try {
      localStorage.setItem("aura_credentials_cache", JSON.stringify(config));
      await postJson("/api/config", config);
      setNotification({ type: "success", text: "Credentials & configurations saved successfully in app state!" });
      if (onSaved) onSaved();
    } catch (err: any) {
      setNotification({ type: "error", text: `Failed to save: ${err?.message || "Unknown error"}` });
    } finally {
      setSaving(false);
    }
  };

  const testIntegration = async (type: string) => {
    setTestingId(type);
    setTestLog(null);
    try {
      const res = await postJson<{ ok: boolean; message: string; latency_ms?: number }>("/api/config/test", {
        type,
        overrides: config,
      });
      setTestLog({
        id: type,
        ok: res.ok,
        message: res.message || "Connection validated",
        latency_ms: res.latency_ms,
      });
    } catch (err: any) {
      setTestLog({
        id: type,
        ok: false,
        message: `Diagnostic failure: ${err?.message || "Connection timeout"}`,
      });
    } finally {
      setTestingId(null);
    }
  };

  const prefillDemoPreset = () => {
    setConfig((prev) => ({
      ...prev,
      AURA_MT5_DEMO_LOGIN: "8840210",
      AURA_MT5_DEMO_SERVER: "Exness-DEMO-Realtime",
      AURA_MT5_DEMO_PASSWORD: "demo_password_123",
      AURA_ANGEL_ONE_CLIENT_CODE: "A192834",
      AURA_ANGEL_ONE_API_KEY: "angel_smartapi_demo_key",
      AURA_DHAN_CLIENT_ID: "1100984120",
      AURA_OLLAMA_URL: "http://localhost:11434",
      AURA_OLLAMA_MODELS: "llama3.3:latest,deepseek-r1:14b",
      AURA_OPENAI_MODELS: "gpt-4o,o1-mini",
      AURA_FREE_AI_PRESET: "balanced",
      AURA_AI_OPINIONS_PER_ROLE: "3",
      AURA_COMMAND_CENTER_OWNER_ID: "owner_commander",
      AURA_LIVE_TRADING_ENABLED: "false",
    }));
    setNotification({ type: "success", text: "Loaded recommended Demo & Research defaults into fields!" });
  };

  const exportEnvFile = () => {
    let content = "# AURA AI OS Environment Export\n# Generated directly from AURA In-App Credentials Manager\n\n";
    for (const [k, v] of Object.entries(config)) {
      content += `${k}=${v}\n`;
    }
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "aura.env";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div id="credentials-manager" className="bg-[#0b101b] border border-slate-800 rounded-xl overflow-hidden shadow-2xl">
      {/* Top Header */}
      <div className="p-4 sm:p-5 bg-gradient-to-r from-slate-900 via-slate-850 to-slate-900 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-mono font-bold text-sm">
            CFG
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold text-slate-100 flex items-center gap-2">
              In-App Environment & Broker Credentials
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 font-medium">
                Live In-App Setup
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Fill and test all MT5, Indian Broker, OpenAI, Ollama, and Telegram credentials directly here without needing manual .env files.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            id="btn-prefill-presets"
            type="button"
            onClick={prefillDemoPreset}
            className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition-colors"
          >
            Load Demo Presets
          </button>
          <button
            id="btn-export-env"
            type="button"
            onClick={exportEnvFile}
            className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition-colors"
          >
            Export .env
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Notifications banner */}
      {notification && (
        <div
          className={`p-3 text-xs border-b font-medium flex items-center justify-between ${
            notification.type === "success"
              ? "bg-emerald-950/40 border-emerald-800/60 text-emerald-300"
              : "bg-rose-950/40 border-rose-800/60 text-rose-300"
          }`}
        >
          <span>{notification.text}</span>
          <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-slate-200 ml-3">✕</button>
        </div>
      )}

      {/* Diagnostic log notification */}
      {testLog && (
        <div
          className={`p-3 text-xs border-b flex items-center justify-between ${
            testLog.ok
              ? "bg-cyan-950/40 border-cyan-800/60 text-cyan-300"
              : "bg-rose-950/40 border-rose-800/60 text-rose-300"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="font-mono uppercase font-bold text-[10px] px-1.5 py-0.5 rounded bg-black/40">
              {testLog.id}
            </span>
            <span>{testLog.message}</span>
          </div>
          {testLog.latency_ms && (
            <span className="text-[11px] font-mono text-slate-400">
              {testLog.latency_ms} ms ping
            </span>
          )}
        </div>
      )}

      {/* Sub Tabs */}
      <div className="flex border-b border-slate-800 bg-slate-900/60 px-4 pt-2 gap-1 overflow-x-auto text-xs font-medium">
        <button
          type="button"
          onClick={() => setActiveTab("brokers")}
          className={`pb-2.5 px-3 border-b-2 transition-colors whitespace-nowrap ${
            activeTab === "brokers"
              ? "border-emerald-400 text-emerald-300 font-semibold"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          🏦 Brokers & Accounts (MT5 / Indian / OANDA)
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("ai")}
          className={`pb-2.5 px-3 border-b-2 transition-colors whitespace-nowrap ${
            activeTab === "ai"
              ? "border-emerald-400 text-emerald-300 font-semibold"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          🧠 AI Models & Multi-Agent Council
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("feeds")}
          className={`pb-2.5 px-3 border-b-2 transition-colors whitespace-nowrap ${
            activeTab === "feeds"
              ? "border-emerald-400 text-emerald-300 font-semibold"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          📊 Macro Feeds & Alpha Vantage
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("alerts")}
          className={`pb-2.5 px-3 border-b-2 transition-colors whitespace-nowrap ${
            activeTab === "alerts"
              ? "border-emerald-400 text-emerald-300 font-semibold"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          🔔 Alerts, Security & Owner Gate
        </button>
      </div>

      {/* Content Form Body */}
      <div className="p-4 sm:p-6 max-h-[62vh] overflow-y-auto space-y-6">
        {activeTab === "brokers" && (
          <div className="space-y-6">
            {/* MT5 Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">MetaTrader 5 (MT5 Broker DEMO)</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "mt5"}
                  onClick={() => testIntegration("mt5")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  {testingId === "mt5" ? "Pinging..." : "Test MT5 Terminal"}
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">MT5 Server Name</label>
                  <input
                    type="text"
                    placeholder="e.g. Exness-DEMO-Realtime"
                    value={config.AURA_MT5_DEMO_SERVER || ""}
                    onChange={(e) => updateField("AURA_MT5_DEMO_SERVER", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">MT5 Demo Login / Account #</label>
                  <input
                    type="text"
                    placeholder="e.g. 8840210"
                    value={config.AURA_MT5_DEMO_LOGIN || ""}
                    onChange={(e) => updateField("AURA_MT5_DEMO_LOGIN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 flex items-center justify-between">
                    <span>MT5 Demo Password</span>
                    <button
                      type="button"
                      onClick={() => toggleSecret("mt5_pwd")}
                      className="text-[10px] text-slate-500 hover:text-slate-300"
                    >
                      {showSecrets["mt5_pwd"] ? "Hide" : "Show"}
                    </button>
                  </label>
                  <input
                    type={showSecrets["mt5_pwd"] ? "text" : "password"}
                    placeholder="••••••••"
                    value={config.AURA_MT5_DEMO_PASSWORD || ""}
                    onChange={(e) => updateField("AURA_MT5_DEMO_PASSWORD", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">MT5 Terminal Executable Path (Optional)</label>
                  <input
                    type="text"
                    placeholder="C:\Program Files\MetaTrader 5\terminal64.exe"
                    value={config.AURA_MT5_TERMINAL_PATH || ""}
                    onChange={(e) => updateField("AURA_MT5_TERMINAL_PATH", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Angel One Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">Angel One (SmartAPI)</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "angel_one"}
                  onClick={() => testIntegration("angel_one")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-amber-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  {testingId === "angel_one" ? "Pinging..." : "Test Angel One"}
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Client Code</label>
                  <input
                    type="text"
                    placeholder="e.g. A192834"
                    value={config.AURA_ANGEL_ONE_CLIENT_CODE || ""}
                    onChange={(e) => updateField("AURA_ANGEL_ONE_CLIENT_CODE", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-amber-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 flex items-center justify-between">
                    <span>SmartAPI Key</span>
                    <button
                      type="button"
                      onClick={() => toggleSecret("angel_key")}
                      className="text-[10px] text-slate-500 hover:text-slate-300"
                    >
                      {showSecrets["angel_key"] ? "Hide" : "Show"}
                    </button>
                  </label>
                  <input
                    type={showSecrets["angel_key"] ? "text" : "password"}
                    placeholder="SmartAPI key"
                    value={config.AURA_ANGEL_ONE_API_KEY || ""}
                    onChange={(e) => updateField("AURA_ANGEL_ONE_API_KEY", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-amber-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">JWT Session Token (Optional)</label>
                  <input
                    type="password"
                    placeholder="eyJhbGciOi..."
                    value={config.AURA_ANGEL_ONE_JWT_TOKEN || ""}
                    onChange={(e) => updateField("AURA_ANGEL_ONE_JWT_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-amber-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Feed Token (Optional)</label>
                  <input
                    type="password"
                    placeholder="Feed token"
                    value={config.AURA_ANGEL_ONE_FEED_TOKEN || ""}
                    onChange={(e) => updateField("AURA_ANGEL_ONE_FEED_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-amber-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Dhan & Flattrade & Shoonya Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-cyan-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">DhanHQ, Flattrade & Shoonya (Finvasia)</h3>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={testingId === "dhan"}
                    onClick={() => testIntegration("dhan")}
                    className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                  >
                    Test Dhan
                  </button>
                  <button
                    type="button"
                    disabled={testingId === "shoonya"}
                    onClick={() => testIntegration("shoonya")}
                    className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded transition-colors disabled:opacity-50"
                  >
                    Test Shoonya
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Dhan Client ID</label>
                  <input
                    type="text"
                    placeholder="e.g. 1100345678"
                    value={config.AURA_DHAN_CLIENT_ID || ""}
                    onChange={(e) => updateField("AURA_DHAN_CLIENT_ID", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Dhan Access Token</label>
                  <input
                    type="password"
                    placeholder="eyJ0eXAi..."
                    value={config.AURA_DHAN_ACCESS_TOKEN || ""}
                    onChange={(e) => updateField("AURA_DHAN_ACCESS_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Shoonya / Finvasia User ID</label>
                  <input
                    type="text"
                    placeholder="FA12345"
                    value={config.AURA_SHOONYA_USER_ID || ""}
                    onChange={(e) => updateField("AURA_SHOONYA_USER_ID", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Shoonya Session Token</label>
                  <input
                    type="password"
                    placeholder="Session token"
                    value={config.AURA_SHOONYA_SESSION_TOKEN || ""}
                    onChange={(e) => updateField("AURA_SHOONYA_SESSION_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* OANDA Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">OANDA v20 Forex REST</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "oanda"}
                  onClick={() => testIntegration("oanda")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-blue-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  Test OANDA
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">OANDA Account ID</label>
                  <input
                    type="text"
                    placeholder="101-001-XXXXXXX-001"
                    value={config.AURA_OANDA_ACCOUNT_ID || ""}
                    onChange={(e) => updateField("AURA_OANDA_ACCOUNT_ID", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-blue-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">OANDA Personal Access Token</label>
                  <input
                    type="password"
                    placeholder="Bearer token"
                    value={config.AURA_OANDA_ACCESS_TOKEN || ""}
                    onChange={(e) => updateField("AURA_OANDA_ACCESS_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-blue-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Environment</label>
                  <select
                    value={config.AURA_OANDA_ENVIRONMENT || "practice"}
                    onChange={(e) => updateField("AURA_OANDA_ENVIRONMENT", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-blue-500 outline-none"
                  >
                    <option value="practice">Practice (DEMO)</option>
                    <option value="live">Live (Restricted)</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "ai" && (
          <div className="space-y-6">
            {/* OpenAI Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">OpenAI / Compatible Models</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "openai"}
                  onClick={() => testIntegration("openai")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  Test OpenAI
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1 flex items-center justify-between">
                    <span>OpenAI API Key</span>
                    <button
                      type="button"
                      onClick={() => toggleSecret("openai_key")}
                      className="text-[10px] text-slate-500 hover:text-slate-300"
                    >
                      {showSecrets["openai_key"] ? "Hide" : "Show"}
                    </button>
                  </label>
                  <input
                    type={showSecrets["openai_key"] ? "text" : "password"}
                    placeholder="sk-proj-..."
                    value={config.OPENAI_API_KEY || ""}
                    onChange={(e) => updateField("OPENAI_API_KEY", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Council Models (Comma-separated)</label>
                  <input
                    type="text"
                    placeholder="gpt-4o,o1-mini"
                    value={config.AURA_OPENAI_MODELS || "gpt-4o,o1-mini"}
                    onChange={(e) => updateField("AURA_OPENAI_MODELS", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Max Concurrency</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={config.AURA_OPENAI_MAX_CONCURRENCY || "4"}
                    onChange={(e) => updateField("AURA_OPENAI_MAX_CONCURRENCY", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Timeout Seconds</label>
                  <input
                    type="number"
                    min="5"
                    max="120"
                    value={config.AURA_OPENAI_TIMEOUT_SECONDS || "30"}
                    onChange={(e) => updateField("AURA_OPENAI_TIMEOUT_SECONDS", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Ollama Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-indigo-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">Local Ollama (Private Self-Hosted Models)</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "ollama"}
                  onClick={() => testIntegration("ollama")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-indigo-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  Ping Ollama
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Ollama Service URL</label>
                  <input
                    type="text"
                    placeholder="http://localhost:11434"
                    value={config.AURA_OLLAMA_URL || "http://localhost:11434"}
                    onChange={(e) => updateField("AURA_OLLAMA_URL", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-indigo-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Local Tagged Models</label>
                  <input
                    type="text"
                    placeholder="llama3.3:latest,deepseek-r1:14b"
                    value={config.AURA_OLLAMA_MODELS || "llama3.3:latest,deepseek-r1:14b"}
                    onChange={(e) => updateField("AURA_OLLAMA_MODELS", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-indigo-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Think / Reasoning Mode</label>
                  <select
                    value={config.AURA_OLLAMA_THINK || "true"}
                    onChange={(e) => updateField("AURA_OLLAMA_THINK", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-indigo-500 outline-none"
                  >
                    <option value="true">True (Enable Chain-of-Thought deliberation)</option>
                    <option value="false">False (Direct output for lower latency)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Model Keep Alive</label>
                  <input
                    type="text"
                    placeholder="5m"
                    value={config.AURA_OLLAMA_KEEP_ALIVE || "5m"}
                    onChange={(e) => updateField("AURA_OLLAMA_KEEP_ALIVE", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-indigo-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* AI Council Rules */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <h3 className="text-sm font-semibold text-slate-200 mb-3 pb-2 border-b border-slate-800">
                Multi-Agent Deliberation Rules
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">AI Preset Profile</label>
                  <select
                    value={config.AURA_FREE_AI_PRESET || "balanced"}
                    onChange={(e) => updateField("AURA_FREE_AI_PRESET", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  >
                    <option value="balanced">Balanced (High quality + fast consensus)</option>
                    <option value="strict">Strict (Requires 5/6 unanimous support)</option>
                    <option value="fast">Ultra-Fast (Reduced rounds for scalping)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Opinions per Specialist Role</label>
                  <input
                    type="number"
                    min="1"
                    max="5"
                    value={config.AURA_AI_OPINIONS_PER_ROLE || "3"}
                    onChange={(e) => updateField("AURA_AI_OPINIONS_PER_ROLE", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Per-Agent Timeout (Seconds)</label>
                  <input
                    type="number"
                    min="5"
                    max="60"
                    value={config.AURA_AI_AGENT_TIMEOUT_SECONDS || "15"}
                    onChange={(e) => updateField("AURA_AI_AGENT_TIMEOUT_SECONDS", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "feeds" && (
          <div className="space-y-6">
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <h3 className="text-sm font-semibold text-slate-200 mb-3 pb-2 border-b border-slate-800">
                Macroeconomic & Stock Fundamental Feeds
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Alpha Vantage API Key</label>
                  <input
                    type="password"
                    placeholder="ALPHA_VANTAGE_KEY"
                    value={config.AURA_ALPHA_VANTAGE_API_KEY || ""}
                    onChange={(e) => updateField("AURA_ALPHA_VANTAGE_API_KEY", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Used for multi-market global equity fundamental quotes and Forex tickers.</p>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">FRED API Key (St. Louis Federal Reserve)</label>
                  <input
                    type="password"
                    placeholder="FRED_API_KEY"
                    value={config.AURA_FRED_API_KEY || ""}
                    onChange={(e) => updateField("AURA_FRED_API_KEY", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-cyan-500 outline-none"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Used for real-time 10-year US Treasury yield curves, CPI inflation and central bank balance sheets.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "alerts" && (
          <div className="space-y-6">
            {/* Telegram Section */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
                  <h3 className="text-sm font-semibold text-slate-200">Telegram Instant Alerts Dispatch</h3>
                </div>
                <button
                  type="button"
                  disabled={testingId === "telegram"}
                  onClick={() => testIntegration("telegram")}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-sky-400 border border-slate-700 rounded transition-colors disabled:opacity-50"
                >
                  Ping Telegram Bot
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Telegram Bot Token</label>
                  <input
                    type="password"
                    placeholder="123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
                    value={config.AURA_TELEGRAM_BOT_TOKEN || ""}
                    onChange={(e) => updateField("AURA_TELEGRAM_BOT_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-sky-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Telegram Chat ID</label>
                  <input
                    type="text"
                    placeholder="e.g. -1001234567890 or 987654321"
                    value={config.AURA_TELEGRAM_CHAT_ID || ""}
                    onChange={(e) => updateField("AURA_TELEGRAM_CHAT_ID", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-sky-500 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Owner Auth & Real Money Locked Guard */}
            <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800">
              <h3 className="text-sm font-semibold text-slate-200 mb-3 pb-2 border-b border-slate-800">
                Security & Guardrails
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Command Center Owner ID</label>
                  <input
                    type="text"
                    value={config.AURA_COMMAND_CENTER_OWNER_ID || "owner_sv"}
                    onChange={(e) => updateField("AURA_COMMAND_CENTER_OWNER_ID", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Owner Command Access Token</label>
                  <input
                    type="password"
                    value={config.AURA_COMMAND_CENTER_TOKEN || "aura_local_dev_token"}
                    onChange={(e) => updateField("AURA_COMMAND_CENTER_TOKEN", e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 font-mono text-xs focus:border-emerald-500 outline-none"
                  />
                </div>
                <div className="sm:col-span-2 p-3 rounded bg-rose-950/20 border border-rose-900/50 flex items-center justify-between">
                  <div>
                    <span className="text-rose-400 font-semibold block text-xs">Real Money Live Trading Gate</span>
                    <span className="text-slate-400 text-[11px]">
                      By default, AURA enforces strict DEMO / Simulation protection. Real money is hard-locked.
                    </span>
                  </div>
                  <span className="px-3 py-1 bg-rose-950 text-rose-300 border border-rose-800 rounded text-xs font-mono font-bold">
                    PROTECTED DEMO
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer Action Bar */}
      <div className="p-4 bg-slate-900 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-slate-400 flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Changes are cached instantly in local app state & synchronized across sessions.</span>
        </div>
        <div className="flex items-center gap-2">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 rounded-lg transition-colors"
            >
              Cancel
            </button>
          )}
          <button
            id="btn-save-credentials"
            type="button"
            disabled={saving}
            onClick={saveConfig}
            className="px-5 py-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg shadow-lg shadow-emerald-900/30 transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {saving ? "Saving Changes..." : "Save Credentials in App"}
          </button>
        </div>
      </div>
    </div>
  );
}
