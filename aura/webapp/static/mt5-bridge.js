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

  function installTradingPreview() {
    const trading = document.getElementById("view-trading");
    if (!trading || document.getElementById("mt5ProtectedPreview")) return;
    const preview = document.createElement("div");
    preview.id = "mt5ProtectedPreview";
    preview.className = "panel";
    preview.innerHTML = `<div class="panel-head"><div><h2>Protected DEMO Order Preview</h2><p>Broker order_check only · minimum volume · native SL/TP · never sends an order</p></div><span class="badge ui_connected">NO SEND</span></div>
      <div class="panel-body form-grid"><div class="field"><label>Exact broker symbol</label><input id="previewSymbol" value="XAUUSD" maxlength="120" /></div><div class="field"><label>Side</label><select id="previewSide"><option>BUY</option><option>SELL</option></select></div><div class="span-2"><button class="btn primary" id="previewOrderBtn">Preview protected DEMO order</button></div><div class="span-2 notice info" id="previewOrderResult">No order preview has been run. A preview cannot submit a trade.</div></div>`;
    trading.querySelector(".grid-2")?.insertAdjacentElement("afterend", preview);
    document.getElementById("previewOrderBtn")?.addEventListener("click", async () => {
      const result = document.getElementById("previewOrderResult");
      const symbol = document.getElementById("previewSymbol").value.trim();
      const side = document.getElementById("previewSide").value;
      result.className = "span-2 notice info";
      result.textContent = `Checking ${side} ${symbol} without sending…`;
      try {
        const response = await fetch(`/api/mt5/execution-check?symbol=${encodeURIComponent(symbol)}&side=${encodeURIComponent(side)}`, {cache:"no-store"});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "preview blocked");
        result.className = "span-2 notice good";
        result.textContent = `${data.side} ${data.symbol} · min ${data.minimum_volume} · margin ${data.margin_required} · entry ${data.entry_price} · SL ${data.native_stop} · TP ${data.native_target} · broker order_check accepted · ORDER NOT SENT`;
      } catch (error) {
        result.className = "span-2 notice bad";
        result.textContent = `Preview blocked: ${error.message} · ORDER NOT SENT`;
      }
    });
  }

  let symbolData = [];
  let selectedSymbol = "XAUUSD";
  let matchingCount = 0;
  let searchVersion = 0;
  let searchTimer;

  async function searchSymbols() {
    const version = ++searchVersion;
    const query = document.getElementById("mt5SymbolSearch").value.trim();
    document.getElementById("mt5ShownCount").textContent = "Searching full broker catalogue…";
    try {
      const response = await fetch(`/api/mt5/preflight?max_symbols=200&q=${encodeURIComponent(query)}`, {cache:"no-store"});
      const data = await response.json();
      if (version !== searchVersion) return;
      if (!response.ok || !data.ok) throw new Error(data.error || "Symbol search failed");
      symbolData = data.symbols || [];
      matchingCount = data.matched_symbol_count ?? symbolData.length;
      renderSymbols();
    } catch (error) {
      if (version !== searchVersion) return;
      symbolData = [];
      renderSymbols();
      document.getElementById("mt5ShownCount").textContent = `Search unavailable: ${error.message}`;
    }
  }

  function renderSymbols() {
    const list = document.getElementById("mt5Symbols");
    const count = document.getElementById("mt5ShownCount");
    if (!list) return;
    const query = (document.getElementById("mt5SymbolSearch")?.value || "").trim().toLowerCase();
    const filtered = symbolData.filter((item) => {
      const haystack = `${item.symbol || ""} ${item.description || ""} ${item.broker_path || ""} ${item.asset_class || ""} ${item.currency || ""}`.toLowerCase();
      return !query || haystack.includes(query);
    });
    list.innerHTML = filtered.length
      ? filtered.slice(0, 200).map((item) => `<button type="button" class="mt5-symbol" title="${esc(item.description)} · ${esc(item.broker_path)} · broker trade mode ${esc(item.trade_mode)}" data-symbol="${esc(item.symbol)}">${esc(item.symbol)}<em>${esc(item.description || item.asset_class || "")}</em></button>`).join("")
      : '<span class="mt5-symbol">No matching tradable contract on this broker. Check the broker account/product catalogue; similarly named shares or ETFs are not substitutes.</span>';
    list.querySelectorAll("[data-symbol]").forEach((button) => button.addEventListener("click", () => {
      selectedSymbol = button.dataset.symbol || selectedSymbol;
      const input = document.getElementById("mt5SymbolSearch");
      if (input) input.value = selectedSymbol;
      const chartSymbol = document.getElementById("chartSymbol");
      if (chartSymbol) chartSymbol.value = selectedSymbol;
      document.querySelector('.nav-item[data-view="charts"]')?.click();
      document.getElementById("chartForm")?.requestSubmit();
      document.getElementById("mt5ExecutionState").textContent = `Selected ${selectedSymbol}. Click Check Execution to validate minimum-volume margin, filling mode and native SL/TP without sending an order.`;
    }));
    if (count) count.textContent = `${Math.min(filtered.length, 200)} shown / ${matchingCount} broker matches`;
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
    const preferred = ["XAUUSD", "XAUUSDm"];
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
      matchingCount = data.matched_symbol_count ?? symbolData.length;
      selectedSymbol = chooseDefaultSymbol();
      renderSymbols();
      const clock = data.market_clock || {};
      const clockSafe = data.market_clock_ok === true;
      setHealth(clockSafe ? "good" : "bad", clockSafe
        ? `MT5 DEMO connected. ${data.tradable_symbol_count || 0} broker symbols discovered; this is not active scan coverage or execution readiness. Data and risk checks still apply.`
        : `MT5 DEMO connected, but trading start is blocked: ${clock.error || "broker clock evidence unavailable"} (${clock.future_skew_seconds ?? "unknown"} seconds future skew).`);
      const execState = document.getElementById("mt5ExecutionState");
      if (execState) execState.textContent = `Connection ready. Selected ${selectedSymbol}; run Check Execution for a no-send broker acceptance test.`;
      if (execButton) execButton.disabled = !clockSafe;
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
    installTradingPreview();
    const maxSymbols = document.getElementById("maxSymbols");
    if (maxSymbols && maxSymbols.value === "10") maxSymbols.value = "25";
    const maxBatches = document.getElementById("maxBatches");
    if (maxBatches) {
      maxBatches.min = "0";
      maxBatches.value = "0";
      maxBatches.previousElementSibling.textContent = "Batch limit (0 = continuous)";
    }
    document.getElementById("mt5CheckBtn")?.addEventListener("click", checkMT5);
    document.getElementById("mt5ExecCheckBtn")?.addEventListener("click", checkExecution);
    document.getElementById("mt5SymbolSearch")?.addEventListener("input", () => {
      ++searchVersion;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(searchSymbols, 350);
    });
    document.getElementById("mt5TradingBtn")?.addEventListener("click", () => {
      const button = document.querySelector('.nav-item[data-view="trading"]');
      if (button) button.click();
    });
    setTimeout(checkMT5, 500);
  });
})();
