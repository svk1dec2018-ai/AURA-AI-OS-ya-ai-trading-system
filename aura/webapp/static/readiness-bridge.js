(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));

  function ensureStyles() {
    if (document.getElementById("aura-readiness-style")) return;
    const style = document.createElement("style");
    style.id = "aura-readiness-style";
    style.textContent = `
      .readiness-card{margin:0 0 14px;padding:14px 16px;border:1px solid #1a2c40;border-radius:15px;background:#09131f}
      .readiness-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
      .readiness-head h2{margin:0;font-size:16px}.readiness-head p{margin:4px 0 0;color:#7f97b0;font-size:11px}
      .readiness-state{padding:6px 9px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.05em;border:1px solid #334a62;background:#111e2d;color:#c9d9e8}
      .readiness-state.good{border-color:#1b6a4b;background:#0c261c;color:#72eab5}.readiness-state.warn{border-color:#705f28;background:#241f0e;color:#e5d078}.readiness-state.bad{border-color:#75333d;background:#2b1519;color:#ff9ca8}
      .readiness-grid{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin-top:11px}.readiness-stat{padding:10px;border:1px solid #16283a;border-radius:10px;background:#0b1622}.readiness-stat small{display:block;color:#6f88a1;font-size:9px;text-transform:uppercase;letter-spacing:.08em}.readiness-stat b{display:block;margin-top:4px;font-size:13px;color:#e8f3ff}
      .readiness-checks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:10px}.readiness-check{display:flex;gap:8px;align-items:flex-start;padding:8px;border:1px solid #142538;border-radius:9px;background:#0a1420;font-size:11px}.readiness-check i{width:8px;height:8px;border-radius:50%;margin-top:3px;flex:0 0 8px;background:#63778d}.readiness-check.good i{background:#30d18a}.readiness-check.bad i{background:#f05c69}.readiness-check span{color:#a9bdd0}.readiness-check strong{display:block;color:#e4f0fb;font-size:11px}
      .readiness-note{margin-top:10px;padding:9px 10px;border:1px solid #4d4019;background:#211b0d;border-radius:9px;color:#d9c56e;font-size:10px}
      @media(max-width:900px){.readiness-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.readiness-checks{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    let node = document.getElementById("auraReleaseReadiness");
    if (node) return node;
    node = document.createElement("section");
    node.id = "auraReleaseReadiness";
    node.className = "readiness-card";
    node.innerHTML = `
      <div class="readiness-head">
        <div><h2>AURA Release Readiness</h2><p>Separates implemented software, current MT5 runtime evidence and external real-money gates.</p></div>
        <span class="readiness-state warn" id="readinessState">CHECKING</span>
      </div>
      <div class="readiness-grid">
        <div class="readiness-stat"><small>Software</small><b id="readinessSoftware">—</b></div>
        <div class="readiness-stat"><small>MT5 runtime</small><b id="readinessMT5">—</b></div>
        <div class="readiness-stat"><small>Self-learning</small><b id="readinessLearning">—</b></div>
        <div class="readiness-stat"><small>Real money</small><b id="readinessLive">LOCKED</b></div>
      </div>
      <div class="readiness-checks" id="readinessChecks"><div class="readiness-check"><i></i><span><strong>Loading checks…</strong></span></div></div>
      <div class="readiness-note">A green MT5 DEMO state proves the protected DEMO runtime is ready/running. It is not automatic authorization for unrestricted real-money trading.</div>`;
    const mt5 = document.getElementById("mt5OwnerBridge");
    if (mt5) mt5.insertAdjacentElement("afterend", node);
    else {
      const anchor = document.querySelector("#view-command .page-head");
      if (anchor) anchor.insertAdjacentElement("afterend", node);
    }
    return node;
  }

  function stateMode(name) {
    if (name === "MT5_DEMO_RUNNING" || name === "MT5_DEMO_READY_TO_START") return "good";
    if (name === "BLOCKED_BY_KILL_SWITCH" || name === "SOFTWARE_VALIDATION_REQUIRED") return "bad";
    return "warn";
  }

  async function refresh() {
    ensurePanel();
    try {
      const response = await fetch("/api/readiness", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      const state = document.getElementById("readinessState");
      state.textContent = String(data.demo_state || "UNKNOWN").replaceAll("_", " ");
      state.className = `readiness-state ${stateMode(data.demo_state)}`;
      document.getElementById("readinessSoftware").textContent = data.software_ready ? "READY" : "CHECK";
      document.getElementById("readinessMT5").textContent = data.mt5_runtime_ready ? (data.runtime_active ? "RUNNING" : "READY") : "NOT READY";
      document.getElementById("readinessLearning").textContent = data.self_learning_runtime_active ? "ACTIVE" : "WAITING";
      document.getElementById("readinessLive").textContent = data.real_money_enabled ? "ENABLED" : "LOCKED";
      const checks = Array.isArray(data.checks) ? data.checks : [];
      document.getElementById("readinessChecks").innerHTML = checks.map((item) => `
        <div class="readiness-check ${item.passed ? "good" : "bad"}"><i></i><span><strong>${esc(item.name)}</strong>${esc(item.detail || "")}</span></div>`).join("") || '<div class="readiness-check"><i></i><span><strong>No readiness checks returned</strong></span></div>';
    } catch (error) {
      const state = document.getElementById("readinessState");
      if (state) { state.textContent = "READINESS ERROR"; state.className = "readiness-state bad"; }
      const checks = document.getElementById("readinessChecks");
      if (checks) checks.innerHTML = `<div class="readiness-check bad"><i></i><span><strong>Readiness endpoint unavailable</strong>${esc(error.message)}</span></div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureStyles();
    ensurePanel();
    refresh();
    setInterval(refresh, 5000);
  });
})();
