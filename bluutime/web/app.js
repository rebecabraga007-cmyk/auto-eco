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
// Canais cujo passo carrega texto — os demais (ligação, pesquisa) não têm modelo.
const PRECISA_MODELO = new Set(["EMAIL", "WHATSAPP", "SOCIAL"]);

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

document.getElementById("trocarMinhaSenha").addEventListener("click", trocarMinhaSenha);

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
const NIVEIS = ["sdr", "gestor", "admin"];

/** Esconde do menu o que o nível da sessão não alcança — a rota já bloqueia
 *  no servidor, isto só evita mostrar um link que vai dar 403. */
function aplicarPermissoesNav(nivel) {
  const meu = NIVEIS.indexOf(nivel);
  document.querySelectorAll("[data-min]").forEach((el) => {
    el.hidden = NIVEIS.indexOf(el.dataset.min) > meu;
  });
}

async function boot() {
  state.me = await api("/api/me");
  document.getElementById("navUser").textContent = state.me.name;
  document.getElementById("navAvatar").textContent = state.me.initials || "·";
  aplicarPermissoesNav(state.me.nivel || "sdr");
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
    // O esforço necessário vem junto: a meta sozinha diz onde chegar, o
    // esforço diz quanto trabalho falta para lá — e era o que ninguém via.
    const [g, esforco] = await Promise.all([
      api(`/api/flow/goals/${ref}/progress`),
      api(`/api/flow/goals/${ref}/calculate-effort`).catch(() => null),
    ]);
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

    const painelEsforco = esforco ? panel("Para bater a meta", grade([
      campo("Leads necessários", esforco.leadsNeeded),
      campo("Atividades necessárias", esforco.activitiesNeeded),
      campo("Atividades por SDR/dia", esforco.activitiesPerUserPerDay),
      campo("Dias úteis no mês", esforco.businessDays),
    ], 4), { subtitle: `Meta de conversão: ${Math.round((esforco.conversionRateGoal || 0) * 100)}%`
           }) : "";

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
      ${painelEsforco}
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
          ${PRECISA_MODELO.has(a.channel)
            // Passo de mensagem tem caminho próprio: o texto sai do modelo e a
            // entrega fica registrada, em vez de só marcar como feita.
            ? `<button class="btn btn-main btn-xs" data-enviar="${a.id}">Enviar</button>`
            : `<button class="btn btn-main btn-xs" data-exec="${a.id}">Executar</button>`}
          <button class="btn btn-default btn-xs" data-adiar="${a.id}">Adiar</button>
          <button class="btn btn-default btn-xs" data-skip="${a.id}">Ignorar</button>
          ${a.lead.status === "ON_EXTRA_ACTIVITY"
            // Só aparece para quem teve a cadência pausada por ter respondido —
            // é o único caso em que existe algo a retomar.
            ? `<button class="btn btn-default btn-xs" data-retomar="${a.lead.id}">Retomar cadência</button>`
            : ""}
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
    view.querySelectorAll("[data-enviar]").forEach((b) => {
      b.onclick = () => enviarAtividade(items.find((a) => String(a.id) === b.dataset.enviar));
    });
    view.querySelectorAll("[data-adiar]").forEach((b) => {
      b.onclick = () => adiarAtividade(items.find((a) => String(a.id) === b.dataset.adiar));
    });
    view.querySelectorAll("[data-retomar]").forEach((b) => {
      b.onclick = async () => {
        try {
          const r = await api(`/api/flow/execution/leads/${b.dataset.retomar}/resume`,
            { method: "POST", body: {} });
          toast(`${r.resumed} atividade(s) retomada(s).`, "ok");
          go("execucao");
        } catch (e) { toast(e.message, "err"); }
      };
    });
    view.querySelectorAll("[data-lead]").forEach((b) => {
      b.onclick = () => openLeadModal(Number(b.dataset.lead));
    });
  },
};

/** Envia a mensagem do passo — o texto vem do modelo da etapa. */
function enviarAtividade(act) {
  const m = modal({
    wide: true,
    title: `Enviar ${act.channel} para ${act.lead.name}`,
    body: `<div class="alert alert-info alert-styled-left" id="evAviso">
        Conferindo o modelo e o destino…
      </div>
      <div id="evPrev"></div>
      <div class="field">
        <label><input type="checkbox" id="evFora"> Enviar fora da janela de 9h–18h</label>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Enviar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;

  const disparar = async (forcar) => {
    const ok = m.root.querySelector("[data-ok]");
    ok.disabled = true;
    ok.innerHTML = `<span class="spinner"></span> enviando…`;
    try {
      const r = await api(`/api/envio/atividades/${act.id}`, { method: "POST", body: {
        forcar, foraDaJanela: m.root.querySelector("#evFora").checked } });
      const d = r.delivery;
      m.close();
      if (d.status === "BLOCKED") {
        // Bloqueio não conclui a atividade: ela continua na fila.
        toast(d.error, "err");
      } else {
        toast(d.status === "SENT" ? "Mensagem enviada."
                                  : "Registrado como SIMULADO — envio está desligado.", "ok");
      }
      go("execucao");
    } catch (e) {
      const faltando = /variáveis sem valor/i.test(e.message);
      m.root.querySelector("#evAviso").className = "alert alert-info alert-styled-left";
      m.root.querySelector("#evAviso").innerHTML = h(e.message);
      ok.disabled = false;
      ok.textContent = faltando ? "Enviar mesmo assim" : "Enviar";
      if (faltando) ok.onclick = () => disparar(true);
    }
  };
  m.root.querySelector("[data-ok]").onclick = () => disparar(false);
  m.root.querySelector("#evAviso").textContent =
    "O texto vem do modelo da etapa. Nada sai enquanto o envio estiver desligado.";
}

/** Reagenda a atividade — o servidor encaixa na próxima janela útil. */
function adiarAtividade(act) {
  const amanha = new Date(Date.now() + 864e5);
  const m = modal({
    title: `Adiar atividade de ${act.lead.name}`,
    body: `<div class="field"><label>Nova data e hora</label>
        <input class="form-control" type="datetime-local" id="adQuando"
               value="${amanha.toISOString().slice(0, 11)}${String(act.lead.bestHour).padStart(2, "0")}:00"></div>
      <span class="text-muted text-size-small">
        Fora do expediente, o servidor empurra para a próxima abertura — não existe
        atividade agendada para domingo de madrugada.</span>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Adiar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const v = m.root.querySelector("#adQuando").value;
    if (!v) return toast("Escolha a data.", "err");
    try {
      const r = await api(`/api/flow/execution/activities/${act.id}/reschedule`,
        { method: "POST", body: { scheduledAt: new Date(v).toISOString() } });
      m.close();
      toast(r.adjusted
        ? `Ajustado para a próxima janela útil: ${r.scheduledLocal.replace("T", " ")}.`
        : "Atividade adiada.", "ok");
      go("execucao");
    } catch (e) { toast(e.message, "err"); }
  };
}

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
          ${s.templateName
            ? `<span class="pill grey ml-5">modelo: ${h(s.templateName)}</span>`
            : PRECISA_MODELO.has(s.activity.channel)
              // Passo de mensagem sem modelo é recusado no envio: melhor dizer
              // aqui do que na hora de disparar para o lead.
              ? `<span class="pill amber ml-5">sem modelo — não envia</span>` : ""}
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
    const [acts, modelos] = await Promise.all([
      api("/api/flow/activities?limit=300"),
      api("/api/flow/templates"),
    ]);
    const lista = acts.data || acts;
    const inner = modal({
      title: "Adicionar etapa",
      body: `<div class="field"><label>Atividade</label>
          <select class="form-control" id="stepAct">${options(acts, "")}</select></div>
        <div class="field" id="stepTplBox"><label>Modelo de mensagem</label>
          <select class="form-control" id="stepTpl"></select>
          <span class="text-muted text-size-small" id="stepTplAviso"></span></div>
        <div class="field"><label>Dia da cadência</label>
          <input class="form-control" type="number" min="1" id="stepDay" value="1"></div>`,
      footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
               <button class="btn btn-main btn-sm" data-ok>Adicionar</button>`,
    });

    const selAct = inner.root.querySelector("#stepAct");
    const selTpl = inner.root.querySelector("#stepTpl");
    const box = inner.root.querySelector("#stepTplBox");
    const aviso = inner.root.querySelector("#stepTplAviso");
    // Só oferece modelo do mesmo canal da atividade — o backend recusa o
    // contrário, e escolher para depois levar 400 é atrito à toa.
    const refresh = () => {
      const act = lista.find((a) => String(a.id) === selAct.value);
      const canal = act ? act.channel : "";
      if (!PRECISA_MODELO.has(canal)) {
        box.style.display = "none";
        return;
      }
      box.style.display = "";
      const doCanal = modelos.filter((t) => t.channel === canal);
      selTpl.innerHTML = doCanal.length
        ? doCanal.map((t) => `<option value="${t.id}">${h(t.name)}</option>`).join("")
        : `<option value="">— nenhum modelo de ${h(canal)} —</option>`;
      aviso.textContent = doCanal.length
        ? `Passo de ${canal}: o texto vem deste modelo.`
        : `Não há modelo de ${canal}. Crie um em Modelos de mensagem, senão este passo não envia.`;
    };
    selAct.onchange = refresh;
    refresh();

    inner.root.querySelector("[data-cancel]").onclick = () => { inner.close(); openCadenceDetail(id); };
    inner.root.querySelector("[data-ok]").onclick = async () => {
      const body = {
        activityId: Number(selAct.value),
        day: Number(inner.root.querySelector("#stepDay").value),
      };
      if (box.style.display !== "none" && selTpl.value) body.templateId = Number(selTpl.value);
      try {
        await api(`/api/flow/cadences/${id}/steps`, { method: "POST", body });
        inner.close(); toast("Etapa adicionada.", "ok"); openCadenceDetail(id);
      } catch (e) { toast(e.message, "err"); }
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
    // Ligações derrubadas: conectou e caiu em até 10s. Não é falha técnica, é
    // sinal de abordagem — e não aparecia em tela nenhuma.
    const [ov, derrubadas] = await Promise.all([
      api("/api/dialer/calls/statistics/overview"),
      api("/api/dialer/calls/statistics/dropped").catch(() => ({ data: [] })),
    ]);
    const o = ov.data[0];
    const best = o.bestHourToCall;
    const listaDerrubadas = derrubadas.data || [];
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
      </div>`)}
      ${panel(`Derrubadas (${listaDerrubadas.length})`, listaDerrubadas.length
        ? table(["Quando", "SDR", "Lead", "Empresa", "Número", "Duração"],
            listaDerrubadas.slice(0, 60).map((c) => ({ cells: [
              fmtDateTime(c.originStarted),
              h((c.user || {}).name || "—"),
              h(c.flowLeadName || "—"),
              h(c.flowLeadCompany || "—"),
              h(c.receiverPhone || "—"),
              `${c.receiverConnectedDuration}s`,
            ] })), { scroll: true })
        : emptyState("Nenhuma ligação derrubada no período."),
        { subtitle: "Atendeu e desligou em até 10 segundos — sinal de abordagem, não de linha." })}`;
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
    // Estado do canal junto: uma lista vazia por não haver conversa é bem
    // diferente de uma lista vazia porque ninguém pareou o número, e antes as
    // duas apareciam idênticas.
    const [list, canais] = await Promise.all([
      api("/api/whatsapp/conversations"),
      api("/api/envio/canais").catch(() => null),
    ]);
    const wa = canais && canais.channels.find((c) => c.channel === "WHATSAPP");
    const aviso = !wa ? "" : wa.state === "CONNECTED"
      ? `<div class="alert alert-success alert-styled-left">
           Número conectado${wa.instance ? ` · ${h(wa.instance)}` : ""}.
           ${canais.sendingEnabled ? "" : "<strong>Envio desligado</strong> — mensagens ficam como SIMULATED."}
         </div>`
      : `<div class="alert alert-info alert-styled-left">
           WhatsApp <strong>${h(wa.state)}</strong>. ${h(wa.reason || "")}
           <a data-page="envio" style="cursor:pointer;text-decoration:underline">Parear número</a>.
         </div>`;
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

    view.innerHTML = `${aviso}<div class="split">
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
      // Município, avançado, resumo de filtros e estimativa de custo vivem
      // em bindEmpresaFilters — a tela só liga os dois botões.
      bindEmpresaFilters();
      document.getElementById("doSearch").onclick = () => runB2B(0);
      document.getElementById("doCobertura").onclick = testarCobertura;
    } else {
      document.getElementById("doSocios").onclick = () => runSocios(0);
    }
  },
};

/* Chips e tokens escrevem num <select multiple> escondido de mesmo id —
   assim `picked()` e o código que já ouvia esses campos continuam valendo. */
const chipsSync = (id, itens, selecionados, { compact = false } = {}) => `
  <div class="chip-grid${compact ? " compact" : ""}" data-chips="${id}">
    ${itens.map(([v, t]) => `<button type="button" class="chip${selecionados.includes(v) ? " active" : ""}"
      data-v="${h(v)}">${h(t)}</button>`).join("")}
  </div>
  <select id="${id}" multiple hidden>
    ${itens.map(([v]) => `<option value="${h(v)}"${selecionados.includes(v) ? " selected" : ""}></option>`).join("")}
  </select>`;

const tokenField = (id, itens, selecionados, placeholder) => `
  <div class="token-field" data-token="${id}">
    ${selecionados.map((v) => {
      const item = itens.find((i) => String(i.codigo) === String(v));
      return `<span class="token"><b>${h(item ? `${item.codigo} ${item.descricao}` : v)}</b><span data-rm="${h(v)}">×</span></span>`;
    }).join("")}
    <input type="text" list="dl-${id}" placeholder="${h(placeholder)}">
    <select id="${id}" multiple>
      ${selecionados.map((v) => `<option value="${h(v)}" selected></option>`).join("")}
    </select>
  </div>
  <datalist id="dl-${id}">
    ${itens.slice(0, 1600).map((i) => `<option value="${h(i.codigo)}">${h(i.codigo)} — ${h(i.descricao)}</option>`).join("")}
  </datalist>`;

/* Delegação: chips e tokens sobrevivem a qualquer re-render da tela. */
document.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip-grid[data-chips] .chip");
  if (chip) {
    const grade = chip.closest("[data-chips]");
    const sel = document.getElementById(grade.dataset.chips);
    const opt = [...sel.options].find((o) => o.value === chip.dataset.v);
    if (!opt) return;
    // "Todos" (valor vazio) é exclusivo: limpa o resto.
    if (chip.dataset.v === "") {
      [...sel.options].forEach((o) => { o.selected = false; });
      grade.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      opt.selected = true; chip.classList.add("active");
    } else {
      opt.selected = !opt.selected;
      chip.classList.toggle("active", opt.selected);
      const todos = grade.querySelector('.chip[data-v=""]');
      if (todos) { todos.classList.remove("active"); const o = [...sel.options][0]; if (o && o.value === "") o.selected = false; }
    }
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    atualizarResumoB2B();
    return;
  }
  const rm = e.target.closest(".token-field [data-rm]");
  if (rm) {
    const campo = rm.closest("[data-token]");
    const sel = document.getElementById(campo.dataset.token);
    [...sel.options].filter((o) => o.value === rm.dataset.rm).forEach((o) => o.remove());
    rm.closest(".token").remove();
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    atualizarResumoB2B();
  }
});

document.addEventListener("change", (e) => {
  const campo = e.target.closest(".token-field[data-token]");
  if (!campo || e.target.tagName !== "INPUT") return;
  const valor = e.target.value.trim();
  if (!valor) return;
  const codigo = valor.split(/[\s—-]/)[0].trim();
  const sel = document.getElementById(campo.dataset.token);
  if ([...sel.options].some((o) => o.value === codigo)) { e.target.value = ""; return; }
  const dl = document.getElementById(`dl-${campo.dataset.token}`);
  const achado = dl && [...dl.options].find((o) => o.value === codigo);
  if (!achado) return toast("Escolha um item da lista.", "err");
  sel.insertAdjacentHTML("beforeend", `<option value="${h(codigo)}" selected></option>`);
  e.target.insertAdjacentHTML("beforebegin",
    `<span class="token"><b>${h(achado.textContent)}</b><span data-rm="${h(codigo)}">×</span></span>`);
  e.target.value = "";
  sel.dispatchEvent(new Event("change", { bubbles: true }));
  atualizarResumoB2B();
});

