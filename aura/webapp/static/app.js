const $ = (id) => document.getElementById(id);

const state = {
  workspace: null,
  runtime: null,
  catalog: null,
  algoOptions: null,
  candidates: [],
  installPrompt: null,
};

const featureSets = {
  scannerFeatures: [
    "market_scanner","market_data_quality","technical_intelligence","smc_ict",
    "volume_vwap","options_intelligence","regime_engine","cross_market"
  ],
  portfolioFeatures: ["portfolio_ledger","order_state","reconciliation"],
  riskFeatures: ["risk_engine","kill_switch","order_state","reconciliation","live_money","fund_transfer","withdrawal"],
  agentFeatures: ["ai_council","specialist_agents","adversarial_reasoning","ceo_orchestrator","explainability","aura_chat","browser_voice","wake_word"],
  forecastFeatures: ["forecasting","ai_council","regime_engine","cross_market"],
  newsFeatures: ["macro_news","knowledge_rag","cross_market"],
  knowledgeFeatures: ["knowledge_rag","cognitive_memory","macro_news"],
  strategyFeatures: ["strategy_library","ai_strategy_architect","algo_studio","autonomous_lab"],
  backtestFeatures: ["backtest","walk_forward","monte_carlo","holdout","parameter_stability","regime_validation"],
  learningFeatures: ["self_learning","shadow_learning","champion_challenger","cognitive_memory","autonomous_lab"],
  brokerFeatures: ["mt5_connector","dhan_connector","angel_one_connector","binance_connector","kraken_connector","oanda_connector"],
  alertFeatures: ["telegram_alerts","whatsapp_alerts","browser_voice"],
  healthFeatures: ["system_health","audit_lineage","market_data_quality","reconciliation"],
  developerFeatures: ["developer_ai","financial_corrections","owner_authority","audit_lineage"],
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

function maskedLogin(value) {
  if (!value) return "—";
  const text = String(value);
  return text.length > 4 ? `••••${text.slice(-4)}` : text;
}

function humanStatus(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

function splitCSV(value) {
  return String(value || "").split(",").map((x) => x.trim()).filter(Boolean);
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3000);
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

async function postJSON(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function navigate(view) {
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  $("sidebar").classList.remove("open");
  $("scrim").classList.remove("show");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function initNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.view));
  });
  document.querySelectorAll("[data-open-view]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.openView));
  });
  $("mobileMenu").addEventListener("click", () => {
    $("sidebar").classList.toggle("open");
    $("scrim").classList.toggle("show");
  });
  $("scrim").addEventListener("click", () => {
    $("sidebar").classList.remove("open");
    $("scrim").classList.remove("show");
  });

  $("globalSearch").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const query = event.currentTarget.value.trim().toLowerCase();
    if (!query) return;
    const hit = [...document.querySelectorAll(".nav-item")].find((node) =>
      node.textContent.toLowerCase().includes(query)
    );
    if (hit) {
      navigate(hit.dataset.view);
      event.currentTarget.value = "";
    } else {
      toast(`No workspace matched "${query}"`);
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("globalSearch").focus();
    }
  });
}

function renderOpportunityRows(items) {
  if (!Array.isArray(items) || !items.length) {
    return '<tr><td colspan="5" class="empty">No fresh opportunities yet.</td></tr>';
  }
  return items.map((item) => {
    const intent = String(item.intent || "—").toLowerCase();
    return `<tr>
      <td><b>${esc(item.symbol)}</b></td>
      <td>${esc(item.timeframe)}</td>
      <td class="intent ${esc(intent)}">${esc(String(item.intent || "—").toUpperCase())}</td>
      <td>${esc(item.confidence ?? "—")}</td>
      <td>${item.agent_policy_allowed === true ? '<span class="badge ui_connected">Allowed</span>' :
        item.agent_policy_allowed === false ? '<span class="badge blocked">Blocked</span>' : "—"}</td>
    </tr>`;
  }).join("");
}

