const $=id=>document.getElementById(id);
const state={capabilities:[],capabilityGroups:{},algoOptions:null};

function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));}
function maskedLogin(v){if(!v)return '—';const s=String(v);return s.length>4?'••••'+s.slice(-4):s;}
function pretty(v){return String(v??'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
function num(v,fallback='0'){return v===null||v===undefined||v===''?fallback:String(v);}
function pct(v){return v===null||v===undefined?'—':`${v}%`;}
function selectedValues(name){return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(x=>x.value);}
function csvValues(id){return $(id).value.split(',').map(x=>x.trim()).filter(Boolean);}

async function getJson(url){const r=await fetch(url,{cache:'no-store'});const j=await r.json();if(!r.ok)throw new Error(j.error||`GET ${url} failed`);return j;}
async function postJson(url,body={}){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();if(!r.ok||j.ok===false)throw new Error(j.error||`POST ${url} failed`);return j;}

function notify(message,type='info'){
  const el=$('toast');
  el.textContent=message;
  el.className=`pill ${type==='error'?'bad':type==='success'?'good':type==='warn'?'warn':''}`;
  el.classList.remove('hidden');
  clearTimeout(notify.timer);
  notify.timer=setTimeout(()=>el.classList.add('hidden'),3600);
}

function showView(view){
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===`view-${view}`));
  document.querySelectorAll('.nav button[data-view]').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  const active=document.querySelector(`.nav button[data-view="${view}"]`);
  $('pageTitle').textContent=active?.dataset.title||'AURA AI OS';
  $('pageSub').textContent=active?.dataset.sub||'Owner command center';
  $('sidebar').classList.remove('open');
  if(view==='capabilities')renderCapabilities();
  if(view==='algo')loadAlgoCandidates();
}

document.addEventListener('click',e=>{
  const nav=e.target.closest('.nav button[data-view]');
  if(nav)showView(nav.dataset.view);
});
$('mobileMenu').addEventListener('click',()=> $('sidebar').classList.toggle('open'));

async function action(url){
  try{
    const body=url==='/api/start'?{max_symbols:Number($('maxSymbols').value),max_batches:Number($('maxBatches').value)}:{};
    await postJson(url,body);
    await refreshStatus();
    notify('Owner action completed.','success');
  }catch(e){notify(e.message,'error');}
}
window.action=action;

async function killAura(){
  if(!confirm('Emergency lock stops the AURA child runtime and blocks restart until you reset the lock. Continue?'))return;
  try{await postJson('/api/kill',{reason:'Emergency lock from AURA owner command center'});await refreshStatus();notify('Emergency lock engaged.','warn');}
  catch(e){notify(e.message,'error');}
}
window.killAura=killAura;

function renderRows(items,kind){
  if(!items?.length)return `<tr><td colspan="${kind==='opp'?5:4}" class="empty">No governed runtime data yet.</td></tr>`;
  return items.map(x=>kind==='opp'
    ?`<tr><td>${esc(x.symbol)}</td><td>${esc(x.timeframe)}</td><td>${esc(x.intent)}</td><td>${esc(x.confidence)}</td><td>${x.agent_policy_allowed===true?'<span class="good">Allowed</span>':x.agent_policy_allowed===false?'<span class="bad">Blocked</span>':'—'}</td></tr>`
    :`<tr><td>${esc(x.symbol)}</td><td>${esc(x.side)}</td><td>${esc(x.quantity)}</td><td>${esc(x.broker_order_id)}</td></tr>`).join('');
}

