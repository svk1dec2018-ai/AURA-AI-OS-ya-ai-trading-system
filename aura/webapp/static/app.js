const $ = (id) => document.getElementById(id);

const state = {
  workspace: null,
  runtime: null,
  catalog: null,
  algoOptions: null,
  candidates: [],
  decisions: { items: [] },
  journal: { items: [] },
  learning: { status: {} },
  intelligence: { items: [] },
  installPrompt: null,
  ownerToken: sessionStorage.getItem("auraOwnerToken") || "",
};

const featureSets = {
  scannerFeatures: ["market_scanner","market_data_quality","technical_intelligence","smc_ict","volume_vwap","options_intelligence","regime_engine","cross_market"],
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
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
}

function maskedLogin(value) {
  if (!value) return "—";
  const text = String(value);
  return text.length > 4 ? `••••${text.slice(-4)}` : text;
}

function humanStatus(value) { return String(value || "unknown").replaceAll("_", " "); }
function splitCSV(value) { return String(value || "").split(",").map((x) => x.trim()).filter(Boolean); }
function fmtTime(value) {
  if (!value) return "—";
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
}

function toast(message) {
  const node = $("toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3200);
}

function apiHeaders(includeJson=false) {
  const headers = {};
  if (includeJson) headers["Content-Type"] = "application/json";
  if (state.ownerToken) headers.Authorization = `Bearer ${state.ownerToken}`;
  return headers;
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store", headers: apiHeaders(false) });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

async function postJSON(url, body={}) {
  const response = await fetch(url, {
    method: "POST",
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    if (response.status === 401) navigate("settings");
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function navigate(view) {
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  $("sidebar")?.classList.remove("open");
  $("scrim")?.classList.remove("show");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function initNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
  document.querySelectorAll("[data-open-view]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.openView)));
  $("mobileMenu")?.addEventListener("click", () => { $("sidebar")?.classList.toggle("open"); $("scrim")?.classList.toggle("show"); });
  $("scrim")?.addEventListener("click", () => { $("sidebar")?.classList.remove("open"); $("scrim")?.classList.remove("show"); });
  $("globalSearch")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const query = event.currentTarget.value.trim().toLowerCase();
    if (!query) return;
    const hit = [...document.querySelectorAll(".nav-item")].find((node) => node.textContent.toLowerCase().includes(query));
    if (hit) { navigate(hit.dataset.view); event.currentTarget.value = ""; } else toast(`No workspace matched "${query}"`);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault(); $("globalSearch")?.focus();
    }
  });
}

function renderOpportunityRows(items) {
  if (!Array.isArray(items) || !items.length) return '<tr><td colspan="5" class="empty">No fresh opportunities yet.</td></tr>';
  return items.map((item) => {
    const intent = String(item.intent || "—").toLowerCase();
    return `<tr><td><b>${esc(item.symbol)}</b></td><td>${esc(item.timeframe)}</td><td class="intent ${esc(intent)}">${esc(String(item.intent || "—").toUpperCase())}</td><td>${esc(item.confidence ?? "—")}</td><td>${item.agent_policy_allowed === true ? '<span class="badge ui_connected">Allowed</span>' : item.agent_policy_allowed === false ? '<span class="badge blocked">Blocked</span>' : "—"}</td></tr>`;
  }).join("");
}

function renderOrderRows(items) {
  if (!Array.isArray(items) || !items.length) return '<tr><td colspan="4" class="empty">No submitted DEMO orders yet.</td></tr>';
  return items.map((item) => `<tr><td><b>${esc(item.symbol)}</b></td><td>${esc(item.side)}</td><td>${esc(item.quantity)}</td><td class="mono">${esc(item.broker_order_id)}</td></tr>`).join("");
}

function setPill(node, mode, text) {
  if (!node) return;
  node.className = `status-pill ${mode || ""}`;
  node.querySelector("span").textContent = text;
}

function updateRuntime(runtime) {
  state.runtime = runtime || {};
  const status = state.runtime.status || {};
  const baseline = state.runtime.baseline || {};
  const counters = status.counters || {};
  const latest = status.latest || {};
  const bootstrap = status.bootstrap || {};
  setPill($("runtimePill"), state.runtime.app_kill_locked ? "bad" : state.runtime.runtime_running ? "good" : "", state.runtime.app_kill_locked ? "KILL LOCKED" : state.runtime.runtime_running ? "Runtime active" : "Runtime stopped");
  const account = baseline.login || bootstrap.account_login;
  const server = baseline.server || bootstrap.account_server;
  setPill($("mt5Pill"), account ? "good" : "", account ? "MT5 DEMO linked" : "MT5 waiting");
  if ($("metricAccount")) $("metricAccount").textContent = maskedLogin(account);
  if ($("metricServer")) $("metricServer").textContent = server || "Waiting for runtime";
  if ($("metricEquity")) $("metricEquity").textContent = latest.portfolio_equity ?? baseline.starting_balance ?? "—";
  if ($("metricCurrency")) $("metricCurrency").textContent = baseline.currency || bootstrap.account_currency || "—";
  if ($("metricDrawdown")) $("metricDrawdown").textContent = latest.drawdown_pct != null ? `${latest.drawdown_pct}%` : "—";
  if ($("metricOpps")) $("metricOpps").textContent = counters.opportunities ?? 0;
  if ($("metricOrders")) $("metricOrders").textContent = `${counters.submitted_orders ?? 0} / ${counters.fills ?? 0}`;
  if ($("metricAlgos")) $("metricAlgos").textContent = state.workspace?.algo?.candidate_count ?? state.candidates.length;
  const oppHTML = renderOpportunityRows(latest.opportunities);
  ["homeOppRows","scannerRows","opportunityRows"].forEach((id) => { if ($(id)) $(id).innerHTML = oppHTML; });
  if ($("tradeOrderRows")) $("tradeOrderRows").innerHTML = renderOrderRows(latest.submitted_orders);
  const metricValues = {
    portfolioEquity: latest.portfolio_equity ?? baseline.starting_balance ?? "—",
    portfolioGross: latest.gross_exposure ?? "—",
    portfolioRecons: counters.reconciliations ?? 0,
    portfolioOrders: counters.submitted_orders ?? 0,
    portfolioFills: counters.fills ?? 0,
    portfolioCurrency: baseline.currency || bootstrap.account_currency || "—",
  };
  Object.entries(metricValues).forEach(([id,value]) => { if ($(id)) $(id).textContent = value; });
  if ($("runtimeLogs")) $("runtimeLogs").textContent = state.runtime.log_tail || "No runtime log yet.";
  if ($("riskKillCard")) {
    const riskKill = status.risk_kill_switch === true;
    $("riskKillCard").textContent = riskKill ? `Risk kill: ${status.risk_kill_switch_reason || "engaged"}` : "Kill switch clear";
    $("riskKillCard").classList.toggle("bad", riskKill); $("riskKillCard").classList.toggle("good", !riskKill);
  }
  const locked = state.runtime.app_kill_locked === true;
  const running = state.runtime.runtime_running === true;
  ["startBtn","quickStart"].forEach((id) => { if ($(id)) $(id).disabled = running || locked; });
  ["stopBtn","quickStop"].forEach((id) => { if ($(id)) $(id).disabled = !running; });
  ["killBtn","quickKill"].forEach((id) => { if ($(id)) $(id).disabled = locked; });
  $("resetBtn")?.classList.toggle("hidden", !locked);
  renderSecurityState();
}

function featureById(id) { return state.catalog?.items?.find((item) => item.id === id); }
function featureCard(item) {
  if (!item) return "";
  const evidence = Array.isArray(item.evidence) && item.evidence.length ? item.evidence.map(esc).join(" · ") : "No completed implementation evidence";
  return `<article class="feature-card"><div class="feature-top"><h3>${esc(item.name)}</h3><span class="badge ${esc(item.status)}">${esc(humanStatus(item.status))}</span></div><p>${esc(item.description)}</p><div class="evidence">${evidence}</div></article>`;
}
function renderFeatureSets() {
  Object.entries(featureSets).forEach(([containerId, ids]) => { const node=$(containerId); if (node) node.innerHTML=ids.map((id)=>featureCard(featureById(id))).join(""); });
  const names=[["HTF Bias","Higher-timeframe directional context"],["SMC / ICT","Structure, liquidity and imbalance evidence"],["Technical","EMA/RSI/MACD/volatility evidence"],["Volume / VWAP","Participation and value evidence"],["Forecast","Calibrated probability / quantile view"]];
  if ($("homeAgents")) $("homeAgents").innerHTML=names.map(([name,desc])=>`<div class="agent-row"><div><b>${esc(name)}</b><small>${esc(desc)}</small></div><span class="badge backend_ready">implemented</span></div>`).join("");
}

function renderCapabilityMatrix() {
  const catalog=state.catalog; if (!catalog) return;
  const counts=catalog.counts||{};
  const summary=[["UI connected",counts.ui_connected||0],["Backend ready",counts.backend_ready||0],["Partial",counts.partial||0],["External gate",counts.external_gate||0],["Pending / blocked",(counts.pending||0)+(counts.blocked||0)]];
  if ($("capabilitySummary")) $("capabilitySummary").innerHTML=summary.map(([label,value])=>`<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  if ($("capabilityRows")) $("capabilityRows").innerHTML=catalog.items.map((item)=>`<tr><td>${esc(item.group)}</td><td><b>${esc(item.name)}</b></td><td><span class="badge ${esc(item.status)}">${esc(humanStatus(item.status))}</span></td><td style="white-space:normal;min-width:260px">${esc(item.description)}</td><td class="mono" style="white-space:normal;min-width:260px">${esc((item.evidence||[]).join(" · ")||"—")}</td></tr>`).join("");
}

function renderPipeline(containerId, completed=[]) {
  const node=$(containerId); if (!node) return;
  const pipeline=state.algoOptions?.validation_pipeline||state.workspace?.algo?.validation_pipeline||["compile","causal_backtest","purged_walk_forward","monte_carlo_robustness","sealed_holdout","parameter_stability","regime_validation","paper_demo_forward","human_approval"];
  node.innerHTML=pipeline.map((step,index)=>`<span class="pipe-step ${completed.includes(step)?"done":index===completed.length?"current":""}">${esc(step.replaceAll("_"," "))}</span>`).join("");
}
function prettyLabel(value){return String(value).replaceAll("_"," ").replace(/\b\w/g,(c)=>c.toUpperCase());}
function renderChoices(containerId,name,values,defaults){const node=$(containerId);if(!node)return;node.innerHTML=values.map((value)=>`<label class="choice"><input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${defaults.includes(value)?"checked":""}>${esc(prettyLabel(value))}</label>`).join("");}
function selected(name){return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((node)=>node.value);}
function renderAlgoOptions(){if(!state.algoOptions)return;renderChoices("algoEntries","algo_entries",state.algoOptions.entries||[],["liquidity_sweep","bos_choch"]);renderChoices("algoConfirmations","algo_confirmations",state.algoOptions.confirmations||[],["relative_volume","regime"]);renderChoices("algoExits","algo_exits",state.algoOptions.exits||[],["atr_stop","risk_reward_target"]);renderPipeline("algoPipeline");renderPipeline("homePipeline");renderPipeline("backtestPipeline");renderStrategyTemplates();}
function renderStrategyTemplates(){
  const form=$("algoName")?.closest("form");if(!form||$("strategyTemplate"))return;
  const field=document.createElement("div");field.className="field span-2";
  field.innerHTML='<label for="strategyTemplate">Research template · performance unverified</label><select id="strategyTemplate"><option value="">Choose a starting strategy</option>'+ (state.algoOptions.templates||[]).map((t,i)=>`<option value="${i}">${esc(t.name)}</option>`).join("")+'</select>';
  form.prepend(field);
  $("strategyTemplate").addEventListener("change",(event)=>{
    if(event.target.value==="")return;const t=state.algoOptions.templates[Number(event.target.value)];
    $("algoName").value=t.name;$("algoThesis").value=t.thesis;$("algoMarkets").value=t.markets.join(", ");$("algoTimeframes").value=t.timeframes.join(", ");
    for(const [name,key] of [["algo_entries","entries"],["algo_confirmations","confirmations"],["algo_exits","exits"]])document.querySelectorAll(`input[name="${name}"]`).forEach((input)=>{input.checked=t[key].includes(input.value);});
  });
}

function renderCandidates(){
  const node=$("strategyCandidates"); if(!node)return;
  if ($("metricAlgos")) $("metricAlgos").textContent=state.candidates.length;
  if(!state.candidates.length){node.innerHTML='<div class="empty">No local Algo Studio candidates yet.</div>';return;}
  node.innerHTML=state.candidates.slice(0,12).map((c)=>`<div class="feature-card" style="margin-bottom:8px"><div class="feature-top"><h3>${esc(c.owner_name||c.candidate_id)}</h3><span class="badge ${c.algorithm?.compilable?"ui_connected":"blocked"}">${c.algorithm?.compilable?"compiled":"blocked"}</span></div><p>${esc(c.blueprint?.market_scope?.join(", ")||"—")} · ${esc(c.blueprint?.timeframe_scope?.join(", ")||"—")} · stage ${esc(c.stage)}</p><div class="evidence">${esc(c.candidate_id)} · next: ${esc(c.validation?.next_required||"—")}</div></div>`).join("");
  const selector=$("backtestCandidate");
  if(selector){const selectedValue=selector.value;selector.innerHTML='<option value="">Select a compiled research candidate</option>'+state.candidates.filter((c)=>c.algorithm?.compilable).map((c)=>`<option value="${esc(c.candidate_id)}">${esc(c.owner_name||c.candidate_id)}</option>`).join("");selector.value=selectedValue;}
}

function renderChart(data){
  const node=$("chartWorkspace");if(!node)return;const candles=(data.candles||[]).slice(-140);
  if(candles.length<2){node.innerHTML='<div class="empty evidence-empty">The broker returned insufficient closed-candle evidence.</div>';return;}
  const values=candles.flatMap((c)=>[c.low,c.high,c.ema8,c.ema21,c.vwap]).map(Number).filter(Number.isFinite);
  const min=Math.min(...values),max=Math.max(...values),span=Math.max(max-min,Number.EPSILON),width=1000,height=430,pad=24;
  const x=(i)=>pad+i*(width-pad*2)/Math.max(candles.length-1,1);const y=(v)=>height-pad-(Number(v)-min)*(height-pad*2)/span;
  const line=(key,color)=>{const points=candles.map((c,i)=>Number.isFinite(Number(c[key]))?`${x(i).toFixed(1)},${y(c[key]).toFixed(1)}`:null).filter(Boolean).join(" ");return points?`<polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.7" vector-effect="non-scaling-stroke"/>`:"";};
  const bodies=candles.map((c,i)=>{const open=Number(c.open),close=Number(c.close),high=Number(c.high),low=Number(c.low);const color=close>=open?"#2bd88b":"#ff6174";const px=x(i),top=y(Math.max(open,close)),bottom=y(Math.min(open,close));return `<line x1="${px}" x2="${px}" y1="${y(high)}" y2="${y(low)}" stroke="${color}"/><rect x="${px-2.2}" y="${top}" width="4.4" height="${Math.max(bottom-top,1)}" fill="${color}"/>`;}).join("");
  node.innerHTML=`<div class="chart-meta"><b>${esc(data.symbol)} · ${esc(data.timeframe)}</b><span>${esc(data.bars)} closed broker bars · MT5 DEMO read-only</span></div><svg class="market-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Broker-origin closed candle chart">${bodies}${line("ema8","#3ec8ff")}${line("ema21","#b38cff")}${line("vwap","#efb84c")}</svg><div class="chart-legend"><span>Price candles</span><span>EMA 8</span><span>EMA 21</span><span>VWAP</span></div>`;
}
async function loadChart(event){event.preventDefault();const node=$("chartWorkspace");node.innerHTML='<div class="empty evidence-empty">Loading closed DEMO candles…</div>';try{const params=new URLSearchParams({symbol:$("chartSymbol").value.trim(),timeframe:$("chartTimeframe").value,bars:$("chartBars").value});renderChart(await getJSON(`/api/chart?${params}`));}catch(error){node.innerHTML=`<div class="notice">Chart unavailable: ${esc(error.message)}</div>`;}}

async function runBacktest(event){event.preventDefault();const button=$("runBacktestBtn"),node=$("backtestResult");button.disabled=true;node.textContent="Running causal research backtest on closed DEMO candles...";try{const result=await postJSON("/api/backtest/run",{candidate_id:$("backtestCandidate").value,symbol:$("backtestSymbol").value.trim(),timeframe:$("backtestTimeframe").value.trim(),bars:Number($("backtestBars").value)});node.textContent=JSON.stringify({artifact_hash:result.artifact_hash,artifact_file:result.artifact_file,data:result.data,metrics:result.metrics,next_required:result.validation?.next_required,live_approved:result.live_approved},null,2);renderPipeline("backtestPipeline",result.validation?.completed||[]);toast("Research backtest completed");}catch(error){node.textContent=`Backtest blocked: ${error.message}`;}finally{button.disabled=false;}}
function initResearchSurfaces(){$("chartForm")?.addEventListener("submit",loadChart);$("backtestForm")?.addEventListener("submit",runBacktest);}

function renderDecisions(){
  const items=state.decisions?.items||[]; const node=$("ceoDecisionFeed");
  if(node){node.innerHTML=items.length?items.slice(0,8).map((d)=>`<article class="feature-card" style="margin-bottom:8px"><div class="feature-top"><h3>${esc(d.symbol||"—")} · ${esc(d.timeframe||"—")}</h3><span class="badge ${String(d.intent||"").toLowerCase()==="flat"?"partial":"ui_connected"}">${esc(String(d.intent||"—").toUpperCase())} · ${esc(d.confidence??"—")}</span></div><p><b>Thesis:</b> ${esc(d.thesis||"—")}</p><p><b>Opposing view:</b> ${esc(d.opposing_view||"—")}</p><p><b>Invalidation:</b> ${esc((d.invalidating_conditions||[]).join(" · ")||"—")}</p><div class="evidence">support ${esc(d.support??"—")} · opposition ${esc(d.opposition??"—")} · agents ${esc((d.agent_ids||[]).length)} · ${esc(fmtTime(d.created_at))}</div></article>`).join(""):'<div class="empty">No persisted CEO decisions yet. Start AURA and wait for a closed-candle agent round.</div>';}
  const agentNode=$("agentEvidenceFeed");
  if(agentNode){const latest=items[0];const ev=latest?.evidence||[];agentNode.innerHTML=ev.length?ev.map((e)=>`<div class="agent-row"><div><b>${esc(e.role||e.agent_id||"Agent")}</b><small>${esc(e.rationale||"")}</small></div><span class="badge backend_ready">${esc(e.intent||"—")} ${esc(e.confidence??"")}</span></div>`).join(""):'<div class="empty">No audited agent evidence yet.</div>';}
}

function renderIntelligence(){
  const items=state.intelligence?.items||[];const node=$("newsFeed");if(!node)return;
  node.innerHTML=items.length?items.map((item)=>`<article class="feature-card" style="margin-bottom:8px"><div class="feature-top"><h3>${esc(item.title||"Untitled event")}</h3><span class="badge backend_ready">${esc(item.kind||"news")}</span></div><p>${esc(item.summary||"")}</p><div class="evidence">${esc(item.source||"—")} · trust ${esc(item.trust_score??"—")} · ${esc(fmtTime(item.published_at))}${(item.symbols||[]).length?` · ${esc(item.symbols.join(", "))}`:""}</div>${item.url?`<p><a href="${esc(item.url)}" target="_blank" rel="noreferrer">Open source ↗</a></p>`:""}</article>`).join(""):'<div class="empty">No persisted fresh intelligence yet. The learning runtime will populate verified source records after its first intelligence poll.</div>';
  if ($("newsServiceState")) {const service=state.intelligence?.service||{};$("newsServiceState").textContent=`Cached: ${service.events_cached??0} · Last poll: ${fmtTime(service.last_poll_at)} · Errors: ${Object.keys(service.errors||{}).length}`;}
}

function renderLearning(){
  const status=state.learning?.status||{};const node=$("learningSnapshot");if(!node)return;
  const audit=status.opportunity_audit||{};const challenger=status.forward_challenger;
  node.innerHTML=`<div class="metric-grid"><div class="metric-card"><div class="metric-label">Learning state</div><div class="metric-value">${esc(status.state||"idle")}</div></div><div class="metric-card"><div class="metric-label">Replay samples</div><div class="metric-value">${esc(status.replay_samples??0)}</div></div><div class="metric-card"><div class="metric-label">Live samples</div><div class="metric-value">${esc(status.live_replay_samples??0)}</div></div><div class="metric-card"><div class="metric-label">Agent observations</div><div class="metric-value">${esc(status.agent_reliability_observations??0)}</div></div><div class="metric-card"><div class="metric-label">Capture rate</div><div class="metric-value">${audit.capture_rate!=null?esc((Number(audit.capture_rate)*100).toFixed(1))+"%":"—"}</div></div><div class="metric-card"><div class="metric-label">Challenger</div><div class="metric-value">${challenger?"ACTIVE":"None"}</div></div></div>${challenger?`<div class="notice info">Forward challenger ${esc(challenger.genome_id)} · samples ${esc(challenger.forward_samples)}. It has no automatic live authority.</div>`:'<div class="notice info">No forward challenger currently installed. Research remains evidence-gated.</div>'}`;
}

function renderJournal(){
  const node=$("journalRows");if(!node)return;const items=state.journal?.items||[];
  node.innerHTML=items.length?items.slice(0,120).map((e)=>`<tr><td>${esc(e.sequence)}</td><td>${esc(e.event_type)}</td><td>${esc(fmtTime(e.created_at))}</td><td class="mono" style="white-space:normal">${esc(JSON.stringify(e.payload))}</td></tr>`).join(""):'<tr><td colspan="4" class="empty">No financial journal events yet.</td></tr>';
}

function renderSecurityState(){
  const required=Boolean(state.runtime?.owner_auth_required);const node=$("ownerAuthState");if(node){node.className=`badge ${required?(state.ownerToken?"ui_connected":"partial"):"backend_ready"}`;node.textContent=required?(state.ownerToken?"Owner token loaded":"Owner token required"):"Loopback-only / token optional";}
  if ($("ownerTokenInput") && document.activeElement!==$("ownerTokenInput")) $("ownerTokenInput").value=state.ownerToken;
}

async function refreshWorkspace({quiet=false}={}){
  try{
    const workspace=await getJSON("/api/workspace");state.workspace=workspace;state.catalog=workspace.capabilities;state.decisions=workspace.decisions||{items:[]};state.learning=workspace.learning||{status:{}};state.intelligence=workspace.intelligence||{items:[]};updateRuntime(workspace.runtime);renderFeatureSets();renderCapabilityMatrix();renderPipeline("homePipeline");renderDecisions();renderLearning();renderIntelligence();if(!quiet)toast("AURA workspace refreshed");
  }catch(error){if(!quiet)toast(`Workspace error: ${error.message}`);}
}

async function refreshDynamic(){
  try{
    const [decisions,journal,learning,intelligence]=await Promise.all([getJSON("/api/decisions"),getJSON("/api/journal"),getJSON("/api/learning"),getJSON("/api/intelligence")]);
    state.decisions=decisions;state.journal=journal;state.learning=learning;state.intelligence=intelligence;renderDecisions();renderJournal();renderLearning();renderIntelligence();
  }catch(error){console.debug("dynamic read-model refresh",error);}
}

async function refreshAlgos(){
  try{const [options,candidates]=await Promise.all([getJSON("/api/algo/options"),getJSON("/api/algo/candidates")]);state.algoOptions=options;state.candidates=candidates.items||[];renderAlgoOptions();renderCandidates();}catch(error){toast(`Algo Studio error: ${error.message}`);}
}

function setTradeMessage(message,mode="info"){const node=$("tradeMessage");if(node){node.className=`notice ${mode}`;node.textContent=message;}}
async function startRuntime(){try{setTradeMessage("Starting protected MT5 DEMO runtime...");await postJSON("/api/start",{max_symbols:Number($("maxSymbols")?.value||25),max_batches:Number($("maxBatches")?.value||100)});await refreshWorkspace({quiet:true});setTradeMessage("AURA DEMO runtime started. Scanner/agents/news/learning will populate from real closed-candle work.","good");}catch(error){setTradeMessage(error.message);toast(error.message);}}
async function stopRuntime(){try{await postJSON("/api/stop");await refreshWorkspace({quiet:true});setTradeMessage("AURA runtime stopped.");}catch(error){setTradeMessage(error.message);}}
async function killRuntime(){if(!confirm("Emergency lock stops the DEMO child process and blocks restart until reset. Continue?"))return;try{await postJSON("/api/kill",{reason:"Emergency lock from owner command center"});await refreshWorkspace({quiet:true});setTradeMessage("Emergency lock engaged.");toast("Emergency lock engaged");}catch(error){toast(error.message);}}
async function resetKill(){if(!confirm("Reset the local emergency lock? Independent financial RiskEngine can still veto trading."))return;try{await postJSON("/api/reset-kill");await refreshWorkspace({quiet:true});setTradeMessage("Local emergency lock reset. Runtime remains stopped until started.");}catch(error){toast(error.message);}}
function initRuntimeControls(){["startBtn","quickStart"].forEach((id)=>$(id)?.addEventListener("click",startRuntime));["stopBtn","quickStop"].forEach((id)=>$(id)?.addEventListener("click",stopRuntime));["killBtn","quickKill"].forEach((id)=>$(id)?.addEventListener("click",killRuntime));$("resetBtn")?.addEventListener("click",resetKill);}

async function buildAlgo(event){event.preventDefault();const payload={name:$("algoName").value.trim(),thesis:$("algoThesis").value.trim(),markets:splitCSV($("algoMarkets").value),timeframes:splitCSV($("algoTimeframes").value),entries:selected("algo_entries"),confirmations:selected("algo_confirmations"),exits:selected("algo_exits")};const button=$("buildAlgoBtn");button.disabled=true;$("algoResult").textContent="Compiling allow-listed strategy blueprint...";try{const candidate=await postJSON("/api/algo/build",payload);$("algoResult").textContent=JSON.stringify({candidate_id:candidate.candidate_id,stage:candidate.stage,compilable:candidate.algorithm?.compilable,compiled_strategy_id:candidate.algorithm?.strategy_id,warmup_bars:candidate.algorithm?.warmup_bars,entries:candidate.blueprint?.entries,confirmations:candidate.blueprint?.confirmations,exits:candidate.blueprint?.exits,next_required:candidate.validation?.next_required,live_approved:candidate.live_approved},null,2);renderPipeline("algoPipeline",candidate.validation?.completed||[]);await refreshAlgos();toast("Research algo candidate compiled");}catch(error){$("algoResult").textContent=`Build blocked: ${error.message}`;toast(error.message);}finally{button.disabled=false;}}
function initAlgoStudio(){$("algoForm")?.addEventListener("submit",buildAlgo);}

function addBubble(kind,text){const node=document.createElement("div");node.className=`bubble ${kind}`;node.textContent=text;$("chatBody")?.appendChild(node);if($("chatBody"))$("chatBody").scrollTop=$("chatBody").scrollHeight;}
function openAssistant(){$("assistantDrawer")?.classList.add("open");$("chatInput")?.focus();}
function closeAssistant(){$("assistantDrawer")?.classList.remove("open");}
async function sendAssistant(text){addBubble("user",text);try{const result=await postJSON("/api/command",{text});addBubble("aura",result.answer||"Command handled.");}catch(error){addBubble("aura",`Command blocked: ${error.message}`);}}
function initAssistant(){
  $("assistantFab")?.addEventListener("click",openAssistant);$("closeAssistant")?.addEventListener("click",closeAssistant);
  $("chatForm")?.addEventListener("submit",async(event)=>{event.preventDefault();const input=$("chatInput");const text=input.value.trim();if(!text)return;input.value="";await sendAssistant(text);});
  $("voiceBtn")?.addEventListener("click",()=>{const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(!Recognition){toast("Browser speech recognition is unavailable.");return;}const recognition=new Recognition();recognition.lang="en-IN";recognition.interimResults=false;recognition.maxAlternatives=1;recognition.onresult=(event)=>sendAssistant(event.results[0][0].transcript);recognition.onerror=()=>toast("Voice input failed or permission was denied.");recognition.start();});
}

function initSecurity(){
  $("saveOwnerToken")?.addEventListener("click",()=>{const value=$("ownerTokenInput")?.value.trim()||"";state.ownerToken=value;if(value)sessionStorage.setItem("auraOwnerToken",value);else sessionStorage.removeItem("auraOwnerToken");renderSecurityState();toast(value?"Owner token stored for this browser session":"Owner token cleared from session");});
  $("clearOwnerToken")?.addEventListener("click",()=>{state.ownerToken="";sessionStorage.removeItem("auraOwnerToken");if($("ownerTokenInput"))$("ownerTokenInput").value="";renderSecurityState();toast("Owner token cleared");});
}

function initInstall(){const button=$("installBtn");window.addEventListener("beforeinstallprompt",(event)=>{event.preventDefault();state.installPrompt=event;if(button)button.disabled=false;});button?.addEventListener("click",async()=>{if(!state.installPrompt){toast("Use the browser Install App option if AURA is already eligible.");return;}state.installPrompt.prompt();await state.installPrompt.userChoice;state.installPrompt=null;});if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});}

async function boot(){initNavigation();initRuntimeControls();initAlgoStudio();initResearchSurfaces();initAssistant();initSecurity();initInstall();$("refreshOwner")?.addEventListener("click",()=>refreshWorkspace());await Promise.all([refreshWorkspace({quiet:true}),refreshAlgos(),refreshDynamic()]);updateRuntime(state.workspace?.runtime||state.runtime||{});renderFeatureSets();renderCapabilityMatrix();renderPipeline("homePipeline");renderPipeline("backtestPipeline");renderCandidates();renderDecisions();renderJournal();renderLearning();renderIntelligence();renderSecurityState();setInterval(()=>refreshWorkspace({quiet:true}),3000);setInterval(refreshDynamic,7000);}

boot().catch((error)=>toast(`AURA startup error: ${error.message}`));