function renderOrderRows(items) {
  if (!Array.isArray(items) || !items.length) {
    return '<tr><td colspan="4" class="empty">No submitted DEMO orders yet.</td></tr>';
  }
  return items.map((item) => `<tr>
    <td><b>${esc(item.symbol)}</b></td>
    <td>${esc(item.side)}</td>
    <td>${esc(item.quantity)}</td>
    <td class="mono">${esc(item.broker_order_id)}</td>
  </tr>`).join("");
}

function setPill(node, mode, text) {
  node.className = `status-pill ${mode || ""}`;
  node.querySelector("span").textContent = text;
}

function updateRuntime(runtime) {
  state.runtime = runtime;
  const status = runtime.status || {};
  const baseline = runtime.baseline || {};
  const counters = status.counters || {};
  const latest = status.latest || {};
  const bootstrap = status.bootstrap || {};

  setPill(
    $("runtimePill"),
    runtime.app_kill_locked ? "bad" : runtime.runtime_running ? "good" : "",
    runtime.app_kill_locked ? "KILL LOCKED" : runtime.runtime_running ? "Runtime active" : "Runtime stopped"
  );

  const account = baseline.login || bootstrap.account_login;
  const server = baseline.server || bootstrap.account_server;
  setPill($("mt5Pill"), account ? "good" : "", account ? "MT5 DEMO linked" : "MT5 waiting");

  $("metricAccount").textContent = maskedLogin(account);
  $("metricServer").textContent = server || "Waiting for runtime";
  $("metricEquity").textContent = latest.portfolio_equity ?? baseline.starting_balance ?? "—";
  $("metricCurrency").textContent = baseline.currency || bootstrap.account_currency || "—";
  $("metricDrawdown").textContent = latest.drawdown_pct != null ? `${latest.drawdown_pct}%` : "—";
  $("metricOpps").textContent = counters.opportunities ?? 0;
  $("metricOrders").textContent = `${counters.submitted_orders ?? 0} / ${counters.fills ?? 0}`;
  $("metricAlgos").textContent = state.workspace?.algo?.candidate_count ?? state.candidates.length ?? 0;

  const oppHTML = renderOpportunityRows(latest.opportunities);
  ["homeOppRows","scannerRows","opportunityRows"].forEach((id) => { if ($(id)) $(id).innerHTML = oppHTML; });
  $("tradeOrderRows").innerHTML = renderOrderRows(latest.submitted_orders);

  $("portfolioEquity").textContent = latest.portfolio_equity ?? baseline.starting_balance ?? "—";
  $("portfolioGross").textContent = latest.gross_exposure ?? "—";
  $("portfolioRecons").textContent = counters.reconciliations ?? 0;
  $("portfolioOrders").textContent = counters.submitted_orders ?? 0;
  $("portfolioFills").textContent = counters.fills ?? 0;
  $("portfolioCurrency").textContent = baseline.currency || bootstrap.account_currency || "—";
  $("runtimeLogs").textContent = runtime.log_tail || "No runtime log yet.";

  const riskKill = status.risk_kill_switch === true;
  const riskNode = $("riskKillCard");
  riskNode.textContent = riskKill ? `Risk kill: ${status.risk_kill_switch_reason || "engaged"}` : "Kill switch clear";
  riskNode.classList.toggle("bad", riskKill);
  riskNode.classList.toggle("good", !riskKill);

  const locked = runtime.app_kill_locked === true;
  const running = runtime.runtime_running === true;
  ["startBtn","quickStart"].forEach((id) => {
    if ($(id)) $(id).disabled = running || locked;
  });
  ["stopBtn","quickStop"].forEach((id) => {
    if ($(id)) $(id).disabled = !running;
  });
  ["killBtn","quickKill"].forEach((id) => {
    if ($(id)) $(id).disabled = locked;
  });
  $("resetBtn").classList.toggle("hidden", !locked);
}