async function refreshStatus(){
  try{
    const d=await getJson('/api/status');
    const s=d.status||{},b=d.baseline||{},c=s.counters||{},l=s.latest||{};
    $('liveDot').classList.toggle('on',d.runtime_running);
    $('runtimeBadge').textContent=d.app_kill_locked?'KILL LOCKED':d.runtime_running?'RUNTIME ACTIVE':'RUNTIME STOPPED';
    $('runtimeBadge').className=`pill ${d.app_kill_locked?'bad':d.runtime_running?'good':''}`;
    $('sideRuntime').textContent=d.app_kill_locked?'Emergency lock engaged':d.runtime_running?'MT5 DEMO runtime active':'Runtime stopped';
    $('account').textContent=maskedLogin(b.login||s.bootstrap?.account_login);
    $('server').textContent=b.server||s.bootstrap?.account_server||'Waiting for DEMO runtime';
    $('currency').textContent=b.currency||s.bootstrap?.account_currency||'—';
    $('equity').textContent=num(l.portfolio_equity??b.starting_balance,'—');
    $('drawdown').textContent=pct(l.drawdown_pct);
    $('opportunities').textContent=num(c.opportunities);
    $('orders').textContent=`${num(c.submitted_orders)} / ${num(c.fills)}`;
    $('batches').textContent=num(c.batches);
    $('mode').textContent=s.mode||d.app_mode;
    $('gross').textContent=num(l.gross_exposure,'—');
    $('activeSymbols').textContent=num(s.bootstrap?.active_symbols,'—');
    $('reconciliations').textContent=num(c.reconciliations);
    $('lastUpdated').textContent=s.updated_at?new Date(s.updated_at).toLocaleString():'No runtime snapshot yet';
    $('oppRows').innerHTML=renderRows(l.opportunities,'opp');
    $('orderRows').innerHTML=renderRows(l.submitted_orders,'order');
    $('logs').textContent=d.log_tail||'AURA runtime log is empty.';
    $('resetBtn').classList.toggle('hidden',!d.app_kill_locked);
    $('startBtn').disabled=d.runtime_running||d.app_kill_locked;
    $('stopBtn').disabled=!d.runtime_running;
    $('killBtn').disabled=d.app_kill_locked;
    const rk=s.risk_kill_switch===true;
    $('riskKill').innerHTML=rk?`<span class="bad">●</span> <strong>Risk kill:</strong> ${esc(s.risk_kill_switch_reason||'engaged')}`:'<span class="good">●</span> <strong>Risk kill switch:</strong> clear';
    $('ownerSafety').textContent=d.safety?.real_money_enabled?'REVIEW':'PROTECTED';
    $('releaseBoundary').textContent=d.release_boundary||'PAPER / DEMO / RESEARCH';
  }catch(e){notify(`Dashboard connection error: ${e.message}`,'error');}
}

async function loadCapabilities(){
  try{
    const data=await getJson('/api/capabilities');
    state.capabilities=data.items||[];state.capabilityGroups=data.groups||{};
    $('capTotal').textContent=state.capabilities.length;
    $('capConnected').textContent=data.counts?.ui_connected||0;
    $('capBackend').textContent=data.counts?.backend_ready||0;
    $('capGated').textContent=(data.counts?.external_gate||0)+(data.counts?.partial||0)+(data.counts?.pending||0);
    const groups=['All',...Object.keys(state.capabilityGroups)];
    $('capGroup').innerHTML=groups.map(g=>`<option value="${esc(g)}">${esc(g)}</option>`).join('');
    renderCapabilities();
  }catch(e){notify(`Capability catalog unavailable: ${e.message}`,'error');}
}

function renderCapabilities(){
  const query=($('capSearch')?.value||'').trim().toLowerCase();
  const group=$('capGroup')?.value||'All';
  const status=$('capStatus')?.value||'All';
  const items=state.capabilities.filter(x=>(group==='All'||x.group===group)&&(status==='All'||x.status===status)&&(!query||`${x.name} ${x.description} ${x.group} ${x.status}`.toLowerCase().includes(query)));
  $('featureGrid').innerHTML=items.length?items.map(x=>`<article class="feature"><div class="feature-top"><div><div class="eyebrow">${esc(x.group)}</div><div class="feature-name">${esc(x.name)}</div></div><span class="tag ${esc(x.status)}">${esc(pretty(x.status))}</span></div><div class="feature-desc">${esc(x.description)}</div>${x.evidence?.length?`<div class="mini">Evidence: ${esc(x.evidence.slice(0,2).join(' · '))}</div>`:''}</article>`).join(''):'<div class="empty">No matching AURA capabilities.</div>';
}
$('capSearch').addEventListener('input',renderCapabilities);$('capGroup').addEventListener('change',renderCapabilities);$('capStatus').addEventListener('change',renderCapabilities);

