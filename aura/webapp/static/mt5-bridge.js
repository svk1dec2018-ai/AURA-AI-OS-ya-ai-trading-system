(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));

  function installStyles() {
    if (document.getElementById("aura-mt5-bridge-style")) return;
    const style = document.createElement("style");
    style.id = "aura-mt5-bridge-style";
    style.textContent = `
      .mt5-bridge{margin:0 0 14px;padding:16px;border:1px solid #1d3148;border-radius:16px;background:linear-gradient(135deg,#0b1624,#0a101b);box-shadow:0 14px 40px rgba(0,0,0,.18)}
      .mt5-bridge-head{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
      .mt5-bridge h2{margin:0 0 4px;font-size:17px}.mt5-bridge p{margin:0;color:#8fa6bf;font-size:12px}
      .mt5-bridge-actions{display:flex;gap:8px;flex-wrap:wrap}.mt5-btn{border:1px solid #28405d;border-radius:9px;padding:8px 12px;background:#101d2d;color:#dcecff;font-weight:700;cursor:pointer}.mt5-btn.primary{border-color:#2b7fff;background:#1159cf;color:white}.mt5-btn:disabled{opacity:.5;cursor:not-allowed}
      .mt5-status-grid{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));gap:8px;margin-top:12px}.mt5-stat{padding:10px;border:1px solid #172a3d;border-radius:10px;background:#0a1420}.mt5-stat small{display:block;color:#7089a3;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.mt5-stat b{display:block;margin-top:4px;font-size:14px;color:#edf7ff}
      .mt5-health{margin-top:10px;padding:10px 12px;border-radius:10px;font-size:12px}.mt5-health.good{background:#0d291f;border:1px solid #176347;color:#7ff0bc}.mt5-health.bad{background:#2b1519;border:1px solid #6d2834;color:#ff9eab}.mt5-health.wait{background:#211d0d;border:1px solid #655824;color:#e9d98a}
      .mt5-exec{margin-top:9px;padding:10px 12px;border-radius:10px;border:1px solid #20384f;background:#0a1420;color:#9fb5c9;font-size:11px}.mt5-exec.good{border-color:#176347;background:#0b2119;color:#77e8b5}.mt5-exec.bad{border-color:#6d2834;background:#271418;color:#ff9eab}
      .mt5-symbol-tools{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}.mt5-symbol-tools input{min-width:220px;flex:1;border:1px solid #213850;background:#08111b;color:#e9f4ff;border-radius:9px;padding:9px 11px}.mt5-count{font-size:11px;color:#8fa6bf}
      .mt5-symbols{display:flex;gap:6px;flex-wrap:wrap;max-height:132px;overflow:auto;margin-top:9px;padding-right:4px}.mt5-symbol{font-size:11px;border:1px solid #20384f;background:#0d1a28;color:#d9eaff;border-radius:999px;padding:5px 8px;cursor:pointer}.mt5-symbol:hover{border-color:#2b7fff}.mt5-symbol em{font-style:normal;color:#6fd7ff;margin-left:5px}
      @media(max-width:900px){.mt5-status-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function panel() {
    let node = document.getElementById("mt5OwnerBridge");
    if (node) return node;
    node = document.createElement("section");
    node.id = "mt5OwnerBridge";
    node.className = "mt5-bridge";
    node.innerHTML = `
      <div class="mt5-bridge-head">
        <div><h2>MT5 DEMO Connection & Live Symbol Universe</h2><p>Connection, broker symbols and a no-send execution check before autonomous DEMO trading.</p></div>
        <div class="mt5-bridge-actions"><button class="mt5-btn primary" id="mt5CheckBtn">Check MT5</button><button class="mt5-btn" id="mt5ExecCheckBtn" disabled>Check Execution</button><button class="mt5-btn" id="mt5TradingBtn">Open Trading Desk</button></div>
      </div>
      <div class="mt5-health wait" id="mt5Health">Checking local MetaTrader 5 DEMO session…</div>
      <div class="mt5-status-grid">
        <div class="mt5-stat"><small>Account</small><b id="mt5Account">—</b></div>
        <div class="mt5-stat"><small>Server</small><b id="mt5Server">—</b></div>
        <div class="mt5-stat"><small>Balance</small><b id="mt5Balance">—</b></div>
        <div class="mt5-stat"><small>Equity</small><b id="mt5Equity">—</b></div>
        <div class="mt5-stat"><small>Tradable symbols</small><b id="mt5SymbolCount">0</b></div>
      </div>
      <div class="mt5-exec" id="mt5ExecutionState">Execution readiness not checked. This check uses broker order_check only and never sends an order.</div>
      <div class="mt5-symbol-tools"><input id="mt5SymbolSearch" placeholder="Filter/select broker symbol, e.g. XAUUSD, BTC, EUR..."/><span class="mt5-count" id="mt5ShownCount"></span></div>
      <div class="mt5-symbols" id="mt5Symbols"><span class="mt5-symbol">Waiting for MT5…</span></div>`;
    const anchor = document.querySelector("#view-command .page-head");
    if (anchor && anchor.parentNode) anchor.insertAdjacentElement("afterend", node);
    else document.querySelector(".workspace")?.prepend(node);
    return node;
  }

  let symbolData = [];
  let selectedSymbol = "XAUUSD";

  function renderSymbols() {
    const list = document.getElementById("mt5Symbols");
    const count = document.getElementById("mt5ShownCount");
    if (!list) return;
    const query = (document.getElementById("mt5SymbolSearch")?.value || "").trim().toLowerCase();
    const filtered = symbolData.filter((item) => {
      const haystack = `${item.symbol || ""} ${item.asset_class || ""} ${item.currency || ""}`.toLowerCase();
      return !query || haystack.includes(query);
    });
    list.innerHTML = filtered.length
      ? filtered.slice(0, 200).map((item) => `<button type="button" class="mt5-symbol" data-symbol="${esc(item.symbol)}">${esc(item.symbol)}<em>${esc(item.asset_class || "")}</em></button>`).join("")
      : '<span class="mt5-symbol">No matching symbols</span>';
    list.querySelectorAll("[data-symbol]").forEach((button) => button.addEventListener("click", () => {
      selectedSymbol = button.dataset.symbol || selectedSymbol;
      const input = document.getElementById("mt5SymbolSearch");
      if (input) input.value = selectedSymbol;
      document.getElementById("mt5ExecutionState").textContent = `Selected ${selectedSymbol}. Click Check Execution to validate minimum-volume margin, filling mode and native SL/TP without sending an order.`;
    }));
    if (count) count.textContent = `${filtered.length} shown / ${symbolData.length} loaded`;
  }

  function setHealth(mode, message) {
    const node = document.getElementById("mt5Health");
    if (!node) return;
    node.className = `mt5-health ${mode}`;
    node.textContent = message;
  }

  function diagnosis(error) {
    const text = String(error || "Unknown MT5 error");
    const lower = text.toLowerCase();
    if (lower.includes("metatrader5 package")) return `${text} — Close AURA and double-click START_AURA_AI_OS.cmd again; it installs the official MT5 bridge automatically.`;
    if (lower.includes("initialize failed") || lower.includes("not connected") || lower.includes("account_info")) return `${text} — Open MetaTrader 5, log in to a DEMO account, wait until MT5 shows an active connection, then click Check MT5.`;
    if (lower.includes("demo")) return `${text} — AURA refuses real-money accounts. Switch MetaTrader 5 to your DEMO account and retry.`;
    return text;
  }

  function chooseDefaultSymbol() {
    const preferred = ["XAUUSD", "XAUUSDm", "GOLD"];
    for (const name of preferred) {
      const exact = symbolData.find((item) => String(item.symbol).toUpperCase() === name.toUpperCase());
      if (exact) return exact.symbol;
    }
    const gold = symbolData.find((item) => String(item.symbol).toUpperCase().includes("XAU"));
    return gold?.symbol || symbolData[0]?.symbol || "XAUUSD";
  }

  async function checkMT5() {
    setHealth("wait", "Checking MT5 terminal, DEMO guard and broker symbols…");
    const execButton = document.getElementById("mt5ExecCheckBtn");
    if (execButton) execButton.disabled = true;
    try {
      const runtime = await fetch("/api/status", { cache: "no-store" }).then((r) => r.json());
      if (runtime.runtime_running) {
        const bootstrap = runtime.status?.bootstrap || {};
        const baseline = runtime.baseline || {};
        document.getElementById("mt5Account").textContent = baseline.login ? `••••${String(baseline.login).slice(-4)}` : "linked";
        document.getElementById("mt5Server").textContent = baseline.server || bootstrap.account_server || "MT5 DEMO";
        document.getElementById("mt5Balance").textContent = baseline.starting_balance ?? "—";
        document.getElementById("mt5Equity").textContent = runtime.status?.latest?.portfolio_equity ?? "—";
        document.getElementById("mt5SymbolCount").textContent = bootstrap.discovered_symbols ?? bootstrap.active_symbols ?? "—";
        setHealth("good", "AURA runtime is active on a verified MT5 DEMO session. Symbol scanning is running from closed broker candles.");
        if (execButton) execButton.disabled = false;
        return;
      }
      const response = await fetch("/api/mt5/preflight?max_symbols=500", { cache: "no-store" });
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "MT5 preflight failed");
      const account = data.account || {};
      document.getElementById("mt5Account").textContent = account.login_last4 ? `••••${account.login_last4}` : "DEMO";
      document.getElementById("mt5Server").textContent = account.server || "—";
      document.getElementById("mt5Balance").textContent = account.balance ?? "—";
      document.getElementById("mt5Equity").textContent = account.equity ?? "—";
      document.getElementById("mt5SymbolCount").textContent = data.tradable_symbol_count ?? 0;
      symbolData = Array.isArray(data.symbols) ? data.symbols : [];
      selectedSymbol = chooseDefaultSymbol();
      renderSymbols();
      setHealth("good", `MT5 DEMO verified. ${data.tradable_symbol_count || 0} tradable broker symbols discovered. AURA can now start protected DEMO scanning/trading.`);
      const execState = document.getElementById("mt5ExecutionState");
      if (execState) execState.textContent = `Connection ready. Selected ${selectedSymbol}; run Check Execution for a no-send broker acceptance test.`;
      if (execButton) execButton.disabled = false;
    } catch (error) {
      symbolData = [];
      renderSymbols();
      ["mt5Account","mt5Server","mt5Balance","mt5Equity"].forEach((id) => { const n=document.getElementById(id); if(n) n.textContent="—"; });
      const n=document.getElementById("mt5SymbolCount"); if(n) n.textContent="0";
      setHealth("bad", diagnosis(error.message));
      const execState = document.getElementById("mt5ExecutionState");
      if (execState) { execState.className = "mt5-exec bad"; execState.textContent = "Execution check unavailable until MT5 DEMO connection succeeds."; }
    }
  }

  async function checkExecution() {
    const state = document.getElementById("mt5ExecutionState");
    const inputValue = (document.getElementById("mt5SymbolSearch")?.value || "").trim();
    const exact = symbolData.find((item) => String(item.symbol).toLowerCase() === inputValue.toLowerCase());
    const symbol = exact?.symbol || selectedSymbol || chooseDefaultSymbol();
    if (!symbol) return;
    state.className = "mt5-exec";
    state.textContent = `Checking ${symbol}: broker margin, filling mode and protected SL/TP via order_check only…`;
    try {
      const response = await fetch(`/api/mt5/execution-check?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "execution readiness check failed");
      state.className = "mt5-exec good";
      state.textContent = `${symbol} EXECUTION READY · min volume ${data.minimum_volume} · margin ${data.margin_required} · SL ${data.native_stop} · TP ${data.native_target} · order_check accepted · order_send NOT attempted${data.pyramiding_would_be_blocked ? " · existing AURA position: new same-direction pyramid would be blocked" : ""}`;
    } catch (error) {
      state.className = "mt5-exec bad";
      state.textContent = `Execution readiness blocked: ${diagnosis(error.message)}`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    installStyles();
    panel();
    document.getElementById("mt5CheckBtn")?.addEventListener("click", checkMT5);
    document.getElementById("mt5ExecCheckBtn")?.addEventListener("click", checkExecution);
    document.getElementById("mt5SymbolSearch")?.addEventListener("input", renderSymbols);
    document.getElementById("mt5TradingBtn")?.addEventListener("click", () => {
      const button = document.querySelector('.nav-item[data-view="trading"]');
      if (button) button.click();
    });
    setTimeout(checkMT5, 500);
  });
})();