function featureById(id) {
  return state.catalog?.items?.find((item) => item.id === id);
}

function featureCard(item) {
  if (!item) return "";
  const evidence = Array.isArray(item.evidence) && item.evidence.length
    ? item.evidence.map(esc).join(" · ")
    : "No completed implementation evidence";
  return `<article class="feature-card">
    <div class="feature-top"><h3>${esc(item.name)}</h3><span class="badge ${esc(item.status)}">${esc(humanStatus(item.status))}</span></div>
    <p>${esc(item.description)}</p>
    <div class="evidence">${evidence}</div>
  </article>`;
}

function renderFeatureSets() {
  Object.entries(featureSets).forEach(([containerId, ids]) => {
    const node = $(containerId);
    if (!node) return;
    node.className = node.classList.contains("feature-grid") ? node.className : "feature-grid";
    node.innerHTML = ids.map((id) => featureCard(featureById(id))).join("");
  });

  const agentNames = [
    ["HTF Bias","Higher-timeframe directional context"],
    ["SMC / ICT","Structure, liquidity and imbalance evidence"],
    ["Technical","EMA/RSI/MACD/volatility evidence"],
    ["Volume / VWAP","Participation and value evidence"],
    ["Forecast","Calibrated probability / quantile view"],
    ["Options / Volatility","IV, Greeks and chain context"],
    ["Macro / Sentiment","Trusted event and news evidence"],
    ["Cross-market","Intermarket confirmation"],
    ["Regime","Trend/range/chop state"],
    ["Execution Quality","Spread, liquidity and friction"],
  ];
  $("homeAgents").innerHTML = agentNames.slice(0,5).map(([name, desc], index) =>
    `<div class="agent-row"><div><b>${esc(name)}</b><small>${esc(desc)}</small><div class="progress"><i style="width:${72-index*5}%"></i></div></div><span class="badge backend_ready">ready</span></div>`
  ).join("");
}

function renderCapabilityMatrix() {
  const catalog = state.catalog;
  if (!catalog) return;
  const counts = catalog.counts || {};
  const items = [
    ["UI connected", counts.ui_connected || 0],
    ["Backend ready", counts.backend_ready || 0],
    ["Partial", counts.partial || 0],
    ["External gate", counts.external_gate || 0],
    ["Pending / blocked", (counts.pending || 0) + (counts.blocked || 0)],
  ];
  $("capabilitySummary").innerHTML = items.map(([label, value]) =>
    `<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`
  ).join("");
  $("capabilityRows").innerHTML = catalog.items.map((item) => `<tr>
    <td>${esc(item.group)}</td>
    <td><b>${esc(item.name)}</b></td>
    <td><span class="badge ${esc(item.status)}">${esc(humanStatus(item.status))}</span></td>
    <td style="white-space:normal;min-width:260px">${esc(item.description)}</td>
    <td class="mono" style="white-space:normal;min-width:260px">${esc((item.evidence || []).join(" · ") || "—")}</td>
  </tr>`).join("");
}

function renderPipeline(containerId, completed = []) {
  const node = $(containerId);
  if (!node) return;
  const pipeline = state.algoOptions?.validation_pipeline || state.workspace?.algo?.validation_pipeline || [
    "compile","causal_backtest","purged_walk_forward","monte_carlo_robustness",
    "sealed_holdout","parameter_stability","regime_validation","paper_demo_forward","human_approval"
  ];
  node.innerHTML = pipeline.map((step, index) => {
    const done = completed.includes(step);
    const current = !done && index === completed.length;
    return `<span class="pipe-step ${done ? "done" : current ? "current" : ""}">${esc(step.replaceAll("_"," "))}</span>`;
  }).join("");
}