/** Faixa que diz o que está filtrando — some a dúvida depois de rolar. */
function atualizarResumoB2B() {
  const alvo = document.getElementById("fResumo");
  if (!alvo) return;
  const rotulo = (id, prefixo) => {
    const sel = document.getElementById(id);
    if (!sel) return [];
    return [...sel.selectedOptions].filter((o) => o.value).map((o) => ({
      id, valor: o.value, texto: `${prefixo}${o.textContent ? o.textContent.slice(0, 34) : o.value}`,
    }));
  };
  const g = (id) => (document.getElementById(id)?.value || "").trim();
  const itens = [
    ...rotulo("fUf", ""), ...rotulo("fSituacao", ""), ...rotulo("fPorte", "porte "),
    ...rotulo("fCnae", "CNAE "), ...rotulo("fNatureza", "nat. "), ...rotulo("fMun", ""),
  ];
  const livres = [["fTexto", ""], ["fSetor", "setor "], ["fCnpj", "CNPJ "],
    ["fCapMin", "capital ≥ "], ["fCapMax", "capital ≤ "], ["fFundDe", "fundada ≥ "], ["fFundAte", "fundada ≤ "]];
  livres.forEach(([id, pre]) => { if (g(id)) itens.push({ id, valor: "", texto: pre + g(id) }); });

  const avancados = ["fPorte", "fCapMin", "fCapMax", "fFundDe", "fFundAte", "fTexto", "fSetor",
    "fCnpj", "fMei", "fEstab", "fNatureza", "fTipo", "fMun"]
    .filter((id) => {
      const el = document.getElementById(id);
      if (!el) return false;
      return el.multiple ? [...el.selectedOptions].some((o) => o.value) : !!(el.value || "").trim();
    }).length;
  const contador = document.getElementById("fAvCount");
  if (contador) {
    contador.textContent = avancados ? `${avancados} ativo${avancados > 1 ? "s" : ""}` : "nenhum ativo";
    contador.className = avancados ? "pill green" : "pill grey";
  }

  alvo.innerHTML = itens.length
    ? itens.map((i) => `<span class="token"><b>${h(i.texto)}</b><span data-limpa="${h(i.id)}"
        data-valor="${h(i.valor)}">×</span></span>`).join("") +
      `<span class="spacer" style="margin-left:auto"></span>
       <a id="fLimparTudo">limpar tudo</a>`
    : `<span class="text-muted text-size-small">Nenhum filtro — a busca traz as empresas mais recentes.</span>`;

  alvo.querySelectorAll("[data-limpa]").forEach((x) => {
    x.onclick = () => {
      const el = document.getElementById(x.dataset.limpa);
      if (!el) return;
      if (el.multiple) {
        [...el.options].filter((o) => o.value === x.dataset.valor).forEach((o) => {
          o.selected = false;
          if (el.closest(".token-field")) o.remove();
        });
        const grade = document.querySelector(`[data-chips="${x.dataset.limpa}"]`);
        if (grade) grade.querySelectorAll(`.chip[data-v="${x.dataset.valor}"]`).forEach((c) => c.classList.remove("active"));
        const campo = el.closest(".token-field");
        if (campo) campo.querySelectorAll(`[data-rm="${x.dataset.valor}"]`).forEach((r) => r.closest(".token").remove());
      } else { el.value = ""; }
      atualizarResumoB2B();
    };
  });
  const tudo = document.getElementById("fLimparTudo");
  if (tudo) tudo.onclick = () => { state.b2bFilters = { situacao: ["ATIVA"], com_telefone: true }; go("capiblu-empresas"); };
}

/** Filtro B2B: três decisões na frente, o resto atrás de um link com contador.
 *
 * A versão anterior despejava 18 controles em quatro grades sempre abertas,
 * quatro deles <select multiple size=5> — com 1300 CNAEs numa caixa de cinco
 * linhas. Aqui UF, CNAE e situação ficam visíveis; o resto é avançado.
 */
function empresaFilters(f, { cnaes, naturezas }) {
  const arr = (v) => Array.isArray(v) ? v.map(String) : v ? [String(v)] : [];
  return `
    <div class="filter-row" style="grid-template-columns:1.1fr 1.4fr .9fr">
      <div><label class="text-muted text-size-small">Estado <span class="text-grey">(clique para marcar)</span></label>
        ${chipsSync("fUf", UFS.map((u) => [u, u]), arr(f.uf), { compact: true })}</div>
      <div><label class="text-muted text-size-small">CNAE <span class="text-grey">— busque por código ou descrição</span></label>
        ${tokenField("fCnae", cnaes, arr(f.cnae), "digitar código ou atividade…")}</div>
      <div><label class="text-muted text-size-small">Situação cadastral</label>
        ${chipsSync("fSituacao", SITUACOES.filter(([v]) => v), arr(f.situacao || ["ATIVA"]))}</div>
    </div>

    <div class="adv-toggle">
      <a id="fAvToggle">▸ Filtros avançados</a>
      <span class="pill grey" id="fAvCount">nenhum ativo</span>
      <span class="text-muted text-size-small">porte, capital, fundação, MEI, matriz/filial, município, natureza, texto livre</span>
      <span class="spacer" style="margin-left:auto"></span>
      <label><input type="checkbox" id="fTel"${f.com_telefone !== false ? " checked" : ""}> Só com telefone</label>
      <label><input type="checkbox" id="fMail"${f.com_email ? " checked" : ""}> Só com e-mail</label>
    </div>

    <div class="adv-body" id="fAvBody" hidden>
      <div class="filter-row" style="grid-template-columns:repeat(3,1fr)">
        <div><label class="text-muted text-size-small">Porte <span class="text-grey">(múltiplo)</span></label>
          ${chipsSync("fPorte", PORTES.filter(([v]) => v), arr(f.porte))}</div>
        <div><label class="text-muted text-size-small">Natureza jurídica</label>
          ${tokenField("fNatureza", naturezas, arr(f.natureza), "digitar natureza…")}</div>
        <div><label class="text-muted text-size-small">Município
            <span class="text-grey" id="fMunAviso">— escolha uma UF primeiro</span></label>
          <select class="form-control input-sm" id="fMun" multiple size="4" disabled></select></div>
      </div>
      <div class="filter-row mt-10" style="grid-template-columns:repeat(4,1fr)">
        <div><label class="text-muted text-size-small">CNPJ exato <span class="text-grey">(ignora o resto)</span></label>
          <input class="form-control input-sm" id="fCnpj" placeholder="06990590000123"></div>
        <div><label class="text-muted text-size-small">Texto livre</label>
          <input class="form-control input-sm" id="fTexto" value="${h(f.texto || "")}"></div>
        <div><label class="text-muted text-size-small">Onde procurar o texto</label>
          <select class="form-control input-sm" id="fEscopo" multiple size="4">
            <option value="razao" selected>Razão social</option>
            <option value="fantasia" selected>Nome fantasia</option>
            <option value="cnae">Descrição do CNAE</option>
            <option value="natureza">Natureza jurídica</option>
          </select></div>
        <div><label class="text-muted text-size-small">Setor <span class="text-grey">(descrição de CNAE)</span></label>
          <input class="form-control input-sm" id="fSetor" placeholder="transporte rodoviário"></div>
      </div>
      <div class="filter-row mt-10" style="grid-template-columns:repeat(5,1fr)">
        <div><label class="text-muted text-size-small">Capital mínimo</label>
          <input class="form-control input-sm" type="number" id="fCapMin" value="${h(f.capital_min || "")}"></div>
        <div><label class="text-muted text-size-small">Capital máximo</label>
          <input class="form-control input-sm" type="number" id="fCapMax" value="${h(f.capital_max || "")}"></div>
        <div><label class="text-muted text-size-small">Fundada de</label>
          <input class="form-control input-sm" type="date" id="fFundDe" value="${h(f.fundada_de || "")}"></div>
        <div><label class="text-muted text-size-small">Fundada até</label>
          <input class="form-control input-sm" type="date" id="fFundAte" value="${h(f.fundada_ate || "")}"></div>
        <div><label class="text-muted text-size-small">Tipo de empresa</label>
          <select class="form-control input-sm" id="fTipo">
            <option value="">Todas</option><option value="privada">Privada</option><option value="publica">Pública</option>
          </select></div>
      </div>
      <div class="filter-row mt-10" style="grid-template-columns:repeat(2,1fr)">
        <div><label class="text-muted text-size-small">MEI</label>
          <select class="form-control input-sm" id="fMei">
            <option value="">Tanto faz</option><option value="optante">Somente MEI</option><option value="excluir">Excluir MEI</option>
          </select></div>
        <div><label class="text-muted text-size-small">Estabelecimento</label>
          <select class="form-control input-sm" id="fEstab">
            <option value="">Matriz e filial</option><option value="matriz">Somente matriz</option><option value="filial">Somente filial</option>
          </select></div>
      </div>
    </div>

    <div class="filter-summary" id="fResumo"></div>

    <div class="alert alert-info alert-styled-left" id="fCusto">
      Buscar empresas é <strong>grátis</strong> — sai da base local da Receita.
      <strong>Incluir decisores</strong> consome uma consulta Assertiva por decisor;
      a estimativa aparece aqui quando você ligar a opção.
    </div>

    <div class="toolbar" style="margin-bottom:0">
      <label><input type="checkbox" id="fDecisores"> Incluir decisores</label>
      <select class="form-control input-sm" id="fModelo" style="min-width:170px">
        <option value="">Atribuir custo ao modelo…</option>
      </select>
      <select class="form-control input-sm" id="fLimite" style="min-width:120px">
        ${[20, 50, 100, 200].map((n) => `<option value="${n}"${n === 50 ? " selected" : ""}>${n} por página</option>`).join("")}
      </select>
      <span class="spacer"></span>
      <button class="btn btn-default" id="doCobertura">Testar cobertura de decisores</button>
      <button class="btn btn-main" id="doSearch">Buscar empresas</button>
    </div>`;
}

/** Preenche o seletor de modelo (para atribuir o custo da busca) com os
 *  modelos salvos em "Minha planilha" — melhor-esforço, sem modelo nenhum o
 *  seletor só fica com o placeholder. */
async function popularSelectModelo(sel) {
  if (!sel) return;
  try {
    const r = await api("/api/capiblu/modelos");
    const modelos = r.modelos || r.data || (Array.isArray(r) ? r : []);
    modelos.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.nome || m.name || `Modelo ${m.id}`;
      sel.appendChild(opt);
    });
  } catch { /* segue sem modelos no seletor */ }
}

/** Liga o avançado, o município e a estimativa de custo. Chamada pela tela
 *  depois de inserir os filtros no DOM. */
function bindEmpresaFilters() {
  atualizarResumoB2B();
  const toggle = document.getElementById("fAvToggle");
  const corpo = document.getElementById("fAvBody");
  if (toggle && corpo) toggle.onclick = () => {
    corpo.hidden = !corpo.hidden;
    toggle.textContent = (corpo.hidden ? "▸" : "▾") + " Filtros avançados";
  };
  const uf = document.getElementById("fUf");
  const mun = document.getElementById("fMun");
  const aviso = document.getElementById("fMunAviso");
  const encherMunicipios = () => {
    const ufs = [...(uf?.selectedOptions || [])].map((o) => o.value);
    const lista = (state.municipios || []).filter((m) => !ufs.length || ufs.includes(m.uf));
    if (!ufs.length) {
      mun.innerHTML = ""; mun.disabled = true;
      if (aviso) aviso.textContent = "— escolha uma UF primeiro";
      return;
    }
    mun.disabled = false;
    if (aviso) aviso.textContent = `— ${lista.length} na${ufs.length > 1 ? "s" : ""} UF${ufs.length > 1 ? "s" : ""} escolhida${ufs.length > 1 ? "s" : ""}`;
    mun.innerHTML = lista.slice(0, 900).map((m) =>
      `<option value="${h(m.codigo)}">${h(m.descricao)}</option>`).join("");
  };
  if (uf && mun) { uf.addEventListener("change", encherMunicipios); encherMunicipios(); }
  [...document.querySelectorAll("#fAvBody input, #fAvBody select, #fResumo")].forEach((el) => {
    el.addEventListener("change", atualizarResumoB2B);
  });
  const dec = document.getElementById("fDecisores");
  const custo = document.getElementById("fCusto");
  if (dec && custo) dec.onchange = () => {
    const n = Number(document.getElementById("fLimite").value) || 50;
    custo.innerHTML = dec.checked
      ? `<strong>Atenção ao custo.</strong> Até ${n} empresas × 1 decisor ≈
         <strong>${fmtMoney(n * 0.119)}</strong> na Assertiva. O gasto é registrado no modelo escolhido.`
      : `Buscar empresas é <strong>grátis</strong> — sai da base local da Receita.
         <strong>Incluir decisores</strong> consome uma consulta Assertiva por decisor;
         a estimativa aparece aqui quando você ligar a opção.`;
  };
  popularSelectModelo(document.getElementById("fModelo"));
}