function choiceHtml(name,value,checked=false){return `<label class="choice"><input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${checked?'checked':''}><span>${esc(pretty(value))}</span></label>`;}
async function loadAlgoOptions(){
  try{
    const data=await getJson('/api/algo/options');state.algoOptions=data;
    $('entryChoices').innerHTML=(data.entries||[]).map((x,i)=>choiceHtml('algo-entry',x,i===0)).join('');
    $('confirmChoices').innerHTML=(data.confirmations||[]).map((x,i)=>choiceHtml('algo-confirm',x,i===0)).join('');
    $('exitChoices').innerHTML=(data.exits||[]).map((x,i)=>choiceHtml('algo-exit',x,i<2)).join('');
    $('pipeline').innerHTML=(data.validation_pipeline||[]).map((x,i)=>`<div class="pipeline-step"><b>${i+1}</b>${esc(pretty(x))}</div>`).join('');
  }catch(e){notify(`Algo Studio options unavailable: ${e.message}`,'error');}
}

async function buildAlgo(){
  const body={name:$('algoName').value.trim(),thesis:$('algoThesis').value.trim(),markets:csvValues('algoMarkets'),timeframes:csvValues('algoTimeframes'),entries:selectedValues('algo-entry'),confirmations:selectedValues('algo-confirm'),exits:selectedValues('algo-exit')};
  try{
    $('buildAlgoBtn').disabled=true;$('algoResult').textContent='Compiling immutable research candidate…';
    const result=await postJson('/api/algo/build',body);
    $('algoResult').textContent=JSON.stringify(result,null,2);
    $('algoStage').textContent=pretty(result.stage);
    $('algoHash').textContent=result.strategy_version?.content_hash?.slice(0,16)||'—';
    $('algoNext').textContent=pretty(result.validation?.next_required||'—');
    notify('Research algo candidate compiled and saved.','success');
    await loadAlgoCandidates();
  }catch(e){$('algoResult').textContent=e.message;notify(e.message,'error');}
  finally{$('buildAlgoBtn').disabled=false;}
}
$('buildAlgoBtn').addEventListener('click',buildAlgo);

async function loadAlgoCandidates(){
  try{
    const d=await getJson('/api/algo/candidates');const items=d.items||[];
    $('candidateCount').textContent=items.length;
    $('candidateRows').innerHTML=items.length?items.slice(0,25).map(x=>`<tr><td>${esc(x.owner_name||x.candidate_id)}</td><td>${esc(pretty(x.stage))}</td><td>${x.algorithm?.compilable?'<span class="good">Compiled</span>':'<span class="bad">Blocked</span>'}</td><td>${esc(pretty(x.validation?.next_required||'—'))}</td><td>${esc((x.strategy_version?.content_hash||'').slice(0,12))}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">No research algo candidates yet.</td></tr>';
  }catch(e){notify(`Candidate library unavailable: ${e.message}`,'error');}
}

$('refreshBtn').addEventListener('click',async()=>{await Promise.all([refreshStatus(),loadCapabilities(),loadAlgoCandidates()]);notify('AURA workspace refreshed.','success');});
$('jumpAlgo').addEventListener('click',()=>showView('algo'));
$('jumpCapabilities').addEventListener('click',()=>showView('capabilities'));

if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{});}
Promise.all([refreshStatus(),loadCapabilities(),loadAlgoOptions(),loadAlgoCandidates()]);
setInterval(refreshStatus,3000);
