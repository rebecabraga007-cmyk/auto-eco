"use strict";

/* ── infra ───────────────────────────────────────────────────────────── */
const view = document.getElementById("view");
const state = { me: null, clients: [], users: [], cadences: [], lostReasons: [], page: "dashboard" };

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) { showLogin(); throw new Error("Não autenticado."); }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text.slice(0, 300) }; }
  if (!res.ok) throw new Error((data && (data.detail || data.message)) || `Erro ${res.status}`);
  return data;
}

/** Baixa um arquivo vindo de uma rota que devolve binário.
 *
 * Não dá para usar `window.open` aqui: o export é POST com o filtro no corpo,
 * e o erro vem em JSON — que precisa virar mensagem em vez de baixar um
 * arquivo chamado "erro". */
async function apiDownload(path, { method = "POST", body, fallbackName = "arquivo.xlsx" } = {}) {
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { showLogin(); throw new Error("Não autenticado."); }
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* corpo não-JSON */ }
    throw new Error(detail);
  }
  const disp = res.headers.get("content-disposition") || "";
  const match = disp.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"),
    { href: url, download: decodeURIComponent(match ? match[1] : fallbackName) });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return blob.size;
}

async function apiUpload(path, file, extra = {}) {
  const form = new FormData();
  form.append("file", file);
  Object.entries(extra).forEach(([k, v]) => form.append(k, v));
  const res = await fetch(path, { method: "POST", credentials: "same-origin", body: form });
  if (res.status === 401) { showLogin(); throw new Error("Não autenticado."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erro ${res.status}`);
  return data;
}

const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("pt-BR") : "—";
const fmtDateTime = (iso) => iso
  ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
  : "—";
const fmtMoney = (v) => (v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const fmtDuration = (s) => s ? `${Math.floor(s / 60)}m ${s % 60}s` : "—";
const todayISO = () => new Date().toISOString().slice(0, 10);

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function modal({ title, body, footer, wide }) {
  const root = document.getElementById("modalRoot");
  root.innerHTML = `<div class="modal-backdrop-x">
      <div class="modal-card${wide ? " wide" : ""}">
        <div class="modal-head"><h3>${h(title)}</h3><button class="close-x" data-close>×</button></div>
        <div class="modal-body">${body}</div>
        ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
      </div></div>`;
  const close = () => { root.innerHTML = ""; };
  root.querySelector("[data-close]").onclick = close;
  root.querySelector(".modal-backdrop-x").onclick = (e) => {
    if (e.target.classList.contains("modal-backdrop-x")) close();
  };
  return { root, close };
}

function confirmDialog(title, message, onYes) {
  const m = modal({
    title, body: `<p>${h(message)}</p>`,
    footer: `<button class="btn btn-default btn-sm" data-no>Cancelar</button>
             <button class="btn btn-danger btn-sm" data-yes>Confirmar</button>`,
  });
  m.root.querySelector("[data-no]").onclick = m.close;
  m.root.querySelector("[data-yes]").onclick = async () => { m.close(); await onYes(); };
}

const LOADING = `<div class="panel panel-flat"><div class="panel-body">
  <span class="spinner"></span> <span class="text-muted ml-5">Carregando…</span></div></div>`;

function panel(title, body, { actions = "", subtitle = "" } = {}) {
  return `<div class="panel panel-flat">
    <div class="panel-heading has-border">
      <div><h2 class="panel-title">${h(title)}</h2>
      ${subtitle ? `<div class="text-muted text-size-small">${h(subtitle)}</div>` : ""}</div>
      <div class="heading-elements">${actions}</div>
    </div>
    <div class="panel-body">${body}</div>
  </div>`;
}

function table(headers, rows, opts = {}) {
  if (!rows.length) return emptyState(opts.empty || "Nada por aqui ainda.");
  return `<div class="table-responsive${opts.scroll ? " table-scroll" : ""}">
    <table class="table table-striped table-hover">
      <thead><tr>${headers.map((x) => `<th>${x}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr${r.attrs || ""}>${r.cells.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>`;
}

const emptyState = (msg) => `<div class="empty-state"><div class="big">◌</div>${h(msg)}</div>`;

function kpis(items) {
  return `<div class="kpi-row">${items.map((i) => `
    <div class="kpi ${i.tone || ""}"><div class="number">${h(i.value)}</div>
    <div class="caption">${h(i.label)}</div></div>`).join("")}</div>`;
}

function bars(items) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return items.map((i) => `<div class="bar-line"><span>${h(i.label)}</span>
    <div class="bar ${i.tone || "success"}"><span style="width:${(i.value / max) * 100}%"></span></div>
    <strong>${h(i.value)}</strong></div>`).join("") || emptyState("Sem dados no período.");
}

const STATUS_LABEL = {
  WAITING: ["Em espera", "grey"], EXECUTING: ["Prospectando", "blue"],
  ON_EXTRA_ACTIVITY: ["Atividade extra", "amber"], PAUSED_FROM_EXECUTING: ["Pausado", "grey"],
  WON: ["Ganho", "green"], LOST: ["Perdido", "red"], SWITCHED_CADENCE: ["Trocou cadência", "grey"],
};
const statusPill = (s) => {
  const [label, tone] = STATUS_LABEL[s] || [s, "grey"];
  return `<span class="pill ${tone}">${h(label)}</span>`;
};
const TYPE_LABEL = { CALL: "Ligação", E_MAIL: "E-mail", SEARCH: "Pesquisa", SOCIAL_POINT: "Ponto social" };
const PRIORITY_LABEL = { VERY_HIGH: "Muito alta", HIGH: "Alta", MEDIUM: "Média", LOW: "Baixa" };
const FOCUS_LABEL = { OUTBOUND: "Outbound", INBOUND: "Inbound", ACTIVE_INBOUND: "Inbound ativo", OTHER: "Outro" };

const options = (list, selected, { valueKey = "id", labelKey = "name", blank = "" } = {}) =>
  (blank ? `<option value="">${h(blank)}</option>` : "") +
  list.map((i) => `<option value="${h(i[valueKey])}"${String(i[valueKey]) === String(selected) ? " selected" : ""}>${h(i[labelKey])}</option>`).join("");

/* ── login ───────────────────────────────────────────────────────────── */
const loginShell = document.getElementById("loginShell");

function showLogin() {
  loginShell.classList.remove("hidden");
  document.body.classList.add("app-loading");
}

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("loginBtn");
  const err = document.getElementById("loginError");
  err.textContent = "";
  btn.disabled = true;
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: { email: document.getElementById("loginEmail").value.trim(),
              senha: document.getElementById("loginPass").value },
    });
    loginShell.classList.add("hidden");
    await boot();
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  location.reload();
});

/* ── roteamento ──────────────────────────────────────────────────────── */
const PAGES = {};

function go(name) {
  const page = PAGES[name] || PAGES.dashboard;
  state.page = name;
  document.getElementById("crumbArea").textContent = page.area || "Bluutime";
  document.getElementById("crumbCurrent").textContent = page.title || name;
  document.querySelectorAll(".navbar-nav > li").forEach((li) => {
    li.classList.toggle("active", !!li.querySelector(`[data-page="${name}"]`));
  });
  view.innerHTML = LOADING;
  location.hash = name;
  Promise.resolve(page.render()).catch((e) => {
    view.innerHTML = panel("Erro", `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`);
  });
}

document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-page]");
  if (!link) return;
  e.preventDefault();
  go(link.dataset.page);
});
window.addEventListener("hashchange", () => {
  const name = location.hash.slice(1);
  if (name && name !== state.page) go(name);
});

/* ── boot ────────────────────────────────────────────────────────────── */
async function boot() {
  state.me = await api("/api/me");
  document.getElementById("navUser").textContent = state.me.name;
  document.getElementById("navAvatar").textContent = state.me.initials || "·";
  document.body.classList.remove("app-loading");
  loginShell.classList.add("hidden");
  const [clients, users, cadences, reasons] = await Promise.all([
    api("/api/clients"), api("/api/users"), api("/api/flow/cadences"), api("/api/flow/lost-reasons"),
  ]);
  state.clients = clients;
  state.users = users.data;
  state.cadences = cadences;
  state.lostReasons = reasons;
  go(location.hash.slice(1) || "dashboard");
}

api("/api/me").then(boot).catch(showLogin);

/* ── Dashboard ───────────────────────────────────────────────────────── */
PAGES.dashboard = {
  area: "Dashboard", title: "Visão geral",
  async render() {
    const ref = todayISO();
    const g = await api(`/api/flow/goals/${ref}/progress`);
    const pct = g.goal.opportunities ? Math.round((g.actual.won / g.goal.opportunities) * 100) : 0;
    const gapTone = g.gapPercent < 0 ? "#f44336" : "#00a443";

    const chart = renderGoalChart(g.series, g.goal.opportunities);
    const ranking = table(
      ["SDR", "Ganhos", "Perdidos", "Conversão", "Atividades", "Ligações", "Significativas"],
      g.ranking.map((r) => ({ cells: [
        `<strong>${h(r.user.name)}</strong>`, `<span style="color:#00a443">${r.won}</span>`,
        `<span style="color:#f44336">${r.lost}</span>`, `${r.conversion}%`,
        r.activities, r.calls, r.meaningful] })),
      { empty: "Nenhum SDR com movimento no mês." });

    view.innerHTML = `
      <div class="dashboard-head">
        <h1>Visão geral</h1>
        <div class="goal-filters">
          <span>${new Date(g.targetMonth).toLocaleDateString("pt-BR", { month: "long", year: "numeric" })}</span>
          <span><i class="blue-dot"></i>${state.cadences.length} cadências</span>
          <span><i class="blue-dot"></i>${state.users.length} usuários</span>
          <button class="btn-goal" id="editGoals">Editar metas</button>
        </div>
      </div>
      <div class="goal-card">
        <div>
          <div class="goal-number">${g.actual.won}</div>
          <div class="goal-title">Oportunidades no mês</div>
          <div class="goal-info-row">
            <div class="round-icon">◎</div>
            <div>Meta de oportunidades<br><strong style="color:#00a443">${g.goal.opportunities}</strong>
            · conversão alvo ${Math.round(g.goal.conversionRate * 100)}%</div>
          </div>
          <div class="goal-info-row">
            <div class="round-icon" style="color:${gapTone}">${g.gapPercent < 0 ? "▼" : "▲"}</div>
            <div><strong style="color:${gapTone}">${Math.abs(g.gapPercent)}%</strong>
            ${g.gapPercent < 0 ? "abaixo" : "acima"} do previsto até hoje <strong>(${g.expectedByNow})</strong>
            <br>para alcançar a meta mensal</div>
          </div>
          <div class="goal-info-row">
            <div class="round-icon">Σ</div>
            <div>Esforço necessário: <strong>${g.effort.leadsNeeded}</strong> leads ·
            <strong>${g.effort.activitiesNeeded}</strong> atividades ·
            <strong>${g.effort.activitiesPerUserPerDay}</strong> atividades/SDR/dia</div>
          </div>
        </div>
        <div class="chart-area">${chart}
          <div class="chart-legend"><span><i class="legend-box"></i>Realizado</span>
          <span><i class="legend-box" style="background:#ededed"></i>Meta</span></div>
        </div>
      </div>

      <div class="ranking-title">Ranking de SDRs · ${pct}% da meta</div>
      ${panel("Desempenho no mês", ranking)}

      <div class="insights-grid">
        <div class="panel panel-flat"><div class="panel-heading has-border"><h2 class="panel-title">Motivos de perda</h2></div>
          <div class="panel-body">${bars(g.lostReasons.slice(0, 6).map((r) => ({ label: r.name, value: r.count, tone: "warning" })))}</div></div>
        <div class="panel panel-flat"><div class="panel-heading has-border"><h2 class="panel-title">Resultado por cliente</h2></div>
          <div class="panel-body">${bars(g.byClient.map((c) => ({ label: c.client, value: c.won + c.lost })))}</div></div>
      </div>`;

    document.getElementById("editGoals").onclick = () => openGoalsModal(ref);
  },
};

function renderGoalChart(series, target) {
  const W = 760, H = 320, padL = 44, padB = 28;
  const max = Math.max(target, ...series.map((s) => s.actual || 0)) || 1;
  const x = (i) => padL + (i * (W - padL - 10)) / Math.max(1, series.length - 1);
  const y = (v) => H - padB - (v / max) * (H - padB - 14);
  const actual = series.filter((s) => s.actual !== null);
  const line = (pts, color, width, dash) =>
    `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${width}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const yy = y(max * f);
    return `<line x1="${padL}" y1="${yy}" x2="${W - 10}" y2="${yy}" stroke="#eee"/>
            <text x="8" y="${yy + 4}" font-size="11" fill="#999">${Math.round(max * f)}</text>`;
  }).join("");
  const areaPts = actual.map((s, i) => `${x(i)},${y(s.actual)}`).join(" ");
  const area = areaPts
    ? `<polygon points="${padL},${y(0)} ${areaPts} ${x(actual.length - 1)},${y(0)}" fill="#d6f9e2"/>`
    : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Oportunidades no mês contra a meta">
    ${grid}${area}
    ${line(series.map((s, i) => `${x(i)},${y(s.target)}`).join(" "), "#ededed", 3)}
    ${areaPts ? line(areaPts, "#00c850", 3) : ""}
    <text x="${padL}" y="${H - 6}" font-size="11" fill="#999">${fmtDate(series[0]?.date)}</text>
    <text x="${W - 70}" y="${H - 6}" font-size="11" fill="#999">${fmtDate(series[series.length - 1]?.date)}</text>
  </svg>`;
}

async function openGoalsModal(ref) {
  const current = await api(`/api/flow/goals/${ref}`);
  const byUser = Object.fromEntries(current.usersGoals.map((g) => [g.user.id, g]));
  const m = modal({
    title: "Metas do mês",
    body: state.users.map((u) => {
      const g = byUser[u.id] || {};
      return `<div class="field-row" data-uid="${u.id}">
        <div class="field"><label>${h(u.name)} — oportunidades</label>
          <input class="form-control" type="number" min="0" data-goal value="${g.opportunitiesGoal ?? 25}"></div>
        <div class="field"><label>Conversão alvo (%)</label>
          <input class="form-control" type="number" min="1" max="100" data-conv value="${Math.round((g.conversionRateGoal ?? 0.15) * 100)}"></div>
      </div>`;
    }).join(""),
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar metas</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async () => {
    const usersGoals = [...m.root.querySelectorAll("[data-uid]")].map((row) => ({
      userId: Number(row.dataset.uid),
      opportunitiesGoal: Number(row.querySelector("[data-goal]").value),
      conversionRateGoal: Number(row.querySelector("[data-conv]").value) / 100,
    }));
    await api(`/api/flow/goals/${ref}`, { method: "PUT", body: { usersGoals } });
    m.close();
    toast("Metas atualizadas.", "ok");
    go("dashboard");
  };
}

/* ── Painel de controle diário ───────────────────────────────────────── */
PAGES.painel = {
  area: "Prospecção", title: "Painel de controle",
  async render() {
    const clientId = state.filterClient || "";
    const res = await api(`/api/flow/control-panel${clientId ? `?client_id=${clientId}` : ""}`);
    const rows = res.data.map((r) => ({ cells: [
      `<div class="media-left"><div class="lead-avatar-dot ${r.online ? "success" : ""}">${h(r.user.initials)}</div></div>
       <div class="media-body"><strong>${h(r.user.name)}</strong><br>
       <span class="text-muted">${r.online ? "Online" : "Offline"}</span></div>`,
      r.lastActivity ? `${TYPE_LABEL[r.lastActivity.type] || r.lastActivity.type}<br>
        <span class="text-muted">${fmtDateTime(r.lastActivity.doneAt)}</span>` : `<span class="text-muted">—</span>`,
      r.leads.prospecting, r.leads.available,
      `<span style="color:#00a443">${r.leads.won}</span>`,
      `<span style="color:#f44336">${r.leads.lost}</span>`,
      `<span style="color:#1e88e5">${r.activities.pending}</span>`,
      r.activities.late ? `<span class="pill red">${r.activities.late}</span>` : "0",
      r.activities.done, r.activities.skipped,
      r.activities.call, r.activities.email, r.activities.search, r.activities.social,
      `${r.calls.connected}/${r.calls.total}`,
    ] }));

    view.innerHTML = `<div class="meetime-page-wide">
      <div class="toolbar">
        <select class="form-control" id="fClient">${options(state.clients, clientId, { blank: "Todos os clientes" })}</select>
        <span class="spacer text-muted text-size-small">Atualizado ${fmtDateTime(res.meta.generatedAt)}</span>
        <button class="btn btn-default btn-xs" id="refresh">Atualizar</button>
      </div>
      <div class="mt-sheet">
        <div class="sheet-title">Painel de controle diário</div>
        <div class="sheet-subtitle">Monitore as atividades da equipe e mantenha o controle do desempenho do dia.</div>
        <div class="table-responsive"><table class="table table-striped table-hover">
          <thead>
            <tr>
              <th colspan="2" style="border-bottom:2px solid #00c850">TIME</th>
              <th colspan="4" style="border-bottom:2px solid #00c850">LEADS</th>
              <th colspan="8" style="border-bottom:2px solid #00c850">ATIVIDADES</th>
            </tr>
            <tr>
              <th>Usuário</th><th>Última atividade</th>
              <th>Prospectando</th><th>Disponíveis</th><th>Ganhos</th><th>Perdidos</th>
              <th>Pendentes</th><th>Atrasadas</th><th>Realizadas</th><th>Ignoradas</th>
              <th>Ligação</th><th>E-mail</th><th>Pesquisa</th><th>Social</th><th>Conectadas</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) => `<tr>${r.cells.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
        </table></div>
      </div></div>`;

    document.getElementById("fClient").onchange = (e) => {
      state.filterClient = e.target.value; go("painel");
    };
    document.getElementById("refresh").onclick = () => go("painel");
  },
};

/* ── Execução: a fila priorizada ─────────────────────────────────────── */
PAGES.execucao = {
  area: "Prospecção", title: "Execução",
  async render() {
    const f = state.queueFilter || {};
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const res = await api(`/api/flow/execution/queue?${qs}`);
    const items = res.data;

    const list = items.length ? items.map((a, i) => `
      <div class="queue-item${a.late ? " late" : ""}" data-act="${a.id}">
        <div class="queue-rank">${i + 1}</div>
        <div>
          <strong>${h(a.lead.name)}</strong>
          <span class="text-muted ml-5">${h(a.lead.company)}</span>
          ${a.lead.client ? `<span class="pill ml-5" style="border-color:${h(a.lead.client.color)}">${h(a.lead.client.name)}</span>` : ""}
          <br>
          <span class="pill ${a.type === "CALL" ? "blue" : a.type === "E_MAIL" ? "grey" : "green"}">${h(TYPE_LABEL[a.type] || a.type)}</span>
          <span class="text-muted ml-5">${h(a.activity ? a.activity.name : "")}</span>
          <br>
          <span class="text-size-small text-muted">
            ${a.late ? `<span style="color:#f44336">Atrasada</span> · ` : ""}agendada ${fmtDateTime(a.scheduledAt)}
            · melhor contato ${a.lead.bestHour}h
            ${a.lead.cadence ? ` · ${h(a.lead.cadence.name)} (${h(PRIORITY_LABEL[a.lead.cadence.priority])})` : ""}
            · score ${a.score}
          </span>
        </div>
        <div class="nowrap">
          <button class="btn btn-main btn-xs" data-exec="${a.id}">Executar</button>
          <button class="btn btn-default btn-xs" data-skip="${a.id}">Ignorar</button>
          <button class="btn btn-default btn-xs" data-lead="${a.lead.id}">Abrir lead</button>
        </div>
      </div>`).join("") : emptyState("Fila vazia — nada pendente para agora.");

    view.innerHTML = `
      <div class="toolbar">
        <select class="form-control" id="qSdr">${options(state.users, f.sdr_id, { blank: "Todos os SDRs" })}</select>
        <select class="form-control" id="qClient">${options(state.clients, f.client_id, { blank: "Todos os clientes" })}</select>
        <select class="form-control" id="qCad">${options(state.cadences, f.cadence_id, { blank: "Todas as cadências" })}</select>
        <select class="form-control" id="qType">
          <option value="">Todos os tipos</option>
          ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}"${f.type === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="refresh">Atualizar</button>
      </div>
      ${kpis([
        { value: res.meta.total, label: "Na fila", tone: "info" },
        { value: res.meta.late, label: "Atrasadas", tone: "danger" },
        { value: res.meta.onTime, label: "No prazo", tone: "success" },
        { value: items[0] ? `${items[0].lead.bestHour}h` : "—", label: "Próxima janela" },
      ])}
      ${panel("Fila priorizada",
        `<div class="alert alert-info alert-styled-left">A ordem combina atraso, prioridade da cadência e janela de melhor contato — não é ordem cronológica.</div>
         <div style="margin:0 -20px -20px">${list}</div>`,
        { subtitle: "Atividades pendentes das próximas 24 horas" })}`;

    const setFilter = (key, value) => {
      state.queueFilter = { ...(state.queueFilter || {}), [key]: value };
      go("execucao");
    };
    document.getElementById("qSdr").onchange = (e) => setFilter("sdr_id", e.target.value);
    document.getElementById("qClient").onchange = (e) => setFilter("client_id", e.target.value);
    document.getElementById("qCad").onchange = (e) => setFilter("cadence_id", e.target.value);
    document.getElementById("qType").onchange = (e) => setFilter("type", e.target.value);
    document.getElementById("refresh").onclick = () => go("execucao");

    view.querySelectorAll("[data-exec]").forEach((b) => {
      b.onclick = () => openExecuteModal(items.find((a) => String(a.id) === b.dataset.exec));
    });
    view.querySelectorAll("[data-skip]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/flow/execution/activities/${b.dataset.skip}/execute`,
          { method: "POST", body: { skip: true } });
        toast("Atividade ignorada.");
        go("execucao");
      };
    });
    view.querySelectorAll("[data-lead]").forEach((b) => {
      b.onclick = () => openLeadModal(Number(b.dataset.lead));
    });
  },
};