function collectEmpresaFilters() {
  const g = (id) => (document.getElementById(id)?.value || "").trim();
  const mei = g("fMei"), estab = g("fEstab"), tipo = g("fTipo");
  const filtros = {
    cnpj: g("fCnpj").replace(/\D/g, ""),
    texto: g("fTexto"), setor: g("fSetor"),
    texto_escopo: picked("fEscopo"),
    uf: picked("fUf"), municipio: picked("fMun"),
    cnae: picked("fCnae"), natureza: picked("fNatureza"),
    porte: picked("fPorte"),
    situacao: picked("fSituacao"),
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
    com_decisores: !!document.getElementById("fDecisores")?.checked,
    modelo_id: g("fModelo") || null,
  };
  Object.keys(filtros).forEach((k) => {
    const v = filtros[k];
    if (v === "" || v === 0 || v === false || v === null || (Array.isArray(v) && !v.length)) delete filtros[k];
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
    `<a class="emp-ficha" data-cnpj="${h((e.cnpj || "").replace(/\D/g, ""))}"
        style="cursor:pointer">${h(e.cnpj || "—")}</a>`,
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
  view.querySelectorAll(".emp-ficha").forEach((a) => {
    a.onclick = () => { state.fichaCnpj = a.dataset.cnpj; go("capiblu-empresa"); };
  });
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

/* ── Procurar pessoa ────────────────────────────────────────────────────
 *
 * Três coisas que a versão anterior não fazia e que vinham do CapiBLU:
 *  · exato e amplo são buscados **juntos** e viram abas com contagem, em vez
 *    de um checkbox que substitui o resultado;
 *  · filtros de sexo e faixa de nascimento rodam no cliente, sem nova consulta;
 *  · o ranking pontua cada candidato contra as pistas que o SDR já tem — e a
 *    fonte paga só é chamada para quem passou do limiar.
 */
const gente = {
  q: "", sexo: "", anoMin: 0, anoMax: 0, pistas: "",
  aba: "exatos",
  exatos: [], exatosCpf: new Set(),
  amplos: [], total: 0, buscados: 0,
  scores: {},          // cpf -> { pct, bateu: [] }
  mk: {},              // cpf -> payload do /mk (cache da sessão)
  abertos: new Set(),  // cpf expandido
  sel: new Set(),      // cpf selecionado
  limiar: 40,
  cpfDireto: "",       // busca direta por CPF, sem passar pelo nome
  cpfAba: "mk",        // fonte ativa: mk (grátis) ou assertiva (paga)
  cpfDados: {},        // fonte -> payload já consultado
  modo: "nome",        // aba ativa do painel de busca: nome | cpf
};

const PAGINA_GENTE = 10;
const CHAVE_RECENTES = "bluutime.gente.recentes";
const CHAVE_AUTORANK = "bluutime.gente.autorank";

/* O Mk não cobra, então pontuar os dez primeiros ao buscar é de graça e
   poupa um clique. Fica ligado por padrão e desligável — em conexão ruim são
   dez requisições que o SDR pode não querer esperar. */
const autoRankLigado = () => localStorage.getItem(CHAVE_AUTORANK) !== "off";
const definirAutoRank = (on) => {
  try { localStorage.setItem(CHAVE_AUTORANK, on ? "on" : "off"); } catch (e) {}
};

/** As últimas oito buscas ficam no navegador — repetir a consulta de ontem
 *  era redigitar o nome inteiro. O CapiBLU guarda no servidor (logBusca);
 *  aqui basta o local, porque a lista é pessoal e descartável. */
function lerRecentes() {
  try { return JSON.parse(localStorage.getItem(CHAVE_RECENTES) || "[]"); }
  catch (e) { return []; }
}
function guardarRecente(q, total) {
  const lista = lerRecentes().filter((x) => x.q !== q);
  lista.unshift({ q, total, quando: Date.now() });
  try { localStorage.setItem(CHAVE_RECENTES, JSON.stringify(lista.slice(0, 8))); }
  catch (e) { /* modo privado: segue sem histórico */ }
}

const pessoaFiltrada = (lista) => lista.filter((p) => {
  if (gente.sexo && !String(p.sexo || "").toUpperCase().startsWith(gente.sexo)) return false;
  const ano = parseInt(String(p.nascimento || "").slice(-4), 10);
  if (gente.anoMin && !(ano >= gente.anoMin)) return false;
  if (gente.anoMax && !(ano <= gente.anoMax)) return false;
  return true;
});

const amplosSemExatos = () => pessoaFiltrada(gente.amplos.filter((p) => !gente.exatosCpf.has(p.cpf)));
const listaAtual = () => gente.aba === "exatos" ? pessoaFiltrada(gente.exatos) : amplosSemExatos();

PAGES["capiblu-gente"] = {
  area: "CapiBLU", title: "Procurar pessoa",
  async render() {
    view.innerHTML = `
      ${panel("Procurar pessoa", `
        <ul class="nav nav-tabs" id="pModo">
          <li${gente.modo === "nome" ? ' class="active"' : ""}><a data-modo="nome">Não sei o CPF — buscar pelo nome</a></li>
          <li${gente.modo === "cpf" ? ' class="active"' : ""}><a data-modo="cpf">Sei o CPF — buscar direto</a></li>
        </ul>
        <div id="buscaNome" class="main-search mt-10"${gente.modo === "nome" ? "" : " hidden"}>
          <div class="form-group has-feedback has-feedback-left">
            <input class="form-control input-xlg" id="pName" placeholder="Nome completo ou parcial"
                   value="${h(gente.q)}">
            <div class="form-control-feedback">⌕</div>
            <div class="help-block" id="pHelp">Ao menos 3 caracteres. Busca exata e ampla saem juntas.</div>
          </div>
          <div class="filter-row" style="grid-template-columns:repeat(4,minmax(140px,1fr))">
            <div><label class="text-muted text-size-small">Sexo</label>
              <div class="chip-grid" id="pSexo">
                ${[["", "Todos"], ["F", "Feminino"], ["M", "Masculino"]].map(([v, t]) =>
                  `<button type="button" class="chip${gente.sexo === v ? " active" : ""}" data-v="${v}">${t}</button>`).join("")}
              </div></div>
            <div><label class="text-muted text-size-small">Nascido de</label>
              <input class="form-control input-sm" id="pAnoMin" type="number" placeholder="1970"
                     value="${gente.anoMin || ""}"></div>
            <div><label class="text-muted text-size-small">até</label>
              <input class="form-control input-sm" id="pAnoMax" type="number" placeholder="1990"
                     value="${gente.anoMax || ""}"></div>
            <div><label class="text-muted text-size-small">Pistas <span class="text-grey">— para o ranking</span></label>
              <input class="form-control input-sm" id="pPistas" placeholder="cidade, telefone ou empresa"
                     value="${h(gente.pistas)}"></div>
          </div>
          <div class="recentes" id="pRecentes"></div>
          <div class="toolbar mt-10" style="border:0;padding:0;background:none">
            <span class="text-muted text-size-small">Base local JBR — não gasta consulta.</span>
            <span class="spacer"></span>
            <button class="btn btn-main btn-sm" id="pSearch" ${gente.q.trim().length < 3 ? "disabled" : ""}>Buscar</button>
          </div>
          <div id="genteOut">${gente.exatos.length || gente.amplos.length ? "" : emptyState("Digite um nome para começar.")}</div>
        </div>
        <div id="buscaCpf" class="main-search mt-10"${gente.modo === "cpf" ? "" : " hidden"}>
          <div class="form-group has-feedback has-feedback-left">
            <input class="form-control input-xlg" id="pCpf" placeholder="CPF — só números" maxlength="14"
                   value="${h(gente.cpfDireto)}">
            <div class="form-control-feedback">⌕</div>
          </div>
          <div class="toolbar mt-10" style="border:0;padding:0;background:none">
            <span class="text-muted text-size-small">Mk é grátis · Assertiva cobra por CPF</span>
            <span class="spacer"></span>
            <button class="btn btn-main btn-sm" id="pCpfGo">Consultar</button>
          </div>
          <div id="cpfDiretoOut"></div>
        </div>`, { subtitle: "Recursos do CapiBLU dentro do fluxo de prospecção" })}`;

    document.getElementById("pModo").onclick = (e) => {
      const a = e.target.closest("[data-modo]"); if (!a) return;
      const novo = a.dataset.modo;
      if (novo === gente.modo) return;
      gente.modo = novo;
      document.querySelectorAll("#pModo > li").forEach((li) => li.classList.remove("active"));
      a.closest("li").classList.add("active");
      document.getElementById("buscaNome").hidden = gente.modo !== "nome";
      document.getElementById("buscaCpf").hidden = gente.modo !== "cpf";
      if (gente.modo === "cpf") {
        // limpa os restos da busca por nome
        gente.exatos = []; gente.amplos = []; gente.exatosCpf = new Set();
        gente.abertos = new Set(); gente.sel = new Set(); gente.scores = {};
        gente.q = ""; document.getElementById("pName").value = "";
        document.getElementById("genteOut").innerHTML = emptyState("Digite um nome para começar.");
      } else {
        // limpa os restos da busca por CPF
        gente.cpfDireto = ""; gente.cpfDados = {};
        document.getElementById("pCpf").value = "";
        document.getElementById("cpfDiretoOut").innerHTML = "";
      }
    };

    document.getElementById("pCpfGo").onclick = buscarCpfDireto;
    document.getElementById("pCpf").onkeydown = (e) => { if (e.key === "Enter") buscarCpfDireto(); };
    if (gente.cpfDireto) renderCpfDireto();

    const nome = document.getElementById("pName");
    const btn = document.getElementById("pSearch");
    nome.oninput = () => { gente.q = nome.value; btn.disabled = gente.q.trim().length < 3; };
    nome.onkeydown = (e) => { if (e.key === "Enter" && !btn.disabled) buscarGente(); };
    btn.onclick = buscarGente;

    document.getElementById("pSexo").onclick = (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      gente.sexo = b.dataset.v; go("capiblu-gente");
    };
    const num = (id, key) => {
      document.getElementById(id).onchange = (e) => {
        gente[key] = parseInt(e.target.value, 10) || 0;
        if (gente.exatos.length || gente.amplos.length) renderGente();
      };
    };
    num("pAnoMin", "anoMin"); num("pAnoMax", "anoMax");
    document.getElementById("pPistas").onchange = (e) => { gente.pistas = e.target.value; };
    renderRecentes();

    if (gente.exatos.length || gente.amplos.length) renderGente();
  },
};

function renderRecentes() {
  const alvo = document.getElementById("pRecentes");
  if (!alvo) return;
  const lista = lerRecentes();
  alvo.innerHTML = lista.length
    ? `<span class="text-muted text-size-small">Últimas buscas:</span>
       ${lista.map((x) => `<button type="button" class="chip" data-rec="${h(x.q)}"
          title="${x.total} resultado(s)">${h(x.q)}</button>`).join("")}`
    : "";
  alvo.querySelectorAll("[data-rec]").forEach((b) => {
    b.onclick = () => {
      document.getElementById("pName").value = b.dataset.rec;
      gente.q = b.dataset.rec;
      document.getElementById("pSearch").disabled = false;
      buscarGente();
    };
  });
}

async function buscarGente() {
  const q = document.getElementById("pName").value.trim();
  if (q.length < 3) return;
  gente.q = q;
  gente.pistas = document.getElementById("pPistas").value.trim();
  gente.exatos = []; gente.amplos = []; gente.exatosCpf = new Set();
  gente.total = 0; gente.buscados = 0; gente.scores = {};
  gente.abertos = new Set(); gente.sel = new Set(); gente.aba = "exatos";

  const out = document.getElementById("genteOut");
  out.innerHTML = LOADING;
  const pedir = (broad, limite, offset) =>
    api(`/api/capiblu/pessoas?q=${encodeURIComponent(q)}&broad=${broad}&limit=${limite}&offset=${offset}`)
      .catch((e) => ({ status: "error", message: e.message, pessoas: [] }));

  // As duas buscas saem juntas: a exata é curta, a ampla vem paginada.
  const [ex, am] = await Promise.all([pedir(false, 100, 0), pedir(true, PAGINA_GENTE, 0)]);
  if (ex.status === "error" && am.status === "error") {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(ex.message || am.message)}</div>`;
    return;
  }
  gente.exatos = ex.pessoas || [];
  gente.exatosCpf = new Set(gente.exatos.map((p) => p.cpf));
  gente.amplos = am.pessoas || [];
  gente.buscados = gente.amplos.length;
  gente.total = am.total || gente.amplos.length;
  if (!gente.exatos.length && gente.amplos.length) gente.aba = "amplos";
  guardarRecente(q, gente.exatos.length + gente.total);
  renderRecentes();
  renderGente();
  if (autoRankLigado()) calcularRanking(10, true);
}

async function carregarMaisAmplos(qtd) {
  const restante = gente.total - gente.buscados;
  const n = qtd === "todos" ? restante : Math.min(qtd, restante);
  if (n <= 0) return;
  const info = document.getElementById("gPagInfo");
  if (info) info.innerHTML = `<span class="spinner"></span> carregando…`;
  try {
    const r = await api(`/api/capiblu/pessoas?q=${encodeURIComponent(gente.q)}&broad=true&limit=${n}&offset=${gente.buscados}`);
    const novos = (r.pessoas || []).filter((p) => !gente.amplos.some((x) => x.cpf === p.cpf));
    gente.amplos = gente.amplos.concat(novos);
    gente.buscados += (r.pessoas || []).length;
    if (r.total) gente.total = r.total;
    if (!novos.length) gente.total = gente.buscados; // servidor sem offset: para de prometer mais
    renderGente();
  } catch (e) { toast(e.message, "err"); renderGente(); }
}

/* Pontuação: quanto do que o SDR já sabe aparece no perfil do candidato.
   Tudo vem do Mk, que é grátis — a Assertiva só entra acima do limiar. */
function normalizar(s) {
  return String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function achatar(obj, nivel = 0) {
  if (obj == null || nivel > 4) return "";
  if (typeof obj !== "object") return " " + obj;
  return Object.values(obj).map((v) => achatar(v, nivel + 1)).join(" ");
}
function pontuarPessoa(pessoa, payload) {
  const texto = normalizar(achatar(payload));
  const soDigitos = texto.replace(/[^0-9]/g, "");
  const pistas = gente.pistas.split(/[,;]+/).map((x) => x.trim()).filter((x) => x.length > 2);
  const bateu = [];
  let pontos = 0;
  pistas.forEach((pista) => {
    const digitos = pista.replace(/\D/g, "");
    const alvo = digitos.length >= 8 ? digitos : normalizar(pista);
    const onde = digitos.length >= 8 ? soDigitos : texto;
    if (alvo && onde.includes(alvo)) { pontos += 30; bateu.push(pista); }
  });
  // Sinais que não dependem de pista: ter telefone, ter e-mail, cadastro ativo.
  const p = payload.pessoa || payload.dados || payload || {};
  if ((p.telefones || payload.telefones || []).length) { pontos += 14; bateu.push("tem telefone"); }
  if ((p.emails || payload.emails || []).length) { pontos += 6; bateu.push("tem e-mail"); }
  if (/ativ/.test(normalizar(p.situacao_cpf || p.situacao))) { pontos += 6; bateu.push("CPF ativo"); }
  if (gente.exatosCpf.has(pessoa.cpf)) { pontos += 14; bateu.push("nome exato"); }
  const max = pistas.length * 30 + 40;
  return { pct: Math.min(100, Math.round((pontos / (max || 40)) * 100)), bateu };
}

async function calcularRanking(quantos, silencioso) {
  const lista = listaAtual().slice(0, quantos);
  if (!lista.length) return;
  const b = document.getElementById("gRank");
  if (b) { b.disabled = true; b.innerHTML = `<span class="spinner"></span> pontuando…`; }
  for (const p of lista) {
    if (gente.scores[p.cpf]) continue;
    try {
      const r = gente.mk[p.cpf] || await api(`/api/capiblu/pessoas/${p.cpf}/mk`);
      gente.mk[p.cpf] = r;
      gente.scores[p.cpf] = pontuarPessoa(p, r);
    } catch (e) { gente.scores[p.cpf] = { pct: null, bateu: [] }; }
  }
  renderGente();
  if (!silencioso) toast(`${lista.length} candidato(s) pontuado(s) — sem custo.`, "ok");
}

const scorePill = (sc) => {
  if (!sc || sc.pct == null) return `<span class="pill grey">—</span>`;
  const tom = sc.pct >= 70 ? "green" : sc.pct >= 40 ? "amber" : "grey";
  return `<span class="pill ${tom}">${sc.pct}%</span>`;
};

const primeiroTelefone = (payload) => {
  const p = (payload && (payload.pessoa || payload.dados || payload)) || {};
  const t = (p.telefones || (payload && payload.telefones) || [])[0];
  return t ? (t.display || t.numero || t.telefone || "") : "";
};

function renderGente() {
  const out = document.getElementById("genteOut");
  const lista = listaAtual();
  const visiveis = lista.slice(0, Math.max(PAGINA_GENTE, gente.buscados));
  const nExatos = pessoaFiltrada(gente.exatos).length;

  const linhas = visiveis.map((p) => {
    const sc = gente.scores[p.cpf];
    const mk = gente.mk[p.cpf];
    const tel = primeiroTelefone(mk);
    const aberto = gente.abertos.has(p.cpf);
    const conf = mk
      ? (tel ? `<span class="pill blue" data-verif="${h(p.cpf)}">verificar</span>`
             : `<span class="pill grey">sem telefone</span>`)
      : `<span class="text-muted">—</span>`;
    return `
      <tr${aberto ? ' class="row-open"' : ""}>
        <td class="check-cell"><input type="checkbox" data-sel="${h(p.cpf)}"${gente.sel.has(p.cpf) ? " checked" : ""}></td>
        <td>${scorePill(sc)}</td>
        <td>
          <div class="lead-media">
            <span class="lead-avatar-dot${sc && sc.pct >= 70 ? " success" : ""}">${h((p.nome || "?").slice(0, 2).toUpperCase())}</span>
            <div style="min-width:0">
              <strong>${h(p.nome || "—")}</strong>
              <div class="text-muted text-size-small">${h(p.sexo === "F" ? "feminino" : p.sexo === "M" ? "masculino" : p.sexo || "—")} · ${h(p.nascimento || "—")}</div>
            </div>
          </div>
        </td>
        <td class="nowrap">${fmtCPF(p.cpf)}</td>
        <td class="nowrap">${tel ? h(tel) : '<span class="text-muted">—</span>'}</td>
        <td id="conf-${h(p.cpf)}">${conf}</td>
        <td class="nowrap">
          <button class="btn btn-main btn-xs" data-plead="${h(p.cpf)}" data-pnome="${h(p.nome || "")}">Virar lead</button>
          <button class="btn btn-default btn-xs" data-pabrir="${h(p.cpf)}">${aberto ? "Fechar ▴" : "Abrir ▾"}</button>
        </td>
      </tr>
      ${aberto ? `<tr class="row-detail"><td colspan="7">${detalhePessoa(p)}</td></tr>` : ""}`;
  }).join("");

  const restante = gente.aba === "amplos" ? gente.total - gente.buscados : 0;
  const paginacao = `
    <div class="table-foot">
      <span class="text-muted text-size-small" id="gPagInfo">
        Mostrando ${visiveis.length}${gente.aba === "amplos" ? ` de ${gente.total}` : ""}
        ${nExatos ? ` · ${nExatos} com nome exato` : ""}
      </span>
      <span class="nowrap">
        ${restante > 0 ? [10, 25, 50].filter((n) => n <= restante)
            .map((n) => `<button class="btn btn-default btn-xs" data-mais="${n}">+${n}</button>`).join(" ") : ""}
        ${restante > 0 ? `<button class="btn btn-default btn-xs" data-mais="todos">Todos os ${gente.total}</button>` : ""}
      </span>
    </div>`;

  out.innerHTML = `
    <div class="panel panel-flat">
      <ul class="nav nav-tabs">
        <li${gente.aba === "exatos" ? ' class="active"' : ""}><a data-aba="exatos">Nome exato
          <span class="badge${gente.aba === "exatos" ? " badge-success" : ""}">${nExatos}</span></a></li>
        <li${gente.aba === "amplos" ? ' class="active"' : ""}><a data-aba="amplos">Outros sobrenomes
          <span class="badge${gente.aba === "amplos" ? " badge-success" : ""}">${gente.total}</span></a></li>
      </ul>
      <div class="toolbar" style="margin:0;border-width:0 0 1px;border-radius:0">
        <button class="btn btn-default btn-xs" id="gRank">Calcular ranking</button>
        <span class="text-muted text-size-small">puxar</span>
        <input class="form-control input-sm" id="gRankQtd" type="number" value="20" min="1" max="200" style="width:64px;min-width:0">
        <span class="text-muted text-size-small">Assertiva só acima de</span>
        <input class="form-control input-sm" id="gLimiar" type="number" value="${gente.limiar}" min="0" max="100" style="width:58px;min-width:0">
        <span class="text-muted text-size-small">%</span>
        <label class="text-muted text-size-small" title="Pontua os 10 primeiros ao buscar — o Mk não cobra">
          <input type="checkbox" id="gAuto"${autoRankLigado() ? " checked" : ""}> automático</label>
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="gExport">Exportar XLSX</button>
        <span class="text-muted text-size-small">Mk é grátis · Assertiva cobra por CPF</span>
      </div>
      <div class="selbar${gente.sel.size ? " on" : ""}">
        <strong>${gente.sel.size}</strong> selecionada(s)
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="gLote">Virar leads</button>
        <button class="btn btn-default btn-xs" id="gLimpar">Limpar</button>
      </div>
      ${lista.length ? `<div class="table-responsive"><table class="table table-striped table-hover">
        <thead><tr>
          <th class="check-cell"><input type="checkbox" id="gTodas"></th>
          <th style="width:64px">SCORE</th><th style="min-width:260px">PESSOA</th>
          <th>CPF</th><th>TELEFONE</th><th>CONFIANÇA</th><th></th>
        </tr></thead>
        <tbody>${linhas}</tbody></table></div>${paginacao}`
        : emptyState("Nenhum resultado com esses filtros.")}
    </div>`;

  out.querySelectorAll("[data-aba]").forEach((a) => {
    a.onclick = () => { gente.aba = a.dataset.aba; renderGente(); };
  });
  out.querySelectorAll("[data-mais]").forEach((b) => {
    b.onclick = () => carregarMaisAmplos(b.dataset.mais === "todos" ? "todos" : Number(b.dataset.mais));
  });
  document.getElementById("gRank").onclick = () => {
    gente.limiar = Number(document.getElementById("gLimiar").value) || 0;
    calcularRanking(Number(document.getElementById("gRankQtd").value) || 20);
  };
  out.querySelectorAll("[data-pabrir]").forEach((b) => {
    b.onclick = () => abrirPessoa(b.dataset.pabrir);
  });
  out.querySelectorAll("[data-plead]").forEach((b) => {
    b.onclick = () => openLeadForm({ name: b.dataset.pnome, cpf: b.dataset.plead });
  });
  out.querySelectorAll("[data-sel]").forEach((c) => {
    c.onchange = () => {
      c.checked ? gente.sel.add(c.dataset.sel) : gente.sel.delete(c.dataset.sel);
      renderGente();
    };
  });
  const todas = document.getElementById("gTodas");
  if (todas) todas.onchange = () => {
    visiveis.forEach((p) => todas.checked ? gente.sel.add(p.cpf) : gente.sel.delete(p.cpf));
    renderGente();
  };
  const auto = document.getElementById("gAuto");
  if (auto) auto.onchange = () => definirAutoRank(auto.checked);
  const exportar = document.getElementById("gExport");
  if (exportar) exportar.onclick = async () => {
    // Exporta o que está na tela — com score e telefone quando já pontuado.
    const alvo = gente.sel.size
      ? [...gente.exatos, ...gente.amplos].filter((p) => gente.sel.has(p.cpf))
      : visiveis;
    if (!alvo.length) return toast("Nada para exportar.", "err");
    exportar.disabled = true;
    try {
      await apiDownload("/api/capiblu/export/pessoas", {
        method: "POST",
        body: {
          columns: ["Nome", "CPF", "Nascimento", "Sexo", "Score", "Telefone"],
          rows: alvo.map((p) => ({
            Nome: p.nome || "", CPF: fmtCPF(p.cpf), Nascimento: p.nascimento || "",
            Sexo: p.sexo || "",
            Score: gente.scores[p.cpf] && gente.scores[p.cpf].pct != null
              ? `${gente.scores[p.cpf].pct}%` : "",
            Telefone: primeiroTelefone(gente.mk[p.cpf]) || "",
          })),
        },
        fallbackName: `pessoas-${gente.q.replace(/\s+/g, "-").toLowerCase()}.xlsx`,
      });
      toast(`${alvo.length} linha(s) exportada(s).`, "ok");
    } catch (e) { toast(e.message, "err"); }
    exportar.disabled = false;
  };
  const limpar = document.getElementById("gLimpar");
  if (limpar) limpar.onclick = () => { gente.sel = new Set(); renderGente(); };
  const lote = document.getElementById("gLote");
  if (lote) lote.onclick = () => {
    const nomes = [...gente.sel].map((cpf) => {
      const p = [...gente.exatos, ...gente.amplos].find((x) => x.cpf === cpf) || {};
      return { name: p.nome, cpf };
    });
    if (!nomes.length) return toast("Selecione ao menos uma pessoa.", "err");
    openLeadLote(nomes);
  };
  out.querySelectorAll("[data-verif]").forEach((s) => {
    s.onclick = () => verificarPosse(s.dataset.verif);
  });
}

/** Abre a pessoa na própria linha — sem modal, sem rolagem aninhada. */
async function abrirPessoa(cpf) {
  if (gente.abertos.has(cpf)) { gente.abertos.delete(cpf); return renderGente(); }
  gente.abertos.add(cpf);
  gente.blocoAtivo = gente.blocoAtivo || {};
  gente.blocoAtivo[cpf] = gente.blocoAtivo[cpf] || "mk";
  renderGente();
  if (!gente.mk[cpf]) {
    try {
      gente.mk[cpf] = await api(`/api/capiblu/pessoas/${cpf}/mk`);
    } catch (e) { gente.mk[cpf] = { status: "error", message: e.message }; }
    renderGente();
  }
}

const BLOCOS_PESSOA = [
  ["mk", "Perfil (Mk)", false],
  ["vinculos", "Vínculos (RAIS)", false],
  ["parentes", "Parentes", false],
  ["contacts", "Contatos (Serasa)", true],
];

function detalhePessoa(p) {
  const cpf = p.cpf;
  gente.blocoAtivo = gente.blocoAtivo || {};
  const ativo = gente.blocoAtivo[cpf] || "mk";
  const dados = (gente.blocos && gente.blocos[cpf] && gente.blocos[cpf][ativo])
    || (ativo === "mk" ? gente.mk[cpf] : null);
  const pago = (BLOCOS_PESSOA.find(([k]) => k === ativo) || [])[2];
  return `
    <div class="detail-box">
      <ul class="nav nav-tabs">
        ${BLOCOS_PESSOA.map(([k, t, cobra]) => `<li${ativo === k ? ' class="active"' : ""}>
          <a data-bloco="${k}" data-cpf="${h(cpf)}">${t}${cobra ? ' <span class="pill amber">paga</span>' : ""}</a></li>`).join("")}
        <li><a data-dossie="${h(cpf)}">Dossiê PDF <span class="pill amber">paga</span></a></li>
      </ul>
      <div class="detail-body">
        ${pago && !dados ? `<div class="alert alert-info alert-styled-left">
            Este bloco <strong>gasta consulta</strong>. Carrega só quando você pedir.
            <button class="btn btn-main btn-xs ml-5" data-carregar="${h(cpf)}">Consultar agora</button>
          </div>` : dados ? renderPessoa(dados, ativo === "mk" ? "mk" : ativo)
                          : `<span class="spinner"></span> <span class="text-muted ml-5">consultando…</span>`}
        ${ativo === "mk" && gente.scores[cpf] && gente.scores[cpf].bateu.length
          ? `<div class="detail-note">Bateu em: ${gente.scores[cpf].bateu.map(h).join(" · ")}.</div>` : ""}
      </div>
    </div>`;
}

/* Delegação: as abas do detalhe são recriadas a cada render. */
document.addEventListener("click", async (e) => {
  const aba = e.target.closest("[data-bloco]");
  if (aba) {
    const { bloco, cpf } = aba.dataset;
    gente.blocoAtivo = gente.blocoAtivo || {};
    gente.blocoAtivo[cpf] = bloco;
    renderGente();
    const cobra = (BLOCOS_PESSOA.find(([k]) => k === bloco) || [])[2];
    if (!cobra) carregarBlocoPessoa(cpf, bloco);
    return;
  }
  const carregar = e.target.closest("[data-carregar]");
  if (carregar) {
    const cpf = carregar.dataset.carregar;
    carregarBlocoPessoa(cpf, gente.blocoAtivo[cpf]);
    return;
  }
  const dossie = e.target.closest("[data-dossie]");
  if (dossie) {
    state.dossieDoc = dossie.dataset.dossie;
    go("capiblu-dossie");
  }
});

async function carregarBlocoPessoa(cpf, bloco) {
  gente.blocos = gente.blocos || {};
  gente.blocos[cpf] = gente.blocos[cpf] || {};
  if (gente.blocos[cpf][bloco]) return;
  if (bloco === "mk" && gente.mk[cpf]) { gente.blocos[cpf].mk = gente.mk[cpf]; return renderGente(); }
  try {
    const r = await api(`/api/capiblu/pessoas/${cpf}/${bloco}`);
    gente.blocos[cpf][bloco] = r;
    if (bloco === "mk") gente.mk[cpf] = r;
  } catch (e) {
    gente.blocos[cpf][bloco] = { status: "error", message: e.message };
  }
  renderGente();
}

/** Busca direta por CPF — a contraparte de "procure pelo nome" para quem já
 *  tem o documento em mãos. A fonte é escolhida na aba: Mk carrega na hora
 *  (grátis), Assertiva só quando pedida (gasta consulta). */
async function buscarCpfDireto() {
  const cpf = document.getElementById("pCpf").value.replace(/\D/g, "");
  if (cpf.length !== 11) return toast("CPF precisa ter 11 dígitos.", "err");
  gente.cpfDireto = cpf;
  gente.cpfAba = "mk";
  gente.cpfDados = {};
  renderCpfDireto();
  await carregarCpfDireto("mk");
}

async function carregarCpfDireto(fonte) {
  if (gente.cpfDados[fonte]) return renderCpfDireto();
  gente.cpfDados[fonte] = { loading: true };
  renderCpfDireto();
  try {
    const r = fonte === "assertiva"
      ? await api(`/api/capiblu/assertiva/cpf?q=${gente.cpfDireto}`)
      : await api(`/api/capiblu/pessoas/${gente.cpfDireto}/mk`);
    gente.cpfDados[fonte] = r;
  } catch (e) {
    gente.cpfDados[fonte] = { status: "error", message: e.message };
  }
  renderCpfDireto();
}

function renderCpfDireto() {
  const out = document.getElementById("cpfDiretoOut");
  if (!out) return;
  if (!gente.cpfDireto) { out.innerHTML = ""; return; }
  const ativo = gente.cpfAba;
  const dados = gente.cpfDados[ativo];
  const carregando = dados && dados.loading;
  out.innerHTML = `
    <div class="detail-box mt-10">
      <ul class="nav nav-tabs">
        <li${ativo === "mk" ? ' class="active"' : ""}><a data-cpfaba="mk">Perfil (Mk)</a></li>
        <li${ativo === "assertiva" ? ' class="active"' : ""}><a data-cpfaba="assertiva">Assertiva <span class="pill amber">paga</span></a></li>
      </ul>
      <div class="detail-body">
        ${ativo === "assertiva" && !dados
          ? `<div class="alert alert-info alert-styled-left">
               Esta consulta <strong>gasta crédito</strong> na Assertiva.
               <button class="btn btn-main btn-xs ml-5" id="cpfCarregarAssertiva">Consultar agora</button>
             </div>`
          : carregando
            ? `<span class="spinner"></span> <span class="text-muted ml-5">consultando…</span>`
            : dados
              ? (ativo === "mk" ? renderPessoa(dados, "mk") : renderAssertiva(dados, "cpf", gente.cpfDireto))
              : `<span class="spinner"></span> <span class="text-muted ml-5">consultando…</span>`}
      </div>
    </div>`;
  out.querySelectorAll("[data-cpfaba]").forEach((a) => {
    a.onclick = () => {
      gente.cpfAba = a.dataset.cpfaba;
      renderCpfDireto();
    };
  });
  const btnAssertiva = document.getElementById("cpfCarregarAssertiva");
  if (btnAssertiva) btnAssertiva.onclick = () => carregarCpfDireto("assertiva");
}

/** Confiança do telefone na própria linha: pertence + linha compartilhada. */
async function verificarPosse(cpf) {
  const cel = document.getElementById(`conf-${cpf}`);
  const tel = primeiroTelefone(gente.mk[cpf]).replace(/\D/g, "");
  if (!tel) return;
  if (cel) cel.innerHTML = `<span class="spinner"></span>`;
  try {
    const pessoa = [...gente.exatos, ...gente.amplos].find((x) => x.cpf === cpf) || {};
    await posseNaCelula(tel, cpf, `conf-${cpf}`, pessoa.nome || "");
  } catch (e) {
    if (cel) cel.innerHTML = `<span class="pill grey" title="${h(e.message)}">n/d</span>`;
  }
}

/** Vira várias pessoas em leads de uma vez, na mesma cadência. */
function openLeadLote(pessoas) {
  const m = modal({
    title: `Virar ${pessoas.length} pessoa(s) em lead`,
    body: `<div class="alert alert-info alert-styled-left">
        Os leads entram sem telefone confirmado; a validação continua disponível na ficha de cada um.
      </div>
      <div class="field"><label>Cliente</label>
        <select class="form-control" id="loteClient">${options(state.clients, "", { blank: "— sem cliente —" })}</select></div>
      <div class="field"><label>Cadência</label>
        <select class="form-control" id="loteCad">${options(state.cadences, "", { blank: "— sem cadência —" })}</select></div>
      <div class="field"><label>SDR responsável</label>
        <select class="form-control" id="loteSdr">${options(state.users, state.me && state.me.id)}</select></div>`,
    footer: `<button class="btn btn-default" id="loteCancel">Cancelar</button>
             <button class="btn btn-main" id="loteOk">Criar leads</button>`,
  });
  m.root.querySelector("#loteCancel").onclick = () => m.close();
  m.root.querySelector("#loteOk").onclick = async () => {
    const body = {
      client_id: m.root.querySelector("#loteClient").value || null,
      cadence_id: m.root.querySelector("#loteCad").value || null,
      sdr_id: m.root.querySelector("#loteSdr").value || null,
    };
    const btn = m.root.querySelector("#loteOk");
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> criando…`;
    let ok = 0;
    for (const p of pessoas) {
      try {
        await api("/api/flow/leads", { method: "POST", body: { name: p.name, cpf: p.cpf, ...body } });
        ok += 1;
      } catch (e) { /* segue: o relatório final diz quantos entraram */ }
    }
    m.close();
    toast(`${ok} de ${pessoas.length} lead(s) criado(s).`, ok ? "ok" : "err");
    gente.sel = new Set();
    renderGente();
  };
}

/* ── Vínculo empregatício ──────────────────────────────────────────────
 *
 * Uma tela responde as duas perguntas, trocando só o título e a fonte:
 * "quem trabalha nessa empresa" (RAIS pelo CNPJ) e "onde essa pessoa
 * trabalhou" (RAIS pelo CPF). Eram dois caminhos separados e o SDR precisa
 * pular de um para o outro no meio da investigação.
 */
PAGES["capiblu-vinculos"] = {
  area: "CapiBLU", title: "Vínculo empregatício",
  async render() {
    const modo = state.vinModo || "empresa";
    const doc = state.vinDoc || "";
    const porEmpresa = modo === "empresa";
    view.innerHTML = `
      <div class="panel panel-flat">
        <ul class="nav nav-tabs">
          <li${porEmpresa ? ' class="active"' : ""}><a data-vinmodo="empresa">Quem trabalha nessa empresa</a></li>
          <li${!porEmpresa ? ' class="active"' : ""}><a data-vinmodo="pessoa">Onde essa pessoa trabalhou</a></li>
        </ul>
        <div class="panel-body">
          <div class="alert alert-info alert-styled-left">
            ${porEmpresa
              ? "Quadro que a empresa declarou na RAIS — nome, CPF e admissão de cada um. Clique em alguém para abrir a pessoa."
              : "Empregos que a pessoa acumulou na RAIS, com cargo e período. Clique na empresa para abrir a ficha."}
            <strong>Gasta consulta.</strong>
          </div>
          <div class="field-row">
            <div class="field"><label>${porEmpresa ? "CNPJ da empresa" : "CPF da pessoa"}</label>
              <input class="form-control input-xlg" id="vinDoc" value="${h(doc)}"
                     placeholder="${porEmpresa ? "76.485.390/0001-07" : "somente números"}"></div>
            <div class="field" style="align-self:end">
              <button class="btn btn-main" id="vinGo">Consultar</button>
              <button class="btn btn-default ml-5" id="vinExport" hidden>Exportar XLSX</button></div>
          </div>
        </div>
      </div>
      <div id="vinOut">${doc ? LOADING : emptyState(porEmpresa ? "Informe um CNPJ." : "Informe um CPF.")}</div>`;

    view.querySelectorAll("[data-vinmodo]").forEach((a) => {
      a.onclick = () => {
        state.vinModo = a.dataset.vinmodo;
        state.vinDoc = "";
        go("capiblu-vinculos");
      };
    });

    const consultar = async () => {
      const limpo = document.getElementById("vinDoc").value.replace(/\D/g, "");
      const minimo = porEmpresa ? 14 : 11;
      if (limpo.length !== minimo) {
        return toast(porEmpresa ? "CNPJ precisa de 14 dígitos." : "CPF precisa de 11 dígitos.", "err");
      }
      state.vinDoc = limpo;
      const out = document.getElementById("vinOut");
      out.innerHTML = LOADING;
      try {
        const r = porEmpresa
          ? await api(`/api/capiblu/empresas/${limpo}/employees`)
          : await api(`/api/capiblu/pessoas/${limpo}/vinculos`);
        state.vinDados = r;
        out.innerHTML = porEmpresa ? renderQuadro(r, limpo) : panel("Vínculos da pessoa", renderVinculos(r),
          { subtitle: `CPF ${fmtCPF(limpo)} · consulta paga` });
        const exp = document.getElementById("vinExport");
        if (exp) exp.hidden = false;
      } catch (e) {
        out.innerHTML = `<div class="alert alert-warning alert-styled-left">${h(e.message)}</div>`;
      }
    };
    document.getElementById("vinGo").onclick = consultar;
    document.getElementById("vinDoc").onkeydown = (e) => { if (e.key === "Enter") consultar(); };
    document.getElementById("vinExport").onclick = async () => {
      const r = state.vinDados || {};
      const lista = r.funcionarios || r.employees || r.vinculos || r.data || [];
      if (!lista.length) return toast("Nada para exportar.", "err");
      try {
        await apiDownload("/api/capiblu/export/vinculos", {
          method: "POST", body: { rows: lista },
          fallbackName: `vinculos-${state.vinDoc}.xlsx`,
        });
        toast(`${lista.length} linha(s) exportada(s).`, "ok");
      } catch (e) { toast(e.message, "err"); }
    };
    if (doc) consultar();
  },
};

/** Quadro de funcionários declarado pela empresa. Cada linha é uma pessoa
 *  que pode virar lead — é isso que o CapiBLU não fazia. */
function renderQuadro(r, cnpj) {
  const lista = r.funcionarios || r.employees || r.data || r.registros || [];
  if (!lista.length) {
    return panel("Quadro de funcionários",
      emptyState("Nada declarado na RAIS para este CNPJ — comum em micro empresa."),
      { subtitle: `CNPJ ${fmtCNPJ(cnpj)}` });
  }
  const rows = lista.map((f) => {
    const cpf = String(f.cpf || f.documento || "").replace(/\D/g, "");
    const adm = f.admissao || f.data_admissao || f.inicio;
    return { cells: [
      `<strong>${h(f.nome || "—")}</strong>`,
      cpf ? fmtCPF(cpf) : '<span class="text-muted">—</span>',
      h(f.cargo || f.ocupacao || f.funcao || "—"),
      h(adm ? (fmtDate(adm) === "—" ? adm : fmtDate(adm)) : "—"),
      h(f.salario ? fmtMoney(Number(f.salario)) : "—"),
      cpf ? `<button class="btn btn-default btn-xs" data-vinpessoa="${h(cpf)}">Ver pessoa</button>
             <button class="btn btn-main btn-xs" data-vinlead="${h(cpf)}"
                     data-vinnome="${h(f.nome || "")}">Virar lead</button>` : "",
    ] };
  });
  const painel = panel(`${lista.length} pessoa(s) no quadro`,
    table(["Nome", "CPF", "Cargo", "Admissão", "Salário", ""], rows, { scroll: true }),
    { subtitle: `CNPJ ${fmtCNPJ(cnpj)} · declarado na RAIS · consulta paga` });
  setTimeout(() => {
    document.querySelectorAll("[data-vinpessoa]").forEach((b) => {
      b.onclick = () => {
        state.vinModo = "pessoa";
        state.vinDoc = b.dataset.vinpessoa;
        go("capiblu-vinculos");
      };
    });
    document.querySelectorAll("[data-vinlead]").forEach((b) => {
      b.onclick = () => openLeadForm({ name: b.dataset.vinnome, cpf: b.dataset.vinlead });
    });
  }, 0);
  return painel;
}

/* ── Consulta Assertiva ────────────────────────────────────────────────
 *
 * Todas as consultas aqui são pagas — por isso o tipo é escolhido antes, o
 * aviso de custo é fixo, e o status da credencial aparece na abertura, não
 * depois de a consulta falhar.
 */
const ASSERTIVA_TIPOS = [
  ["cpf", "CPF", "somente números", "Cadastro, endereços, telefones e e-mails do CPF."],
  ["cnpj", "CNPJ", "somente números", "Cadastro da empresa e possíveis decisores."],
  ["telefone", "Telefone", "DDD + número", "De quem é o número, pela Assertiva."],
  ["email", "E-mail", "nome@dominio.com", "A quem pertence o e-mail."],
  ["nome", "Nome", "nome completo", "Candidatos com esse nome. Aceita filtros."],
];

PAGES["capiblu-assertiva"] = {
  area: "CapiBLU", title: "Consulta Assertiva",
  async render() {
    const tipo = state.asTipo || "cpf";
    const meta = ASSERTIVA_TIPOS.find(([k]) => k === tipo) || ASSERTIVA_TIPOS[0];
    view.innerHTML = `
      <div class="panel panel-flat">
        <ul class="nav nav-tabs">
          ${ASSERTIVA_TIPOS.map(([k, t]) => `<li${tipo === k ? ' class="active"' : ""}>
            <a data-astipo="${k}">${t}</a></li>`).join("")}
        </ul>
        <div class="panel-body">
          <div class="alert alert-warning alert-styled-left">
            <strong>Consulta paga.</strong> ${h(meta[3])}
            Cada chamada é registrada no seu consumo — veja em
            <a data-page="capiblu-consumo">Consumo e custo</a>.
          </div>
          <div id="asStatus" class="help-block">verificando a credencial…</div>
          <div class="field-row">
            <div class="field"><label>${h(meta[1])}</label>
              <input class="form-control input-xlg" id="asQ" placeholder="${h(meta[2])}"></div>
            <div class="field" style="align-self:end">
              <button class="btn btn-main" id="asGo">Consultar</button></div>
          </div>
        </div>
      </div>
      <div id="asOut"></div>`;

    view.querySelectorAll("[data-astipo]").forEach((a) => {
      a.onclick = () => { state.asTipo = a.dataset.astipo; go("capiblu-assertiva"); };
    });

    api("/api/capiblu/assertiva/status").then((s) => {
      const el = document.getElementById("asStatus");
      if (!el) return;
      const ok = s.status === "ok" || s.ativo || s.autenticado;
      el.innerHTML = ok
        ? `<span class="pill green">credencial ativa</span>`
        : `<span class="pill amber">${h(s.message || s.detail || "credencial indisponível")}</span>`;
    }).catch(() => {
      const el = document.getElementById("asStatus");
      if (el) el.innerHTML = `<span class="pill grey">status desconhecido</span>`;
    });

    const consultar = async () => {
      const q = document.getElementById("asQ").value.trim();
      if (!q) return toast("Informe o que consultar.", "err");
      const out = document.getElementById("asOut");
      out.innerHTML = LOADING;
      try {
        const r = tipo === "nome"
          ? await api("/api/capiblu/assertiva/nome", { method: "POST", body: { nome: q } })
          : await api(`/api/capiblu/assertiva/${tipo}?q=${encodeURIComponent(q)}`);
        out.innerHTML = renderAssertiva(r, tipo, q);
      } catch (e) {
        out.innerHTML = `<div class="alert alert-warning alert-styled-left">${h(e.message)}</div>`;
      }
    };
    document.getElementById("asGo").onclick = consultar;
    document.getElementById("asQ").onkeydown = (e) => { if (e.key === "Enter") consultar(); };
  },
};

/** A Assertiva devolve formato diferente por tipo — o que dá para reconhecer
 *  vira tabela de gente; o resto cai no genérico, com o JSON à mão. */
function renderAssertiva(r, tipo, q) {
  const resp = r.resposta || r.data || r;
  const pessoas = resp.pessoas || resp.candidatos || resp.resultados || [];
  const corpo = pessoas.length
    ? table(["Nome", "Documento", "Nascimento", "Cidade", ""],
        pessoas.slice(0, 60).map((p) => {
          const doc = String(p.cpf || p.cnpj || p.documento || "").replace(/\D/g, "");
          return { cells: [
            `<strong>${h(p.nome || p.razaoSocial || p.nomeOuRazaoSocial || "—")}</strong>`,
            doc.length === 14 ? fmtCNPJ(doc) : fmtCPF(doc),
            h(p.nascimento || p.dataNascimento || "—"),
            h(p.cidade || p.municipio || "—"),
            doc.length === 11
              ? `<button class="btn btn-default btn-xs" data-pdet="${h(doc)}">Ver ficha</button>`
              : doc ? `<a data-ficha="${h(doc)}">Abrir ficha</a>` : "",
          ] };
        }), { scroll: true })
    : `${renderPessoa(r, "mk") || ""}
       <div class="sub-block"><h4>Resposta completa</h4>
         <div class="json-box">${h(JSON.stringify(r, null, 2))}</div></div>`;
  const painel = panel(`Assertiva · ${h(tipo)} · ${h(q)}`, corpo,
    { subtitle: "Consulta paga · registrada no consumo" });
  setTimeout(() => {
    document.querySelectorAll("[data-pdet]").forEach((b) => {
      b.onclick = () => { state.dossieDoc = b.dataset.pdet; go("capiblu-dossie"); };
    });
  }, 0);
  return painel;
}

PAGES["capiblu-telefone"] = {
  area: "CapiBLU", title: "De quem é este telefone",
  async render() {
    const aba = state.telAba || "reverso";
    view.innerHTML = `
      <div class="panel panel-flat">
        <ul class="nav nav-tabs">
          <li${aba === "reverso" ? ' class="active"' : ""}><a data-taba="reverso">De quem é o número</a></li>
          <li${aba === "posse" ? ' class="active"' : ""}><a data-taba="posse">Confirmar posse</a></li>
        </ul>
        <div class="panel-body">
          <div class="alert alert-info alert-styled-left">
            ${aba === "reverso"
              ? "Traz todos os CPFs e CNPJs atrelados ao número. <strong>Gasta uma consulta.</strong>"
              : "Responde se aquele número é mesmo daquele documento, e avisa quando a linha é compartilhada. <strong>Gasta uma consulta.</strong>"}
          </div>
          <div class="field-row">
            <div class="field"><label>Telefone com DDD</label>
              <input class="form-control input-xlg" id="tPhone" placeholder="41999998888"
                     value="${h(state.telPhone || "")}"></div>
            ${aba === "posse" ? `<div class="field"><label>CPF ou CNPJ</label>
              <input class="form-control input-xlg" id="tDoc" placeholder="somente números"></div>` : ""}
          </div>
          <button class="btn btn-main" id="tGo">Consultar</button>
        </div>
      </div>
      <div id="telOut"></div>`;

    view.querySelectorAll("[data-taba]").forEach((a) => {
      a.onclick = () => {
        state.telPhone = document.getElementById("tPhone").value;
        state.telAba = a.dataset.taba;
        go("capiblu-telefone");
      };
    });

    document.getElementById("tGo").onclick = async () => {
      const phone = document.getElementById("tPhone").value.replace(/\D/g, "");
      const doc = (document.getElementById("tDoc")?.value || "").replace(/\D/g, "");
      if (phone.length < 10) return toast("Informe o telefone com DDD.", "err");
      if (aba === "posse" && doc.length < 11) return toast("Informe o CPF ou CNPJ.", "err");
      const out = document.getElementById("telOut");
      out.innerHTML = LOADING;
      try {
        const r = await api(aba === "posse" ? `/api/capiblu/telefones/${phone}/pertence/${doc}`
                                           : `/api/capiblu/telefones/${phone}`);
        out.innerHTML = aba === "posse" ? renderPertence(r, phone, doc) : renderReverso(r, phone);
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
          <select class="form-control" id="dTipo">
            <option value="cnpj"${(state.dossieDoc || "").length === 14 ? " selected" : ""}>CNPJ</option>
            <option value="cpf"${(state.dossieDoc || "").length === 11 ? " selected" : ""}>CPF</option>
          </select></div>
        <div class="field"><label>Documento</label>
          <input class="form-control" id="dDoc" value="${h(state.dossieDoc || "")}"></div>
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

/* ── Modelos de mensagem ───────────────────────────────────────────────
 *
 * Eram 5 rotas prontas desde a fase 1 e sem tela — montar cadência de e-mail ou
 * WhatsApp exigia chamar a API na mão.
 */
const VARIAVEIS = [
  ["primeiro_nome", "Caio"], ["nome", "Caio Emiliano"], ["empresa", "Omeco"],
  ["razao_social", "OMECO IND. LTDA"], ["cargo", "Sócio-Administrador"],
  ["cidade", "Curitiba"], ["estado", "PR"], ["cnpj", "76485390000107"],
  ["email", "caio@omeco.com.br"], ["telefone", "(41) 99923-5178"],
  ["remetente", "Felipe Oliveira"], ["remetente_email", "felipe@blu.com.br"],
];

const CANAL_PILL = { EMAIL: "blue", WHATSAPP: "green", SOCIAL: "grey" };

PAGES["modelos-mensagem"] = {
  area: "Prospecção", title: "Modelos de mensagem",
  async render() {
    view.innerHTML = `
      <div class="toolbar">
        <span class="text-muted text-size-small">
          O texto de cada passo de e-mail, WhatsApp ou social. Use
          <code>{{primeiro_nome}}</code> e companhia — a pré-visualização mostra
          o resultado com um lead de verdade.
        </span>
        <span class="spacer"></span>
        <button class="btn btn-main btn-xs" id="tmNovo">Novo modelo</button>
      </div>
      <div id="tmOut">${LOADING}</div>`;
    document.getElementById("tmNovo").onclick = () => editarModelo(null);
    await listarModelosMensagem();
  },
};

async function listarModelosMensagem() {
  const out = document.getElementById("tmOut");
  try {
    const modelos = await api("/api/flow/templates");
    if (!modelos.length) {
      out.innerHTML = panel("Modelos", emptyState(
        "Nenhum modelo ainda. Sem modelo, um passo de e-mail não tem o que enviar."));
      return;
    }
    const rows = modelos.map((t) => ({ cells: [
      `<strong>${h(t.name)}</strong>`,
      `<span class="pill ${CANAL_PILL[t.channel] || "grey"}">${h(t.channel)}</span>`,
      h(t.subject || "—"),
      t.variables.length
        ? t.variables.map((v) => `<code class="text-size-small">${h(v)}</code>`).join(" ")
        : `<span class="text-muted">sem variável</span>`,
      `<button class="btn btn-default btn-xs tm-ver" data-id="${t.id}">Pré-visualizar</button>
       <button class="btn btn-default btn-xs tm-edit" data-id="${t.id}">Editar</button>
       <button class="btn btn-default btn-xs tm-del" data-id="${t.id}" data-nome="${h(t.name)}">Excluir</button>`,
    ] }));
    out.innerHTML = panel(`${modelos.length} modelos`,
      table(["Nome", "Canal", "Assunto", "Variáveis", ""], rows, { scroll: true }));

    const acha = (id) => modelos.find((t) => String(t.id) === id);
    out.querySelectorAll(".tm-ver").forEach((b) => {
      b.onclick = () => preverModelo(b.dataset.id);
    });
    out.querySelectorAll(".tm-edit").forEach((b) => {
      b.onclick = () => editarModelo(acha(b.dataset.id));
    });
    out.querySelectorAll(".tm-del").forEach((b) => {
      b.onclick = () => confirmDialog("Excluir modelo",
        `Excluir “${b.dataset.nome}”? Se algum passo de cadência usar este modelo, ele é apenas desativado.`,
        async () => {
          const r = await api(`/api/flow/templates/${b.dataset.id}`, { method: "DELETE" });
          toast(r.deactivated
            ? `Desativado — ${r.usedBySteps} passo(s) ainda apontam para ele.`
            : "Modelo excluído.", "ok");
          go("modelos-mensagem");
        });
    });
  } catch (e) {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

function editarModelo(t) {
  const novo = !t;
  const m = modal({
    wide: true,
    title: novo ? "Novo modelo" : `Editar “${t.name}”`,
    body: `
      <div class="field-row">
        <div class="field"><label>Nome</label>
          <input class="form-control" id="tmNome" value="${h(t ? t.name : "")}"></div>
        <div class="field"><label>Canal</label>
          <select class="form-control" id="tmCanal"${novo ? "" : " disabled"}>
            ${["EMAIL", "WHATSAPP", "SOCIAL"].map((c) =>
              `<option value="${c}"${t && t.channel === c ? " selected" : ""}>${c}</option>`).join("")}
          </select>
          ${novo ? "" : `<span class="text-muted text-size-small">
            O canal não muda depois: passos de cadência já apontam para ele.</span>`}</div>
      </div>
      <div class="field" id="tmAssuntoBox">
        <label>Assunto <span class="text-grey">(só e-mail)</span></label>
        <input class="form-control" id="tmAssunto" value="${h(t ? t.subject : "")}"></div>
      <div class="field"><label>Mensagem</label>
        <textarea class="form-control" id="tmCorpo" style="min-height:190px">${h(t ? t.body : "")}</textarea></div>
      <div class="field">
        <label class="text-muted text-size-small">Clique para inserir no cursor</label><br>
        ${VARIAVEIS.map(([v, ex]) => `<button type="button" class="btn btn-default btn-xs mr-10 mb-10"
          data-var="${v}" title="ex.: ${h(ex)}">{{${v}}}</button>`).join("")}
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });

  const corpo = m.root.querySelector("#tmCorpo");
  const assunto = m.root.querySelector("#tmAssunto");
  const canal = m.root.querySelector("#tmCanal");
  let ultimo = corpo;
  [corpo, assunto].forEach((el) => { el.onfocus = () => { ultimo = el; }; });

  const soEmail = () => {
    m.root.querySelector("#tmAssuntoBox").style.display =
      canal.value === "EMAIL" ? "" : "none";
  };
  canal.onchange = soEmail;
  soEmail();

  m.root.querySelectorAll("[data-var]").forEach((b) => {
    b.onclick = () => {
      // Insere no ponto do cursor, não no fim: escrever o texto e depois ter de
      // recortar a variável para o lugar certo é o que torna chip inútil.
      const el = ultimo;
      const ini = el.selectionStart ?? el.value.length;
      const fim = el.selectionEnd ?? el.value.length;
      const token = `{{${b.dataset.var}}}`;
      el.value = el.value.slice(0, ini) + token + el.value.slice(fim);
      el.focus();
      el.setSelectionRange(ini + token.length, ini + token.length);
    };
  });

  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const nome = m.root.querySelector("#tmNome").value.trim();
    if (!nome) return toast("Dê um nome ao modelo.", "err");
    if (!corpo.value.trim()) return toast("A mensagem está vazia.", "err");
    const body = { name: nome, subject: assunto.value, body: corpo.value };
    try {
      if (novo) {
        await api("/api/flow/templates", { method: "POST",
          body: { ...body, channel: canal.value, createdById: state.me.id } });
      } else {
        await api(`/api/flow/templates/${t.id}`, { method: "PATCH", body });
      }
      m.close();
      toast("Modelo salvo.", "ok");
      go("modelos-mensagem");
    } catch (e) { toast(e.message, "err"); }
  };
}

async function preverModelo(tid) {
  try {
    const p = await api(`/api/flow/templates/${tid}/preview`, { method: "POST", body: {} });
    modal({
      wide: true,
      title: `Como fica para ${p.leadName}`,
      body: `
        ${p.missing.length ? `<div class="alert alert-info alert-styled-left">
          <strong>Sem valor para este lead:</strong> ${p.missing.map(h).join(", ")}.
          A variável sai literal na mensagem.</div>` : ""}
        ${p.subject ? `<div class="field"><label>Assunto</label>
          <div class="json-box">${h(p.subject)}</div></div>` : ""}
        <div class="field"><label>Mensagem</label>
          <div class="json-box" style="white-space:pre-wrap">${h(p.body)}</div></div>`,
    });
  } catch (e) { toast(e.message, "err"); }
}

/* ── Envio: canais, entregas e trilha ──────────────────────────────────
 *
 * Toda a fase 3 respondia só por API. `POST /envio/teste` é o que confere a
 * configuração antes de encostar em lead real — e era o que não tinha botão.
 */
const ESTADO_PILL = {
  CONNECTED: "green", CONNECTING: "amber", DISCONNECTED: "red",
  UNREACHABLE: "red", NOT_CONFIGURED: "grey",
};

PAGES["envio"] = {
  area: "Prospecção", title: "Canais e entregas",
  async render() {
    const aba = state.envioAba || "canais";
    view.innerHTML = `
      <ul class="nav nav-tabs">
        ${[["canais", "Canais"], ["entregas", "Entregas"], ["trilha", "Trilha de acesso"]]
          .map(([k, t]) => `<li${aba === k ? " class=\"active\"" : ""}><a data-eaba="${k}">${t}</a></li>`).join("")}
      </ul>
      <div id="enOut">${LOADING}</div>`;
    view.querySelectorAll("[data-eaba]").forEach((a) => {
      a.onclick = () => { state.envioAba = a.dataset.eaba; go("envio"); };
    });
    try {
      await ({ canais: abaCanais, entregas: abaEntregas, trilha: abaTrilha }[aba])();
    } catch (e) {
      document.getElementById("enOut").innerHTML =
        `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    }
  },
};

async function abaCanais() {
  const out = document.getElementById("enOut");
  const r = await api("/api/envio/canais");
  out.innerHTML = `
    <div class="alert ${r.sendingEnabled ? "alert-success" : "alert-info"} alert-styled-left">
      ${r.sendingEnabled
        ? "<strong>Envio ligado.</strong> As mensagens saem de verdade para os leads."
        : `<strong>Envio desligado.</strong> Tudo volta como <code>SIMULATED</code> e fica
           registrado — nada chega a lead nenhum. Para ligar, defina
           <code>BLUUTIME_SEND=1</code> no <code>.env</code>.`}
    </div>
    ${r.channels.map((c) => panel(h(c.label), `
      <div class="filter-row" style="grid-template-columns:repeat(3,1fr)">
        <div><label class="text-muted text-size-small">Estado</label><br>
          <span class="pill ${ESTADO_PILL[c.state] || "grey"}">${h(c.state)}</span></div>
        <div><label class="text-muted text-size-small">Configurado</label><br>
          ${c.configured ? `<span class="pill green">sim</span>`
                         : `<span class="pill red">não</span>`}</div>
        <div><label class="text-muted text-size-small">
          ${c.channel === "EMAIL" ? "Remetente" : "Instância"}</label><br>
          <code>${h(c.from || c.instance || "—")}</code></div>
      </div>
      ${c.reason ? `<div class="alert alert-info alert-styled-left mt-10">${h(c.reason)}</div>` : ""}
      <div class="mt-10">
        <button class="btn btn-default btn-sm en-teste" data-canal="${c.channel}">
          Enviar teste para mim</button>
        ${c.channel === "WHATSAPP" && c.configured && c.state !== "CONNECTED"
          ? `<button class="btn btn-main btn-sm ml-5" id="waParear">Parear número</button>`
          : ""}
        ${c.channel === "WHATSAPP" && c.state === "CONNECTED"
          ? `<span class="text-muted text-size-small ml-5">Número pareado.</span>` : ""}
      </div>
      ${c.channel === "WHATSAPP" ? `<div id="waQr" class="mt-10"></div>` : ""}`)).join("")}`;

  out.querySelectorAll(".en-teste").forEach((b) => {
    b.onclick = () => testarCanal(b.dataset.canal);
  });
  const parear = document.getElementById("waParear");
  if (parear) parear.onclick = () => parearWhatsapp();
}

function testarCanal(canal) {
  const eEmail = canal === "EMAIL";
  const m = modal({
    title: `Teste de ${canal}`,
    body: `<div class="alert alert-info alert-styled-left">
        Manda para o destino que você informar — use o seu, não o de um lead.
      </div>
      <div class="field"><label>${eEmail ? "E-mail" : "Telefone com DDD"}</label>
        <input class="form-control" id="etDest" placeholder="${eEmail ? "voce@blusalesgroup.com.br" : "41999999999"}"></div>
      <div class="field"><label>Mensagem</label>
        <textarea class="form-control" id="etCorpo" style="min-height:90px">Teste do Bluutime.</textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Enviar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const to = m.root.querySelector("#etDest").value.trim();
    if (!to) return toast("Informe o destino.", "err");
    try {
      const r = await api("/api/envio/teste", { method: "POST", body: {
        channel: canal, to, body: m.root.querySelector("#etCorpo").value } });
      m.close();
      modal({ title: `Resultado: ${r.status}`, body: `
        <div class="alert ${r.status === "SENT" ? "alert-success" : "alert-info"} alert-styled-left">
          ${r.status === "SENT"
            ? "Aceito pelo provedor. Confira se chegou."
            : h(r.error || "Nada saiu.")}
        </div>
        <div class="json-box">${h(JSON.stringify(r, null, 2))}</div>` });
    } catch (e) { toast(e.message, "err"); }
  };
}

const STATUS_PILL = { SENT: "green", SIMULATED: "blue", BLOCKED: "amber", FAILED: "red" };

async function abaEntregas() {
  const out = document.getElementById("enOut");
  const f = state.entregaFiltro || {};
  const qs = new URLSearchParams(
    Object.entries(f).filter(([, v]) => v)).toString();
  const r = await api(`/api/envio/entregas${qs ? "?" + qs : ""}`);
  const rows = r.data.map((d) => ({ cells: [
    fmtDateTime(d.createdAt),
    `<span class="pill ${STATUS_PILL[d.status] || "grey"}">${h(d.status)}</span>`,
    h(d.channel),
    d.lead ? h(d.lead.name) : `<span class="text-muted">—</span>`,
    h(d.to || "—"),
    h(d.subject || "—"),
    d.error ? `<span class="text-muted text-size-small">${h(d.error)}</span>` : "—",
  ] }));
  out.innerHTML = `
    <div class="toolbar">
      <select class="form-control" id="efStatus">
        <option value="">Todos os status</option>
        ${["SENT", "SIMULATED", "BLOCKED", "FAILED"].map((s) =>
          `<option value="${s}"${f.status === s ? " selected" : ""}>${s}</option>`).join("")}
      </select>
      <select class="form-control" id="efCanal">
        <option value="">Todos os canais</option>
        ${["EMAIL", "WHATSAPP"].map((c) =>
          `<option value="${c}"${f.channel === c ? " selected" : ""}>${c}</option>`).join("")}
      </select>
      <span class="spacer text-muted text-size-small">
        É aqui que se responde “por que este lead não recebeu nada?”.</span>
    </div>
    ${panel(`${r.data.length} tentativas`, rows.length
      ? table(["Quando", "Status", "Canal", "Lead", "Destino", "Assunto", "Motivo"], rows, { scroll: true })
      : emptyState("Nenhuma tentativa de envio ainda."))}`;

  const aplica = () => {
    state.entregaFiltro = {
      status: document.getElementById("efStatus").value,
      channel: document.getElementById("efCanal").value,
    };
    go("envio");
  };
  document.getElementById("efStatus").onchange = aplica;
  document.getElementById("efCanal").onchange = aplica;
}

async function abaTrilha() {
  const out = document.getElementById("enOut");
  const acao = state.trilhaAcao || "";
  const r = await api(`/api/envio/auditoria${acao ? `?action=${acao}` : ""}`);
  const rows = r.data.map((l) => ({ cells: [
    fmtDateTime(l.at),
    h(l.actor),
    `<span class="pill ${l.level === "admin" ? "amber" : "grey"}">${h(l.level)}</span>`,
    `<code>${h(l.action)}</code>`,
    h(l.subject || "—"),
    l.status === 200 ? `<span class="pill green">200</span>`
                     : `<span class="pill red">${l.status}</span>`,
  ] }));
  out.innerHTML = `
    <div class="alert alert-info alert-styled-left">
      Quem acessou dado pessoal de quem. O documento aparece <strong>mascarado</strong>:
      a trilha existe para provar o acesso, não para republicar o CPF.
    </div>
    <div class="toolbar">
      <select class="form-control" id="trAcao">
        <option value="">Todas as ações</option>
        ${[...new Set(r.actions)].map((a) =>
          `<option value="${a}"${acao === a ? " selected" : ""}>${a}</option>`).join("")}
      </select>
      <span class="spacer"></span>
    </div>
    ${panel(`${r.data.length} acessos`, rows.length
      ? table(["Quando", "Quem", "Perfil", "Ação", "Alvo", "Resultado"], rows, { scroll: true })
      : emptyState("Nenhum acesso a dado pessoal registrado."))}`;
  document.getElementById("trAcao").onchange = (e) => {
    state.trilhaAcao = e.target.value; go("envio");
  };
}

/* ── Fichas do CapiBLU ─────────────────────────────────────────────────
 *
 * As rotas devolviam JSON completo e a tela mostrava `JSON.stringify` — era a
 * nota 6 da auditoria. Aqui viram ficha de verdade.
 *
 * Um cuidado atravessa as três: separar o que é **grátis** (base local da
 * Receita, já paga) do que **gasta consulta** (Assertiva, Mk). Bloco pago só
 * carrega quando o usuário pede.
 */
const fmtCNPJ = (v) => {
  const d = String(v || "").replace(/\D/g, "").padStart(14, "0");
  return d.length === 14
    ? `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12)}` : v;
};
const fmtCPF = (v) => {
  const d = String(v || "").replace(/\D/g, "");
  return d.length === 11 ? `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9)}` : (v || "—");
};
const fone = (ddd, num) => (ddd && num) ? `(${ddd.slice(0,2)}) ${num || ddd.slice(2)}` : (num || ddd || "");

/** Linha de "rótulo: valor" — o formato da ficha inteira. */
const campo = (label, valor) => `
  <div><span class="text-muted text-size-small">${h(label)}</span><br>
    <span>${valor === 0 || valor ? h(String(valor)) : "—"}</span></div>`;

const grade = (itens, cols = 4) => `
  <div class="filter-row" style="grid-template-columns:repeat(${cols},1fr);row-gap:14px">
    ${itens.join("")}</div>`;

const NIVEL_ROTULO = {
  1: ["green", "decide sozinho"], 2: ["blue", "decide na área"], 3: ["grey", "influencia"],
};

const fichaEmpresaBusca = { modo: "cnpj", texto: "", resultados: [] };

PAGES["capiblu-empresa"] = {
  area: "CapiBLU", title: "Ficha da empresa",
  async render() {
    const cnpj = state.fichaCnpj || "";
    view.innerHTML = `
      ${panel("Consultar CNPJ", `
        <ul class="nav nav-tabs" id="feModo">
          <li${fichaEmpresaBusca.modo === "cnpj" ? ' class="active"' : ""}><a data-modo="cnpj">Sei o CNPJ — buscar direto</a></li>
          <li${fichaEmpresaBusca.modo === "nome" ? ' class="active"' : ""}><a data-modo="nome">Não sei o CNPJ — buscar pelo nome</a></li>
        </ul>
        <div id="buscaCnpj" class="mt-10"${fichaEmpresaBusca.modo === "cnpj" ? "" : " hidden"}>
          <div class="filter-row" style="grid-template-columns:3fr 1fr">
            <div><input class="form-control input-xlg" id="fcCnpj"
                        placeholder="76.485.390/0001-07" value="${h(cnpj)}"></div>
            <div><button class="btn btn-main" style="width:100%" id="fcGo">Abrir ficha</button></div>
          </div>
          <div id="fcOut" class="mt-10">${cnpj ? LOADING : emptyState("Informe um CNPJ.")}</div>
        </div>
        <div id="buscaNomeEmpresa" class="mt-10"${fichaEmpresaBusca.modo === "nome" ? "" : " hidden"}>
          <div class="filter-row" style="grid-template-columns:3fr 1fr">
            <div><input class="form-control input-xlg" id="feTexto" placeholder="Razão social ou nome fantasia"
                        value="${h(fichaEmpresaBusca.texto)}"></div>
            <div><button class="btn btn-main" style="width:100%" id="feGo">Buscar</button></div>
          </div>
          <div id="feOut" class="mt-10"></div>
        </div>`, { subtitle: "Cadastro e QSA vêm da base local da Receita — não gastam consulta." })}`;

    document.getElementById("feModo").onclick = (e) => {
      const a = e.target.closest("[data-modo]"); if (!a) return;
      const novo = a.dataset.modo;
      if (novo === fichaEmpresaBusca.modo) return;
      fichaEmpresaBusca.modo = novo;
      document.querySelectorAll("#feModo > li").forEach((li) => li.classList.remove("active"));
      a.closest("li").classList.add("active");
      document.getElementById("buscaCnpj").hidden = fichaEmpresaBusca.modo !== "cnpj";
      document.getElementById("buscaNomeEmpresa").hidden = fichaEmpresaBusca.modo !== "nome";
      if (fichaEmpresaBusca.modo === "nome") {
        // limpa os restos da ficha por CNPJ
        state.fichaCnpj = "";
        document.getElementById("fcCnpj").value = "";
        document.getElementById("fcOut").innerHTML = emptyState("Informe um CNPJ.");
      } else {
        // limpa os restos da busca por nome
        fichaEmpresaBusca.texto = ""; fichaEmpresaBusca.resultados = [];
        document.getElementById("feTexto").value = "";
        document.getElementById("feOut").innerHTML = "";
      }
    };

    const abrir = () => {
      const v = document.getElementById("fcCnpj").value.replace(/\D/g, "");
      if (v.length !== 14) return toast("CNPJ precisa de 14 dígitos.", "err");
      state.fichaCnpj = v;
      go("capiblu-empresa");
    };
    document.getElementById("fcGo").onclick = abrir;
    document.getElementById("fcCnpj").onkeydown = (e) => { if (e.key === "Enter") abrir(); };

    document.getElementById("feGo").onclick = buscarEmpresaPorNome;
    document.getElementById("feTexto").onkeydown = (e) => { if (e.key === "Enter") buscarEmpresaPorNome(); };
    if (fichaEmpresaBusca.resultados.length) renderEmpresaBusca();

    if (cnpj) await renderFichaEmpresa(cnpj);
  },
};

async function buscarEmpresaPorNome() {
  const texto = document.getElementById("feTexto").value.trim();
  if (texto.length < 3) return toast("Digite ao menos 3 caracteres.", "err");
  fichaEmpresaBusca.texto = texto;
  const out = document.getElementById("feOut");
  out.innerHTML = LOADING;
  try {
    const r = await api(`/api/capiblu/empresas?texto=${encodeURIComponent(texto)}&limite=20`);
    fichaEmpresaBusca.resultados = r.empresas || [];
    renderEmpresaBusca();
  } catch (e) {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
  }
}

function renderEmpresaBusca() {
  const out = document.getElementById("feOut");
  if (!out) return;
  const lista = fichaEmpresaBusca.resultados;
  if (!lista.length) { out.innerHTML = emptyState("Nenhuma empresa encontrada."); return; }
  out.innerHTML = table(["Razão social", "CNPJ", "Município", "Situação", ""], lista.map((e) => ({ cells: [
    `<strong>${h(e.razao_social || e.nome_fantasia || "—")}</strong>
     ${e.nome_fantasia && e.razao_social ? `<br><span class="text-muted text-size-small">${h(e.nome_fantasia)}</span>` : ""}`,
    h(e.cnpj || "—"),
    `${h(e.municipio || "")}${e.uf ? `/${h(e.uf)}` : ""}`,
    `<span class="pill ${e.situacao === "ATIVA" ? "green" : "grey"}">${h(e.situacao || "—")}</span>`,
    `<button class="btn btn-default btn-xs" data-abrirempresa="${h((e.cnpj || "").replace(/\D/g, ""))}">Abrir ficha</button>`,
  ] })), { scroll: true });
  out.querySelectorAll("[data-abrirempresa]").forEach((b) => {
    b.onclick = () => {
      fichaEmpresaBusca.modo = "cnpj";
      state.fichaCnpj = b.dataset.abrirempresa;
      go("capiblu-empresa");
    };
  });
}

async function renderFichaEmpresa(cnpj) {
  const out = document.getElementById("fcOut");
  let c;
  try {
    c = (await api(`/api/capiblu/empresas/${cnpj}`)).company;
  } catch (e) {
    out.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    return;
  }
  const ativa = (c.descricao_situacao_cadastral || "").toUpperCase() === "ATIVA";
  const socios = c.qsa || [];
  out.innerHTML = `
    <div class="panel panel-flat">
      <div class="panel-heading has-border">
        <h2 class="panel-title">${h(c.razao_social || "—")}</h2>
        <div class="heading-elements">
          <span class="pill ${ativa ? "green" : "red"}">${h(c.descricao_situacao_cadastral || "—")}</span>
          <button class="btn btn-default btn-xs ml-5" id="fcLead">Virar lead</button>
        </div>
      </div>
      <div class="panel-body">
        ${c.nome_fantasia ? `<p class="text-muted">${h(c.nome_fantasia)}</p>` : ""}
        ${grade([
          campo("CNPJ", fmtCNPJ(c.cnpj)),
          campo("Abertura", c.data_inicio_atividade),
          campo("Porte", c.porte),
          campo("Capital social", c.capital_social
            ? Number(c.capital_social).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : null),
          campo("Natureza jurídica", c.natureza_juridica),
          campo("Matriz ou filial", c.descricao_identificador_matriz_filial),
          campo("Simples", c.opcao_pelo_simples ? "optante" : "não optante"),
          campo("MEI", c.opcao_pelo_mei ? "optante" : "não"),
        ])}
        <h4 style="font-size:13px;margin-top:20px">Atividade</h4>
        ${grade([campo(`CNAE ${c.cnae_fiscal || ""}`, c.cnae_fiscal_descricao)], 1)}
        <h4 style="font-size:13px;margin-top:20px">Onde fica e como falar</h4>
        ${grade([
          campo("Endereço", [c.descricao_tipo_de_logradouro, c.logradouro, c.numero, c.complemento]
            .filter(Boolean).join(" ")),
          campo("Bairro", c.bairro),
          campo("Município", [c.municipio, c.uf].filter(Boolean).join("/")),
          campo("CEP", c.cep),
          campo("Telefone 1", fone(c.ddd_telefone_1)),
          campo("Telefone 2", fone(c.ddd_telefone_2)),
          campo("E-mail", c.email),
          campo("Situação desde", c.data_situacao_cadastral),
        ])}
      </div>
    </div>

    ${panel(`Quadro societário (${socios.length})`, socios.length ? table(
      ["Sócio", "CPF/CNPJ", "Qualificação", "Entrada", "Faixa etária"],
      socios.map((s) => ({ cells: [
        `<strong>${h(s.nome_socio)}</strong>`,
        h(s.cnpj_cpf_do_socio || "—"),
        h(s.qualificacao_socio || "—"),
        h(s.data_entrada_sociedade || "—"),
        h(s.faixa_etaria || "—"),
      ] }))) : emptyState("Sem QSA na base da Receita."),
      { subtitle: "Base local — grátis." })}

    <div id="fcPagos">
      ${panel("Decisores, vínculos e conexões", `
        <div class="alert alert-info alert-styled-left">
          Estes blocos <strong>gastam consulta</strong> na Assertiva. Carregam só quando você pedir.
        </div>
        <button class="btn btn-main btn-sm mr-10" data-bloco="decisores">Quem manda aqui</button>
        <button class="btn btn-default btn-sm mr-10" data-bloco="vinculos">Vínculos (RAIS)</button>
        <button class="btn btn-default btn-sm" data-bloco="conexoes">Conexões</button>`)}
    </div>`;

  document.getElementById("fcLead").onclick = () => openLeadForm({
    company: c.nome_fantasia || c.razao_social, razaoSocial: c.razao_social,
    cnpj: c.cnpj, city: c.municipio, state: c.uf,
    phone: fone(c.ddd_telefone_1), email: c.email || "",
  });
  view.querySelectorAll("[data-bloco]").forEach((b) => {
    b.onclick = () => carregarBloco(cnpj, b.dataset.bloco);
  });
}

async function carregarBloco(cnpj, bloco) {
  const alvo = document.getElementById("fcPagos");
  const antes = alvo.innerHTML;
  alvo.innerHTML = `<div class="alert alert-info alert-styled-left"><span class="spinner"></span>
    Consultando ${h(bloco)}…</div>` + antes;
  try {
    const r = await api(`/api/capiblu/empresas/${cnpj}/${bloco}`);
    alvo.innerHTML = ({ decisores: blocoDecisores, vinculos: blocoLista,
                        conexoes: blocoLista })[bloco](r, bloco) + antes;
    view.querySelectorAll("[data-bloco]").forEach((b) => {
      b.onclick = () => carregarBloco(cnpj, b.dataset.bloco);
    });
  } catch (e) {
    alvo.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>` + antes;
  }
}

function blocoDecisores(r) {
  const dec = r.decisores || [];
  const cad = r.cadastro_assertiva || {};
  const niv = r.por_nivel || {};
  const linhas = dec.map((d) => {
    const [cor, rot] = NIVEL_ROTULO[d.nivel] || ["grey", d.rotulo || "—"];
    return { cells: [
      `<strong>${h(d.nome)}</strong>`,
      fmtCPF(d.cpf),
      h(d.cargo || "—"),
      `<span class="pill ${cor}">nível ${h(d.nivel || "—")} · ${h(rot)}</span>`,
      h(d.area || "—"),
      h(d.fonte_cargo || "—"),
    ] };
  });
  return panel(`Decisores (${r.total || dec.length})`,
    `${grade([
      campo("Funcionários", cad.quantidade_funcionarios),
      campo("Porte (Assertiva)", cad.porte),
      campo("Idade da empresa", cad.idade_empresa ? `${cad.idade_empresa} anos` : null),
      campo("Situação", cad.situacao),
    ])}
    <div class="mt-10 mb-20">
      ${[1, 2, 3].map((n) => {
        const [cor, rot] = NIVEL_ROTULO[n];
        return `<span class="pill ${cor} mr-10">nível ${n} · ${rot}: <strong>${niv["nivel_" + n] ?? 0}</strong></span>`;
      }).join("")}
    </div>
    ${linhas.length ? table(["Nome", "CPF", "Cargo", "Nível", "Área", "Fonte"], linhas, { scroll: true })
      : emptyState("Nenhum decisor encontrado — em micro empresa isso é comum; use o QSA.")}`,
    { subtitle: "Consulta paga · Assertiva" });
}

/** Vínculos e conexões variam de forma; renderiza o que houver de lista. */
function blocoLista(r, bloco) {
  const lista = r.vinculos || r.conexoes || r.registros || r.data || [];
  if (!Array.isArray(lista) || !lista.length) {
    return panel(bloco, emptyState("Nada encontrado."), { subtitle: "Consulta paga" });
  }
  const cols = [...new Set(lista.flatMap((x) => Object.keys(x)))].slice(0, 8);
  return panel(`${bloco} (${lista.length})`, table(
    cols.map((c) => c.replace(/_/g, " ")),
    lista.map((x) => ({ cells: cols.map((c) => {
      const v = x[c];
      return h(typeof v === "object" && v !== null ? JSON.stringify(v).slice(0, 40) : String(v ?? "—").slice(0, 40));
    }) })), { scroll: true }), { subtitle: "Consulta paga · Assertiva" });
}

/* ── Renderização das fichas de pessoa e telefone ─────────────────────── */

/** Cadastro, perfil Mk, vínculos, parentes ou contatos — cada bloco tem forma
 *  própria, então o que não for reconhecido cai numa tabela genérica em vez de
 *  virar JSON cru. */
function renderPessoa(r, bloco) {
  if (r.status === "unavailable" || r.status === "error") {
    return `<div class="alert alert-info alert-styled-left">${h(r.message || r.detail || "Indisponível.")}</div>`;
  }
  if (!bloco && r.pessoa) {
    const p = r.pessoa;
    return grade([
      campo("Nome", p.nome), campo("CPF", fmtCPF(p.cpf)),
      campo("Nascimento", p.nascimento),
      campo("Sexo", p.sexo === "F" ? "feminino" : p.sexo === "M" ? "masculino" : p.sexo),
    ], 2);
  }
  if (bloco === "mk") return renderMk(r);
  if (bloco === "parentes") return renderParentes(r);
  if (bloco === "vinculos") return renderVinculos(r);
  if (bloco === "contacts") return renderContatos(r);
  return tabelaGenerica(r);
}

function renderMk(r) {
  // A resposta de verdade do integrax-cpf vem em r.data (não r.dados) — e
  // nome/cpf/renda/score ficam um nível abaixo, em DadosBasicos/DadosEconomicos.
  // As listas (telefones, enderecos, empresas, vizinhos, beneficios) já vêm
  // soltas no nível de cima, então essas continuam batendo direto.
  const p = r.pessoa || r.data || r.dados || r;
  const basicos = p.DadosBasicos || {};
  const economicos = p.DadosEconomicos || {};
  const tels = p.telefones || r.telefones || [];
  const ends = p.enderecos || r.enderecos || [];
  const mails = p.emails || r.emails || [];
  // Quatro blocos que vêm no mesmo payload e antes eram descartados.
  const empresas = p.empresas || r.empresas || p.qsa || r.qsa || [];
  const vizinhos = p.vizinhos || r.vizinhos || [];
  const consumo = p.perfilConsumo || p.perfil_consumo || r.perfil_consumo || {};
  const beneficios = (p.beneficios || r.beneficios || []).filter((b) => b && (b.valor || b.recebimento || b.beneficio || b.totalRecebido));
  const nome = basicos.nome || p.nome || "";
  const cpf = String(basicos.cpf || p.cpf || "").replace(/\D/g, "");
  const situacao = (basicos.situacaoCadastral || {}).descricaoSituacaoCadastral || p.situacao_cpf || p.situacao;
  const score = (economicos.score || {}).scoreCSB || p.score;

  const bloco = (titulo, corpo, extra = "") => corpo
    ? `<div class="sub-block"><h4>${h(titulo)}${extra}</h4>${corpo}</div>` : "";

  return `
    ${grade([
      campo("Nome", nome), campo("CPF", fmtCPF(cpf)),
      campo("Nascimento", basicos.dataNascimento || p.nascimento || p.data_nascimento),
      campo("Mãe", basicos.nomeMae || p.nome_mae), campo("Renda estimada", economicos.renda || p.renda),
      campo("Score", score), campo("Escolaridade", basicos.escolaridade || p.escolaridade),
      campo("Situação do CPF", situacao),
    ])}
    ${bloco(`Telefones (${tels.length})`,
      tels.length ? table(["Número", "Tipo", "WhatsApp", "Confiança", "Atualizado"],
        tels.slice(0, 12).map((t, i) => {
          const num = String(t.display || t.numero || t.telefone || "").replace(/\D/g, "");
          return { cells: [
            `<strong>${h(t.display || t.numero || t.telefone || "—")}</strong>`,
            h(t.categoria || t.tipo || "—"),
            t.whatsapp ? `<span class="pill green">sim</span>` : `<span class="text-muted">—</span>`,
            `<span id="tp-${h(cpf)}-${i}">${num && cpf
              ? `<a data-posse="${h(num)}" data-doc="${h(cpf)}" data-cel="tp-${h(cpf)}-${i}"
                    data-nome="${h(nome)}">verificar</a>`
              : '<span class="text-muted">—</span>'}</span>`,
            h(t.atualizacao || t.data || t.status || "—"),
          ] };
        }), { scroll: true }) : "",
      tels.length && cpf ? `<button class="btn btn-default btn-xs" data-posse-todos="${h(cpf)}">Verificar todos</button>` : "")}
    ${bloco("E-mails", mails.length
      ? `<p>${mails.slice(0, 8).map((e) => h(typeof e === "string" ? e : e.email)).join(" · ")}</p>` : "")}
    ${bloco(`Endereços (${ends.length})`, ends.length
      ? table(["Endereço", "Bairro", "Cidade", "CEP"], ends.slice(0, 8).map((e) => ({ cells: [
          h(endereco(e)), h(e.bairro || "—"),
          h([e.cidade || e.municipio, e.uf].filter(Boolean).join("/")), h(e.cep || "—"),
        ] })), { scroll: true }) : "")}
    ${bloco(`Empresas e participações (${empresas.length})`, empresas.length
      ? table(["Razão social", "CNPJ", "Participação", ""], empresas.slice(0, 12).map((e) => {
          const doc = String(e.cnpj || e.documento || "").replace(/\D/g, "");
          return { cells: [
            `<strong>${h(e.razao_social || e.nome || e.empresa || e.relacao || "—")}</strong>`,
            fmtCNPJ(doc),
            h(e.qualificacao || e.participacao || e.cargo || e.tipoRelacao || "—"),
            doc ? `<a data-ficha="${h(doc)}">Abrir ficha</a>` : "",
          ] };
        }), { scroll: true }) : "")}
    ${bloco(`Vizinhos (${vizinhos.length})`, vizinhos.length
      ? table(["Nome", "CPF", "Telefone"], vizinhos.slice(0, 10).map((v) => ({ cells: [
          h(v.nome || "—"), fmtCPF(v.cpf),
          h((v.telefones && v.telefones[0] && (v.telefones[0].display || v.telefones[0].numero)) || v.telefone || "—"),
        ] })), { scroll: true }) : "")}
    ${bloco("Perfil de consumo", Object.keys(consumo).length
      ? `<div class="tag-wrap">${Object.entries(consumo)
          .filter(([k, v]) => k.startsWith("possui_") && v === true)
          .map(([k]) => `<span class="pill green">${h(k.replace(/^possui_/, "").replace(/_/g, " "))}</span>`).join(" ")}</div>
        <div class="help-block">Sinais de consumo confirmados pela base.</div>` : "")}
    ${bloco(`Benefícios (${beneficios.length})`, beneficios.length
      ? table(["Benefício", "Situação", "Valor"], beneficios.slice(0, 8).map((b) => ({ cells: [
          h(b.beneficio || b.descricao || "—"), h(b.situacao || b.recebimento || "—"),
          h(b.totalRecebido || (b.valor ? fmtMoney(Number(b.valor)) : "—")),
        ] })), { scroll: true }) : "")}`;
}

/* Verificação de posse dentro da ficha: uma linha ou todas. */
document.addEventListener("click", async (e) => {
  const um = e.target.closest("[data-posse]");
  if (um) return posseNaCelula(um.dataset.posse, um.dataset.doc, um.dataset.cel, um.dataset.nome);
  const todos = e.target.closest("[data-posse-todos]");
  if (todos) {
    const doc = todos.dataset.posseTodos;
    todos.disabled = true;
    for (const a of [...document.querySelectorAll(`[data-posse][data-doc="${doc}"]`)]) {
      await posseNaCelula(a.dataset.posse, doc, a.dataset.cel);
    }
    todos.disabled = false;
    return;
  }
  const ficha = e.target.closest("[data-ficha]");
  if (ficha) { state.fichaCnpj = ficha.dataset.ficha; go("capiblu-empresa"); }
});

/** Selo de confiança do telefone: posse (WorkAPI) + dono do WhatsApp.
 *
 * As duas fontes respondem coisas diferentes — "de quem é a linha" e "quem
 * atende" — e o SDR precisa das duas antes de ligar ou mandar mensagem. O
 * DonoDoZap é melhor-esforço: se não responder, fica só a posse.
 */
async function posseNaCelula(phone, doc, celId, nome) {
  const cel = document.getElementById(celId);
  if (cel) cel.innerHTML = `<span class="spinner"></span>`;
  let selo = `<span class="pill grey">n/d</span>`;
  try {
    const r = await api(`/api/capiblu/telefones/${phone}/pertence/${doc}`);
    const ok = r.pertence ?? r.atrelado ?? r.confirmado;
    const compart = r.compartilhada ?? r.linha_compartilhada;
    const n = r.total ?? r.vinculos ?? null;
    selo = compart
      ? `<span class="pill blue" title="A linha aparece para mais de um documento">compart.${n ? ` (${n})` : ""}</span>`
      : ok ? `<span class="pill green">confirmado</span>` : `<span class="pill amber">não confirmado</span>`;
  } catch (err) {
    selo = `<span class="pill grey" title="${h(err.message)}">n/d</span>`;
  }
  if (cel) cel.innerHTML = selo;
  try {
    const z = await api(`/api/capiblu/telefones/${phone}/donodozap` +
                        (nome ? `?nome=${encodeURIComponent(nome)}` : ""));
    if (z.status === "unavailable" || !cel) return;
    const bate = z.confere ?? z.match_ok ?? (z.match ? true : null);
    const quem = z.nome || z.match || "";
    if (z.alerta_compartilhado) {
      cel.innerHTML = selo + ` <span class="pill blue" title="${h(z.total || "")} vínculos no WhatsApp">zap compart.</span>`;
    } else if (quem) {
      cel.innerHTML = selo +
        ` <span class="pill ${bate === false ? "amber" : "green"}" title="No WhatsApp: ${h(quem)}">zap: ${h(String(quem).split(" ")[0])}</span>`;
    }
  } catch (err) { /* melhor-esforço: o selo de posse já está na tela */ }
}

function renderParentes(r) {
  const lista = r.parentes || r.conexoes || r.data || [];
  if (!lista.length) return emptyState("Nenhum parente ou conexão encontrada.");
  return table(["Nome", "CPF", "Parentesco", "Telefone"], lista.map((p) => ({ cells: [
    `<strong>${h(p.nome || "—")}</strong>`,
    fmtCPF(p.cpf),
    h(p.parentesco || p.vinculo || p.tipo || "—"),
    h((p.telefones && p.telefones[0] && (p.telefones[0].display || p.telefones[0].numero))
      || p.telefone || "—"),
  ] })), { scroll: true });
}

/** Vínculos da RAIS: onde a pessoa trabalhou, com admissão e saída.
 *  Antes caía no \`tabelaGenerica\` — dado certo com cara de depuração. */
function renderVinculos(r) {
  const lista = r.vinculos || r.empregos || r.data || r.registros || [];
  if (!lista.length) return emptyState("Nenhum vínculo declarado na RAIS.");
  const rows = lista.map((v) => {
    const doc = String(v.cnpj || v.documento || "").replace(/\D/g, "");
    const admissao = v.admissao || v.data_admissao || v.inicio;
    const saida = v.desligamento || v.data_desligamento || v.fim;
    return { cells: [
      `<strong>${h(v.razao_social || v.empresa || v.nome_empresa || "—")}</strong>`,
      doc ? `<a data-ficha="${h(doc)}">${fmtCNPJ(doc)}</a>` : '<span class="text-muted">—</span>',
      h(v.cargo || v.ocupacao || v.funcao || "—"),
      h(admissao ? fmtDate(admissao) === "—" ? admissao : fmtDate(admissao) : "—"),
      saida ? h(fmtDate(saida) === "—" ? saida : fmtDate(saida))
            : `<span class="pill green">no emprego</span>`,
      h(v.salario ? fmtMoney(Number(v.salario)) : "—"),
    ] };
  });
  return `
    <div class="help-block">Declarado pela empresa na RAIS — o vínculo pode estar
      encerrado sem que a base registre a saída.</div>
    ${table(["Empresa", "CNPJ", "Cargo", "Admissão", "Saída", "Salário"], rows, { scroll: true })}`;
}

/** Contatos do bureau: telefone e e-mail com a origem declarada. */
function renderContatos(r) {
  const tels = r.telefones || (r.contatos && r.contatos.telefones) || [];
  const mails = r.emails || (r.contatos && r.contatos.emails) || [];
  const cpf = String(r.cpf || (r.pessoa && r.pessoa.cpf) || "").replace(/\D/g, "");
  if (!tels.length && !mails.length) return emptyState("Nenhum contato retornado para este documento.");
  const linhaTel = tels.slice(0, 15).map((t, i) => {
    const num = String(t.numero || t.telefone || t.display || t).replace(/\D/g, "");
    return { cells: [
      `<strong>${h(fmtTelefone(num) || num || "—")}</strong>`,
      h(t.tipo || t.categoria || "—"),
      h(t.origem || t.fonte || "Serasa"),
      t.whatsapp ? `<span class="pill green">sim</span>` : '<span class="text-muted">—</span>',
      `<span id="cc-${h(cpf)}-${i}">${num && cpf
        ? `<a data-posse="${h(num)}" data-doc="${h(cpf)}" data-cel="cc-${h(cpf)}-${i}">verificar</a>`
        : '<span class="text-muted">—</span>'}</span>`,
    ] };
  });
  return `
    <div class="alert alert-info alert-styled-left">
      Consulta paga. Os contatos vêm do bureau e não passaram por validação de posse —
      use <strong>verificar</strong> antes de tratar como número da pessoa.
    </div>
    ${tels.length ? `<div class="sub-block"><h4>Telefones (${tels.length})</h4>
      ${table(["Número", "Tipo", "Origem", "WhatsApp", "Confiança"], linhaTel, { scroll: true })}</div>` : ""}
    ${mails.length ? `<div class="sub-block"><h4>E-mails (${mails.length})</h4>
      ${table(["E-mail", "Origem"], mails.slice(0, 12).map((e) => ({ cells: [
        h(typeof e === "string" ? e : (e.email || "—")),
        h(typeof e === "object" ? (e.origem || e.fonte || "Serasa") : "Serasa"),
      ] })))}</div>` : ""}`;
}

const fmtTelefone = (raw) => {
  const d = String(raw || "").replace(/\D/g, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return d;
};

/** Última linha de defesa: monta tabela a partir das chaves da própria lista. */
function tabelaGenerica(r) {
  const lista = Object.values(r).find((v) => Array.isArray(v) && v.length && typeof v[0] === "object");
  if (!lista) {
    const simples = Object.entries(r).filter(([, v]) => typeof v !== "object");
    return simples.length ? grade(simples.map(([k, v]) => campo(k.replace(/_/g, " "), v)), 3)
                          : emptyState("Nada encontrado.");
  }
  const cols = [...new Set(lista.flatMap((x) => Object.keys(x)))].slice(0, 8);
  return table(cols.map((c) => c.replace(/_/g, " ")),
    lista.map((x) => ({ cells: cols.map((c) => {
      const v = x[c];
      return h(typeof v === "object" && v !== null
        ? JSON.stringify(v).slice(0, 40) : String(v ?? "—").slice(0, 40));
    }) })), { scroll: true });
}

/** Telefone reverso: de quem é este número. */
/** O endereço vem ora como texto, ora como objeto — achatar aqui evita o
 *  clássico "[object Object]" na célula. */
function endereco(e) {
  if (!e) return "—";
  if (typeof e === "string") return e;
  const rua = [e.logradouro || e.endereco, e.numero, e.complemento].filter(Boolean).join(" ");
  const cidade = [e.bairro, e.cidade || e.municipio, e.uf].filter(Boolean).join(", ");
  return [rua, cidade, e.cep].filter(Boolean).join(" · ") || "—";
}

function renderReverso(r, phone) {
  const regs = r.registros || [];
  const rows = regs.map((x) => {
    const doc = String(x.cpf_cnpj || "").replace(/\D/g, "");
    return { cells: [
      `<strong>${h(x.nome || "—")}</strong>`,
      doc.length === 14 ? fmtCNPJ(doc) : fmtCPF(doc),
      `<span class="pill ${doc.length === 14 ? "blue" : "grey"}">${doc.length === 14 ? "empresa" : "pessoa"}</span>`,
      h(endereco(x.endereco)),
      doc.length === 14
        ? `<button class="btn btn-default btn-xs rv-emp" data-cnpj="${h(doc)}">Abrir ficha</button>` : "",
    ] };
  });
  const painel = panel(`${regs.length} atrelado(s) a ${h(phone)}`,
    rows.length ? table(["Nome", "Documento", "Tipo", "Endereço", ""], rows, { scroll: true })
                : emptyState("Nenhum registro para este número."),
    { subtitle: `Consulta paga${r.remaining_daily != null
        ? ` · restam ${r.remaining_daily} hoje` : ""}` });
  setTimeout(() => {
    document.querySelectorAll(".rv-emp").forEach((b) => {
      b.onclick = () => { state.fichaCnpj = b.dataset.cnpj; go("capiblu-empresa"); };
    });
  }, 0);
  return painel;
}

/** Validação telefone × documento: o número é mesmo daquela pessoa?
 *  Verde confirma, âmbar nega — azul aqui seria confundido com explicação. */
function renderPertence(r, phone, doc) {
  const pertence = r.pertence ?? r.atrelado ?? r.confirmado;
  const compartilhada = r.compartilhada ?? r.linha_compartilhada;
  const vinculos = r.total ?? r.vinculos ?? null;
  return panel("Validação", `
    <div class="alert ${pertence ? "alert-success" : "alert-warning"} alert-styled-left">
      <strong>${pertence ? "Confirmado" : "Não confirmado"}</strong> —
      ${h(phone)} ${pertence ? "está atrelado a" : "não aparece atrelado a"} ${h(doc)}.
    </div>
    ${compartilhada ? `<div class="alert alert-info alert-styled-left">
        <strong>Linha compartilhada</strong> — este número aparece para
        ${vinculos ? `<strong>${h(vinculos)}</strong> documentos` : "mais de um documento"}.
        Confirme com quem atender antes de tratar como contato direto.
      </div>` : ""}
    ${tabelaGenerica(r)}`, { subtitle: "Consulta paga" });
}

/** Pareia o WhatsApp: abre a sessão, mostra o QR e acompanha até conectar.
 *
 * O QR do whatsmeow expira em cerca de 40s e a sessão cai junto — por isso a
 * tela renova sozinha em vez de deixar um código morto na frente do usuário.
 */
async function parearWhatsapp() {
  const alvo = document.getElementById("waQr");
  const btn = document.getElementById("waParear");
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> conectando…`; }
  alvo.innerHTML = `<div class="alert alert-info alert-styled-left">
    <span class="spinner"></span> Abrindo a sessão…</div>`;

  try {
    await api("/api/envio/whatsapp/conectar", { method: "POST", body: {} });
  } catch (e) {
    alvo.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    if (btn) { btn.disabled = false; btn.textContent = "Parear número"; }
    return;
  }

  let tentativas = 0;
  const buscar = async () => {
    // Para se o usuário saiu da tela — senão o laço segue consultando à toa.
    if (!document.getElementById("waQr")) return;
    let q = {};
    try { q = await api("/api/envio/whatsapp/qrcode"); } catch { /* segue tentando */ }

    if (q.qrcode) {
      alvo.innerHTML = `
        <div class="alert alert-info alert-styled-left">
          No celular: <strong>WhatsApp → Aparelhos conectados → Conectar um aparelho</strong>.
          Aparece como <strong>Bluutime</strong>. O código renova sozinho.
        </div>
        <div style="text-align:center;padding:10px">
          <img src="${h(q.qrcode)}" alt="QR Code" style="width:260px;height:260px">
        </div>`;
    } else if (tentativas === 0) {
      alvo.innerHTML = `<div class="alert alert-info alert-styled-left">
        <span class="spinner"></span> Gerando o código…</div>`;
    }

    // Conectou? Aí a tela inteira recarrega para refletir o estado novo.
    const est = await api("/api/envio/canais").catch(() => null);
    const wa = est && est.channels.find((c) => c.channel === "WHATSAPP");
    if (wa && wa.state === "CONNECTED") {
      toast("WhatsApp pareado.", "ok");
      go("envio");
      return;
    }
    if (++tentativas < 40) setTimeout(buscar, 3000);
    else alvo.innerHTML = `<div class="alert alert-info alert-styled-left">
      Tempo esgotado sem parear. Clique em “Parear número” para tentar de novo.</div>`;
  };
  buscar();
}

/** Trocar a própria senha. Pede a atual — é o que impede que uma sessão
 *  esquecida aberta vire troca de credencial por quem passar na mesa. */
function trocarMinhaSenha() {
  const m = modal({
    title: "Trocar minha senha",
    body: `
      <div class="field"><label>Senha atual</label>
        <input class="form-control" id="msAtual" type="password"></div>
      <div class="field"><label>Nova senha <span class="text-grey">(mínimo 8)</span></label>
        <input class="form-control" id="msNova" type="password"></div>
      <div class="field"><label>Repita a nova senha</label>
        <input class="form-control" id="msRepete" type="password"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Trocar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const v = (id) => m.root.querySelector(id).value;
    if (v("#msNova").length < 8) return toast("A nova senha precisa de ao menos 8 caracteres.", "err");
    if (v("#msNova") !== v("#msRepete")) return toast("As duas não são iguais.", "err");
    try {
      await api("/api/auth/change-password", { method: "POST", body: {
        senha_atual: v("#msAtual"), nova_senha: v("#msNova") } });
      m.close();
      toast("Senha alterada.", "ok");
    } catch (e) { toast(e.message, "err"); }
  };
}

/* ── Migração do Meetime ───────────────────────────────────────────────
 *
 * Antes só existia por `curl`, e levava cinco minutos sem mostrar nada — quem
 * disparava não sabia se estava andando ou travado.
 */
PAGES["migracao"] = {
  area: "Configurações", title: "Migração do Meetime",
  async render() {
    view.innerHTML = `
      <div class="alert alert-info alert-styled-left">
        A junção entre lead e cadência custa <strong>uma consulta por lead</strong> —
        é a única exata que a API v2 oferece. Por isso a migração tem teto e
        “Completar” existe: ele preenche só quem ficou de fora, sem reimportar nada.
      </div>
      <div id="mgProgresso"></div>
      <div id="mgStatus">${LOADING}</div>`;
    // O progresso vem primeiro e sem `await`: `renderStatusMigracao` consulta a
    // API do Meetime e leva ~20s, e a barra é justamente o que não pode esperar.
    acompanharProgresso();
    await renderStatusMigracao();
  },
};

async function renderStatusMigracao() {
  const el = document.getElementById("mgStatus");
  let s;
  try {
    s = await api("/api/meetime/status");
  } catch (e) {
    el.innerHTML = `<div class="alert alert-info alert-styled-left">${h(e.message)}</div>`;
    return;
  }
  if (!s.configured) {
    el.innerHTML = `<div class="alert alert-info alert-styled-left">${h(s.message)}</div>`;
    return;
  }
  const remoto = s.remote || {};
  const local = s.imported || {};
  // Os dois lados juntos: só assim dá para ver o que ainda não veio.
  const linhas = Object.keys(remoto).map((k) => ({ cells: [
    h(k),
    typeof remoto[k] === "number" ? remoto[k].toLocaleString("pt-BR") : `<span class="text-muted">${h(remoto[k])}</span>`,
    local[k] != null ? local[k].toLocaleString("pt-BR") : "—",
  ] }));
  el.innerHTML = panel("Meetime × Bluutime",
    table(["Recurso", "No Meetime", "Importado aqui"], linhas),
    { subtitle: `${h(s.baseUrl)} · "tempo esgotado" é recurso que não respondeu no prazo, não erro`,
      actions: `<button class="btn btn-default btn-xs" id="mgCompletar">Completar junção</button>
                <button class="btn btn-main btn-xs ml-5" id="mgSync">Migrar de novo</button>` });

  document.getElementById("mgCompletar").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      const r = await api("/api/meetime/completar-juncao", { method: "POST", body: { limite: 1000 } });
      toast(r.pendentes === 0 ? "Nada a completar."
        : `${r.atualizados} de ${r.processados} completados.`, "ok");
    } catch (err) { toast(err.message, "err"); }
    go("migracao");
  };
  document.getElementById("mgSync").onclick = () => confirmDialog(
    "Migrar de novo",
    "Reimporta tudo do Meetime. Registros existentes são atualizados pelo meetime_id, não duplicados. Leva alguns minutos.",
    async () => {
      api("/api/meetime/sync", { method: "POST", body: { maxLeads: 1500, maxProspections: 1500 } })
        .then(() => { toast("Migração concluída.", "ok"); go("migracao"); })
        .catch((e) => toast(e.message, "err"));
      // Não espera a resposta: a barra é que acompanha, senão a tela congela.
      toast("Migração iniciada.", "ok");
      acompanharProgresso();
    });
}

/** Consulta o progresso enquanto houver tarefa rodando. */
async function acompanharProgresso() {
  const el = document.getElementById("mgProgresso");
  if (!el) return;
  let p;
  try { p = await api("/api/meetime/progresso"); } catch { return; }

  if (!p || p.estado === "PARADO") { el.innerHTML = ""; return; }

  const barra = p.percentual != null ? `
    <div style="height:8px;background:#eee;border-radius:4px;margin-top:8px">
      <div style="height:8px;width:${p.percentual}%;border-radius:4px;background:#00a443;
                  transition:width .4s"></div>
    </div>
    <div class="text-muted text-size-small mt-10">
      ${p.feito.toLocaleString("pt-BR")} de ${p.total.toLocaleString("pt-BR")} · ${p.percentual}%
    </div>` : "";

  const tom = p.estado === "ERRO" ? "alert-info" : p.estado === "PRONTO" ? "alert-success" : "alert-info";
  el.innerHTML = panel(h(p.titulo || "Migração"), `
    <div class="alert ${tom} alert-styled-left">
      ${p.estado === "RODANDO" ? `<span class="spinner"></span> ` : ""}
      <strong>${h(p.estado)}</strong> · ${h(p.etapa || "")} · ${p.segundos}s
      ${p.erro ? `<br>${h(p.erro)}` : ""}
    </div>
    ${barra}
    ${p.resultado ? `<div class="json-box mt-10">${h(JSON.stringify(p.resultado, null, 2))}</div>` : ""}`);

  if (p.estado === "RODANDO") setTimeout(acompanharProgresso, 2000);
}