function prettyLabel(value) {
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function renderChoices(containerId, name, values, defaults) {
  const node = $(containerId);
  node.innerHTML = values.map((value) => `<label class="choice">
    <input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${defaults.includes(value) ? "checked" : ""}>
    ${esc(prettyLabel(value))}
  </label>`).join("");
}

function selected(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((node) => node.value);
}

function renderAlgoOptions() {
  if (!state.algoOptions) return;
  renderChoices("algoEntries", "algo_entries", state.algoOptions.entries || [], ["liquidity_sweep","bos_choch"]);
  renderChoices("algoConfirmations", "algo_confirmations", state.algoOptions.confirmations || [], ["relative_volume","regime"]);
  renderChoices("algoExits", "algo_exits", state.algoOptions.exits || [], ["atr_stop","risk_reward_target"]);
  renderPipeline("algoPipeline");
  renderPipeline("homePipeline");
  renderPipeline("backtestPipeline");
}

function renderCandidates() {
  const node = $("strategyCandidates");
  $("metricAlgos").textContent = state.candidates.length;
  if (!state.candidates.length) {
    node.innerHTML = '<div class="empty">No local Algo Studio candidates yet.</div>';
    return;
  }
  node.innerHTML = state.candidates.slice(0,8).map((candidate) => {
    const algo = candidate.algorithm || {};
    const validation = candidate.validation || {};
    return `<div class="feature-card" style="margin-bottom:8px">
      <div class="feature-top"><h3>${esc(candidate.owner_name || candidate.candidate_id)}</h3><span class="badge ${algo.compilable ? "ui_connected" : "blocked"}">${algo.compilable ? "compiled" : "blocked"}</span></div>
      <p>${esc(candidate.blueprint?.market_scope?.join(", ") || "—")} · ${esc(candidate.blueprint?.timeframe_scope?.join(", ") || "—")} · stage ${esc(candidate.stage)}</p>
      <div class="evidence">${esc(candidate.candidate_id)} · next: ${esc(validation.next_required || "—")}</div>
    </div>`;
  }).join("");
}

async function refreshWorkspace({quiet=false} = {}) {
  try {
    const workspace = await getJSON("/api/workspace");
    state.workspace = workspace;
    state.catalog = workspace.capabilities;
    updateRuntime(workspace.runtime);
    renderFeatureSets();
    renderCapabilityMatrix();
    renderPipeline("homePipeline");
    if (!quiet) toast("AURA workspace refreshed");
  } catch (error) {
    if (!quiet) toast(`Workspace error: ${error.message}`);
  }
}

async function refreshAlgos() {
  try {
    const [options, candidates] = await Promise.all([
      getJSON("/api/algo/options"),
      getJSON("/api/algo/candidates"),
    ]);
    state.algoOptions = options;
    state.candidates = candidates.items || [];
    renderAlgoOptions();
    renderCandidates();
  } catch (error) {
    toast(`Algo Studio error: ${error.message}`);
  }
}

function setTradeMessage(message, mode="info") {
  const node = $("tradeMessage");
  node.className = `notice ${mode}`;
  node.textContent = message;
}

async function startRuntime() {
  const maxSymbols = Number($("maxSymbols")?.value || 10);
  const maxBatches = Number($("maxBatches")?.value || 100);
  try {
    setTradeMessage("Starting protected MT5 DEMO runtime...");
    await postJSON("/api/start", { max_symbols:maxSymbols, max_batches:maxBatches });
    await refreshWorkspace({quiet:true});
    setTradeMessage("AURA DEMO runtime started. Scanner/agents will populate after closed-candle work begins.", "good");
  } catch (error) {
    setTradeMessage(error.message);
    toast(error.message);
  }
}

async function stopRuntime() {
  try {
    await postJSON("/api/stop");
    await refreshWorkspace({quiet:true});
    setTradeMessage("AURA runtime stopped.");
  } catch (error) {
    setTradeMessage(error.message);
  }
}

async function killRuntime() {
  if (!confirm("Emergency lock will stop the AURA DEMO child process and block restart until you reset the lock. Continue?")) return;
  try {
    await postJSON("/api/kill", { reason:"Emergency lock from owner command center" });
    await refreshWorkspace({quiet:true});
    setTradeMessage("Emergency lock engaged.", "info");
    toast("Emergency lock engaged");
  } catch (error) {
    setTradeMessage(error.message);
  }
}

async function resetKill() {
  if (!confirm("Reset the local emergency lock? The independent financial RiskEngine may still veto trading.")) return;
  try {
    await postJSON("/api/reset-kill");
    await refreshWorkspace({quiet:true});
    setTradeMessage("Local emergency lock reset. DEMO runtime is still stopped until started.");
  } catch (error) {
    setTradeMessage(error.message);
  }
}

function initRuntimeControls() {
  ["startBtn","quickStart"].forEach((id) => $(id)?.addEventListener("click", startRuntime));
  ["stopBtn","quickStop"].forEach((id) => $(id)?.addEventListener("click", stopRuntime));
  ["killBtn","quickKill"].forEach((id) => $(id)?.addEventListener("click", killRuntime));
  $("resetBtn").addEventListener("click", resetKill);
}

async function buildAlgo(event) {
  event.preventDefault();
  const payload = {
    name: $("algoName").value.trim(),
    thesis: $("algoThesis").value.trim(),
    markets: splitCSV($("algoMarkets").value),
    timeframes: splitCSV($("algoTimeframes").value),
    entries: selected("algo_entries"),
    confirmations: selected("algo_confirmations"),
    exits: selected("algo_exits"),
  };
  const button = $("buildAlgoBtn");
  button.disabled = true;
  $("algoResult").textContent = "Compiling allow-listed strategy blueprint...";
  try {
    const candidate = await postJSON("/api/algo/build", payload);
    $("algoResult").textContent = JSON.stringify({
      candidate_id: candidate.candidate_id,
      stage: candidate.stage,
      compilable: candidate.algorithm?.compilable,
      compiled_strategy_id: candidate.algorithm?.strategy_id,
      warmup_bars: candidate.algorithm?.warmup_bars,
      entries: candidate.blueprint?.entries,
      confirmations: candidate.blueprint?.confirmations,
      exits: candidate.blueprint?.exits,
      next_required: candidate.validation?.next_required,
      live_approved: candidate.live_approved,
    }, null, 2);
    renderPipeline("algoPipeline", candidate.validation?.completed || []);
    await refreshAlgos();
    toast("Research algo candidate compiled");
  } catch (error) {
    $("algoResult").textContent = `Build blocked: ${error.message}`;
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

function initAlgoStudio() {
  $("algoForm").addEventListener("submit", buildAlgo);
}

function openAssistant() {
  $("assistantDrawer").classList.add("open");
  $("chatInput").focus();
}
function closeAssistant() {
  $("assistantDrawer").classList.remove("open");
}

function addBubble(kind, text) {
  const node = document.createElement("div");
  node.className = `bubble ${kind}`;
  node.textContent = text;
  $("chatBody").appendChild(node);
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
}

function assistantReply(text) {
  const q = text.toLowerCase();
  const runtime = state.runtime || {};
  const status = runtime.status || {};
  const counters = status.counters || {};
  const baseline = runtime.baseline || {};
  const counts = state.catalog?.counts || {};

  if (q.includes("status") || q.includes("running") || q.includes("chalu")) {
    return `Runtime: ${runtime.app_kill_locked ? "EMERGENCY LOCKED" : runtime.runtime_running ? "ACTIVE" : "STOPPED"}.
MT5: ${baseline.server ? `DEMO server ${baseline.server}` : "waiting for runtime/account snapshot"}.
Opportunities: ${counters.opportunities ?? 0}; orders: ${counters.submitted_orders ?? 0}; fills: ${counters.fills ?? 0}.
Real-money is disabled in this PWA.`;
  }
  if (q.includes("risk") || q.includes("safety") || q.includes("safe")) {
    return `Independent RiskEngine remains final financial authority. Local emergency lock: ${runtime.app_kill_locked ? "ENGAGED" : "clear"}. Real-money, fund transfer and withdrawal are disabled. AI/CEO output cannot bypass the risk layer.`;
  }
  if (q.includes("broker") || q.includes("mt5") || q.includes("exness")) {
    return `MT5/Exness DEMO is the UI-connected execution path in this local app. Dhan, Angel One and OANDA require account/credential validation; Binance/Kraken have market-data foundations. Check “Brokers & Data” for truthful status.`;
  }
  if (q.includes("algo") || q.includes("strategy")) {
    return `Local Algo Studio candidates: ${state.candidates.length}. One-click compilation creates immutable RESEARCH candidates from safe primitives. They still need causal backtest → walk-forward → robustness → holdout → paper/demo → human approval.`;
  }
  if (q.includes("feature") || q.includes("capabil") || q.includes("kitna") || q.includes("kya kya")) {
    return `Capability inventory: ${counts.ui_connected || 0} UI-connected, ${counts.backend_ready || 0} backend-ready, ${counts.partial || 0} partial, ${counts.external_gate || 0} external-gated, ${counts.pending || 0} pending. Open Owner Control for A-to-Z evidence paths.`;
  }
  if (q.includes("predict") || q.includes("forecast")) {
    return `AURA's design uses probabilistic forecasts and calibration, not guaranteed future prediction. Forecast backend exists; the unified live forecast panel still needs its read-model bridge attached to this PWA.`;
  }
  if (q.includes("news") || q.includes("learn")) {
    return `AURA has trusted news/macro ingestion, Knowledge/RAG firewall, forward-only outcome learning and shadow/challenger research. The local PWA now exposes their status; deeper live feeds are being unified without inventing data.`;
  }
  return `I can currently answer local status, risk, brokers, capabilities, forecasts and Algo Studio state. The full provider-backed AURA chat bridge is a separate backend capability and is not being faked inside this local helper.`;
}

function initAssistant() {
  $("assistantFab").addEventListener("click", openAssistant);
  $("closeAssistant").addEventListener("click", closeAssistant);
  $("chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("chatInput");
    const text = input.value.trim();
    if (!text) return;
    addBubble("user", text);
    input.value = "";
    window.setTimeout(() => addBubble("aura", assistantReply(text)), 120);
  });

  $("voiceBtn").addEventListener("click", () => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      toast("Browser speech recognition is unavailable on this browser.");
      return;
    }
    const recognition = new Recognition();
    recognition.lang = "en-IN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const text = event.results[0][0].transcript;
      $("chatInput").value = text;
      addBubble("user", text);
      $("chatInput").value = "";
      addBubble("aura", assistantReply(text));
    };
    recognition.onerror = () => toast("Voice input failed or permission was denied.");
    recognition.start();
  });
}

function initInstall() {
  const button = $("installBtn");
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.installPrompt = event;
    button.disabled = false;
  });
  button.addEventListener("click", async () => {
    if (!state.installPrompt) {
      toast("Use your browser's Install App option if AURA is already eligible for installation.");
      return;
    }
    state.installPrompt.prompt();
    await state.installPrompt.userChoice;
    state.installPrompt = null;
  });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

async function boot() {
  initNavigation();
  initRuntimeControls();
  initAlgoStudio();
  initAssistant();
  initInstall();
  $("refreshOwner").addEventListener("click", () => refreshWorkspace());
  await Promise.all([refreshWorkspace({quiet:true}), refreshAlgos()]);
  updateRuntime(state.workspace?.runtime || state.runtime || {});
  renderFeatureSets();
  renderCapabilityMatrix();
  renderPipeline("homePipeline");
  renderPipeline("backtestPipeline");
  setInterval(() => refreshWorkspace({quiet:true}), 3000);
}

boot().catch((error) => toast(`AURA startup error: ${error.message}`));