function openExecuteModal(act) {
  if (!act) return;
  const tpl = act.activity && act.activity.emailTemplate;
  const merge = (text) => (text || "")
    .replace(/\{\{firstName\}\}/g, act.lead.name.split(" ")[0])
    .replace(/\{\{company\}\}/g, act.lead.company);

  const script = act.activity ? merge(act.activity.instruction) : "";
  const callBlock = act.type === "CALL" ? `
    <div class="field-row">
      <div class="field"><label>Resultado da ligação</label>
        <select class="form-control" id="callOutput">
          <option value="">Não conectou</option>
          <option value="NO_CONTACT">Conectou · sem contato</option>
          <option value="NOT_MEANINGFUL">Conectou · não significativa</option>
          <option value="MEANINGFUL">Conectou · significativa</option>
        </select></div>
      <div class="field"><label>Duração (segundos)</label>
        <input class="form-control" type="number" min="0" id="callDuration" value="0"></div>
    </div>` : "";

  const m = modal({
    title: `${TYPE_LABEL[act.type] || act.type} — ${act.lead.name}`,
    wide: true,
    body: `
      <div class="alert alert-info alert-styled-left">
        <strong>${h(act.lead.company)}</strong> · ${h(act.lead.phone || "sem telefone")} ·
        ${h(act.lead.email || "sem e-mail")}
        ${act.lead.cadence ? ` · cadência ${h(act.lead.cadence.name)}` : ""}
      </div>
      ${script ? `<div class="field"><label>Script</label>
        <div class="json-box" style="max-height:200px">${h(script)}</div></div>` : ""}
      ${tpl ? `<div class="field"><label>E-mail — ${h(merge(tpl.subject))}</label>
        <div class="json-box" style="max-height:200px">${h(merge(tpl.html).replace(/<[^>]+>/g, " "))}</div></div>` : ""}
      ${callBlock}
      <div class="field"><label>Anotações</label><textarea class="form-control" id="execNotes"></textarea></div>`,
    footer: `<button class="btn btn-danger btn-sm" data-lost>Marcar perdido</button>
             <button class="btn btn-success btn-sm" data-won>Marcar ganho</button>
             <span style="flex:1"></span>
             <button class="btn btn-default btn-sm" data-cancel>Fechar</button>
             <button class="btn btn-main btn-sm" data-done>Concluir atividade</button>`,
  });

  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-done]").onclick = async () => {
    const notes = m.root.querySelector("#execNotes").value;
    if (act.type === "CALL") {
      const output = m.root.querySelector("#callOutput").value;
      await api("/api/dialer/calls", { method: "POST", body: {
        leadId: act.lead.id, userId: state.me.id,
        status: output ? "CONNECTED" : "NOT_PERFORMED", output,
        duration: Number(m.root.querySelector("#callDuration").value) || 0,
        receiverPhone: act.lead.phone,
      } });
    }
    await api(`/api/flow/execution/activities/${act.id}/execute`, { method: "POST", body: { notes } });
    m.close();
    toast("Atividade concluída.", "ok");
    go("execucao");
  };
  m.root.querySelector("[data-won]").onclick = async () => {
    await api(`/api/flow/execution/leads/${act.lead.id}/outcome`,
      { method: "POST", body: { outcome: "WON" } });
    m.close(); toast("Lead marcado como ganho.", "ok"); go("execucao");
  };
  m.root.querySelector("[data-lost]").onclick = () => { m.close(); openLostModal(act.lead.id, () => go("execucao")); };
}

function openLostModal(leadId, after) {
  const m = modal({
    title: "Marcar como perdido",
    body: `<div class="field"><label>Motivo da perda</label>
        <select class="form-control" id="lostReason">${options(state.lostReasons, "", { blank: "Selecione…" })}</select></div>
      <div class="field"><label>Anotações</label><textarea class="form-control" id="lostNotes"></textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-danger btn-sm" data-ok>Confirmar perda</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const reason = m.root.querySelector("#lostReason").value;
    if (!reason) return toast("Escolha o motivo da perda.", "err");
    await api(`/api/flow/execution/leads/${leadId}/outcome`, { method: "POST", body: {
      outcome: "LOST", lostReasonId: Number(reason),
      annotations: m.root.querySelector("#lostNotes").value } });
    m.close(); toast("Lead marcado como perdido."); after && after();
  };
}

/* ── Leads ───────────────────────────────────────────────────────────── */
PAGES.leads = {
  area: "Prospecção", title: "Leads",
  async render() {
    const f = state.leadFilter || { page: 1, limit: 50 };
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const res = await api(`/api/flow/leads?${qs}`);
    const rows = res.data.map((l) => ({ cells: [
      `<input type="checkbox" class="lead-check" value="${l.id}">`,
      `<a data-open-lead="${l.id}"><strong>${h(l.name)}</strong></a><br>
       <span class="text-muted text-size-small">${h(l.position || "")}</span>`,
      `${h(l.company)}<br><span class="text-muted text-size-small">${h(l.cnpj || "")}</span>`,
      `${h(l.city || "")}${l.state ? `/${h(l.state)}` : ""}`,
      h(l.phone || "—"),
      statusPill(l.status),
      l.cadence ? h(l.cadence.name) : "—",
      l.client ? `<span class="pill" style="border-color:${h(l.client.color)}">${h(l.client.name)}</span>` : "—",
      l.sdr ? h(l.sdr.name) : "—",
      fmtDate(l.createdAt),
    ] }));

    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="lq" placeholder="Buscar por nome, empresa, e-mail ou CNPJ" value="${h(f.q || "")}">
        <select class="form-control" id="lStatus">
          <option value="">Todas as situações</option>
          ${Object.entries(STATUS_LABEL).map(([k, v]) => `<option value="${k}"${f.status === k ? " selected" : ""}>${v[0]}</option>`).join("")}
        </select>
        <select class="form-control" id="lClient">${options(state.clients, f.client_id, { blank: "Todos os clientes" })}</select>
        <select class="form-control" id="lCad">${options(state.cadences, f.cadence_id, { blank: "Todas as cadências" })}</select>
        <select class="form-control" id="lSdr">${options(state.users, f.sdr_id, { blank: "Todos os SDRs" })}</select>
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="bulkBtn">Ações em massa</button>
        <button class="btn btn-main btn-xs" id="newLead">Novo lead</button>
      </div>
      ${panel(`${res.pagination.totalRowCount} leads`,
        table(["<input type='checkbox' id='checkAll'>", "Lead", "Empresa", "Cidade", "Telefone",
               "Situação", "Cadência", "Cliente", "SDR", "Criado"], rows, { scroll: true }),
        { actions: pager(res.pagination) })}`;

    bindLeadFilters(f);
    document.getElementById("newLead").onclick = () => openLeadForm();
    document.getElementById("bulkBtn").onclick = openBulkModal;
    const checkAll = document.getElementById("checkAll");
    if (checkAll) checkAll.onchange = (e) =>
      view.querySelectorAll(".lead-check").forEach((c) => { c.checked = e.target.checked; });
    view.querySelectorAll("[data-open-lead]").forEach((a) => {
      a.onclick = () => openLeadModal(Number(a.dataset.openLead));
    });
    view.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => { state.leadFilter = { ...f, page: Number(b.dataset.gotoPage) }; go("leads"); };
    });
  },
};

const pager = (p) => p.totalPageCount > 1
  ? `<span class="text-muted text-size-small mr-10">Página ${p.page} de ${p.totalPageCount}</span>
     <button class="btn btn-default btn-xs" data-goto-page="${p.page - 1}" ${p.page <= 1 ? "disabled" : ""}>‹</button>
     <button class="btn btn-default btn-xs" data-goto-page="${p.page + 1}" ${p.page >= p.totalPageCount ? "disabled" : ""}>›</button>`
  : "";

function bindLeadFilters(f) {
  const set = (key, value) => { state.leadFilter = { ...f, [key]: value, page: 1 }; go("leads"); };
  const q = document.getElementById("lq");
  let timer;
  q.oninput = () => { clearTimeout(timer); timer = setTimeout(() => set("q", q.value), 350); };
  document.getElementById("lStatus").onchange = (e) => set("status", e.target.value);
  document.getElementById("lClient").onchange = (e) => set("client_id", e.target.value);
  document.getElementById("lCad").onchange = (e) => set("cadence_id", e.target.value);
  document.getElementById("lSdr").onchange = (e) => set("sdr_id", e.target.value);
}

function selectedLeadIds() {
  return [...view.querySelectorAll(".lead-check:checked")].map((c) => Number(c.value));
}

function openBulkModal() {
  const ids = selectedLeadIds();
  if (!ids.length) return toast("Selecione ao menos um lead.", "err");
  const m = modal({
    title: `Ações em massa · ${ids.length} leads`,
    body: `<div class="field"><label>Ação</label>
        <select class="form-control" id="bulkAction">
          <option value="transfer">Transferir para outro SDR</option>
          <option value="switch_cadence">Trocar de cadência</option>
          <option value="back_to_waiting">Voltar para espera</option>
          <option value="lost">Marcar como perdido</option>
          <option value="delete">Apagar</option>
        </select></div>
      <div class="field" id="bulkExtra"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Aplicar</button>`,
  });
  const extra = m.root.querySelector("#bulkExtra");
  const action = m.root.querySelector("#bulkAction");
  const renderExtra = () => {
    if (action.value === "transfer")
      extra.innerHTML = `<label>SDR de destino</label><select class="form-control" id="bulkVal">${options(state.users, "")}</select>`;
    else if (action.value === "switch_cadence")
      extra.innerHTML = `<label>Cadência</label><select class="form-control" id="bulkVal">${options(state.cadences, "")}</select>`;
    else if (action.value === "lost")
      extra.innerHTML = `<label>Motivo</label><select class="form-control" id="bulkVal">${options(state.lostReasons, "")}</select>`;
    else extra.innerHTML = "";
  };
  renderExtra();
  action.onchange = renderExtra;
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const val = m.root.querySelector("#bulkVal");
    const body = { leadIds: ids, action: action.value };
    if (action.value === "transfer") body.sdrId = Number(val.value);
    if (action.value === "switch_cadence") body.cadenceId = Number(val.value);
    if (action.value === "lost") body.lostReasonId = Number(val.value);
    const res = await api("/api/flow/leads/bulk", { method: "POST", body });
    m.close(); toast(`${res.affected} leads atualizados.`, "ok"); go("leads");
  };
}

async function openLeadModal(id) {
  const l = await api(`/api/flow/leads/${id}`);
  const timeline = l.timeline.length ? `<div class="timeline">${l.timeline.map((a) => `
      <div class="timeline-item">
        <span class="pill ${a.status === "DONE" ? "green" : a.status === "SKIPPED" ? "grey" : a.late ? "red" : "blue"}">
          ${h(TYPE_LABEL[a.type] || a.type)}</span>
        <strong class="ml-5">${h(a.activity ? a.activity.name : "")}</strong><br>
        <span class="text-muted text-size-small">
          ${a.status === "PENDING" ? `agendada ${fmtDateTime(a.scheduledAt)}${a.late ? " · atrasada" : ""}`
            : `${a.status === "DONE" ? "realizada" : "ignorada"} ${fmtDateTime(a.doneAt)}`}
          ${a.user ? ` · ${h(a.user.name)}` : ""}</span>
        ${a.notes ? `<div class="text-size-small mt-10">${h(a.notes)}</div>` : ""}
      </div>`).join("")}</div>` : emptyState("Nenhuma atividade registrada.");

  const m = modal({
    title: l.name, wide: true,
    body: `<div class="two-col">
      <div>
        <table class="table table-striped"><tbody>
          <tr><td class="text-grey">Empresa</td><td>${h(l.company)}</td></tr>
          <tr><td class="text-grey">Cargo</td><td>${h(l.position || "—")}</td></tr>
          <tr><td class="text-grey">CNPJ</td><td>${h(l.cnpj || "—")}</td></tr>
          <tr><td class="text-grey">Telefone</td><td>${h(l.phone || "—")}</td></tr>
          <tr><td class="text-grey">E-mail</td><td>${h(l.email || "—")}</td></tr>
          <tr><td class="text-grey">Cidade</td><td>${h(l.city || "—")}${l.state ? `/${h(l.state)}` : ""}</td></tr>
          <tr><td class="text-grey">Situação</td><td>${statusPill(l.status)}</td></tr>
          <tr><td class="text-grey">Cadência</td><td>${l.cadence ? h(l.cadence.name) : "—"}</td></tr>
          <tr><td class="text-grey">Cliente</td><td>${l.client ? h(l.client.name) : "—"}</td></tr>
          <tr><td class="text-grey">SDR</td><td>${l.sdr ? h(l.sdr.name) : "—"}</td></tr>
          <tr><td class="text-grey">Base</td><td>${l.leadBase ? h(l.leadBase.name) : "—"}</td></tr>
          <tr><td class="text-grey">Melhor horário</td><td>${l.bestHour}h</td></tr>
          ${l.lostReason ? `<tr><td class="text-grey">Motivo da perda</td><td>${h(l.lostReason.name)}</td></tr>` : ""}
        </tbody></table>
        <div class="mt-10">
          <button class="btn btn-default btn-xs" data-enrich>Enriquecer no CapiBLU</button>
          <button class="btn btn-default btn-xs" data-validate>Validar telefone</button>
          <button class="btn btn-default btn-xs" data-wa>Abrir WhatsApp</button>
        </div>
        <div id="enrichOut" class="mt-10"></div>
      </div>
      <div><h4 style="margin:0 0 12px;font-size:13px">Linha do tempo</h4>${timeline}</div>
    </div>`,
    footer: `<button class="btn btn-danger btn-sm" data-lost>Perdido</button>
             <button class="btn btn-success btn-sm" data-won>Ganho</button>
             <span style="flex:1"></span>
             <button class="btn btn-default btn-sm" data-edit>Editar</button>
             <button class="btn btn-default btn-sm" data-close2>Fechar</button>`,
  });

  m.root.querySelector("[data-close2]").onclick = m.close;
  m.root.querySelector("[data-edit]").onclick = () => { m.close(); openLeadForm(l); };
  m.root.querySelector("[data-won]").onclick = async () => {
    await api(`/api/flow/execution/leads/${l.id}/outcome`, { method: "POST", body: { outcome: "WON" } });
    m.close(); toast("Lead ganho.", "ok"); go(state.page);
  };
  m.root.querySelector("[data-lost]").onclick = () => { m.close(); openLostModal(l.id, () => go(state.page)); };
  m.root.querySelector("[data-wa]").onclick = async () => {
    const conv = await api("/api/whatsapp/conversations", { method: "POST", body: { leadId: l.id } });
    m.close(); state.waActive = conv.id; go("whatsapp");
  };

  const out = m.root.querySelector("#enrichOut");
  m.root.querySelector("[data-enrich]").onclick = async () => {
    out.innerHTML = `<span class="spinner"></span> consultando CapiBLU…`;
    try {
      const r = await api(`/api/capiblu/leads/${l.id}/enrich`, { method: "POST" });
      out.innerHTML = `<div class="alert alert-success alert-styled-left">
        ${r.updated.length ? `Campos atualizados: ${h(r.updated.join(", "))}.` : "Nada novo a preencher."}
        ${r.contacts.length} contato(s) encontrados na empresa.</div>
        <div class="json-box">${h(JSON.stringify(r.contacts, null, 2))}</div>`;
    } catch (e) { out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`; }
  };
  m.root.querySelector("[data-validate]").onclick = async () => {
    out.innerHTML = `<span class="spinner"></span> validando telefone…`;
    try {
      const r = await api(`/api/capiblu/leads/${l.id}/validate-phone`, { method: "POST" });
      out.innerHTML = `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>`;
    } catch (e) { out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`; }
  };
}

function openLeadForm(lead) {
  const l = lead || {};
  const m = modal({
    title: l.id ? `Editar ${l.name}` : "Novo lead",
    body: `
      <div class="field-row">
        <div class="field"><label>Nome *</label><input class="form-control" id="fName" value="${h(l.name || "")}"></div>
        <div class="field"><label>Cargo</label><input class="form-control" id="fPosition" value="${h(l.position || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Empresa</label><input class="form-control" id="fCompany" value="${h(l.company || "")}"></div>
        <div class="field"><label>CNPJ</label><input class="form-control" id="fCnpj" value="${h(l.cnpj || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Telefone</label><input class="form-control" id="fPhone" value="${h(l.phone || "")}"></div>
        <div class="field"><label>E-mail</label><input class="form-control" id="fEmail" value="${h(l.email || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Cidade</label><input class="form-control" id="fCity" value="${h(l.city || "")}"></div>
        <div class="field"><label>UF</label><input class="form-control" id="fState" value="${h(l.state || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Cliente</label>
          <select class="form-control" id="fClient">${options(state.clients, l.client && l.client.id, { blank: "—" })}</select></div>
        <div class="field"><label>SDR</label>
          <select class="form-control" id="fSdr">${options(state.users, l.sdr && l.sdr.id, { blank: "—" })}</select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Cadência</label>
          <select class="form-control" id="fCadence">${options(state.cadences, l.cadence && l.cadence.id, { blank: "—" })}</select></div>
        <div class="field"><label>Melhor horário de contato</label>
          <input class="form-control" type="number" min="6" max="22" id="fHour" value="${l.bestHour || 18}"></div>
      </div>
      <div class="field"><label>Anotações</label><textarea class="form-control" id="fNotes">${h(l.annotations || "")}</textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async () => {
    const g = (id) => m.root.querySelector(id).value.trim();
    const body = {
      name: g("#fName"), position: g("#fPosition"), company: g("#fCompany"),
      cnpj: g("#fCnpj"), phone: g("#fPhone"), email: g("#fEmail"),
      city: g("#fCity"), state: g("#fState"), annotations: g("#fNotes"),
      bestHour: Number(g("#fHour")) || 18,
      clientId: Number(g("#fClient")) || null, sdrId: Number(g("#fSdr")) || null,
      cadenceId: Number(g("#fCadence")) || null,
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (l.id) await api(`/api/flow/leads/${l.id}`, { method: "PATCH", body });
    else await api("/api/flow/leads", { method: "POST", body });
    m.close(); toast("Lead salvo.", "ok"); go("leads");
  };
}

/* ── Cadências ───────────────────────────────────────────────────────── */
PAGES.cadencias = {
  area: "Prospecção", title: "Cadências",
  async render() {
    const f = state.cadFilter || {};
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v != null));
    const list = await api(`/api/flow/cadences?${qs}`);
    state.cadences = list;
    const rows = list.map((c) => ({ cells: [
      `<a data-open-cad="${c.id}"><strong>${h(c.name)}</strong></a>
       ${c.description ? `<br><span class="text-muted text-size-small">${h(c.description)}</span>` : ""}`,
      c.client ? `<span class="pill" style="border-color:${h(c.client.color)}">${h(c.client.name)}</span>` : "—",
      `<span class="pill">${h(FOCUS_LABEL[c.cadenceFocus] || c.cadenceFocus)}</span>`,
      `<span class="pill ${c.priority === "VERY_HIGH" ? "red" : c.priority === "HIGH" ? "amber" : "grey"}">${h(PRIORITY_LABEL[c.priority])}</span>`,
      c.stepsCount,
      c.overview.total, `<span style="color:#00a443">${c.overview.won}</span>`,
      `<span style="color:#f44336">${c.overview.lost}</span>`,
      c.overview.total ? `${Math.round((c.overview.won / c.overview.total) * 100)}%` : "—",
      c.users.map((u) => h(u.name)).join(", ") || "—",
      c.executing ? `<span class="pill green">Ativa</span>` : `<span class="pill grey">Pausada</span>`,
      `<button class="btn btn-default btn-xs" data-edit-cad="${c.id}">Editar</button>`,
    ] }));

    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="cq" placeholder="Buscar cadência" value="${h(f.q || "")}">
        <select class="form-control" id="cClient">${options(state.clients, f.client_id, { blank: "Todos os clientes" })}</select>
        <select class="form-control" id="cFocus">
          <option value="">Todos os focos</option>
          ${Object.entries(FOCUS_LABEL).map(([k, v]) => `<option value="${k}"${f.focus === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <select class="form-control" id="cPrio">
          <option value="">Todas as prioridades</option>
          ${Object.entries(PRIORITY_LABEL).map(([k, v]) => `<option value="${k}"${f.priority === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="newCad">Criar cadência</button>
      </div>
      ${panel(`${list.length} cadências`,
        table(["Cadência", "Cliente", "Foco", "Prioridade", "Etapas", "Leads", "Ganhos",
               "Perdidos", "Conversão", "Responsáveis", "Situação", ""], rows, { scroll: true }))}`;

    const set = (k, v) => { state.cadFilter = { ...f, [k]: v }; go("cadencias"); };
    const q = document.getElementById("cq");
    let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => set("q", q.value), 350); };
    document.getElementById("cClient").onchange = (e) => set("client_id", e.target.value);
    document.getElementById("cFocus").onchange = (e) => set("focus", e.target.value);
    document.getElementById("cPrio").onchange = (e) => set("priority", e.target.value);
    document.getElementById("newCad").onclick = () => openCadenceForm();
    view.querySelectorAll("[data-open-cad]").forEach((a) => {
      a.onclick = () => openCadenceDetail(Number(a.dataset.openCad));
    });
    view.querySelectorAll("[data-edit-cad]").forEach((b) => {
      b.onclick = () => openCadenceForm(list.find((c) => String(c.id) === b.dataset.editCad));
    });
  },
};

async function openCadenceDetail(id) {
  const c = await api(`/api/flow/cadences/${id}`);
  const byDay = {};
  c.steps.forEach((s) => { (byDay[s.day] = byDay[s.day] || []).push(s); });
  const steps = Object.keys(byDay).sort((a, b) => a - b).map((day) => `
    <div class="mb-20"><strong>Dia ${h(day)}</strong>
      ${byDay[day].map((s) => `<div class="queue-item" style="grid-template-columns:1fr auto">
        <div><span class="pill ${s.activity.type === "CALL" ? "blue" : "green"}">${h(TYPE_LABEL[s.activity.type])}</span>
          <strong class="ml-5">${h(s.activity.name)}</strong>
          ${s.activity.instruction ? `<br><span class="text-muted text-size-small">${h(s.activity.instruction.slice(0, 160))}</span>` : ""}</div>
        <button class="btn btn-default btn-xs" data-del-step="${s.id}">Remover</button>
      </div>`).join("")}
    </div>`).join("") || emptyState("Cadência sem etapas.");

  const m = modal({
    title: c.name, wide: true,
    body: `${kpis([
      { value: c.overview.total, label: "Leads" },
      { value: c.overview.won, label: "Ganhos", tone: "success" },
      { value: c.overview.lost, label: "Perdidos", tone: "danger" },
      { value: c.overview.total ? `${Math.round((c.overview.won / c.overview.total) * 100)}%` : "—", label: "Conversão", tone: "info" },
    ])}
    <div class="mt-10 mb-20">
      <span class="pill">${h(FOCUS_LABEL[c.cadenceFocus])}</span>
      <span class="pill ml-5">${h(PRIORITY_LABEL[c.priority])}</span>
      ${c.client ? `<span class="pill ml-5" style="border-color:${h(c.client.color)}">${h(c.client.name)}</span>` : ""}
      <span class="pill ml-5 ${c.executing ? "green" : "grey"}">${c.executing ? "Ativa" : "Pausada"}</span>
    </div>
    <h4 style="font-size:13px">Etapas</h4>${steps}`,
    footer: `<button class="btn btn-default btn-sm" data-add-step>Adicionar etapa</button>
             <span style="flex:1"></span>
             <button class="btn btn-default btn-sm" data-close2>Fechar</button>`,
  });
  m.root.querySelector("[data-close2]").onclick = m.close;
  m.root.querySelector("[data-add-step]").onclick = async () => {
    const acts = await api("/api/flow/activities?limit=300");
    const inner = modal({
      title: "Adicionar etapa",
      body: `<div class="field"><label>Atividade</label>
          <select class="form-control" id="stepAct">${options(acts, "")}</select></div>
        <div class="field"><label>Dia da cadência</label>
          <input class="form-control" type="number" min="1" id="stepDay" value="1"></div>`,
      footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
               <button class="btn btn-main btn-sm" data-ok>Adicionar</button>`,
    });
    inner.root.querySelector("[data-cancel]").onclick = () => { inner.close(); openCadenceDetail(id); };
    inner.root.querySelector("[data-ok]").onclick = async () => {
      await api(`/api/flow/cadences/${id}/steps`, { method: "POST", body: {
        activityId: Number(inner.root.querySelector("#stepAct").value),
        day: Number(inner.root.querySelector("#stepDay").value) } });
      inner.close(); toast("Etapa adicionada.", "ok"); openCadenceDetail(id);
    };
  };
  m.root.querySelectorAll("[data-del-step]").forEach((b) => {
    b.onclick = async () => {
      await api(`/api/flow/cadences/${id}/steps/${b.dataset.delStep}`, { method: "DELETE" });
      toast("Etapa removida."); openCadenceDetail(id);
    };
  });
}

function openCadenceForm(cad) {
  const c = cad || {};
  const m = modal({
    title: c.id ? `Editar ${c.name}` : "Nova cadência",
    body: `
      <div class="field"><label>Nome *</label><input class="form-control" id="cName" value="${h(c.name || "")}"></div>
      <div class="field"><label>Descrição</label><textarea class="form-control" id="cDesc">${h(c.description || "")}</textarea></div>
      <div class="field-row">
        <div class="field"><label>Cliente</label>
          <select class="form-control" id="cClientSel">${options(state.clients, c.client && c.client.id, { blank: "—" })}</select></div>
        <div class="field"><label>Foco</label>
          <select class="form-control" id="cFocusSel">
            ${Object.entries(FOCUS_LABEL).map(([k, v]) => `<option value="${k}"${c.cadenceFocus === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Prioridade</label>
          <select class="form-control" id="cPrioSel">
            ${Object.entries(PRIORITY_LABEL).map(([k, v]) => `<option value="${k}"${c.priority === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
        <div class="field"><label>Situação</label>
          <select class="form-control" id="cExec">
            <option value="true"${c.executing !== false ? " selected" : ""}>Ativa</option>
            <option value="false"${c.executing === false ? " selected" : ""}>Pausada</option>
          </select></div>
      </div>
      <div class="field"><label>Responsáveis</label>
        <select class="form-control" id="cUsers" multiple size="4">
          ${state.users.map((u) => `<option value="${u.id}"${(c.users || []).some((x) => x.id === u.id) ? " selected" : ""}>${h(u.name)}</option>`).join("")}
        </select></div>`,
    footer: `${c.id ? `<button class="btn btn-danger btn-sm" data-del>Excluir</button><span style="flex:1"></span>` : ""}
             <button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const del = m.root.querySelector("[data-del]");
  if (del) del.onclick = () => confirmDialog("Excluir cadência", `Excluir "${c.name}"?`, async () => {
    try { await api(`/api/flow/cadences/${c.id}`, { method: "DELETE" }); toast("Cadência excluída."); go("cadencias"); }
    catch (e) { toast(e.message, "err"); }
  });
  m.root.querySelector("[data-save]").onclick = async () => {
    const body = {
      name: m.root.querySelector("#cName").value.trim(),
      description: m.root.querySelector("#cDesc").value.trim(),
      clientId: Number(m.root.querySelector("#cClientSel").value) || null,
      cadenceFocus: m.root.querySelector("#cFocusSel").value,
      priority: m.root.querySelector("#cPrioSel").value,
      executing: m.root.querySelector("#cExec").value === "true",
      userIds: [...m.root.querySelector("#cUsers").selectedOptions].map((o) => Number(o.value)),
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (c.id) await api(`/api/flow/cadences/${c.id}`, { method: "PATCH", body });
    else await api("/api/flow/cadences", { method: "POST", body });
    m.close(); toast("Cadência salva.", "ok"); go("cadencias");
  };
}

/* ── Atividades ──────────────────────────────────────────────────────── */
PAGES.atividades = {
  area: "Prospecção", title: "Atividades",
  async render() {
    const f = state.actFilter || {};
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const list = await api(`/api/flow/activities?${qs}`);
    const rows = list.map((a) => ({ cells: [
      `<strong>${h(a.name)}</strong>`,
      `<span class="pill ${a.type === "CALL" ? "blue" : a.type === "E_MAIL" ? "grey" : "green"}">
        ${h(TYPE_LABEL[a.type] || a.type)}${a.socialNetwork ? ` · ${h(a.socialNetwork)}` : ""}</span>`,
      a.emailTemplate ? h(a.emailTemplate.subject) : h((a.instruction || "").slice(0, 110) || "—"),
      `<button class="btn btn-default btn-xs" data-edit-act="${a.id}">Editar</button>
       <button class="btn btn-default btn-xs" data-del-act="${a.id}">Excluir</button>`,
    ] }));

    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="aq" placeholder="Buscar atividade" value="${h(f.q || "")}">
        <select class="form-control" id="aType">
          <option value="">Todos os tipos</option>
          ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}"${f.type === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="newAct">Nova atividade</button>
      </div>
      ${panel(`${list.length} atividades`, table(["Atividade", "Tipo", "Script / assunto", ""], rows, { scroll: true }),
        { subtitle: "Biblioteca reutilizável. Merge tags aceitas: {{firstName}}, {{company}}" })}`;

    const set = (k, v) => { state.actFilter = { ...f, [k]: v }; go("atividades"); };
    const q = document.getElementById("aq");
    let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => set("q", q.value), 350); };
    document.getElementById("aType").onchange = (e) => set("type", e.target.value);
    document.getElementById("newAct").onclick = () => openActivityForm();
    view.querySelectorAll("[data-edit-act]").forEach((b) => {
      b.onclick = () => openActivityForm(list.find((a) => String(a.id) === b.dataset.editAct));
    });
    view.querySelectorAll("[data-del-act]").forEach((b) => {
      b.onclick = () => confirmDialog("Excluir atividade", "Confirma a exclusão?", async () => {
        try { await api(`/api/flow/activities/${b.dataset.delAct}`, { method: "DELETE" }); toast("Excluída."); go("atividades"); }
        catch (e) { toast(e.message, "err"); }
      });
    });
  },
};

function openActivityForm(act) {
  const a = act || {};
  const tpl = a.emailTemplate || {};
  const m = modal({
    title: a.id ? "Editar atividade" : "Nova atividade",
    body: `
      <div class="field"><label>Nome *</label><input class="form-control" id="aName" value="${h(a.name || "")}"></div>
      <div class="field-row">
        <div class="field"><label>Tipo</label>
          <select class="form-control" id="aTypeSel">
            ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}"${a.type === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
        <div class="field"><label>Rede (ponto social)</label>
          <select class="form-control" id="aSocial">
            <option value="">—</option>
            <option value="WHATSAPP"${a.socialNetwork === "WHATSAPP" ? " selected" : ""}>WhatsApp</option>
            <option value="LINKEDIN"${a.socialNetwork === "LINKEDIN" ? " selected" : ""}>LinkedIn</option>
          </select></div>
      </div>
      <div class="field"><label>Instrução / script</label>
        <textarea class="form-control" id="aInstr">${h(a.instruction || "")}</textarea></div>
      <div class="field"><label>Assunto do e-mail</label>
        <input class="form-control" id="aSubject" value="${h(tpl.subject || "")}"></div>
      <div class="field"><label>Corpo do e-mail (HTML)</label>
        <textarea class="form-control" id="aHtml">${h(tpl.html || "")}</textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async () => {
    const body = {
      name: m.root.querySelector("#aName").value.trim(),
      type: m.root.querySelector("#aTypeSel").value,
      socialNetwork: m.root.querySelector("#aSocial").value,
      instruction: m.root.querySelector("#aInstr").value,
      emailTemplate: { subject: m.root.querySelector("#aSubject").value,
                       html: m.root.querySelector("#aHtml").value },
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (a.id) await api(`/api/flow/activities/${a.id}`, { method: "PATCH", body });
    else await api("/api/flow/activities", { method: "POST", body });
    m.close(); toast("Atividade salva.", "ok"); go("atividades");
  };
}

/* ── Bases de leads ──────────────────────────────────────────────────── */
PAGES.bases = {
  area: "Prospecção", title: "Bases de leads",
  async render() {
    const res = await api("/api/flow/lead-bases");
    const rows = res.data.map((b) => ({ cells: [
      `<strong>${h(b.name)}</strong>`,
      `<span class="pill ${b.source === "CAPIBLU" ? "green" : "grey"}">${h(b.source)}</span>`,
      b.client ? h(b.client.name) : "—",
      b.numberOfLeads, b.discardedLeads,
      `<span class="pill ${b.status === "COMPLETED" ? "green" : b.status === "FAILED" ? "red" : "amber"}">${h(b.status)}</span>`,
      b.createdBy ? h(b.createdBy.name) : "—",
      fmtDate(b.created),
      `<button class="btn btn-default btn-xs" data-leads-base="${b.id}">Ver leads</button>
       ${b.sourceQuery ? `<button class="btn btn-default btn-xs" data-query="${b.id}">Ver consulta</button>` : ""}`,
    ] }));

    view.innerHTML = `
      <div class="toolbar">
        <span class="text-muted">${res.data.length} bases</span>
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="importCsv">Importar CSV</button>
        <button class="btn btn-main btn-xs" data-page="capiblu-empresas">Montar no CapiBLU</button>
      </div>
      ${panel("Bases de leads",
        table(["Base", "Origem", "Cliente", "Leads", "Descartados", "Situação", "Criada por", "Data", ""], rows, { scroll: true }),
        { subtitle: "Base vinda do CapiBLU guarda a consulta que a gerou — dá para reexecutar" })}`;

    document.getElementById("importCsv").onclick = openImportWizard;
    view.querySelectorAll("[data-leads-base]").forEach((b) => {
      b.onclick = () => { state.leadFilter = { lead_base_id: b.dataset.leadsBase, page: 1 }; go("leads"); };
    });
    view.querySelectorAll("[data-query]").forEach((b) => {
      b.onclick = () => {
        const base = res.data.find((x) => String(x.id) === b.dataset.query);
        modal({ title: `Consulta de ${base.name}`,
          body: `<div class="json-box">${h(JSON.stringify(JSON.parse(base.sourceQuery), null, 2))}</div>` });
      };
    });
  },
};

function openImportWizard() {
  const m = modal({
    title: "Importar base de leads", wide: true,
    body: `<div class="wizard-steps"><span class="active" data-s="1">1. Arquivo</span>
      <span data-s="2">2. Campos</span><span data-s="3">3. Execução</span></div>
      <div id="wizBody">
        <div class="field"><label>Arquivo CSV</label>
          <input class="form-control" type="file" id="wizFile" accept=".csv,.txt"></div>
        <div class="text-muted text-size-small">A primeira linha precisa conter os nomes das colunas.</div>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-next>Continuar</button>`,
  });
  const body = m.root.querySelector("#wizBody");
  const next = m.root.querySelector("[data-next]");
  let preview = null;
  m.root.querySelector("[data-cancel]").onclick = m.close;

  const step = (n) => m.root.querySelectorAll("[data-s]").forEach((s) =>
    s.classList.toggle("active", Number(s.dataset.s) === n));

  next.onclick = async () => {
    if (!preview) {
      const file = m.root.querySelector("#wizFile").files[0];
      if (!file) return toast("Escolha um arquivo.", "err");
      const fd = new FormData();
      fd.append("file", file);
      next.disabled = true;
      try {
        const res = await fetch("/api/flow/lead-bases/preview", { method: "POST", body: fd, credentials: "same-origin" });
        preview = await res.json();
        if (!res.ok) throw new Error(preview.detail || "Falha ao ler o arquivo.");
      } catch (e) { next.disabled = false; return toast(e.message, "err"); }
      next.disabled = false;
      step(2);
      const fields = [["name", "Nome completo *"], ["firstName", "Primeiro nome"], ["email", "E-mail"],
        ["company", "Empresa"], ["position", "Cargo"], ["phone", "Telefone"], ["cnpj", "CNPJ"],
        ["city", "Cidade"], ["state", "UF"], ["site", "Site"], ["annotations", "Anotações"]];
      const guess = (label) => preview.columns.find((c) =>
        c.toLowerCase().replace(/[^a-z]/g, "").includes(label.toLowerCase().slice(0, 4))) || "";
      body.innerHTML = `<div class="alert alert-info alert-styled-left">
          ${preview.columns.length} colunas · ${preview.sample.length} linhas na amostra</div>
        ${fields.map(([key, label]) => `<div class="field-row" style="align-items:center">
          <label style="font-size:12px;color:#777">${label}</label>
          <select class="form-control" data-map="${key}">
            <option value="">— ignorar —</option>
            ${preview.columns.map((c) => `<option value="${h(c)}"${c === guess(key) ? " selected" : ""}>${h(c)}</option>`).join("")}
          </select></div>`).join("")}`;
      next.textContent = "Continuar";
      return;
    }
    if (!m.root.querySelector("#wizName")) {
      const mapping = {};
      body.querySelectorAll("[data-map]").forEach((s) => { if (s.value) mapping[s.dataset.map] = s.value; });
      if (!mapping.name) return toast("Mapeie a coluna do nome.", "err");
      preview.mapping = mapping;
      step(3);
      body.innerHTML = `
        <div class="field"><label>Nome da base *</label>
          <input class="form-control" id="wizName" value="[Importação] - ${new Date().toLocaleDateString("pt-BR")}"></div>
        <div class="field-row">
          <div class="field"><label>Cliente</label>
            <select class="form-control" id="wizClient">${options(state.clients, "", { blank: "—" })}</select></div>
          <div class="field"><label>SDR</label>
            <select class="form-control" id="wizSdr">${options(state.users, "", { blank: "—" })}</select></div>
        </div>
        <div class="field"><label>Colocar em cadência</label>
          <select class="form-control" id="wizCad">${options(state.cadences.filter((c) => c.executing), "", { blank: "Não iniciar agora" })}</select></div>`;
      next.textContent = "Importar";
      return;
    }
    next.disabled = true;
    next.innerHTML = `<span class="spinner"></span> importando…`;
    try {
      const res = await api("/api/flow/lead-bases/import", { method: "POST", body: {
        name: m.root.querySelector("#wizName").value.trim(),
        content: preview.content, delimiter: preview.delimiter, mapping: preview.mapping,
        clientId: Number(m.root.querySelector("#wizClient").value) || null,
        sdrId: Number(m.root.querySelector("#wizSdr").value) || null,
        cadenceId: Number(m.root.querySelector("#wizCad").value) || null,
        createdById: state.me.id,
      } });
      m.close();
      toast(`${res.imported} leads importados (${res.discarded} descartados).`, "ok");
      go("bases");
    } catch (e) { toast(e.message, "err"); next.disabled = false; next.textContent = "Importar"; }
  };
}

/* ── Clientes ────────────────────────────────────────────────────────── */
PAGES.clientes = {
  area: "Prospecção", title: "Clientes",
  async render() {
    const list = await api("/api/clients");
    state.clients = list;
    const rows = list.map((c) => ({ cells: [
      `<span class="dot" style="background:${h(c.color)}"></span><strong>${h(c.name)}</strong>`,
      c.cadences, c.leads,
      `<span style="color:#00a443">${c.won}</span>`,
      `<span style="color:#f44336">${c.lost}</span>`,
      c.won + c.lost ? `${Math.round((c.won / (c.won + c.lost)) * 100)}%` : "—",
      c.active ? `<span class="pill green">Ativo</span>` : `<span class="pill grey">Inativo</span>`,
      `<button class="btn btn-default btn-xs" data-edit-client="${c.id}">Editar</button>
       <button class="btn btn-default btn-xs" data-leads-client="${c.id}">Ver leads</button>`,
    ] }));

    view.innerHTML = `
      <div class="toolbar">
        <span class="text-muted">${list.length} clientes</span>
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="newClient">Novo cliente</button>
      </div>
      <div class="alert alert-info alert-styled-left">
        Esta é a entidade que o Meetime não tem. Lá o cliente vira prefixo no nome da cadência
        (<code>[BLU]</code>, <code>[FROTAÍ]</code>); aqui cadência, lead, base e meta penduram num cliente de verdade.
      </div>
      ${panel("Clientes atendidos",
        table(["Cliente", "Cadências", "Leads", "Ganhos", "Perdidos", "Conversão", "Situação", ""], rows))}`;

    document.getElementById("newClient").onclick = () => openClientForm();
    view.querySelectorAll("[data-edit-client]").forEach((b) => {
      b.onclick = () => openClientForm(list.find((c) => String(c.id) === b.dataset.editClient));
    });
    view.querySelectorAll("[data-leads-client]").forEach((b) => {
      b.onclick = () => { state.leadFilter = { client_id: b.dataset.leadsClient, page: 1 }; go("leads"); };
    });
  },
};

function openClientForm(client) {
  const c = client || {};
  const m = modal({
    title: c.id ? `Editar ${c.name}` : "Novo cliente",
    body: `<div class="field"><label>Nome *</label><input class="form-control" id="clName" value="${h(c.name || "")}"></div>
      <div class="field-row">
        <div class="field"><label>Cor</label><input class="form-control" type="color" id="clColor" value="${h(c.color || "#00a443")}"></div>
        <div class="field"><label>Situação</label>
          <select class="form-control" id="clActive">
            <option value="true"${c.active !== false ? " selected" : ""}>Ativo</option>
            <option value="false"${c.active === false ? " selected" : ""}>Inativo</option>
          </select></div>
      </div>`,
    footer: `${c.id ? `<button class="btn btn-danger btn-sm" data-del>Excluir</button><span style="flex:1"></span>` : ""}
             <button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const del = m.root.querySelector("[data-del]");
  if (del) del.onclick = () => confirmDialog("Excluir cliente", `Excluir "${c.name}"?`, async () => {
    await api(`/api/clients/${c.id}`, { method: "DELETE" }); toast("Cliente excluído."); go("clientes");
  });
  m.root.querySelector("[data-save]").onclick = async () => {
    const body = { name: m.root.querySelector("#clName").value.trim(),
                   color: m.root.querySelector("#clColor").value,
                   active: m.root.querySelector("#clActive").value === "true" };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (c.id) await api(`/api/clients/${c.id}`, { method: "PATCH", body });
    else await api("/api/clients", { method: "POST", body });
    m.close(); toast("Cliente salvo.", "ok"); go("clientes");
  };
}

/* ── Ligações ────────────────────────────────────────────────────────── */
PAGES.ligacoes = {
  area: "Ligações", title: "Painel de Ligações",
  async render() {
    const o = (await api("/api/dialer/calls/statistics/overview")).data[0];
    const best = o.bestHourToCall;
    view.innerHTML = `
      ${kpis([
        { value: o.totalCalls, label: "Ligações no período" },
        { value: o.totalConnected, label: "Conectadas", tone: "success" },
        { value: `${o.meaningfulRate}%`, label: "Significativas", tone: "info" },
        { value: fmtDuration(o.averageDuration), label: "Duração média", tone: "warning" },
      ])}
      <div class="two-col mt-10">
        ${panel("Conexão por hora do dia",
          bars(o.byHour.map((r) => ({ label: `${r.hour}h`, value: r.connected,
            tone: best && r.hour === best.bestStartHour ? "success" : "info" }))),
          { subtitle: best ? `Melhor janela: ${best.bestStartHour}h–${best.bestEndHour}h, ${best.connectedPercentage}% de conexão` : "" })}
        ${panel("Resultado das conectadas",
          bars((o.statuses.find((s) => s.status === "CONNECTED") || { outputs: [] }).outputs.map((x) => ({
            label: { MEANINGFUL: "Significativa", NOT_MEANINGFUL: "Não significativa", NO_CONTACT: "Sem contato" }[x.output] || x.output,
            value: x.count,
            tone: x.output === "MEANINGFUL" ? "success" : x.output === "NO_CONTACT" ? "warning" : "info",
          }))))}
      </div>
      ${panel("Distribuição", `<div class="stat-line">
        <span><b>${o.totalMobile}</b>Celular</span>
        <span><b>${o.totalLandline}</b>Fixo</span>
        <span><b>${fmtDuration(o.totalDurationInSeconds)}</b>Tempo total</span>
        <span><b>${o.averageDailyCallsPerRep}</b>Ligações/SDR/dia</span>
      </div>`)}`;
  },
};

PAGES["lista-ligacoes"] = {
  area: "Ligações", title: "Lista de Ligações",
  async render() {
    const f = state.callFilter || { page: 1 };
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const res = await api(`/api/dialer/calls?${qs}`);
    const OUT = { MEANINGFUL: ["Significativa", "green"], NOT_MEANINGFUL: ["Não significativa", "blue"],
                  NO_CONTACT: ["Sem contato", "amber"] };
    const rows = res.data.map((c) => {
      const [label, tone] = c.status === "CONNECTED" ? (OUT[c.output] || ["Conectada", "grey"]) : ["Não conectada", "red"];
      return { cells: [
        `<span class="pill ${tone}">${label}</span>`,
        c.user ? h(c.user.name) : "—",
        `${h(c.flowLeadName || "—")}<br><span class="text-muted text-size-small">${h(c.flowLeadCompany || "")}</span>`,
        h(c.receiverPhone), fmtDateTime(c.originStarted), fmtDuration(c.receiverConnectedDuration),
        c.receiverType === "MOBILE" ? "Celular" : "Fixo",
      ] };
    });
    view.innerHTML = `
      <div class="toolbar">
        <select class="form-control" id="cfUser">${options(state.users, f.user_id, { blank: "Todos os usuários" })}</select>
        <select class="form-control" id="cfOut">
          <option value="">Todos os resultados</option>
          ${Object.entries(OUT).map(([k, v]) => `<option value="${k}"${f.output === k ? " selected" : ""}>${v[0]}</option>`).join("")}
        </select>
        <span class="spacer"></span>
        <a class="btn btn-default btn-xs" href="/api/reports/dropped-calls">Baixar derrubadas</a>
      </div>
      ${panel(`${res.pagination.totalRowCount} ligações`,
        table(["Situação", "Usuário", "Lead", "Destino", "Data", "Duração", "Tipo"], rows, { scroll: true }),
        { actions: pager(res.pagination) })}`;
    const set = (k, v) => { state.callFilter = { ...f, [k]: v, page: 1 }; go("lista-ligacoes"); };
    document.getElementById("cfUser").onchange = (e) => set("user_id", e.target.value);
    document.getElementById("cfOut").onchange = (e) => set("output", e.target.value);
    view.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => { state.callFilter = { ...f, page: Number(b.dataset.gotoPage) }; go("lista-ligacoes"); };
    });
  },
};

PAGES.extrato = {
  area: "Ligações", title: "Extrato",
  async render() {
    const res = await api("/api/dialer/calls/statements");
    const rows = res.data.map((r) => ({ cells: [
      r.user ? h(r.user.name) : "—", r.calls, r.minutes, fmtMoney(r.cost)] }));
    view.innerHTML = `
      ${kpis([
        { value: res.meta.totalMinutes, label: "Minutos no período" },
        { value: fmtMoney(res.meta.totalCost), label: "Custo estimado", tone: "warning" },
        { value: fmtMoney(res.meta.pricePerMinute), label: "Preço por minuto" },
        { value: res.data.length, label: "Usuários com consumo", tone: "info" },
      ])}
      ${panel("Consumo por usuário", table(["Usuário", "Ligações", "Minutos", "Custo"], rows))}`;
  },
};

/* ── WhatsApp ────────────────────────────────────────────────────────── */
PAGES.whatsapp = {
  area: "WhatsApp", title: "Conversas",
  async render() {
    const list = await api("/api/whatsapp/conversations");
    const activeId = state.waActive || (list[0] && list[0].id);
    const rows = list.map((c) => `<div class="wa-row${c.id === activeId ? " active" : ""}" data-conv="${c.id}">
      <strong>${h(c.title)}</strong><br>
      <span class="text-muted text-size-small">${h(c.preview || "—")}</span><br>
      <span class="text-muted text-size-small">${fmtDateTime(c.lastMessageAt)}</span></div>`).join("")
      || emptyState("Nenhuma conversa por aqui ainda");

    let thread = `<div class="whatsapp-empty" style="padding:60px">Selecione um contato para visualizar a conversa</div>`;
    if (activeId) {
      const c = await api(`/api/whatsapp/conversations/${activeId}`);
      thread = `
        <div class="panel-heading has-border"><h2 class="panel-title">${h(c.title)}</h2>
          <div class="heading-elements"><span class="text-muted text-size-small">${h(c.phone)}</span></div></div>
        <div class="wa-thread">${c.messages.map((msg) => `
          <div class="bubble ${msg.direction === "OUT" ? "out" : "in"}">${h(msg.body)}
            <time>${fmtDateTime(msg.sentAt)}</time></div>`).join("")
          || `<div class="text-muted" style="text-align:center">Sem mensagens.</div>`}</div>
        <div style="display:flex;gap:8px;padding:14px">
          <input class="form-control" id="waInput" placeholder="Escreva uma mensagem">
          <button class="btn btn-main btn-sm" id="waSend">Enviar</button>
        </div>`;
    }

    view.innerHTML = `<div class="split">
      ${panel("Conversas", `<div class="wa-list">${rows}</div>`)}
      <div class="panel panel-flat">${thread}</div>
    </div>`;

    view.querySelectorAll("[data-conv]").forEach((r) => {
      r.onclick = () => { state.waActive = Number(r.dataset.conv); go("whatsapp"); };
    });
    const send = document.getElementById("waSend");
    if (send) {
      const input = document.getElementById("waInput");
      const submit = async () => {
        const body = input.value.trim();
        if (!body) return;
        await api(`/api/whatsapp/conversations/${activeId}/messages`, { method: "POST", body: { body } });
        go("whatsapp");
      };
      send.onclick = submit;
      input.onkeydown = (e) => { if (e.key === "Enter") submit(); };
    }
  },
};

/* ── Estatísticas e relatórios ───────────────────────────────────────── */
PAGES.estatisticas = {
  area: "Estatísticas", title: "Prospecção",
  async render() {
    const clientId = state.statClient || "";
    const s = await api(`/api/flow/statistics/summary${clientId ? `?client_id=${clientId}` : ""}`);
    const cadRows = s.cadences.map((c) => ({ cells: [
      h(c.name), c.client ? h(c.client.name) : "—",
      `<span class="pill">${h(PRIORITY_LABEL[c.priority])}</span>`,
      c.total, c.won, `${c.conversion}%`] }));

    view.innerHTML = `
      <div class="toolbar">
        <select class="form-control" id="sClient">${options(state.clients, clientId, { blank: "Todos os clientes" })}</select>
        <span class="spacer text-muted text-size-small">Últimos 30 dias</span>
      </div>
      ${kpis([
        { value: s.activities.total, label: "Atividades realizadas" },
        { value: `${s.activities.latePercent}%`, label: "Fora do prazo", tone: "danger" },
        { value: s.outcomes.won, label: "Oportunidades", tone: "success" },
        { value: `${s.outcomes.conversion}%`, label: "Conversão", tone: "info" },
      ])}
      <div class="two-col mt-10">
        ${panel("Atividades por tipo", bars(s.activities.byType.map((t) => ({
          label: TYPE_LABEL[t.type] || t.type, value: t.count,
          tone: t.type === "CALL" ? "warning" : t.type === "E_MAIL" ? "info" : "success" }))))}
        ${panel("Funil de leads", bars(s.funnel.map((f) => ({
          label: (STATUS_LABEL[f.status] || [f.status])[0], value: f.count,
          tone: f.status === "WON" ? "success" : f.status === "LOST" ? "warning" : "info" }))))}
      </div>
      <div class="two-col">
        ${panel("Motivos de perda", bars(s.lostReasons.slice(0, 8).map((r) => ({ label: r.name, value: r.count, tone: "warning" }))))}
        ${panel("Origem dos leads", bars(s.origins.slice(0, 8).map((o) => ({ label: o.name, value: o.total }))))}
      </div>
      ${panel("Conversão por cadência",
        table(["Cadência", "Cliente", "Prioridade", "Leads", "Ganhos", "Conversão"], cadRows))}`;

    document.getElementById("sClient").onchange = (e) => { state.statClient = e.target.value; go("estatisticas"); };
  },
};

PAGES.relatorios = {
  area: "Estatísticas", title: "Relatórios",
  async render() {
    const list = await api("/api/reports");
    const rows = list.map((r) => ({ cells: [
      `<strong>${h(r.name)}</strong>`, h(r.description),
      `<a class="btn btn-default btn-xs" href="/api/reports/${h(r.key)}">Baixar CSV</a>`] }));
    view.innerHTML = panel("Relatórios", table(["Relatório", "Para que serve", ""], rows),
      { subtitle: "Download imediato em CSV (separador ponto-e-vírgula, compatível com Excel pt-BR)" });
  },
};

/* ── CapiBLU ─────────────────────────────────────────────────────────── */
PAGES["capiblu-ferramentas"] = {
  area: "CapiBLU", title: "Todas as ferramentas",
  async render() {
    const s = await api("/api/capiblu/status");
    const byArea = {};
    s.tools.forEach((t) => { (byArea[t.area] = byArea[t.area] || []).push(t); });
    view.innerHTML = `
      ${s.available
        ? `<div class="alert alert-success alert-styled-left">Serviço de dados do CapiBLU carregado em processo — as consultas rodam direto na base local.</div>`
        : `<div class="alert alert-info alert-styled-left">CapiBLU indisponível: ${h(s.error || "")}. As telas de consulta ficam sem dados até o serviço subir.</div>`}
      ${Object.entries(byArea).map(([area, tools]) => panel(area,
        `<div class="tool-grid">${tools.map((t) => `<div class="tool-card">
          <h4>${h(t.name)}</h4>
          <div class="what">${h(t.what)}</div>
          <div class="mt-10"><span class="pill ${t.cost.startsWith("grátis") ? "green" : "amber"}">${h(t.cost)}</span></div>
          <div class="mt-10"><code>${h(t.path)}</code></div>
        </div>`).join("")}</div>`)).join("")}`;
  },
};

const UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT","PA","PB",
             "PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"];
const PORTES = [["", "Todos"], ["00", "Não informado"], ["01", "Micro"], ["03", "Pequeno"],
                ["01,03", "Micro e pequeno"], ["05", "Médio e grande"]];
const SITUACOES = [["ATIVA", "Ativa"], ["BAIXADA", "Baixada"], ["INAPTA", "Inapta"],
                   ["SUSPENSA", "Suspensa"], ["NULA", "Nula"], ["", "Todas"]];
const lookupCache = {};

async function lookup(tipo) {
  if (!lookupCache[tipo]) {
    const r = await api(`/api/capiblu/lookups/${tipo}`);
    lookupCache[tipo] = r.itens || [];
  }
  return lookupCache[tipo];
}

const multi = (id, items, { size = 4, label = (i) => `${i.codigo} — ${i.descricao}` } = {}) =>
  `<select class="form-control" id="${id}" multiple size="${size}">
    ${items.map((i) => `<option value="${h(i.codigo ?? i)}">${h(typeof i === "string" ? i : label(i))}</option>`).join("")}
  </select>`;

const picked = (id) => [...(document.getElementById(id)?.selectedOptions || [])].map((o) => o.value);

PAGES["capiblu-empresas"] = {
  area: "CapiBLU", title: "Prospecção B2B",
  async render() {
    const f = state.b2bFilters || { situacao: ["ATIVA"], com_telefone: true };
    const [cnaes, naturezas, municipios] = await Promise.all([
      lookup("cnae"), lookup("natureza"), lookup("municipio")]);
    state.municipios = municipios;

    const perfil = state.b2bPerfil || "empresas";
    view.innerHTML = `
      <ul class="nav nav-tabs">
        <li${perfil === "empresas" ? ' class="active"' : ""}><a data-perfil="empresas">Empresas</a></li>
        <li${perfil === "socios" ? ' class="active"' : ""}><a data-perfil="socios">Sócios e pessoas</a></li>
      </ul>
      <div class="panel panel-flat" style="border-top:0">
        <div class="panel-heading has-border">
          <h2 class="panel-title">Filtros</h2>
          <div class="heading-elements">
            <span class="text-muted text-size-small">Base local da Receita Federal · não gasta consulta</span>
          </div>
        </div>
        <div class="panel-body">${perfil === "empresas"
          ? empresaFilters(f, { cnaes, naturezas, municipios })
          : socioFilters(state.socioFilters || {})}</div>
      </div>
      <div id="b2bOut">${emptyState("Defina os filtros e busque.")}</div>`;

    view.querySelectorAll("[data-perfil]").forEach((a) => {
      a.onclick = () => { state.b2bPerfil = a.dataset.perfil; go("capiblu-empresas"); };
    });

    if (perfil === "empresas") {
      const ufSel = document.getElementById("fUf");
      const munSel = document.getElementById("fMun");
      const refreshMun = () => {
        const ufs = picked("fUf");
        const list = ufs.length ? municipios.filter((m) => ufs.includes(m.uf)) : municipios;
        munSel.innerHTML = list.slice(0, 4000)
          .map((m) => `<option value="${h(m.codigo)}">${h(m.descricao)}${ufs.length > 1 ? ` (${h(m.uf)})` : ""}</option>`).join("");
      };
      ufSel.onchange = refreshMun;
      refreshMun();
      document.getElementById("doSearch").onclick = () => runB2B(0);
      document.getElementById("doCobertura").onclick = testarCobertura;
    } else {
      document.getElementById("doSocios").onclick = () => runSocios(0);
    }
  },
};

function empresaFilters(f, { cnaes, naturezas }) {
  return `
    <div class="filter-row" style="grid-template-columns:repeat(4,1fr)">
      <div><label class="text-muted text-size-small">UF <span class="text-grey">(múltipla)</span></label>
        ${multi("fUf", UFS, { size: 5 })}</div>
      <div><label class="text-muted text-size-small">Município</label>
        <select class="form-control" id="fMun" multiple size="5"></select></div>
      <div><label class="text-muted text-size-small">CNAE <span class="text-grey">(múltiplo)</span></label>
        ${multi("fCnae", cnaes, { size: 5 })}</div>
      <div><label class="text-muted text-size-small">Natureza jurídica</label>
        ${multi("fNatureza", naturezas, { size: 5 })}</div>
    </div>
    <div class="filter-row mt-10" style="grid-template-columns:repeat(4,1fr)">
      <div><label class="text-muted text-size-small">CNPJ exato <span class="text-grey">(ignora o resto)</span></label>
        <input class="form-control" id="fCnpj" placeholder="06990590000123"></div>
      <div><label class="text-muted text-size-small">Texto livre</label>
        <input class="form-control" id="fTexto" value="${h(f.texto || "")}"></div>
      <div><label class="text-muted text-size-small">Onde procurar o texto</label>
        <select class="form-control" id="fEscopo" multiple size="4">
          <option value="razao" selected>Razão social</option>
          <option value="fantasia" selected>Nome fantasia</option>
          <option value="cnae">Descrição do CNAE</option>
          <option value="natureza">Natureza jurídica</option>
        </select></div>
      <div><label class="text-muted text-size-small">Setor <span class="text-grey">(por descrição de CNAE)</span></label>
        <input class="form-control" id="fSetor" placeholder="transporte rodoviário"></div>
    </div>
    <div class="filter-row mt-10" style="grid-template-columns:repeat(5,1fr)">
      <div><label class="text-muted text-size-small">Porte</label>
        <select class="form-control" id="fPorte">
          ${PORTES.map(([v, t]) => `<option value="${v}"${f.porte === v ? " selected" : ""}>${t}</option>`).join("")}
        </select></div>
      <div><label class="text-muted text-size-small">Situação cadastral</label>
        <select class="form-control" id="fSituacao">
          ${SITUACOES.map(([v, t]) => `<option value="${v}"${(f.situacao || ["ATIVA"])[0] === v ? " selected" : ""}>${t}</option>`).join("")}
        </select></div>
      <div><label class="text-muted text-size-small">Capital mínimo</label>
        <input class="form-control" type="number" id="fCapMin" value="${h(f.capital_min || "")}"></div>
      <div><label class="text-muted text-size-small">Capital máximo</label>
        <input class="form-control" type="number" id="fCapMax" value="${h(f.capital_max || "")}"></div>
      <div><label class="text-muted text-size-small">Tipo de empresa</label>
        <select class="form-control" id="fTipo">
          <option value="">Todas</option>
          <option value="privada">Privada</option>
          <option value="publica">Pública</option>
        </select></div>
    </div>
    <div class="filter-row mt-10" style="grid-template-columns:repeat(5,1fr)">
      <div><label class="text-muted text-size-small">Fundada de</label>
        <input class="form-control" type="date" id="fFundDe"></div>
      <div><label class="text-muted text-size-small">Fundada até</label>
        <input class="form-control" type="date" id="fFundAte"></div>
      <div><label class="text-muted text-size-small">MEI</label>
        <select class="form-control" id="fMei">
          <option value="">Tanto faz</option>
          <option value="optante">Somente MEI</option>
          <option value="excluir">Excluir MEI</option>
        </select></div>
      <div><label class="text-muted text-size-small">Estabelecimento</label>
        <select class="form-control" id="fEstab">
          <option value="">Matriz e filial</option>
          <option value="matriz">Somente matriz</option>
          <option value="filial">Somente filial</option>
        </select></div>
      <div><label class="text-muted text-size-small">Por página</label>
        <select class="form-control" id="fLimite">
          ${[20, 50, 100, 200].map((n) => `<option value="${n}"${n === 50 ? " selected" : ""}>${n}</option>`).join("")}
        </select></div>
    </div>
    <div class="toolbar mt-10" style="border:0;padding:0;background:none">
      <label><input type="checkbox" id="fTel"${f.com_telefone !== false ? " checked" : ""}> Só com telefone</label>
      <label><input type="checkbox" id="fMail"> Só com e-mail</label>
      <span class="spacer"></span>
      <button class="btn btn-default" id="doCobertura">Testar cobertura de decisores</button>
      <button class="btn btn-main" id="doSearch">Buscar empresas</button>
    </div>`;
}

function collectEmpresaFilters() {
  const g = (id) => (document.getElementById(id)?.value || "").trim();
  const mei = g("fMei"), estab = g("fEstab"), tipo = g("fTipo"), sit = g("fSituacao");
  const filtros = {
    cnpj: g("fCnpj").replace(/\D/g, ""),
    texto: g("fTexto"), setor: g("fSetor"),
    texto_escopo: picked("fEscopo"),
    uf: picked("fUf"), municipio: picked("fMun"),
    cnae: picked("fCnae"), natureza: picked("fNatureza"),
    porte: g("fPorte") ? g("fPorte").split(",") : [],
    situacao: sit ? [sit] : [],
    capital_min: Number(g("fCapMin")) || 0,
    capital_max: Number(g("fCapMax")) || 0,
    fundada_de: g("fFundDe"), fundada_ate: g("fFundAte"),
    tipo_empresa: tipo,
    mei_optante: mei === "optante",
    mei_excluir: mei === "excluir",
    somente_matriz: estab === "matriz",
    somente_filial: estab === "filial",
    com_telefone: document.getElementById("fTel").checked,
    com_email: document.getElementById("fMail").checked,
  };
  Object.keys(filtros).forEach((k) => {
    const v = filtros[k];
    if (v === "" || v === 0 || v === false || (Array.isArray(v) && !v.length)) delete filtros[k];
  });
  return filtros;
}

async function runB2B(offset) {
  const filtros = collectEmpresaFilters();
  const limite = Number(document.getElementById("fLimite").value) || 50;
  state.b2bFilters = filtros;
  const out = document.getElementById("b2bOut");
  out.innerHTML = LOADING;
  try {
    const res = await api("/api/capiblu/prospect/preview",
      { method: "POST", body: { filtros, limite, offset } });
    state.b2bResult = res;
    renderB2B(res);
  } catch (e) {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

async function testarCobertura() {
  const res = state.b2bResult;
  if (!res || !res.empresas.length) return toast("Busque as empresas primeiro.", "err");
  const cnpjs = res.empresas.map((e) => (e.cnpj || "").replace(/\D/g, "")).filter(Boolean).slice(0, 60);
  const out = document.getElementById("b2bOut");
  const prev = out.innerHTML;
  out.innerHTML = `<div class="alert alert-info alert-styled-left"><span class="spinner"></span>
    Medindo cobertura em ${cnpjs.length} CNPJs — 2 consultas por empresa, sem puxar telefone.</div>` + prev;
  try {
    const r = await api("/api/capiblu/prospect/cobertura", { method: "POST", body: { cnpjs } });
    modal({ title: "Cobertura de decisores", wide: true,
      body: `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>` });
    out.innerHTML = prev;
  } catch (e) { out.innerHTML = prev; toast(e.message, "err"); }
}

function renderB2B(res) {
  const empresas = res.empresas || [];
  const money = (v) => v ? Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 }) : "—";
  // Busca por texto usa o índice FTS, que não guarda telefone — nesses casos a
  // coluna vem vazia mesmo quando a empresa tem número.
  const fone = (e) => [e.telefone_1, e.telefone_2].filter(Boolean).join(" / ") || "—";
  const rows = empresas.map((e) => ({ cells: [
    `<input type="checkbox" class="emp-check" value="${h(e.cnpj || "")}" checked>`,
    `<strong>${h(e.razao_social || e.nome_fantasia || "—")}</strong>
     ${e.nome_fantasia && e.razao_social ? `<br><span class="text-muted text-size-small">${h(e.nome_fantasia)}</span>` : ""}`,
    h(e.cnpj || "—"),
    `${h(e.municipio || "")}${e.uf ? `/${h(e.uf)}` : ""}`,
    h(e.cnae || e.cnae_codigo || "—"),
    h(e.porte || "—"),
    `<span class="pill ${e.situacao === "ATIVA" ? "green" : "grey"}">${h(e.situacao || "—")}</span>`,
    money(e.capital_social),
    h(fone(e)),
    h(e.email || "—"),
  ] }));

  const page = Math.floor((res.offset || 0) / (res.limite || 50)) + 1;
  const hasMore = empresas.length >= (res.limite || 50);

  document.getElementById("b2bOut").innerHTML = `
    <div class="toolbar">
      <span class="text-muted">
        <strong>${res.total ?? empresas.length}${res.totalAprox ? "+" : ""}</strong> empresas encontradas ·
        mostrando ${empresas.length} · fonte ${h(res.fonte || "local")}
      </span>
      <span class="spacer"></span>
      <button class="btn btn-default btn-xs" id="selNone">Limpar seleção</button>
      <button class="btn btn-default btn-xs" id="dedupBtn">Checar duplicados</button>
      <button class="btn btn-default btn-xs" id="xlsxBtn">Baixar XLSX</button>
      <button class="btn btn-main btn-xs" id="toBase">Montar base de leads</button>
    </div>
    <div id="dedupOut"></div>
    ${panel("Resultado",
      table([`<input type="checkbox" id="empAll" checked>`, "Razão social", "CNPJ", "Município",
             "CNAE", "Porte", "Situação", "Capital social", "Telefone", "E-mail"],
            rows, { scroll: true }),
      { actions: `<span class="text-muted text-size-small mr-10">Página ${page}</span>
          <button class="btn btn-default btn-xs" id="pgPrev"${(res.offset || 0) <= 0 ? " disabled" : ""}>‹</button>
          <button class="btn btn-default btn-xs" id="pgNext"${hasMore ? "" : " disabled"}>›</button>` })}`;

  const all = document.getElementById("empAll");
  if (all) all.onchange = (e) =>
    view.querySelectorAll(".emp-check").forEach((c) => { c.checked = e.target.checked; });
  document.getElementById("selNone").onclick = () => {
    view.querySelectorAll(".emp-check").forEach((c) => { c.checked = false; });
    if (all) all.checked = false;
  };
  document.getElementById("pgPrev").onclick = () =>
    runB2B(Math.max(0, (res.offset || 0) - (res.limite || 50)));
  document.getElementById("pgNext").onclick = () =>
    runB2B((res.offset || 0) + (res.limite || 50));

  const selected = () => [...view.querySelectorAll(".emp-check:checked")].map((c) => c.value).filter(Boolean);

  document.getElementById("dedupBtn").onclick = async () => {
    const out = document.getElementById("dedupOut");
    out.innerHTML = `<div class="alert alert-info alert-styled-left"><span class="spinner"></span> checando…</div>`;
    const r = await api("/api/capiblu/dedup", { method: "POST", body: { cnpjs: selected() } });
    out.innerHTML = `<div class="alert ${r.meta.duplicates ? "alert-info" : "alert-success"} alert-styled-left">
      ${r.meta.duplicates} de ${r.meta.checked} já existem como lead aqui dentro.
      ${r.existing.slice(0, 8).map((x) => h(x.name)).join(", ")}</div>`;
  };
  document.getElementById("xlsxBtn").onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> gerando…`;
    try {
      // Reenvia os filtros, não as linhas da tela: o XLSX sai com a consulta
      // inteira, não só com a página que está à vista.
      await apiDownload("/api/capiblu/export/empresas", {
        body: { filtros: state.b2bFilters || {}, limite: Math.min(res.total || 1000, 5000) },
        fallbackName: "empresas.xlsx" });
      toast("Arquivo baixado.", "ok");
    } catch (err) { toast(err.message, "err"); }
    btn.disabled = false;
    btn.textContent = "Baixar XLSX";
  };
  document.getElementById("toBase").onclick = () => openProspectImport(selected());
}

/* ── Perfil "Sócios e pessoas" da prospecção ─────────────────────────── */
function socioFilters(f) {
  return `
    <div class="filter-row" style="grid-template-columns:repeat(4,1fr)">
      <div><label class="text-muted text-size-small">Nome</label>
        <input class="form-control" id="sNome" value="${h(f.nome || "")}"></div>
      <div><label class="text-muted text-size-small">Sobrenome</label>
        <input class="form-control" id="sSobrenome" value="${h(f.sobrenome || "")}"></div>
      <div><label class="text-muted text-size-small">Cargo <span class="text-grey">(qualificação societária)</span></label>
        <input class="form-control" id="sCargo" placeholder="administrador"></div>
      <div><label class="text-muted text-size-small">Anos na empresa (mínimo)</label>
        <input class="form-control" type="number" id="sAnos" min="0"></div>
    </div>
    <div class="filter-row mt-10" style="grid-template-columns:repeat(4,1fr)">
      <div><label class="text-muted text-size-small">UF</label>${multi("sUf", UFS, { size: 4 })}</div>
      <div><label class="text-muted text-size-small">CNPJ da empresa</label>
        <input class="form-control" id="sCnpj"></div>
      <div><label class="text-muted text-size-small">Por página</label>
        <select class="form-control" id="sLimite">
          ${[20, 50, 100, 200].map((n) => `<option value="${n}"${n === 50 ? " selected" : ""}>${n}</option>`).join("")}
        </select></div>
      <div><label class="text-muted text-size-small">&nbsp;</label>
        <button class="btn btn-main" style="width:100%" id="doSocios">Buscar sócios</button></div>
    </div>`;
}

async function runSocios(offset = 0) {
  const g = (id) => (document.getElementById(id)?.value || "").trim();
  const filtros = {
    nome: g("sNome"), sobrenome: g("sSobrenome"), cargo: g("sCargo"),
    anos_min: Number(g("sAnos")) || 0, uf: picked("sUf"),
    cnpj: g("sCnpj").replace(/\D/g, ""),
  };
  Object.keys(filtros).forEach((k) => {
    const v = filtros[k];
    if (v === "" || v === 0 || (Array.isArray(v) && !v.length)) delete filtros[k];
  });
  state.socioFilters = filtros;
  const out = document.getElementById("b2bOut");
  out.innerHTML = LOADING;
  try {
    const r = await api("/api/capiblu/prospect/pessoas", { method: "POST",
      body: { filtros, limite: Number(g("sLimite")) || 50, offset } });
    const pessoas = r.pessoas || r.data || [];
    const rows = pessoas.map((p) => ({ cells: [
      `<strong>${h(p.nome || p.nome_socio || "—")}</strong>`,
      h(p.cpf || p.cpf_cnpj_socio || "—"),
      h(p.qualificacao || p.cargo || "—"),
      h(p.razao_social || p.empresa || "—"),
      h(p.cnpj || "—"),
      `${h(p.municipio || "")}${p.uf ? `/${h(p.uf)}` : ""}`,
      h(p.data_entrada || "—"),
    ] }));
    out.innerHTML = panel(`${r.total ?? pessoas.length} pessoas`,
      table(["Nome", "CPF", "Cargo", "Empresa", "CNPJ", "Local", "Entrada"], rows, { scroll: true }),
      { subtitle: r.status === "unavailable" ? r.message : "Base local — não gasta consulta" });
  } catch (e) {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

function openProspectImport(cnpjs) {
  if (!cnpjs.length) return toast("Selecione ao menos uma empresa.", "err");
  const m = modal({
    title: `Montar base com ${cnpjs.length} empresas`,
    body: `
      <div class="alert alert-info alert-styled-left">
        O CapiBLU vai buscar sócios e decisores de cada CNPJ e trazer os telefones priorizados.
        Rotas de telefone <strong>gastam consulta</strong>.
      </div>
      <div class="field"><label>Nome da base *</label>
        <input class="form-control" id="pbName" value="[CapiBLU] - ${new Date().toLocaleDateString("pt-BR")}"></div>
      <div class="field-row">
        <div class="field"><label>Cliente</label>
          <select class="form-control" id="pbClient">${options(state.clients, "", { blank: "—" })}</select></div>
        <div class="field"><label>SDR responsável</label>
          <select class="form-control" id="pbSdr">${options(state.users, "", { blank: "—" })}</select></div>
      </div>
      <div class="field"><label>Colocar em cadência</label>
        <select class="form-control" id="pbCad">${options(state.cadences.filter((c) => c.executing), "", { blank: "Não iniciar agora" })}</select></div>
      <div class="field-row">
        <div class="field"><label>Máx. decisores por empresa</label>
          <input class="form-control" type="number" id="pbMaxDec" value="3" min="0" max="10"></div>
        <div class="field"><label>Máx. telefones por contato</label>
          <input class="form-control" type="number" id="pbMaxTel" value="3" min="1" max="5"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Tipo de telefone</label>
          <select class="form-control" id="pbTipoTel">
            <option value="celular">Celular</option>
            <option value="celular_fixo">Celular e fixo</option>
            <option value="todos">Todos</option>
          </select></div>
        <div class="field"><label>Fonte do telefone</label>
          <select class="form-control" id="pbFonte">
            <option value="assertiva">Assertiva</option>
            <option value="mk">Mk Buscas</option>
          </select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Sócios</label>
          <select class="form-control" id="pbSocios">
            <option value="todos">Todos os sócios</option>
            <option value="admin">Só sócio-administrador / diretor / presidente</option>
          </select></div>
        <div class="field"><label>Máx. sócios por empresa <span class="text-grey">(0 = sem limite)</span></label>
          <input class="form-control" type="number" id="pbMaxSocios" value="0" min="0" max="20"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Fonte dos decisores</label>
          <select class="form-control" id="pbDecFonte">
            <option value="assertiva">Assertiva (rápida)</option>
            <option value="linkedin">LinkedIn (lenta, costuma bloquear)</option>
          </select></div>
        <div class="field"><label>Fallback por hierarquia <span class="text-grey">(0 = desligado)</span></label>
          <input class="form-control" type="number" id="pbFallback" value="0" min="0" max="5"></div>
      </div>
      <div class="field"><label>Filtro de cargo</label>
        <div class="mb-20" id="pbChips">
          ${["1", "2", "3", "administrador", "representante", "diretor", "gerente", "coordenador"]
            .map((c) => `<button type="button" class="btn btn-default btn-xs mr-10" data-chip="${c}">
              ${c === "1" ? "Nível 1 — decide sozinho" : c === "2" ? "Nível 2 — decide na área"
                : c === "3" ? "Nível 3 — influencia" : c}</button>`).join("")}
        </div>
        <input class="form-control" id="pbCargos" placeholder="clique nos atalhos ou escreva: diretor,gerente"></div>
      <div class="field">
        <label><input type="checkbox" id="pbPular"> Descartar empresa que não tem nenhum decisor</label><br>
        <label><input type="checkbox" id="pbApenasCargo"> Modo estrito: só decisores do cargo pedido (sem sócios)</label>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Montar base</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const cargos = m.root.querySelector("#pbCargos");
  m.root.querySelectorAll("[data-chip]").forEach((b) => {
    b.onclick = () => {
      const parts = cargos.value.split(",").map((s) => s.trim()).filter(Boolean);
      const chip = b.dataset.chip;
      const i = parts.indexOf(chip);
      if (i >= 0) parts.splice(i, 1); else parts.push(chip);
      cargos.value = parts.join(",");
      b.classList.toggle("btn-main", i < 0);
    };
  });

  const ok = m.root.querySelector("[data-ok]");
  ok.onclick = async () => {
    const g = (id) => m.root.querySelector(id).value;
    const chk = (id) => m.root.querySelector(id).checked;
    const name = g("#pbName").trim();
    if (!name) return toast("Dê um nome à base.", "err");
    ok.disabled = true;
    ok.innerHTML = `<span class="spinner"></span> montando…`;
    try {
      const res = await api("/api/capiblu/prospect/import", { method: "POST", body: {
        cnpjs, name,
        clientId: Number(g("#pbClient")) || null, sdrId: Number(g("#pbSdr")) || null,
        cadenceId: Number(g("#pbCad")) || null, createdById: state.me.id,
        maxDecisores: Number(g("#pbMaxDec")), maxTelefones: Number(g("#pbMaxTel")),
        tipoTelefone: g("#pbTipoTel"), fonteTelefone: g("#pbFonte"),
        sociosModo: g("#pbSocios"), maxSocios: Number(g("#pbMaxSocios")),
        decisoresFonte: g("#pbDecFonte"), fallbackHierarquia: Number(g("#pbFallback")),
        pularSemDecisor: chk("#pbPular"), apenasCargo: chk("#pbApenasCargo"),
        cargos: cargos.value.trim(), incluirDecisores: Number(g("#pbMaxDec")) > 0,
      } });
      m.close();
      toast(`${res.imported} leads criados${res.failureCount ? ` · ${res.failureCount} CNPJs falharam` : ""}.`, "ok");
      if (res.semDecisorCount) showSemDecisor(res);
      go("bases");
    } catch (e) { toast(e.message, "err"); ok.disabled = false; ok.textContent = "Montar base"; }
  };
}

function showSemDecisor(res) {
  modal({
    title: `${res.semDecisorCount} empresas sem decisor`,
    body: `<div class="alert alert-info alert-styled-left">
        Micro empresa quase nunca tem decisor cadastrado — nesses casos só entram os sócios do QSA.
      </div>
      ${table(["CNPJ", "Razão social", "Motivo"],
        res.semDecisor.map((x) => ({ cells: [h(x.cnpj), h(x.razaoSocial), h(x.motivo || "—")] })))}`,
  });
}

PAGES["capiblu-gente"] = {
  area: "CapiBLU", title: "Procurar GENTE",
  async render() {
    view.innerHTML = `
      ${panel("Buscar pessoa pelo nome", `
        <div class="main-search">
          <div class="form-group has-feedback has-feedback-left">
            <input class="form-control input-xlg" id="pName" placeholder="Nome completo ou parcial">
            <div class="form-control-feedback">⌕</div>
            <div class="help-block">Base local JBR — não gasta consulta. A busca ampla encontra nomes compostos parecidos.</div>
          </div>
          <div class="toolbar" style="border:0;padding:0;background:none">
            <label><input type="checkbox" id="pBroad"> Busca ampla</label>
            <span class="spacer"></span>
            <button class="btn btn-main btn-sm" id="pSearch">Buscar</button>
          </div>
        </div>`, { subtitle: "Recursos do CapiBLU dentro do fluxo de prospecção" })}
      <div id="genteOut"></div>`;

    const run = async () => {
      const q = document.getElementById("pName").value.trim();
      if (q.length < 3) return toast("Digite ao menos 3 caracteres.", "err");
      const out = document.getElementById("genteOut");
      out.innerHTML = LOADING;
      try {
        const r = await api(`/api/capiblu/pessoas?q=${encodeURIComponent(q)}&broad=${document.getElementById("pBroad").checked}`);
        const pessoas = r.pessoas || [];
        const rows = pessoas.map((p) => ({ cells: [
          `<strong>${h(p.nome || "—")}</strong>`, h(p.cpf || "—"),
          h(p.nascimento || "—"), h(p.sexo || "—"),
          `<button class="btn btn-default btn-xs" data-pdet="${h(p.cpf || "")}">Detalhes</button>
           <button class="btn btn-default btn-xs" data-plead="${h(p.cpf || "")}" data-pnome="${h(p.nome || "")}">Virar lead</button>`,
        ] }));
        out.innerHTML = panel(`${r.total || pessoas.length} pessoas`,
          table(["Nome", "CPF", "Nascimento", "Sexo", ""], rows, { scroll: true }),
          { subtitle: r.status === "unavailable" ? r.message : "" });
        out.querySelectorAll("[data-pdet]").forEach((b) => { b.onclick = () => openPersonModal(b.dataset.pdet); });
        out.querySelectorAll("[data-plead]").forEach((b) => {
          b.onclick = () => openLeadForm({ name: b.dataset.pnome, cpf: b.dataset.pdet });
        });
      } catch (e) { out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`; }
    };
    document.getElementById("pSearch").onclick = run;
    document.getElementById("pName").onkeydown = (e) => { if (e.key === "Enter") run(); };
  },
};

function openPersonModal(cpf) {
  const m = modal({
    title: `CPF ${cpf}`, wide: true,
    body: `<div class="toolbar" style="margin:0 0 14px">
        <button class="btn btn-default btn-xs" data-block="">Cadastro</button>
        <button class="btn btn-default btn-xs" data-block="mk">Perfil completo (Mk)</button>
        <button class="btn btn-default btn-xs" data-block="vinculos">Vínculos (RAIS)</button>
        <button class="btn btn-default btn-xs" data-block="parentes">Parentes</button>
        <button class="btn btn-default btn-xs" data-block="contacts">Contatos (Serasa)</button>
      </div><div id="pOut">${emptyState("Escolha o que consultar.")}</div>`,
  });
  m.root.querySelectorAll("[data-block]").forEach((b) => {
    b.onclick = async () => {
      const out = m.root.querySelector("#pOut");
      out.innerHTML = `<span class="spinner"></span> consultando…`;
      const path = b.dataset.block ? `/api/capiblu/pessoas/${cpf}/${b.dataset.block}` : `/api/capiblu/pessoas/${cpf}`;
      try {
        const r = await api(path);
        out.innerHTML = `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>`;
      } catch (e) { out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`; }
    };
  });
}

PAGES["capiblu-telefone"] = {
  area: "CapiBLU", title: "De quem é este telefone",
  async render() {
    view.innerHTML = `
      ${panel("Telefone reverso", `
        <div class="field-row">
          <div class="field"><label>Telefone com DDD</label>
            <input class="form-control input-xlg" id="tPhone" placeholder="41999998888"></div>
          <div class="field"><label>Validar contra um documento (opcional)</label>
            <input class="form-control input-xlg" id="tDoc" placeholder="CPF ou CNPJ"></div>
        </div>
        <button class="btn btn-main" id="tGo">Consultar</button>
        <span class="text-muted text-size-small ml-5">Gasta consulta</span>`)}
      <div id="telOut"></div>`;
    document.getElementById("tGo").onclick = async () => {
      const phone = document.getElementById("tPhone").value.replace(/\D/g, "");
      const doc = document.getElementById("tDoc").value.replace(/\D/g, "");
      if (phone.length < 10) return toast("Informe o telefone com DDD.", "err");
      const out = document.getElementById("telOut");
      out.innerHTML = LOADING;
      try {
        const r = await api(doc ? `/api/capiblu/telefones/${phone}/pertence/${doc}`
                                : `/api/capiblu/telefones/${phone}`);
        out.innerHTML = panel("Resultado", `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>`);
      } catch (e) { out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`; }
    };
  },
};

/* ── Minha planilha: subir → escolher campos → enriquecer → baixar ─────── */
const planilha = { upload: null, sheet: null, cnpjCol: null, catalogo: null, run: null };

PAGES["capiblu-enriquecimento"] = {
  area: "CapiBLU", title: "Minha planilha",
  async render() {
    view.innerHTML = `
      <div class="alert alert-info alert-styled-left">
        Suba sua planilha, escolha o que preencher e baixe de volta com as colunas
        originais intactas. O que vem da Receita é instantâneo e não gasta consulta;
        telefone e sócio passam pela Assertiva e são cobrados por linha.
      </div>
      <div id="etapa1"></div><div id="etapa2"></div>
      <div id="etapa3"></div><div id="etapa4"></div>`;
    renderUploadStep();
    if (planilha.upload) { await renderCamposStep(); }
    if (planilha.run) renderResultado();
  },
};

function renderUploadStep() {
  const up = planilha.upload;
  document.getElementById("etapa1").innerHTML = panel("1 · A planilha", up ? `
      <div class="toolbar" style="border:0;padding:0;background:none">
        <span><strong>${h(up.fileName)}</strong>
          <span class="text-muted">· ${up.sheets.length} aba${up.sheets.length > 1 ? "s" : ""}</span></span>
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="pTrocar">Trocar planilha</button>
      </div>
      <div class="filter-row mt-10">
        <div><label class="text-muted text-size-small">Aba</label>
          <select class="form-control" id="pSheet">
            ${up.sheets.map((s) => `<option value="${h(s.nome || s.name)}"
              ${(s.nome || s.name) === planilha.sheet ? " selected" : ""}>
              ${h(s.nome || s.name)} (${s.linhas ?? s.rows ?? "?"} linhas)</option>`).join("")}
          </select></div>
        <div><label class="text-muted text-size-small">Coluna do CNPJ</label>
          <select class="form-control" id="pCnpjCol"></select></div>
      </div>` : `
      <div class="field">
        <label>Arquivo XLSX ou CSV</label>
        <input type="file" class="form-control" id="pFile" accept=".xlsx,.xls,.csv">
      </div>
      <button class="btn btn-main btn-sm" id="pSubir">Subir planilha</button>`);

  if (!up) {
    document.getElementById("pSubir").onclick = async () => {
      const file = document.getElementById("pFile").files[0];
      if (!file) return toast("Escolha um arquivo.", "err");
      const btn = document.getElementById("pSubir");
      btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> subindo…`;
      try {
        const r = await apiUpload("/api/capiblu/planilha/upload", file);
        planilha.upload = { ...r, fileName: file.name };
        planilha.sheet = (r.sheets[0].nome || r.sheets[0].name);
        planilha.run = null;
        go("capiblu-enriquecimento");
      } catch (e) { toast(e.message, "err"); btn.disabled = false; btn.textContent = "Subir planilha"; }
    };
    return;
  }

  const sheetSel = document.getElementById("pSheet");
  const colSel = document.getElementById("pCnpjCol");
  const fillCols = () => {
    const s = up.sheets.find((x) => (x.nome || x.name) === sheetSel.value) || up.sheets[0];
    const cols = (s.colunas || s.columns || []).map((c) => typeof c === "string" ? c : c.header);
    // A coluna de CNPJ é adivinhada pelo nome; o usuário corrige se errar.
    const guess = cols.find((c) => /cnpj|documento|doc/i.test(c)) || cols[0];
    planilha.cnpjCol = planilha.cnpjCol && cols.includes(planilha.cnpjCol) ? planilha.cnpjCol : guess;
    colSel.innerHTML = cols.map((c) =>
      `<option${c === planilha.cnpjCol ? " selected" : ""}>${h(c)}</option>`).join("");
  };
  sheetSel.onchange = () => { planilha.sheet = sheetSel.value; planilha.cnpjCol = null; fillCols(); };
  colSel.onchange = () => { planilha.cnpjCol = colSel.value; };
  fillCols();
  document.getElementById("pTrocar").onclick = () => {
    Object.assign(planilha, { upload: null, sheet: null, cnpjCol: null, run: null });
    go("capiblu-enriquecimento");
  };
}

async function renderCamposStep() {
  const el = document.getElementById("etapa2");
  el.innerHTML = LOADING;
  try {
    planilha.catalogo = planilha.catalogo || await api("/api/capiblu/planilha/catalogo");
  } catch (e) {
    el.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    return;
  }
  const grupos = planilha.catalogo.grupos || [];
  const pago = (g) => /assertiva|integralx|workapi/i.test(g.fonte || "");
  el.innerHTML = panel("2 · O que preencher", `
    ${grupos.map((g, i) => `
      <div class="mb-20">
        <label style="font-weight:600">
          <input type="checkbox" class="grp-all" data-grp="${i}"> ${h(g.grupo)}
        </label>
        <span class="pill ${pago(g) ? "amber" : "green"} ml-5">${h(g.fonte || "")}</span>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:4px"
             class="mt-10">
          ${(g.campos || []).map((c) => `<label class="text-size-small">
            <input type="checkbox" class="campo" data-grp="${i}" value="${h(c.key)}"> ${h(c.label)}
          </label>`).join("")}
        </div>
      </div>`).join("")}
    <div class="toolbar" style="border:0;padding:0;background:none">
      <span class="text-muted text-size-small" id="pCusto">nenhum campo escolhido</span>
      <span class="spacer"></span>
      <input class="form-control" type="number" id="pLimite" value="50" min="1" max="2000"
             style="width:90px" title="Quantas linhas processar">
      <button class="btn btn-default btn-sm" id="pPrevia">Testar 1 linha</button>
      <button class="btn btn-main btn-sm" id="pRodar">Enriquecer</button>
    </div>`, { subtitle: "Campos da Receita são instantâneos e gratuitos; os demais gastam consulta por linha." });

  const marcados = () => [...view.querySelectorAll(".campo:checked")].map((c) => c.value);
  const atualizaCusto = () => {
    const n = marcados().length;
    const pagos = [...view.querySelectorAll(".campo:checked")]
      .filter((c) => pago(grupos[+c.dataset.grp])).length;
    document.getElementById("pCusto").innerHTML = n
      ? `${n} campo${n > 1 ? "s" : ""} · <strong>${pagos ? `${pagos} cobrado${pagos > 1 ? "s" : ""}` : "nenhum cobrado"}</strong>`
      : "nenhum campo escolhido";
  };
  view.querySelectorAll(".campo").forEach((c) => { c.onchange = atualizaCusto; });
  view.querySelectorAll(".grp-all").forEach((g) => {
    g.onchange = () => {
      view.querySelectorAll(`.campo[data-grp="${g.dataset.grp}"]`)
        .forEach((c) => { c.checked = g.checked; });
      atualizaCusto();
    };
  });

  document.getElementById("pPrevia").onclick = () => rodarEnriquecimento(marcados(), 1, true);
  document.getElementById("pRodar").onclick = () =>
    rodarEnriquecimento(marcados(), Number(document.getElementById("pLimite").value) || 50, false);
}

async function rodarEnriquecimento(fields, limite, previa) {
  if (!fields.length) return toast("Escolha ao menos um campo.", "err");
  const el = document.getElementById("etapa3");
  el.innerHTML = `<div class="alert alert-info alert-styled-left"><span class="spinner"></span>
    Enriquecendo ${limite} linha${limite > 1 ? "s" : ""}…</div>`;
  try {
    const r = await api("/api/capiblu/planilha/enriquecer", { method: "POST", body: {
      upload_id: planilha.upload.upload_id, sheet: planilha.sheet,
      cnpj_col: planilha.cnpjCol, fields, limite } });
    planilha.run = { ...r, previa };
    el.innerHTML = "";
    renderResultado();
  } catch (e) {
    el.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

function renderResultado() {
  const r = planilha.run;
  const cols = [...(r.base_cols || []), ...(r.added_cols || [])]
    .map((c) => typeof c === "string" ? { key: c, label: c } : c);
  // Campo que a fonte não tinha volta como string vazia, não como nulo — sem
  // este trecho a célula fica em branco e parece erro de renderização.
  const cell = (v) => {
    const s = String(v ?? "").trim();
    return s ? h(s.slice(0, 42)) : `<span class="text-muted">—</span>`;
  };
  const rows = (r.rows || []).map((row) => ({ cells: cols.map((c) => cell(row[c.key])) }));
  document.getElementById("etapa3").innerHTML = panel(
    `${r.previa ? "Prévia" : "3 · Resultado"}`,
    table(cols.map((c) => c.label), rows, { scroll: true }),
    { subtitle: `${r.enriquecidas} de ${r.total_aba} linhas · coluna de CNPJ: ${h(r.cnpj_col)}`,
      actions: r.previa
        ? `<span class="text-muted text-size-small">Confira e rode a planilha inteira.</span>`
        : `<button class="btn btn-main btn-xs" id="pBaixar">Baixar XLSX</button>` });

  const btn = document.getElementById("pBaixar");
  if (btn) btn.onclick = async () => {
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> gerando…`;
    try {
      await apiDownload("/api/capiblu/export/planilha", {
        body: { columns: cols, rows: r.rows }, fallbackName: "planilha-enriquecida.xlsx" });
      toast("Planilha baixada.", "ok");
    } catch (e) { toast(e.message, "err"); }
    btn.disabled = false; btn.textContent = "Baixar XLSX";
  };
}

/* ── Meus modelos: o layout de coluna que cada cliente pede ──────────── */
PAGES["capiblu-modelos"] = {
  area: "CapiBLU", title: "Meus modelos",
  async render() {
    view.innerHTML = `
      <div class="alert alert-info alert-styled-left">
        Cliente que pede a lista num layout específico vira um modelo: suba uma
        planilha de exemplo, o CapiBLU reconhece as colunas, e a exportação passa
        a sair nesse formato.
      </div>
      ${panel("Novo modelo a partir de um exemplo", `
        <div class="field-row">
          <div class="field"><label>Planilha de exemplo (só o cabeçalho importa)</label>
            <input type="file" class="form-control" id="mFile" accept=".xlsx,.xls,.csv"></div>
          <div class="field"><label>&nbsp;</label>
            <button class="btn btn-main" style="width:100%" id="mAnalisar">Analisar colunas</button></div>
        </div>`)}
      <div id="mAnalise"></div>
      <div id="mLista">${LOADING}</div>`;

    document.getElementById("mAnalisar").onclick = async () => {
      const file = document.getElementById("mFile").files[0];
      if (!file) return toast("Escolha um arquivo.", "err");
      const out = document.getElementById("mAnalise");
      out.innerHTML = LOADING;
      try {
        const r = await apiUpload("/api/capiblu/modelo/analisar", file);
        renderAnalise(r, file.name);
      } catch (e) {
        out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
      }
    };
    await listarModelos();
  },
};

function renderAnalise(r, fileName) {
  const cols = r.colunas || [];
  const rows = cols.map((c) => ({ cells: [
    h(c.header),
    c.fillable
      ? `<span class="pill green">${h(c.campo_label || c.campo)}</span>`
      : `<span class="pill grey">não reconhecida</span>`,
    h(c.fonte || "—"),
  ] }));
  const reconhecidas = cols.filter((c) => c.fillable).length;
  document.getElementById("mAnalise").innerHTML = panel(
    `Colunas de ${h(fileName)}`,
    table(["Cabeçalho na planilha", "Campo do CapiBLU", "Fonte"], rows, { scroll: true }),
    { subtitle: `${reconhecidas} de ${cols.length} colunas reconhecidas · aba ${h(r.aba || "—")}`,
      actions: `<input class="form-control" id="mNome" placeholder="Nome do modelo"
                  style="width:200px;display:inline-block">
                <button class="btn btn-main btn-xs ml-5" id="mSalvar">Salvar modelo</button>` });

  document.getElementById("mSalvar").onclick = async () => {
    const nome = document.getElementById("mNome").value.trim();
    if (!nome) return toast("Dê um nome ao modelo.", "err");
    try {
      await api("/api/capiblu/modelos", { method: "POST",
        body: { nome, aba: r.aba, colunas: cols } });
      toast("Modelo salvo.", "ok");
      document.getElementById("mAnalise").innerHTML = "";
      await listarModelos();
    } catch (e) { toast(e.message, "err"); }
  };
}

async function listarModelos() {
  const el = document.getElementById("mLista");
  try {
    const r = await api("/api/capiblu/modelos");
    const modelos = r.modelos || r.data || (Array.isArray(r) ? r : []);
    if (!modelos.length) {
      el.innerHTML = panel("Modelos salvos", emptyState("Nenhum modelo ainda."));
      return;
    }
    el.innerHTML = panel("Modelos salvos", table(
      ["Nome", "Aba", "Colunas", ""],
      modelos.map((m) => ({ cells: [
        `<strong>${h(m.nome || m.name)}</strong>`,
        h(m.aba || "—"),
        String((m.colunas || m.columns || []).length),
        `<button class="btn btn-default btn-xs mod-usar" data-id="${h(m.id)}">Exportar com este modelo</button>`,
      ] }))));
    view.querySelectorAll(".mod-usar").forEach((b) => {
      b.onclick = () => exportarPorModelo(b.dataset.id);
    });
  } catch (e) {
    el.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

async function exportarPorModelo(modeloId) {
  // Exporta o resultado da última busca da Prospecção B2B no layout do modelo.
  const res = state.b2bResult;
  if (!res || !res.empresas?.length) {
    return toast("Faça uma busca em Prospecção B2B primeiro — é o resultado dela que sai no modelo.", "err");
  }
  try {
    await apiDownload("/api/capiblu/export/modelo", {
      body: { modelo_id: modeloId, empresas: res.empresas },
      fallbackName: "lista-no-modelo.xlsx" });
    toast(`${res.empresas.length} empresas exportadas.`, "ok");
  } catch (e) { toast(e.message, "err"); }
}

PAGES["capiblu-dossie"] = {
  area: "CapiBLU", title: "Dossiê",
  async render() {
    view.innerHTML = panel("Gerar dossiê em PDF", `
      <div class="alert alert-info alert-styled-left">
        Disponível apenas para administradores. O PDF reúne cadastro, telefones, endereços,
        vínculos e validações; com <code>insight</code> inclui resumo por IA.
      </div>
      <div class="field-row">
        <div class="field"><label>Tipo</label>
          <select class="form-control" id="dTipo"><option value="cnpj">CNPJ</option><option value="cpf">CPF</option></select></div>
        <div class="field"><label>Documento</label><input class="form-control" id="dDoc"></div>
      </div>
      <div class="field">
        <label><input type="checkbox" id="dInsight"> Incluir resumo por IA</label><br>
        <label><input type="checkbox" id="dFamilia"> Consultar parentes</label>
      </div>
      <button class="btn btn-main btn-sm" id="dGo">Gerar PDF</button>`);
    document.getElementById("dGo").onclick = async () => {
      const doc = document.getElementById("dDoc").value.replace(/\D/g, "");
      const tipo = document.getElementById("dTipo").value;
      if (!doc) return toast("Informe o documento.", "err");
      const qs = new URLSearchParams({
        insight: document.getElementById("dInsight").checked,
        familia: document.getElementById("dFamilia").checked,
      });
      const btn = document.getElementById("dGo");
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> montando o PDF…`;
      try {
        // Pela rota do Bluutime, não direto no serviço de dados: é ela que
        // valida o dígito do CNPJ antes de gastar a consulta.
        await apiDownload(`/api/capiblu/dossie/${tipo}/${doc}?${qs}`,
                          { method: "GET", fallbackName: `dossie-${doc}.pdf` });
        toast("Dossiê baixado.", "ok");
      } catch (e) { toast(e.message, "err"); }
      btn.disabled = false;
      btn.textContent = "Gerar PDF";
    };
  },
};

PAGES["capiblu-consumo"] = {
  area: "CapiBLU", title: "Consumo e custo",
  async render() {
    const dias = state.consumoDias || 7;
    view.innerHTML = `
      <div class="toolbar">
        <label class="text-muted text-size-small">Período</label>
        <select class="form-control" id="cdDias">
          ${[7, 15, 30, 60].map((d) => `<option value="${d}"${d === dias ? " selected" : ""}>${d} dias</option>`).join("")}
        </select>
        <span class="spacer text-muted text-size-small">O relatório oficial da Assertiva é consultado ao vivo — leva alguns segundos.</span>
      </div>
      <div id="cdOut">${LOADING}</div>`;
    document.getElementById("cdDias").onchange = (e) => {
      state.consumoDias = Number(e.target.value); go("capiblu-consumo");
    };

    const out = document.getElementById("cdOut");
    let r;
    try {
      r = await api(`/api/capiblu/consumo?dias=${dias}`);
    } catch (e) {
      out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
      return;
    }
    if (r.status === "unavailable") {
      out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(r.detail || "Relatório indisponível.")}</div>`;
      return;
    }
    const a = r.assertiva || {};
    const interno = r.interno || {};
    const dif = r.diferenca || {};
    const periodo = r.periodo || {};
    const funcRows = Object.entries(a.por_funcionalidade || {}).map(([k, v]) => ({
      cells: [h(k), h(v), fmtMoney((a.custo_por_funcionalidade || {})[k] || 0)] }));
    // O relatório oficial identifica o usuário pelo nome de exibição, o log
    // interno pelo e-mail — por isso as duas visões ficam lado a lado, sem join.
    const userRows = (interno.por_usuario || []).map((u) => ({
      cells: [h(u.user), h(u.n_consultas), fmtMoney(u.custo_total)] }));
    const oficialRows = Object.entries(a.por_usuario || {}).map(([k, v]) => ({
      cells: [h(k), h(v)] }));
    const modeloRows = ((r.modelos || {}).modelos || []).map((mo) => ({
      cells: [h(mo.modelo_nome), h(mo.tipo), h(mo.n_consultas), fmtMoney(mo.custo_total)] }));

    out.innerHTML = `
      ${kpis([
        { value: a.consultas ?? "—", label: "Consultas · relatório oficial" },
        { value: interno.chamadas ?? "—", label: "Chamadas · log interno", tone: "info" },
        { value: fmtMoney(a.custo_estimado || 0), label: "Custo oficial no período", tone: "warning" },
        { value: dif.chamadas ?? "—", label: "Diferença de chamadas", tone: dif.chamadas ? "danger" : "" },
      ])}
      ${dif.chamadas ? `<div class="alert alert-info alert-styled-left">
        O log interno registra ${h(dif.chamadas)} chamadas a mais que o relatório oficial
        (${fmtMoney(dif.custo || 0)}). Nem toda chamada interna vira consulta paga — a diferença
        é o que foi respondido por base local ou cache.</div>` : ""}
      ${panel("Por funcionalidade", table(["Funcionalidade", "Consultas", "Custo"], funcRows),
        { subtitle: `Período ${h(periodo.desde || "")} a ${h(periodo.ate || "")} · preço médio ${fmtMoney(r.preco_medio || 0)}` })}
      <div class="two-col">
        ${panel("Por usuário · log interno", table(["Usuário", "Chamadas", "Custo estimado"], userRows))}
        ${panel("Por usuário · relatório oficial", table(["Usuário", "Consultas"], oficialRows))}
      </div>
      ${modeloRows.length ? panel("Por modelo de planilha",
        table(["Modelo", "Tipo", "Consultas", "Custo"], modeloRows)) : ""}`;
  },
};

/* ── Administração ───────────────────────────────────────────────────── */
PAGES.usuarios = {
  area: "Empresa", title: "Usuários e times",
  async render() {
    const [users, teams] = await Promise.all([api("/api/users"), api("/api/teams")]);
    state.users = users.data;
    const rows = users.data.map((u) => ({ cells: [
      `<div class="media-left"><div class="lead-avatar-dot ${u.online ? "success" : ""}">${h(u.initials)}</div></div>
       <div class="media-body"><strong>${h(u.name)}</strong><br>
       <span class="text-muted text-size-small">${h(u.email)}</span></div>`,
      u.roles.map((r) => `<span class="pill">${h(r)}</span>`).join(" "),
      u.team ? h(u.team.name) : "—",
      u.dailyGoal,
      u.active ? `<span class="pill green">Ativo</span>` : `<span class="pill grey">Inativo</span>`,
      `<button class="btn btn-default btn-xs" data-edit-user="${u.id}">Editar</button>`,
    ] }));
    view.innerHTML = `
      <div class="toolbar"><span class="text-muted">${users.data.length} usuários · ${teams.length} times</span>
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="newUser">Novo usuário</button></div>
      ${panel("Usuários", table(["Usuário", "Papéis", "Time", "Meta diária", "Situação", ""], rows))}
      ${panel("Times", table(["Time", "Integrantes"],
        teams.map((t) => ({ cells: [h(t.name), t.users.map((u) => h(u.name)).join(", ") || "—"] }))))}`;
    document.getElementById("newUser").onclick = () => openUserForm();
    view.querySelectorAll("[data-edit-user]").forEach((b) => {
      b.onclick = () => openUserForm(users.data.find((u) => String(u.id) === b.dataset.editUser));
    });
  },
};

function openUserForm(user) {
  const u = user || {};
  const ROLES = ["ADMINISTRATOR", "MANAGER", "SDR", "SALESMAN"];
  const m = modal({
    title: u.id ? `Editar ${u.name}` : "Novo usuário",
    body: `<div class="field"><label>Nome *</label><input class="form-control" id="uName" value="${h(u.name || "")}"></div>
      <div class="field"><label>E-mail *</label>
        <input class="form-control" id="uEmail" value="${h(u.email || "")}"${u.id ? " disabled" : ""}></div>
      <div class="field"><label>Papéis</label>
        <select class="form-control" id="uRoles" multiple size="4">
          ${ROLES.map((r) => `<option value="${r}"${(u.roles || []).includes(r) ? " selected" : ""}>${r}</option>`).join("")}
        </select></div>
      <div class="field-row">
        <div class="field"><label>Meta diária</label>
          <input class="form-control" type="number" id="uGoal" value="${u.dailyGoal || 170}"></div>
        <div class="field"><label>Situação</label>
          <select class="form-control" id="uActive">
            <option value="true"${u.active !== false ? " selected" : ""}>Ativo</option>
            <option value="false"${u.active === false ? " selected" : ""}>Inativo</option>
          </select></div>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async () => {
    const body = {
      name: m.root.querySelector("#uName").value.trim(),
      roles: [...m.root.querySelector("#uRoles").selectedOptions].map((o) => o.value),
      dailyGoal: Number(m.root.querySelector("#uGoal").value),
      active: m.root.querySelector("#uActive").value === "true",
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (u.id) await api(`/api/users/${u.id}`, { method: "PATCH", body });
    else {
      body.email = m.root.querySelector("#uEmail").value.trim();
      if (!body.email) return toast("O e-mail é obrigatório.", "err");
      await api("/api/users", { method: "POST", body });
    }
    m.close(); toast("Usuário salvo.", "ok"); go("usuarios");
  };
}

PAGES.integracoes = {
  area: "Integrações", title: "Integrações e webhooks",
  async render() {
    const [list, hooks, capi] = await Promise.all([
      api("/api/integrations"), api("/api/webhooks"), api("/api/capiblu/status")]);
    const cards = list.map((i) => `<div class="tool-card">
      <h4>${h(i.name)}</h4><div class="what">${h(i.kind)}</div>
      <div class="mt-10"><span class="pill ${i.connected ? "green" : "grey"}">${i.connected ? "Conectado" : "Não conectado"}</span>
        ${i.lastSync ? `<span class="text-muted text-size-small ml-5">${fmtDateTime(i.lastSync)}</span>` : ""}</div>
      <div class="mt-10"><button class="btn btn-default btn-xs" data-toggle-int="${h(i.key)}">
        ${i.connected ? "Desconectar" : "Conectar"}</button></div></div>`).join("");
    const hookRows = hooks.map((w) => ({ cells: [
      w.events.map((e) => `<span class="pill">${h(e)}</span>`).join(" "),
      `<code>${h(w.targetUrl)}</code>`,
      w.enabled ? `<span class="pill green">Ativo</span>` : `<span class="pill grey">Inativo</span>`,
      fmtDate(w.created),
      `<button class="btn btn-default btn-xs" data-del-hook="${w.id}">Remover</button>`] }));

    view.innerHTML = `
      ${panel("CapiBLU", `<div class="stat-line">
          <span><b>${capi.available ? "Ativo" : "Indisponível"}</b>Serviço de dados</span>
          <span><b>${capi.tools.length}</b>Ferramentas expostas</span>
          <span><b>${capi.areas.length}</b>Áreas</span></div>
        ${capi.available ? "" : `<div class="alert alert-info alert-styled-left mt-10">${h(capi.error || "")}</div>`}`,
        { actions: `<button class="btn btn-default btn-xs" data-page="capiblu-ferramentas">Ver ferramentas</button>` })}
      ${panel("Integrações", `<div class="tool-grid">${cards}</div>`)}
      ${panel("Webhooks", table(["Eventos", "URL de destino", "Situação", "Criado", ""], hookRows),
        { actions: `<button class="btn btn-main btn-xs" id="newHook">Novo webhook</button>` })}`;

    view.querySelectorAll("[data-toggle-int]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/integrations/${b.dataset.toggleInt}`, { method: "PATCH", body: {} });
        go("integracoes");
      };
    });
    view.querySelectorAll("[data-del-hook]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/webhooks/${b.dataset.delHook}`, { method: "DELETE" });
        toast("Webhook removido."); go("integracoes");
      };
    });
    document.getElementById("newHook").onclick = () => {
      const m = modal({
        title: "Novo webhook",
        body: `<div class="field"><label>URL de destino *</label>
            <input class="form-control" id="whUrl" placeholder="https://..."></div>
          <div class="field"><label>Eventos</label>
            <select class="form-control" id="whEvents" multiple size="3">
              <option value="LEAD.WON" selected>LEAD.WON</option>
              <option value="LEAD.LOST">LEAD.LOST</option>
              <option value="LEAD.CREATED">LEAD.CREATED</option>
            </select></div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
                 <button class="btn btn-main btn-sm" data-save>Criar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-save]").onclick = async () => {
        try {
          await api("/api/webhooks", { method: "POST", body: {
            targetUrl: m.root.querySelector("#whUrl").value.trim(),
            events: [...m.root.querySelector("#whEvents").selectedOptions].map((o) => o.value) } });
          m.close(); toast("Webhook criado.", "ok"); go("integracoes");
        } catch (e) { toast(e.message, "err"); }
      };
    };
  },
};

PAGES.financeiro = {
  area: "Empresa", title: "Financeiro",
  async render() {
    const [f, statement] = await Promise.all([
      api("/api/financial/company"), api("/api/dialer/calls/statements")]);
    const rows = [
      ["FLOW por usuário", f.paidUsers, fmtMoney(f.subscription.userProductValues.FLOW)],
      ["COMBO", 1, fmtMoney(f.subscription.userProductValues.COMBO)],
      ["CALLER ID", 1, fmtMoney(f.addOns.CALLER_ID_NUMBERS)],
      ["Telefonia (uso)", `${statement.meta.totalMinutes} min`, fmtMoney(statement.meta.totalCost)],
    ].map((r) => ({ cells: r.map(h) }));
    view.innerHTML = `
      ${kpis([
        { value: fmtMoney(f.subscription.value), label: "Mensalidade atual" },
        { value: f.paidUsers, label: "Usuários pagos", tone: "info" },
        { value: f.availableFreeUsers, label: "Usuários gratuitos", tone: "success" },
        { value: fmtMoney(f.yearlyEstimate), label: "Estimativa anual", tone: "warning" },
      ])}
      ${panel("Composição da fatura", table(["Item", "Quantidade", "Valor"], rows),
        { subtitle: `Cobrança por ${f.billingType === "BANK_SLIP" ? "boleto" : f.billingType} · ciclo ${f.subscription.cycle}` })}`;
  },
};

PAGES.ajustes = {
  area: "Prospecção", title: "Ajustes",
  async render() {
    const [cfg, reasons, fields, holidays] = await Promise.all([
      api("/api/flow/configuration"), api("/api/flow/lost-reasons"),
      api("/api/flow/new-lead-fields"), api("/api/flow/configuration/holidays")]);

    view.innerHTML = `
      ${panel("Metas diárias", table(["Usuário", "Atividades por dia"],
        cfg.usersGoals.map((g) => {
          const u = state.users.find((x) => x.id === g.userId);
          return { cells: [h(u ? u.name : g.userId), g.dailyGoal] };
        })), { subtitle: `Padrão da empresa: ${cfg.defaultDailyGoal} atividades/dia` })}

      ${panel("Motivos de perda",
        table(["Motivo", ""], reasons.map((r) => ({ cells: [h(r.name),
          `<button class="btn btn-default btn-xs" data-del-reason="${r.id}">Remover</button>`] }))),
        { actions: `<button class="btn btn-main btn-xs" id="newReason">Adicionar</button>` })}

      ${panel("Campos do lead",
        table(["Campo", "Identificador", "Tipo", "Obrigatório"],
          fields.map((f) => ({ cells: [h(f.name), `<code>${h(f.identifier)}</code>`,
            f.customField ? `<span class="pill green">Personalizado</span>` : `<span class="pill grey">Nativo</span>`,
            f.required ? "Sim" : "Não"] }))),
        { actions: `<button class="btn btn-main btn-xs" id="newField">Novo campo</button>` })}

      ${panel("Calendário de trabalho",
        table(["Feriado", "Data"], holidays.map((x) => ({ cells: [h(x.name || "—"), fmtDate(x.date)] }))),
        { subtitle: "Dias úteis: segunda a sexta. A fila não agenda atividade em fim de semana.",
          actions: `<button class="btn btn-main btn-xs" id="newHoliday">Adicionar feriado</button>` })}`;

    view.querySelectorAll("[data-del-reason]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/flow/lost-reasons/${b.dataset.delReason}`, { method: "DELETE" });
        toast("Motivo removido."); go("ajustes");
      };
    });
    document.getElementById("newReason").onclick = () => promptOne("Novo motivo de perda", "Motivo", async (v) => {
      await api("/api/flow/lost-reasons", { method: "POST", body: { name: v } });
      state.lostReasons = await api("/api/flow/lost-reasons");
      toast("Motivo adicionado.", "ok"); go("ajustes");
    });
    document.getElementById("newField").onclick = () => {
      const m = modal({
        title: "Novo campo personalizado",
        body: `<div class="field"><label>Nome *</label><input class="form-control" id="cfName"></div>
          <div class="field"><label>Identificador *</label>
            <input class="form-control" id="cfIdent" placeholder="ex.: segmento"></div>
          <div class="field"><label>Tipo</label>
            <select class="form-control" id="cfType">
              <option value="STRING">Texto</option><option value="NUMBER">Número</option>
              <option value="DATE">Data</option></select></div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
                 <button class="btn btn-main btn-sm" data-save>Criar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-save]").onclick = async () => {
        try {
          await api("/api/flow/new-lead-fields", { method: "POST", body: {
            name: m.root.querySelector("#cfName").value.trim(),
            identifier: m.root.querySelector("#cfIdent").value.trim(),
            dataType: m.root.querySelector("#cfType").value } });
          m.close(); toast("Campo criado.", "ok"); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      };
    };
    document.getElementById("newHoliday").onclick = () => {
      const m = modal({
        title: "Adicionar feriado",
        body: `<div class="field"><label>Data</label><input class="form-control" type="date" id="hDate"></div>
          <div class="field"><label>Descrição</label><input class="form-control" id="hName"></div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
                 <button class="btn btn-main btn-sm" data-save>Adicionar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-save]").onclick = async () => {
        try {
          await api("/api/flow/configuration/holidays", { method: "POST", body: {
            date: m.root.querySelector("#hDate").value,
            name: m.root.querySelector("#hName").value.trim() } });
          m.close(); toast("Feriado adicionado.", "ok"); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      };
    };
  },
};

function promptOne(title, label, onOk) {
  const m = modal({
    title,
    body: `<div class="field"><label>${h(label)}</label><input class="form-control" id="promptVal"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const v = m.root.querySelector("#promptVal").value.trim();
    if (!v) return toast("Preencha o campo.", "err");
    m.close();
    try { await onOk(v); } catch (e) { toast(e.message, "err"); }
  };
}

/* ── Contas de acesso ──────────────────────────────────────────────────
 *
 * Distinta de "Usuários e times", que lista o pessoal da operação vindo do
 * Meetime. Aqui é quem consegue *entrar* — o cadastro do `auth.py` do CapiBLU,
 * compartilhado entre as duas ferramentas. Eram 10 rotas prontas sem tela, e a
 * falta dela obrigava a mexer no CapiBLU para criar conta ou trocar senha.
 */
PAGES["contas"] = {
  area: "Configurações", title: "Contas de acesso",
  async render() {
    const eu = await api("/api/envio/quem-sou-eu");
    if (eu.nivel !== "admin") {
      view.innerHTML = `<div class="alert alert-info alert-styled-left">
        Só administradores gerenciam contas de acesso.
        Seu perfil é <strong>${h(eu.nivel)}</strong>.</div>`;
      return;
    }
    const aba = state.contasAba || "contas";
    view.innerHTML = `
      <ul class="nav nav-tabs">
        ${[["contas", "Contas"], ["grupos", "Grupos"], ["tokens", "Tokens de API"],
           ["consumo", "Limite diário"]].map(([k, t]) =>
          `<li${aba === k ? " class=\"active\"" : ""}><a data-aba="${k}">${t}</a></li>`).join("")}
      </ul>
      <div id="ctOut">${LOADING}</div>`;
    view.querySelectorAll("[data-aba]").forEach((a) => {
      a.onclick = () => { state.contasAba = a.dataset.aba; go("contas"); };
    });
    const abas = { contas: abaContas, grupos: abaGrupos, tokens: abaTokens, consumo: abaConsumo };
    try {
      await abas[aba]();
    } catch (e) {
      document.getElementById("ctOut").innerHTML =
        `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    }
  },
};

const rolePill = (r) => r === "admin"
  ? `<span class="pill amber">administrador</span>`
  : `<span class="pill grey">usuário</span>`;

const epoch = (s) => s ? new Date(s * 1000).toISOString() : null;

async function abaContas() {
  const out = document.getElementById("ctOut");
  const { users } = await api("/api/admin/users");
  const rows = users.map((u) => ({ cells: [
    `<strong>${h(u.nome || "—")}</strong>`,
    h(u.email),
    rolePill(u.role),
    u.ativo ? `<span class="pill green">ativo</span>` : `<span class="pill red">inativo</span>`,
    u.ultimo_login ? fmtDateTime(epoch(u.ultimo_login)) : "nunca entrou",
    `<button class="btn btn-default btn-xs ct-senha" data-id="${u.id}" data-nome="${h(u.email)}">Trocar senha</button>
     <button class="btn btn-default btn-xs ct-toggle" data-id="${u.id}" data-ativo="${u.ativo}">${u.ativo ? "Desativar" : "Reativar"}</button>`,
  ] }));
  out.innerHTML = panel("Quem consegue entrar",
    table(["Nome", "E-mail", "Perfil", "Situação", "Último acesso", ""], rows),
    { subtitle: "Mesmo cadastro do CapiBLU — a conta serve às duas ferramentas.",
      actions: `<button class="btn btn-main btn-xs" id="ctNova">Nova conta</button>` });

  document.getElementById("ctNova").onclick = novaConta;
  out.querySelectorAll(".ct-senha").forEach((b) => {
    b.onclick = () => trocarSenha(b.dataset.id, b.dataset.nome);
  });
  out.querySelectorAll(".ct-toggle").forEach((b) => {
    b.onclick = async () => {
      const ativo = b.dataset.ativo !== "true";
      try {
        await api(`/api/admin/users/${b.dataset.id}`, { method: "PATCH", body: { ativo } });
        toast(ativo ? "Conta reativada." : "Conta desativada.", "ok");
        go("contas");
      } catch (e) { toast(e.message, "err"); }
    };
  });
}

function novaConta() {
  const m = modal({
    title: "Nova conta de acesso",
    body: `
      <div class="field"><label>Nome</label><input class="form-control" id="ncNome"></div>
      <div class="field"><label>E-mail</label>
        <input class="form-control" id="ncEmail" type="email"></div>
      <div class="field"><label>Senha provisória <span class="text-grey">(mínimo 8 caracteres)</span></label>
        <input class="form-control" id="ncSenha" type="password"></div>
      <div class="field"><label>Perfil</label>
        <select class="form-control" id="ncRole">
          <option value="user">Usuário — usa as ferramentas, com limite diário</option>
          <option value="admin">Administrador — sem limite, gerencia contas</option>
        </select></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Criar conta</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const v = (id) => m.root.querySelector(id).value.trim();
    if (!v("#ncEmail") || !v("#ncSenha")) return toast("E-mail e senha são obrigatórios.", "err");
    if (v("#ncSenha").length < 8) return toast("A senha precisa de ao menos 8 caracteres.", "err");
    try {
      await api("/api/admin/users", { method: "POST", body: {
        email: v("#ncEmail"), nome: v("#ncNome"),
        senha: v("#ncSenha"), role: v("#ncRole") } });
      m.close();
      toast("Conta criada.", "ok");
      go("contas");
    } catch (e) { toast(e.message, "err"); }
  };
}

function trocarSenha(uid, email) {
  const m = modal({
    title: `Trocar a senha de ${email}`,
    body: `<div class="alert alert-info alert-styled-left">
        A pessoa passa a entrar com esta senha. Combine com ela antes.
      </div>
      <div class="field"><label>Nova senha <span class="text-grey">(mínimo 8)</span></label>
        <input class="form-control" id="tsSenha" type="password"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Trocar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const senha = m.root.querySelector("#tsSenha").value;
    if (senha.length < 8) return toast("A senha precisa de ao menos 8 caracteres.", "err");
    try {
      await api(`/api/admin/users/${uid}/password`, { method: "POST", body: { senha } });
      m.close();
      toast("Senha alterada.", "ok");
    } catch (e) { toast(e.message, "err"); }
  };
}

async function abaGrupos() {
  const out = document.getElementById("ctOut");
  const { grupos } = await api("/api/admin/grupos");
  // Grupo guarda só id, nome e data — `criar_grupo` não aceita limite. O limite
  // diário é por conta, na aba ao lado.
  const rows = (grupos || []).map((g) => ({ cells: [
    `<strong>${h(g.nome || g.name)}</strong>`,
    g.criado_em ? fmtDate(epoch(g.criado_em)) : "—",
    `<button class="btn btn-default btn-xs gr-del" data-id="${g.id}">Excluir</button>`,
  ] }));
  out.innerHTML = panel("Grupos", rows.length
    ? table(["Nome", "Criado em", ""], rows)
    : emptyState("Nenhum grupo. Serve para organizar as contas por equipe ou cliente."),
    { subtitle: "O limite diário é definido por conta, na aba “Limite diário”.",
      actions: `<button class="btn btn-main btn-xs" id="grNovo">Novo grupo</button>` });

  document.getElementById("grNovo").onclick = () =>
    promptOne("Novo grupo", "Nome do grupo", async (nome) => {
      await api("/api/admin/grupos", { method: "POST", body: { nome } });
      toast("Grupo criado.", "ok");
      go("contas");
    });
  out.querySelectorAll(".gr-del").forEach((b) => {
    b.onclick = async () => {
      try {
        await api(`/api/admin/grupos/${b.dataset.id}`, { method: "DELETE" });
        toast("Grupo excluído.", "ok"); go("contas");
      } catch (e) { toast(e.message, "err"); }
    };
  });
}

async function abaTokens() {
  const out = document.getElementById("ctOut");
  const r = await api("/api/admin/tokens");
  const rows = (r.tokens || []).map((t) => ({ cells: [
    `<strong>${h(t.nome || t.name || "—")}</strong>`,
    h(t.email || t.usuario || "—"),
    t.criado_em ? fmtDate(epoch(t.criado_em)) : "—",
    t.ultimo_uso ? fmtDateTime(epoch(t.ultimo_uso)) : "nunca usado",
    `<button class="btn btn-default btn-xs tk-del" data-id="${t.id}">Revogar</button>`,
  ] }));
  out.innerHTML = panel("Tokens de API", rows.length
    ? table(["Nome", "Dono", "Criado", "Último uso", ""], rows)
    : emptyState("Nenhum token. Token permite chamar a API sem passar pelo login."),
    { subtitle: "O valor do token aparece uma única vez, na criação.",
      actions: `<button class="btn btn-main btn-xs" id="tkNovo">Novo token</button>` });

  document.getElementById("tkNovo").onclick = () => {
    const m = modal({
      title: "Novo token de API",
      body: `<div class="field">
               <label>Nome <span class="text-grey">(para você reconhecer depois)</span></label>
               <input class="form-control" id="tnNome" placeholder="integração n8n"></div>
             <div class="field"><label>Age em nome de</label>
               <select class="form-control" id="tnUser">
                 ${(r.usuarios || []).map((u) =>
                   `<option value="${u.id}">${h(u.email)}</option>`).join("")}
               </select></div>`,
      footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
               <button class="btn btn-main btn-sm" data-ok>Gerar</button>`,
    });
    m.root.querySelector("[data-cancel]").onclick = m.close;
    m.root.querySelector("[data-ok]").onclick = async () => {
      const nome = m.root.querySelector("#tnNome").value.trim();
      if (!nome) return toast("Dê um nome ao token.", "err");
      try {
        const novo = await api("/api/admin/tokens", { method: "POST", body: {
          nome, user_id: Number(m.root.querySelector("#tnUser").value) } });
        m.close();
        // O valor só existe agora: o servidor guarda o hash.
        modal({ title: "Token gerado", body: `
          <div class="alert alert-info alert-styled-left">
            Copie agora — este valor não aparece de novo.
          </div>
          <div class="json-box" style="user-select:all">${h(novo.token || novo.valor || JSON.stringify(novo))}</div>` });
        go("contas");
      } catch (e) { toast(e.message, "err"); }
    };
  };
  out.querySelectorAll(".tk-del").forEach((b) => {
    b.onclick = async () => {
      try {
        await api(`/api/admin/tokens/${b.dataset.id}`, { method: "DELETE" });
        toast("Token revogado.", "ok"); go("contas");
      } catch (e) { toast(e.message, "err"); }
    };
  });
}

async function abaConsumo() {
  const out = document.getElementById("ctOut");
  const r = await api("/api/admin/consumo");
  const rows = (r.consumo || []).map((u) => {
    const limite = u.limite_diario ?? r.limite_default;
    const pct = limite ? Math.min(100, Math.round(u.consumo_hoje / limite * 100)) : 0;
    return { cells: [
      `<strong>${h(u.nome || "—")}</strong><br>
       <span class="text-muted text-size-small">${h(u.email)}</span>`,
      `${u.consumo_hoje} de ${limite}
       <div style="height:5px;background:#eee;border-radius:3px;margin-top:4px">
         <div style="height:5px;width:${pct}%;border-radius:3px;
                     background:${pct > 85 ? "#c62828" : "#00a443"}"></div>
       </div>`,
      u.limite_diario_custom != null
        ? `<span class="pill blue">próprio: ${u.limite_diario_custom}</span>`
        : `<span class="text-muted">padrão (${r.limite_default})</span>`,
      `<button class="btn btn-default btn-xs lm-set" data-id="${u.id}">Ajustar limite</button>`,
    ] };
  });
  out.innerHTML = panel(`Consumo de ${r.dia}`, rows.length
    ? table(["Conta", "Hoje", "Limite", ""], rows)
    : emptyState("Nenhuma conta com limite — administrador não tem teto."),
    { subtitle: "Administrador não consome cota; o limite vale para o perfil de usuário." });

  out.querySelectorAll(".lm-set").forEach((b) => {
    b.onclick = () => promptOne("Ajustar limite", "Consultas por dia", async (v) => {
      await api(`/api/admin/users/${b.dataset.id}`, { method: "PATCH",
        body: { limite_diario: Number(v) } });
      toast("Limite atualizado.", "ok");
      go("contas");
    });
  });
}
