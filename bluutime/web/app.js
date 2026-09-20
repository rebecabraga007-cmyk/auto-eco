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
        <div class="modal-head"><h3>${h(title)}</h3><button class="close-x" data-close title="Fechar" aria-label="Fechar">×</button></div>
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

/* ── período ─────────────────────────────────────────────────────────────
   Toda rota de estatística (`/flow/statistics/summary`, `/dialer/calls*`,
   `/reports/{key}`) já aceitava `since`/`until` desde sempre; o que não
   existia era o controle. Sem ele cada tela ficava presa na janela padrão
   do backend, e não havia como olhar um mês fechado nem comparar períodos. */
const PERIODOS = [["7d", "Últimos 7 dias"], ["30d", "Últimos 30 dias"],
                  ["90d", "Últimos 90 dias"], ["mes", "Este mês"],
                  ["mes-1", "Mês passado"], ["livre", "Escolher datas"]];

const diaISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function periodoDatas(p = state.periodo || { tipo: "30d" }) {
  const hoje = new Date();
  if (p.tipo === "livre") return { since: p.since || "", until: p.until || "" };
  if (p.tipo === "mes")
    return { since: diaISO(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), until: diaISO(hoje) };
  if (p.tipo === "mes-1")
    return { since: diaISO(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)),
             until: diaISO(new Date(hoje.getFullYear(), hoje.getMonth(), 0)) };
  const ini = new Date(hoje);
  ini.setDate(ini.getDate() - (Number(String(p.tipo).replace("d", "")) || 30));
  return { since: diaISO(ini), until: diaISO(hoje) };
}

/** Query string dos filtros da tela: período, time e o que ela quiser juntar.
 *  Período e time andam sempre juntos — são as mesmas telas —, então vale um
 *  helper só em vez de cada chamada lembrar de somar os dois. */
function filtrosQS(extra = {}) {
  const { since, until } = periodoDatas();
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);
  if (state.teamId) qs.set("team_id", state.teamId);
  Object.entries(extra).forEach(([k, v]) => { if (v) qs.set(k, v); });
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/** Só o período — para quem não tem recorte por time (ex.: relatórios). */
function periodoQS(extra = {}) {
  const { since, until } = periodoDatas();
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);
  Object.entries(extra).forEach(([k, v]) => { if (v) qs.set(k, v); });
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/** Seletor de time. Some quando a empresa não tem times cadastrados. */
function timeControle() {
  const times = state.teams || [];
  if (!times.length) return "";
  return `<select class="form-control input-sm" id="pdTime" aria-label="Time">
    ${options(times, state.teamId || "", { blank: "Todos os times" })}</select>`;
}

function periodoControle() {
  const p = state.periodo || { tipo: "30d" };
  const { since, until } = periodoDatas(p);
  return `<select class="form-control input-sm" id="pdTipo" aria-label="Período">
      ${PERIODOS.map(([k, v]) => `<option value="${k}"${p.tipo === k ? " selected" : ""}>${h(v)}</option>`).join("")}
    </select>
    <input class="form-control input-sm" type="date" id="pdDe" value="${h(since)}" aria-label="Data inicial"${p.tipo === "livre" ? "" : " disabled"}>
    <span class="text-muted text-size-small">até</span>
    <input class="form-control input-sm" type="date" id="pdAte" value="${h(until)}" aria-label="Data final"${p.tipo === "livre" ? "" : " disabled"}>`;
}

/** Liga o controle. `aoMudar` costuma ser `() => go(state.page)`. */
function ligarPeriodo(aoMudar) {
  const tipo = document.getElementById("pdTipo");
  if (!tipo) return;
  const de = document.getElementById("pdDe");
  const ate = document.getElementById("pdAte");
  tipo.onchange = () => {
    // Ao abrir "escolher datas" o intervalo já vem preenchido com o que estava
    // valendo: começar com dois campos vazios obrigaria a redigitar tudo.
    state.periodo = tipo.value === "livre"
      ? { tipo: "livre", ...periodoDatas(state.periodo || { tipo: "30d" }) }
      : { tipo: tipo.value };
    aoMudar();
  };
  const manual = () => {
    if (!de.value || !ate.value) return;
    if (de.value > ate.value) { toast("A data inicial é depois da final.", "err"); return; }
    state.periodo = { tipo: "livre", since: de.value, until: ate.value };
    aoMudar();
  };
  de.onchange = manual;
  ate.onchange = manual;
  const time = document.getElementById("pdTime");
  if (time) time.onchange = () => { state.teamId = time.value; aoMudar(); };
}

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

/** `lead/31343806` → ["lead", "31343806"]. O Meetime dá endereço próprio a cada
 *  lead (/prospector/leads/{id}/timeline); sem isto, detalhe de lead só existia
 *  como modal — não dava pra mandar o link pra ninguém. */
function rota(hash) {
  const [nome, ...resto] = String(hash || "").split("/");
  return { nome, args: resto };
}

function go(name) {
  const { nome, args } = rota(name);
  const page = PAGES[nome] || PAGES.dashboard;
  state.page = name;
  document.getElementById("crumbArea").textContent = page.area || "Bluutime";
  document.getElementById("crumbCurrent").textContent = page.title || nome;
  document.querySelectorAll(".navbar-nav > li").forEach((li) => {
    li.classList.toggle("active", !!li.querySelector(`[data-page="${nome}"]`));
  });
  view.innerHTML = LOADING;
  location.hash = name;
  Promise.resolve(page.render(...args)).catch((e) => {
    view.innerHTML = panel("Erro", `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`);
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

/** Pra gates que não são item de menu (botão dentro de uma tela) — mesma
 *  regra do `data-min`, só que decidida em JS em vez de atributo no HTML. */
function nivelPeloMenos(nivel) {
  return NIVEIS.indexOf((state.me || {}).nivel || "sdr") >= NIVEIS.indexOf(nivel);
}

function renderNavAvatar() {
  const el = document.getElementById("navAvatar");
  if (!el) return;
  el.innerHTML = state.me.avatarUrl
    ? `<img src="${h(state.me.avatarUrl)}" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`
    : h(state.me.initials || "·");
}

async function boot() {
  state.me = await api("/api/me");
  document.getElementById("navUser").textContent = state.me.name;
  renderNavAvatar();
  aplicarPermissoesNav(state.me.nivel || "sdr");
  document.body.classList.remove("app-loading");
  loginShell.classList.add("hidden");
  const [clients, users, cadences, reasons, dialerCfg, teams] = await Promise.all([
    api("/api/clients"), api("/api/users"), api("/api/flow/cadences"), api("/api/flow/lost-reasons"),
    api("/api/dialer/configuration"), api("/api/teams").catch(() => []),
  ]);
  const etapas = await api("/api/flow/lead-stages").catch(() => ({ field: null, options: [] }));
  state.stageField = etapas.field;
  state.stageOptions = etapas.options;
  // Os campos personalizados alimentam o formulário de lead e o filtro da
  // lista — carregar aqui evita que abrir o formulário por outro caminho
  // (pela página do lead, por exemplo) mostre um cadastro incompleto.
  state.leadFields = (await api("/api/flow/new-lead-fields").catch(() => []))
    .filter((c) => c.customField);
  state.clients = clients;
  state.users = users.data;
  state.cadences = cadences;
  state.lostReasons = reasons;
  state.dialerConfig = dialerCfg;
  state.teams = teams;
  go(location.hash.slice(1) || "dashboard");
}

api("/api/me").then(boot).catch(showLogin);

/* ── Dashboard ───────────────────────────────────────────────────────── */
// Mês de referência do Dashboard: `null` é o mês corrente. O original tem
// seletor de período nas metas, e sem ele não dava para olhar um mês fechado.
function mesRef(delta = 0) {
  const base = state.metaMes ? new Date(`${state.metaMes}T12:00:00`) : new Date();
  const d = new Date(base.getFullYear(), base.getMonth() + delta, 1, 12);
  return diaISO(d);
}

PAGES.dashboard = {
  area: "Dashboard", title: "Visão geral",
  async render() {
    const ref = state.metaMes || todayISO();
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
          <button class="btn btn-default btn-xs" id="mesAnterior" title="Mês anterior" aria-label="Mês anterior">‹</button>
          <span>${new Date(`${g.targetMonth.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" })}</span>
          <button class="btn btn-default btn-xs" id="mesSeguinte" title="Mês seguinte" aria-label="Mês seguinte">›</button>
          ${state.metaMes ? `<button class="btn btn-default btn-xs" id="mesHoje">Este mês</button>` : ""}
          <span><i class="blue-dot"></i>${state.cadences.length} cadências</span>
          <span><i class="blue-dot"></i>${state.users.length} usuários</span>
          ${nivelPeloMenos("gestor")
            ? `<button class="btn-goal" id="editGoals">Editar metas</button>`
            : `<span class="text-muted text-size-small">Só gestor edita metas.</span>`}
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

      ${(() => {
        // Os três indicadores que o original tem como cartões próprios:
        // atividades, leads e conversão, cada um contra a sua meta.
        const ind = g.indicadores;
        if (!ind) return "";
        const a = ind.atividades;
        const noRitmo = a.feitas >= a.esperadoAteHoje;
        return `<div class="ranking-title">Indicadores do mês</div>
        <div class="kpi-row" style="grid-template-columns:repeat(3,1fr)">
          <div class="kpi">
            <div class="number">${a.feitas}</div>
            <div class="caption">Atividades realizadas
              <span class="pill ${noRitmo ? "green" : "red"}">${noRitmo ? "no ritmo" : "abaixo"}</span></div>
            <div class="text-muted text-size-small mt-10">
              Meta do mês ${a.meta} · esperado até hoje ${a.esperadoAteHoje}<br>
              ${a.mediaDiaria}/dia útil${a.atrasadas ? ` · <span class="text-muted">${a.atrasadas} fora do prazo</span>` : ""}</div>
          </div>
          <div class="kpi">
            <div class="number">${ind.leads.finalizados}</div>
            <div class="caption">Leads finalizados</div>
            <div class="text-muted text-size-small mt-10">
              ${ind.leads.prospectando} prospectando · ${ind.leads.aguardando} aguardando início</div>
          </div>
          <div class="kpi">
            <div class="number">${g.actual.conversion}%</div>
            <div class="caption">Conversão
              <span class="pill ${g.actual.conversion >= Math.round(g.goal.conversionRate * 100) ? "green" : "amber"}">
                meta ${Math.round(g.goal.conversionRate * 100)}%</span></div>
            <div class="text-muted text-size-small mt-10">
              ${g.actual.won} ganhos de ${g.actual.won + g.actual.lost} finalizados</div>
          </div>
        </div>`;
      })()}

      <div class="ranking-title">Ranking de SDRs · ${pct}% da meta</div>
      ${panel("Desempenho no mês", ranking)}

      <div class="insights-grid">
        <div class="panel panel-flat"><div class="panel-heading has-border"><h2 class="panel-title">Motivos de perda</h2></div>
          <div class="panel-body">${bars(g.lostReasons.slice(0, 6).map((r) => ({ label: r.name, value: r.count, tone: "warning" })))}</div></div>
        <div class="panel panel-flat"><div class="panel-heading has-border"><h2 class="panel-title">Resultado por cliente</h2></div>
          <div class="panel-body">${bars(g.byClient.map((c) => ({ label: c.client, value: c.won + c.lost })))}</div></div>
      </div>`;

    const editar = document.getElementById("editGoals");
    if (editar) editar.onclick = () => openGoalsModal(ref);
    document.getElementById("mesAnterior").onclick = () => { state.metaMes = mesRef(-1); go("dashboard"); };
    document.getElementById("mesSeguinte").onclick = () => { state.metaMes = mesRef(1); go("dashboard"); };
    const hoje = document.getElementById("mesHoje");
    if (hoje) hoje.onclick = () => { state.metaMes = null; go("dashboard"); };
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

/** Modal de metas: total da empresa em cima, participantes embaixo.
 *
 * Antes listava os 36 usuários da base — inativos inclusive — com dois
 * campos cada, e não havia nem total nem como tirar alguém. No original a
 * meta nasce no nível da empresa e é distribuída entre quem participa. */
async function openGoalsModal(ref) {
  const current = await api(`/api/flow/goals/${ref}`);
  const nome = (id) => (state.users.find((u) => u.id === id) || {}).name || `Usuário ${id}`;
  // Estado local: o modal recalcula enquanto se digita e só grava no fim.
  let linhas = current.usersGoals.map((g) => ({
    userId: g.user.id, nome: g.user.name,
    meta: g.opportunitiesGoal, conv: Math.round(g.conversionRateGoal * 100),
  }));

  const m = modal({
    wide: true,
    title: `Metas de ${new Date(`${current.targetMonth}T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" })}`,
    body: `<div id="gmCorpo"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar metas</button>`,
  });

  const desenhar = () => {
    const total = linhas.reduce((n, l) => n + (Number(l.meta) || 0), 0);
    const convMedia = linhas.length
      ? Math.round(linhas.reduce((n, l) => n + (Number(l.conv) || 0), 0) / linhas.length) : 15;
    const disponiveis = state.users
      .filter((u) => u.active !== false && !linhas.some((l) => l.userId === u.id));
    m.root.querySelector("#gmCorpo").innerHTML = `
      <div class="gm-total">
        <div class="field"><label for="gmMeta">Meta de oportunidades da empresa</label>
          <input class="form-control" type="number" min="0" id="gmMeta" value="${total}"></div>
        <div class="field"><label for="gmConv">Conversão alvo (%)</label>
          <input class="form-control" type="number" min="1" max="100" id="gmConv" value="${convMedia}"></div>
        <div class="text-muted text-size-small">
          Mexer aqui redistribui entre os ${linhas.length} participante${linhas.length === 1 ? "" : "s"};
          mexer em alguém embaixo atualiza o total.</div>
      </div>
      ${linhas.length ? linhas.map((l, i) => `
        <div class="field-row gm-linha" data-i="${i}">
          <div class="field"><label>${h(l.nome)} — oportunidades</label>
            <input class="form-control" type="number" min="0" data-goal value="${l.meta}"></div>
          <div class="field"><label>Conversão alvo (%)</label>
            <input class="form-control" type="number" min="1" max="100" data-conv value="${l.conv}"></div>
          <div class="field" style="flex:0 0 auto;align-self:end">
            <button class="btn btn-default btn-xs" data-remover="${i}" title="Tirar da meta">Remover</button></div>
        </div>`).join("")
        : `<p class="text-muted">Nenhum participante ainda — escolha alguém abaixo.</p>`}
      ${disponiveis.length ? `
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <select class="form-control" id="gmNovo">${options(disponiveis, "", { blank: "Adicionar participante…" })}</select>
        </div>` : `<p class="text-muted text-size-small">Todos os usuários ativos já participam.</p>`}`;

    m.root.querySelectorAll(".gm-linha").forEach((row) => {
      const i = Number(row.dataset.i);
      row.querySelector("[data-goal]").oninput = (e) => { linhas[i].meta = Number(e.target.value) || 0; atualizarTotal(); };
      row.querySelector("[data-conv]").oninput = (e) => { linhas[i].conv = Number(e.target.value) || 0; atualizarTotal(); };
      row.querySelector("[data-remover]").onclick = () => { linhas.splice(i, 1); desenhar(); };
    });
    const novo = m.root.querySelector("#gmNovo");
    if (novo) novo.onchange = () => {
      const id = Number(novo.value);
      if (!id) return;
      linhas.push({ userId: id, nome: nome(id), meta: 25, conv: convMedia || 15 });
      desenhar();
    };
    m.root.querySelector("#gmMeta").onchange = (e) => {
      const alvo = Number(e.target.value) || 0;
      if (!linhas.length) return desenhar();
      // Divisão inteira com o resto no primeiro: somar 7 em 3 pessoas tem que
      // dar 7, e não 6 nem 9.
      const base = Math.floor(alvo / linhas.length);
      const resto = alvo - base * linhas.length;
      linhas = linhas.map((l, i) => ({ ...l, meta: base + (i < resto ? 1 : 0) }));
      desenhar();
    };
    m.root.querySelector("#gmConv").onchange = (e) => {
      const v = Number(e.target.value) || 0;
      linhas = linhas.map((l) => ({ ...l, conv: v }));
      desenhar();
    };
  };

  const atualizarTotal = () => {
    const total = linhas.reduce((n, l) => n + (Number(l.meta) || 0), 0);
    const conv = linhas.length
      ? Math.round(linhas.reduce((n, l) => n + (Number(l.conv) || 0), 0) / linhas.length) : 15;
    m.root.querySelector("#gmMeta").value = total;
    m.root.querySelector("#gmConv").value = conv;
  };

  desenhar();
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api(`/api/flow/goals/${ref}`, { method: "PUT", body: {
        usersGoals: linhas.map((l) => ({
          userId: l.userId, opportunitiesGoal: Number(l.meta) || 0,
          conversionRateGoal: (Number(l.conv) || 0) / 100,
        })),
      } });
      m.close();
      toast("Metas atualizadas.", "ok");
      go("dashboard");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
  };
}

/** Origem dos leads com conversão, não só volume.
 *
 * A origem aqui é a base de onde o lead veio: o Bluutime não guarda fonte,
 * canal e campanha como o Meetime, que os recebe da integração de inbound. */
function painelOrigem(origins) {
  const ordem = state.origemOrdem || "total";
  const lista = [...origins].sort((a, b) => ordem === "conversao"
    ? (b.won / Math.max(1, b.total)) - (a.won / Math.max(1, a.total))
    : b.total - a.total);
  const linha = (o) => {
    const pct = o.total ? Math.round((o.won / o.total) * 100) : 0;
    return `<div class="origem-linha">
      <div class="origem-topo"><span>${h(o.name)}</span>
        <strong>${o.won}/${o.total}</strong></div>
      <div class="qual-barra" title="${o.won} ganhos e ${o.lost} perdidos">
        <span class="qual-sim" style="width:${pct}%"></span>
        <span class="qual-nao" style="width:${100 - pct}%"></span>
      </div>
      <div class="text-muted text-size-small">${pct}% de conversão</div>
    </div>`;
  };
  return `
    <div class="panel panel-flat">
      <div class="panel-heading has-border">
        <div><h2 class="panel-title">Origem dos leads</h2>
          <div class="text-muted text-size-small">Base de onde o lead veio, com quanto cada uma converte</div></div>
        <div class="heading-elements">
          <select class="form-control input-xs" id="origemOrdem">
            <option value="total"${ordem === "total" ? " selected" : ""}>Por volume</option>
            <option value="conversao"${ordem === "conversao" ? " selected" : ""}>Por conversão</option>
          </select>
          ${lista.length > 6 ? `<button class="btn btn-default btn-xs" id="origemMais">Ver mais</button>` : ""}
        </div>
      </div>
      <div class="panel-body">${lista.length ? lista.slice(0, 6).map(linha).join("")
        : emptyState("Nenhum lead finalizado no período.")}</div>
    </div>`;
}

function ligarPainelOrigem(origins) {
  const sel = document.getElementById("origemOrdem");
  if (sel) sel.onchange = () => { state.origemOrdem = sel.value; go("estatisticas"); };
  const mais = document.getElementById("origemMais");
  if (mais) mais.onclick = () => {
    const lista = [...origins].sort((a, b) => b.total - a.total);
    const m = modal({
      wide: true,
      title: `Origem dos leads (${lista.length})`,
      body: table(["Origem", "Ganhos", "Perdidos", "Total", "Conversão"],
        lista.map((o) => ({ cells: [
          h(o.name), o.won, o.lost, o.total,
          `${o.total ? Math.round((o.won / o.total) * 100) : 0}%`,
        ] })), { scroll: true }),
      footer: `<button class="btn btn-main btn-sm" data-close-origem>Fechar</button>`,
    });
    m.root.querySelector("[data-close-origem]").onclick = m.close;
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
        ${rows.length ? `<div class="table-responsive"><table class="table table-striped table-hover">
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
        </table></div>` : emptyState("Nenhum usuário com atividade neste filtro.")}
      </div></div>`;

    document.getElementById("fClient").onchange = (e) => {
      state.filterClient = e.target.value; go("painel");
    };
    document.getElementById("refresh").onclick = () => go("painel");
  },
};

/* ── Execução: a fila priorizada ─────────────────────────────────────── */
/* ── Execução ────────────────────────────────────────────────────────────
   O original abre com um check-in ("iniciar atividades") e executa uma
   atividade por vez, com um menu de preferências do lado. A fila aqui
   continua priorizada por score, mas ganhou as três coisas que faltavam:
   o modo rápido, o agrupamento por passo e a separação das extras. */
const EXEC_PREF_PADRAO = { agrupar: false, quentes: true, avancar: true };

function execPrefs() {
  try {
    return { ...EXEC_PREF_PADRAO, ...JSON.parse(localStorage.getItem("bluutime.exec") || "{}") };
  } catch {
    // localStorage bloqueado (janela anônima, cookie de terceiro): a tela
    // funciona com o padrão em vez de quebrar na primeira leitura.
    return { ...EXEC_PREF_PADRAO };
  }
}

function salvarExecPrefs(p) {
  try { localStorage.setItem("bluutime.exec", JSON.stringify(p)); } catch { /* sem persistência */ }
}

function passoRotulo(a) {
  if (a.extra) return "Atividade extra";
  if (!a.passo) return "Cadência";
  return `Dia ${a.passo.dia} · ${a.passo.ordem}ª atividade`;
}

/** Modo rápido: uma atividade por vez, sem voltar para a lista entre elas. */
function modoRapido(items, i = 0) {
  if (i >= items.length) {
    toast("Fila concluída.", "ok");
    return go("execucao");
  }
  const act = items[i];
  const fila = {
    indice: i + 1, total: items.length,
    proximo: () => (execPrefs().avancar ? modoRapido(items, i + 1) : go("execucao")),
    pular: () => modoRapido(items, i + 1),
  };
  if (PRECISA_MODELO.has(act.channel)) return enviarAtividade(act, fila);
  return openExecuteModal(act, fila);
}

PAGES.execucao = {
  area: "Prospecção", title: "Execução",
  async render() {
    const f = state.queueFilter || {};
    const prefs = execPrefs();
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const [res, quentes, geral] = await Promise.all([
      api(`/api/flow/execution/queue?${qs}`),
      prefs.quentes ? api("/api/flow/hot-leads").catch(() => ({ data: [] })) : Promise.resolve({ data: [] }),
      api("/api/flow/execution/overall").catch(() => null),
    ]);
    const items = res.data;

    const cartao = (a, i) => `
      <div class="queue-item${a.late ? " late" : ""}" data-act="${a.id}">
        <div class="queue-rank">${i + 1}</div>
        <div>
          <strong>${h(a.lead.name)}</strong>
          <span class="text-muted ml-5">${h(a.lead.company)}</span>
          ${a.lead.client ? `<span class="pill ml-5" style="border-color:${h(a.lead.client.color)}">${h(a.lead.client.name)}</span>` : ""}
          <br>
          <span class="pill ${a.type === "CALL" ? "blue" : a.type === "E_MAIL" ? "grey" : "green"}">${h(TYPE_LABEL[a.type] || a.type)}</span>
          <span class="text-muted ml-5">${h(a.activity ? a.activity.name : "")}</span>
          ${a.extra ? `<span class="pill amber ml-5">Extra</span>` : ""}
          <br>
          <span class="text-size-small text-muted">
            ${a.late ? `<span style="color:#f44336">Atrasada</span> · ` : ""}agendada ${fmtDateTime(a.scheduledAt)}
            · melhor contato ${a.lead.bestHour}h
            ${a.lead.cadence ? ` · ${h(a.lead.cadence.name)} (${h(PRIORITY_LABEL[a.lead.cadence.priority])})` : ""}
            · ${h(passoRotulo(a))}
            · ${a.tentativas} tentativa${a.tentativas === 1 ? "" : "s"}
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
          <button class="btn btn-success btn-xs" data-ganho="${a.lead.id}">Ganho</button>
          <button class="btn btn-danger btn-xs" data-perdido="${a.lead.id}">Perdido</button>
          ${a.lead.status === "ON_EXTRA_ACTIVITY"
            // Só aparece para quem teve a cadência pausada por ter respondido —
            // é o único caso em que existe algo a retomar.
            ? `<button class="btn btn-default btn-xs" data-retomar="${a.lead.id}">Retomar cadência</button>`
            : ""}
          <button class="btn btn-default btn-xs" data-lead="${a.lead.id}">Abrir lead</button>
        </div>
      </div>`;

    let list;
    if (!items.length) {
      list = emptyState(f.q ? "Nenhuma atividade com esse texto." : "Fila vazia — nada pendente para agora.");
    } else if (prefs.agrupar) {
      // Agrupar por passo é o jeito do original de mostrar a cadência: a
      // ordem por score continua dentro de cada grupo.
      const grupos = new Map();
      items.forEach((a) => {
        const chave = passoRotulo(a);
        if (!grupos.has(chave)) grupos.set(chave, []);
        grupos.get(chave).push(a);
      });
      let n = 0;
      list = [...grupos.entries()].map(([chave, linhas]) => `
        <div class="queue-grupo">${h(chave)} <span>${linhas.length}</span></div>
        ${linhas.map((a) => cartao(a, n++)).join("")}`).join("");
    } else {
      list = items.map(cartao).join("");
    }

    // `state.leadFields` já vem filtrado no boot: só os personalizados.
    const campos = state.leadFields || [];

    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="qBusca" placeholder="Buscar lead, empresa, e-mail ou telefone…" value="${h(f.q || "")}">
        <select class="form-control" id="qSdr">${options(state.users, f.sdr_id, { blank: "Todos os SDRs" })}</select>
        <select class="form-control" id="qClient">${options(state.clients, f.client_id, { blank: "Todos os clientes" })}</select>
        <select class="form-control" id="qCad">${options(state.cadences, f.cadence_id, { blank: "Todas as cadências" })}</select>
        <select class="form-control" id="qType">
          <option value="">Todos os tipos</option>
          ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}"${f.type === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <select class="form-control" id="qEscopo">
          ${[["todas", "Cadência e extras"], ["cadencia", "Só da cadência"], ["extras", "Só extras"]].map(([v, r]) =>
            `<option value="${v}"${(f.escopo || "todas") === v ? " selected" : ""}>${r}</option>`).join("")}
        </select>
        ${campos.length ? `
          <select class="form-control" id="qCampo">${options(campos, f.field_id, { blank: "Campo personalizado" })}</select>
          <input class="form-control" id="qCampoVal" placeholder="valor" value="${h(f.field_value || "")}"${f.field_id ? "" : " disabled"}>` : ""}
        <span class="spacer"></span>
        <button class="btn btn-default btn-xs" id="prefs" title="Preferências da execução">⚙ Preferências</button>
        <button class="btn btn-default btn-xs" id="refresh">Atualizar</button>
      </div>
      ${geral ? panel("Meu dia", `
        <div class="split" style="grid-template-columns:1fr auto;align-items:center">
          <div>
            <div style="font-size:15px">
              Você está prospectando <strong>${geral.prospectando}</strong> leads
              ${geral.disponiveis ? `· <strong>${geral.disponiveis}</strong> em espera para começar` : ""}
            </div>
            <div class="bar mt-10" style="height:22px">
              <span style="width:${Math.min(100, geral.hoje.percentual)}%;background:${geral.bateuMeta ? "var(--green)" : "var(--blue)"}"></span>
            </div>
            <div class="text-muted text-size-small mt-10">
              ${geral.hoje.feitas} de ${geral.hoje.meta || "—"} atividades hoje
              ${geral.hoje.meta ? ` · ${geral.hoje.percentual}%` : " (sem meta definida)"}
              ${geral.hoje.ignoradas ? ` · ${geral.hoje.ignoradas} ignoradas` : ""}
            </div>
          </div>
          <div style="text-align:center;min-width:150px">
            ${geral.bateuMeta
              ? `<div style="font-size:42px;line-height:1">🏆</div>
                 <div class="pill green">Meta batida</div>`
              : `<div class="round-icon" style="margin:0 auto">${Math.round(geral.hoje.percentual)}%</div>`}
            ${items.length ? `<button class="btn btn-main btn-sm mt-10" id="iniciar">▶ Iniciar atividades</button>` : ""}
            ${geral.disponiveis ? `<button class="btn btn-default btn-sm mt-10" id="puxarLeads">Ver leads em espera</button>` : ""}
          </div>
        </div>`) : ""}
      ${kpis([
        { value: res.meta.total, label: "Na fila", tone: "info" },
        { value: res.meta.late, label: "Atrasadas", tone: "danger" },
        { value: res.meta.onTime, label: "No prazo", tone: "success" },
        { value: res.meta.extras, label: "Extras" },
      ])}
      ${panel("Fila priorizada",
        `<div class="alert alert-info alert-styled-left">A ordem combina atraso, prioridade da cadência e janela de melhor contato — não é ordem cronológica.</div>
         <div style="margin:0 -20px -20px">${list}</div>`,
        { subtitle: "Atividades pendentes das próximas 24 horas",
          actions: items.length
            ? `<button class="btn btn-main btn-xs" id="iniciar2">▶ Modo rápido</button>` : "" })}
      ${quentes.data.length ? panel(`Leads aguardando a primeira ligação (${quentes.data.length})`,
        table(["Lead", "Empresa", "Telefone", "Esperando há", ""],
          quentes.data.map((l) => ({ cells: [
            `<a data-lead="${l.id}"><strong>${h(l.name)}</strong></a>`,
            h(l.company || "—"), h(l.phone || "—"),
            l.horasEsperando >= 48 ? `<span class="pill red">${Math.round(l.horasEsperando / 24)} dias</span>`
              : l.horasEsperando >= 24 ? `<span class="pill amber">${Math.round(l.horasEsperando / 24)} dia</span>`
              : `<span class="pill">${l.horasEsperando}h</span>`,
            `<button class="btn btn-default btn-xs" data-lead="${l.id}">Abrir</button>`,
          ] })), { scroll: true }),
        { subtitle: "Ninguém ligou para eles ainda. Os mais antigos vêm primeiro — lead novo esfria rápido." }) : ""}`;

    const puxar = document.getElementById("puxarLeads");
    // Leva para a lista filtrada em vez de iniciar tudo de uma vez: começar
    // cadência é decisão por lead (qual cadência, qual cliente), e um botão
    // que dispara em lote esconderia essa escolha.
    if (puxar) puxar.onclick = () => {
      state.leadFilter = { page: 1, limit: 50, status: "WAITING" };
      go("leads");
    };
    ["iniciar", "iniciar2"].forEach((id) => {
      const b = document.getElementById(id);
      if (b) b.onclick = () => modoRapido(items, 0);
    });
    document.getElementById("prefs").onclick = () => abrirPrefsExecucao();

    const setFilter = (key, value) => {
      state.queueFilter = { ...(state.queueFilter || {}), [key]: value };
      go("execucao");
    };
    let tb;
    document.getElementById("qBusca").oninput = (e) => {
      clearTimeout(tb);
      const v = e.target.value;
      tb = setTimeout(() => setFilter("q", v), 350);
    };
    document.getElementById("qSdr").onchange = (e) => setFilter("sdr_id", e.target.value);
    document.getElementById("qClient").onchange = (e) => setFilter("client_id", e.target.value);
    document.getElementById("qCad").onchange = (e) => setFilter("cadence_id", e.target.value);
    document.getElementById("qType").onchange = (e) => setFilter("type", e.target.value);
    document.getElementById("qEscopo").onchange = (e) => setFilter("escopo", e.target.value);
    const qCampo = document.getElementById("qCampo");
    if (qCampo) {
      // Trocar de campo zera o valor, como na lista de Leads: manter o valor
      // antigo devolveria uma fila vazia sem dizer por quê.
      qCampo.onchange = () => {
        state.queueFilter = { ...(state.queueFilter || {}), field_id: qCampo.value, field_value: "" };
        go("execucao");
      };
      const val = document.getElementById("qCampoVal");
      let tv;
      val.oninput = () => { clearTimeout(tv); tv = setTimeout(() => setFilter("field_value", val.value), 350); };
    }
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
    view.querySelectorAll("[data-ganho]").forEach((b) => {
      b.onclick = () => confirmDialog("Marcar como ganho",
        "O lead sai da cadência e as atividades pendentes são descartadas.", async () => {
          try {
            await api(`/api/flow/execution/leads/${b.dataset.ganho}/outcome`,
              { method: "POST", body: { outcome: "WON" } });
            toast("Lead marcado como ganho.", "ok"); go("execucao");
          } catch (e) { toast(e.message, "err"); }
        });
    });
    view.querySelectorAll("[data-perdido]").forEach((b) => {
      b.onclick = () => openLostModal(Number(b.dataset.perdido), () => go("execucao"));
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

function abrirPrefsExecucao() {
  const p = execPrefs();
  const linha = (id, rotulo, ligado, ajuda) => `
    <div class="field"><label><input type="checkbox" id="${id}"${ligado ? " checked" : ""}> ${rotulo}</label>
      <div class="text-muted text-size-small" style="margin-left:22px">${ajuda}</div></div>`;
  const m = modal({
    title: "Preferências da execução",
    body: `
      ${linha("pAgrupar", "Agrupar a fila por passo da cadência", p.agrupar,
              "Junta as atividades do mesmo dia da cadência; a ordem por prioridade continua dentro de cada grupo.")}
      ${linha("pAvancar", "No modo rápido, ir sozinho para a próxima", p.avancar,
              "Desligado, o modo rápido para depois de cada atividade e volta para a fila.")}
      ${linha("pQuentes", "Mostrar os leads aguardando a primeira ligação", p.quentes,
              "Desligado, a tela carrega mais rápido e fica só com a fila.")}
      <p class="text-muted text-size-small">As preferências ficam só neste navegador.</p>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = () => {
    salvarExecPrefs({
      agrupar: m.root.querySelector("#pAgrupar").checked,
      avancar: m.root.querySelector("#pAvancar").checked,
      quentes: m.root.querySelector("#pQuentes").checked,
    });
    m.close();
    go("execucao");
  };
}

/** Envia a mensagem do passo — o texto vem do modelo da etapa.
 *
 * `fila` só chega no modo rápido: é ele que troca o "voltar para a lista"
 * pelo "abrir a próxima atividade" e acrescenta o botão de pular. */
function enviarAtividade(act, fila = null) {
  const seguir = fila ? fila.proximo : () => go("execucao");
  const m = modal({
    wide: true,
    title: `${fila ? `${fila.indice}/${fila.total} · ` : ""}Enviar ${act.channel} para ${act.lead.name}`,
    body: `<div class="alert alert-info alert-styled-left" id="evAviso">
        O texto vem do modelo da etapa. Nada sai enquanto o envio estiver desligado.
      </div>
      <div class="field">
        <label><input type="checkbox" id="evFora"> Enviar fora da janela de 9h–18h</label>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             ${fila ? `<button class="btn btn-default btn-sm" data-pular>Pular</button>` : ""}
             <button class="btn btn-main btn-sm" data-ok>Enviar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  if (fila) m.root.querySelector("[data-pular]").onclick = () => { m.close(); fila.pular(); };

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
      seguir();
    } catch (e) {
      const faltando = /variáveis sem valor/i.test(e.message);
      m.root.querySelector("#evAviso").className = "alert alert-danger alert-styled-left";
      m.root.querySelector("#evAviso").innerHTML = h(e.message);
      ok.disabled = false;
      ok.textContent = faltando ? "Enviar mesmo assim" : "Enviar";
      if (faltando) ok.onclick = () => disparar(true);
    }
  };
  m.root.querySelector("[data-ok]").onclick = () => disparar(false);
}

/** Reagenda a atividade — o servidor encaixa na próxima janela útil. */
function adiarAtividade(act) {
  const amanha = new Date(Date.now() + 864e5);
  const m = modal({
    title: `Adiar atividade de ${act.lead.name}`,
    body: `<div class="field"><label for="adQuando">Nova data e hora</label>
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

function openExecuteModal(act, fila = null) {
  if (!act) return;
  const seguir = fila ? fila.proximo : () => go("execucao");
  const tpl = act.activity && act.activity.emailTemplate;
  const merge = (text) => (text || "")
    .replace(/\{\{firstName\}\}/g, act.lead.name.split(" ")[0])
    .replace(/\{\{company\}\}/g, act.lead.company);

  const script = act.activity ? merge(act.activity.instruction) : "";
  const callerIds = (state.dialerConfig && state.dialerConfig.callerIdList)
    || ((state.dialerConfig && state.dialerConfig.callerIds) || []).map((n) => ({ number: n, label: "" }));
  const callBlock = act.type === "CALL" ? `
    <div class="field-row">
      <div class="field"><label for="callOutput">Resultado da ligação</label>
        <select class="form-control" id="callOutput">
          <option value="">Não conectou</option>
          <option value="NO_CONTACT">Conectou · sem contato</option>
          <option value="NOT_MEANINGFUL">Conectou · não significativa</option>
          <option value="MEANINGFUL">Conectou · significativa</option>
        </select></div>
      <div class="field"><label for="callDuration">Duração (segundos)</label>
        <input class="form-control" type="number" min="0" id="callDuration" value="0"></div>
      ${callerIds.length ? `<div class="field"><label for="callOrigin">Número de origem</label>
        <select class="form-control" id="callOrigin">
          ${callerIds.map((n) => `<option value="${h(n.number)}"${n.default ? " selected" : ""}>${h(n.number)}${n.label ? ` — ${h(n.label)}` : ""}</option>`).join("")}
        </select></div>` : ""}
    </div>` : "";

  const m = modal({
    title: `${fila ? `${fila.indice}/${fila.total} · ` : ""}${TYPE_LABEL[act.type] || act.type} — ${act.lead.name}`,
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
      <div class="field"><label for="execNotes">Anotações</label><textarea class="form-control" id="execNotes"></textarea></div>`,
    footer: `<button class="btn btn-danger btn-sm" data-lost>Marcar perdido</button>
             <button class="btn btn-success btn-sm" data-won>Marcar ganho</button>
             <span style="flex:1"></span>
             <button class="btn btn-default btn-sm" data-cancel>Fechar</button>
             ${fila ? `<button class="btn btn-default btn-sm" data-pular>Pular</button>` : ""}
             <button class="btn btn-main btn-sm" data-done>Concluir atividade</button>`,
  });

  m.root.querySelector("[data-cancel]").onclick = m.close;
  if (fila) m.root.querySelector("[data-pular]").onclick = () => { m.close(); fila.pular(); };
  m.root.querySelector("[data-done]").onclick = async () => {
    try {
      const notes = m.root.querySelector("#execNotes").value;
      if (act.type === "CALL") {
        const output = m.root.querySelector("#callOutput").value;
        const originSelect = m.root.querySelector("#callOrigin");
        await api("/api/dialer/calls", { method: "POST", body: {
          leadId: act.lead.id, userId: state.me.id,
          status: output ? "CONNECTED" : "NOT_PERFORMED", output,
          duration: Number(m.root.querySelector("#callDuration").value) || 0,
          receiverPhone: act.lead.phone,
          originPhone: originSelect ? originSelect.value : "",
        } });
      }
      await api(`/api/flow/execution/activities/${act.id}/execute`, { method: "POST", body: { notes } });
      m.close();
      toast("Atividade concluída.", "ok");
      seguir();
    } catch (e) { toast(e.message, "err"); }
  };
  m.root.querySelector("[data-won]").onclick = async () => {
    try {
      await api(`/api/flow/execution/leads/${act.lead.id}/outcome`,
        { method: "POST", body: { outcome: "WON" } });
      m.close(); toast("Lead marcado como ganho.", "ok"); seguir();
    } catch (e) { toast(e.message, "err"); }
  };
  m.root.querySelector("[data-lost]").onclick = () => { m.close(); openLostModal(act.lead.id, seguir); };
}

function openLostModal(leadId, after) {
  const m = modal({
    title: "Marcar como perdido",
    body: `<div class="field"><label for="lostReason">Motivo da perda</label>
        <select class="form-control" id="lostReason">${options(state.lostReasons, "", { blank: "Selecione…" })}</select></div>
      <div class="field"><label for="lostNotes">Anotações</label><textarea class="form-control" id="lostNotes"></textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-danger btn-sm" data-ok>Confirmar perda</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const reason = m.root.querySelector("#lostReason").value;
    if (!reason) return toast("Escolha o motivo da perda.", "err");
    try {
      await api(`/api/flow/execution/leads/${leadId}/outcome`, { method: "POST", body: {
        outcome: "LOST", lostReasonId: Number(reason),
        annotations: m.root.querySelector("#lostNotes").value } });
      m.close(); toast("Lead marcado como perdido."); after && after();
    } catch (e) { toast(e.message, "err"); }
  };
}

/* ── Leads ───────────────────────────────────────────────────────────── */
PAGES.leads = {
  area: "Prospecção", title: "Leads",
  async render() {
    const f = state.leadFilter || { page: 1, limit: 50 };
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const res = await api(`/api/flow/leads?${qs}`);
    const campos = state.leadFields || [];
    const rows = res.data.map((l) => ({ cells: [
      `<input type="checkbox" class="lead-check" value="${l.id}">`,
      `<a data-open-lead="${l.id}"><strong>${h(l.name)}</strong></a><br>
       <span class="text-muted text-size-small">${h(l.position || "")}</span>`,
      l.fitscore ? `<span class="pill green" title="Lead scoring">${l.fitscore}</span>` : `<span class="text-muted">—</span>`,
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
      ${res.stages && res.stages.length ? `<ul class="nav nav-tabs">
        <li${!f.stage ? ' class="active"' : ""}><a data-stage="">Todas
          <span class="badge${!f.stage ? " badge-success" : ""}">${res.pagination.totalRowCount}</span></a></li>
        ${res.stages.map((e) => `<li${f.stage === e.label ? ' class="active"' : ""}>
          <a data-stage="${h(e.label)}">${h(e.label)}
            <span class="badge${f.stage === e.label ? " badge-success" : ""}">${e.count}</span></a></li>`).join("")}
      </ul>` : ""}
      <div class="toolbar">
        <input class="form-control grow" id="lq" placeholder="Buscar por nome, empresa, e-mail ou CNPJ" value="${h(f.q || "")}">
        <select class="form-control" id="lStatus">
          <option value="">Todas as situações</option>
          ${Object.entries(STATUS_LABEL).map(([k, v]) => `<option value="${k}"${f.status === k ? " selected" : ""}>${v[0]}</option>`).join("")}
        </select>
        <select class="form-control" id="lClient">${options(state.clients, f.client_id, { blank: "Todos os clientes" })}</select>
        <select class="form-control" id="lCad">${options(state.cadences, f.cadence_id, { blank: "Todas as cadências" })}</select>
        <select class="form-control" id="lSdr">${options(state.users, f.sdr_id, { blank: "Todos os SDRs" })}</select>
        ${campos.length ? `
        <select class="form-control" id="lCampo" aria-label="Campo personalizado">
          <option value="">Campo personalizado…</option>
          ${campos.map((c) => `<option value="${c.id}"${String(f.field_id) === String(c.id) ? " selected" : ""}>${h(c.name)}</option>`).join("")}
        </select>
        <select class="form-control" id="lCampoOp" aria-label="Critério"${f.field_id ? "" : " disabled"}>
          <option value="EQUALS"${f.field_op === "EQUALS" ? " selected" : ""}>Igual a</option>
          <option value="LIKE"${f.field_op === "LIKE" ? " selected" : ""}>Contém</option>
        </select>
        <input class="form-control" id="lCampoVal" placeholder="Valor" aria-label="Valor do campo"
          value="${h(f.field_value || "")}"${f.field_id ? "" : " disabled"}>` : ""}
        <span class="spacer"></span>
        <select class="form-control input-sm" id="lPorPagina" aria-label="Itens por página">
          ${[10, 25, 50, 100].map((n) => `<option value="${n}"${Number(f.limit || 50) === n ? " selected" : ""}>${n}/página</option>`).join("")}
        </select>
        <a class="btn btn-default btn-xs" id="lExport" href="/api/flow/leads/export?${qs}">Exportar</a>
        <button class="btn btn-default btn-xs" id="bulkBtn">Ações em massa</button>
        <button class="btn btn-main btn-xs" id="newLead">Novo lead</button>
      </div>
      ${panel(`${res.pagination.totalRowCount} leads`,
        table(["<input type='checkbox' id='checkAll'>", "Lead", "Score", "Empresa", "Cidade", "Telefone",
               "Situação", "Cadência", "Cliente", "SDR", "Criado"], rows, { scroll: true }),
        { actions: pager(res.pagination) })}`;

    bindLeadFilters(f);
    view.querySelectorAll("[data-stage]").forEach((a) => {
      a.onclick = () => { state.leadFilter = { ...f, stage: a.dataset.stage, page: 1 }; go("leads"); };
    });
    document.getElementById("newLead").onclick = () => openLeadForm();
    document.getElementById("bulkBtn").onclick = openBulkModal;
    const checkAll = document.getElementById("checkAll");
    if (checkAll) checkAll.onchange = (e) =>
      view.querySelectorAll(".lead-check").forEach((c) => { c.checked = e.target.checked; });
    view.querySelectorAll("[data-open-lead]").forEach((a) => {
      a.onclick = () => go(`lead/${a.dataset.openLead}`);
    });
    view.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => { state.leadFilter = { ...f, page: Number(b.dataset.gotoPage) }; go("leads"); };
    });
  },
};

const pager = (p) => p.totalPageCount > 1
  ? `<span class="text-muted text-size-small mr-10">Página ${p.page} de ${p.totalPageCount}</span>
     <button class="btn btn-default btn-xs" data-goto-page="${p.page - 1}" ${p.page <= 1 ? "disabled" : ""} title="Página anterior" aria-label="Página anterior">‹</button>
     <button class="btn btn-default btn-xs" data-goto-page="${p.page + 1}" ${p.page >= p.totalPageCount ? "disabled" : ""} title="Próxima página" aria-label="Próxima página">›</button>`
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

  const campo = document.getElementById("lCampo");
  if (campo) {
    // Trocar de campo zera o valor: manter "gold" ao passar de Porte para
    // Origem devolveria uma lista vazia sem explicar por quê.
    campo.onchange = () => {
      state.leadFilter = { ...f, field_id: campo.value, field_value: "", page: 1 };
      go("leads");
    };
    document.getElementById("lCampoOp").onchange = (e) => set("field_op", e.target.value);
    const val = document.getElementById("lCampoVal");
    let t2;
    val.oninput = () => { clearTimeout(t2); t2 = setTimeout(() => set("field_value", val.value), 350); };
  }

  const porPagina = document.getElementById("lPorPagina");
  if (porPagina) porPagina.onchange = () => set("limit", porPagina.value);
}

function selectedLeadIds() {
  return [...view.querySelectorAll(".lead-check:checked")].map((c) => Number(c.value));
}

function openBulkModal() {
  const ids = selectedLeadIds();
  if (!ids.length) return toast("Selecione ao menos um lead.", "err");
  const m = modal({
    title: `Ações em massa · ${ids.length} leads`,
    body: `<div class="field"><label for="bulkAction">Ação</label>
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
      extra.innerHTML = `<label for="bulkVal">SDR de destino</label><select class="form-control" id="bulkVal">${options(state.users, "")}</select>`;
    else if (action.value === "switch_cadence")
      extra.innerHTML = `<label for="bulkVal">Cadência</label><select class="form-control" id="bulkVal">${options(state.cadences, "")}</select>`;
    else if (action.value === "lost")
      extra.innerHTML = `<label for="bulkVal">Motivo</label><select class="form-control" id="bulkVal">${options(state.lostReasons, "")}</select>`;
    else extra.innerHTML = "";
  };
  renderExtra();
  action.onchange = renderExtra;
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const aplicar = async () => {
    try {
      const val = m.root.querySelector("#bulkVal");
      const body = { leadIds: ids, action: action.value };
      if (action.value === "transfer") body.sdrId = Number(val.value);
      if (action.value === "switch_cadence") body.cadenceId = Number(val.value);
      if (action.value === "lost") body.lostReasonId = Number(val.value);
      const res = await api("/api/flow/leads/bulk", { method: "POST", body });
      m.close(); toast(`${res.affected} leads atualizados.`, "ok"); go("leads");
    } catch (e) { toast(e.message, "err"); }
  };
  m.root.querySelector("[data-ok]").onclick = () => {
    if (action.value === "delete") {
      confirmDialog("Apagar leads", `Apagar ${ids.length} lead(s) selecionado(s)? Não dá pra desfazer.`, aplicar);
    } else {
      aplicar();
    }
  };
}

/* ── página do lead ──────────────────────────────────────────────────────
   Espelha /prospector/leads/{id}/timeline do Meetime: cabeçalho com as ações,
   coluna da esquerda com os dados e a direita em abas. O modal continua
   existindo para quem abre do meio de uma fila, mas agora o lead tem endereço. */

function passoTimeline(a) {
  if (a.kind === "CALL") {
    const [rot, tom] = a.status === "CONNECTED"
      ? ({ MEANINGFUL: ["Significativa", "green"], NOT_MEANINGFUL: ["Não significativa", "blue"],
           NO_CONTACT: ["Sem contato", "amber"] }[a.output] || ["Conectada", "grey"])
      : ["Não conectada", "red"];
    return `<div class="timeline-item">
      <span class="pill ${tom}">Ligação · ${h(rot)}</span>
      <strong class="ml-5">${h(a.receiverPhone || "—")}</strong><br>
      <span class="text-muted text-size-small">${fmtDateTime(a.originStarted)}
        · ${fmtDuration(a.receiverConnectedDuration)}
        ${a.user ? ` · ${h(a.user.name)}` : ""}</span>
    </div>`;
  }
  return `<div class="timeline-item">
    <span class="pill ${a.status === "DONE" ? "green" : a.status === "SKIPPED" ? "grey" : a.late ? "red" : "blue"}">
      ${h(TYPE_LABEL[a.type] || a.type)}</span>
    <strong class="ml-5">${h(a.activity ? a.activity.name : "")}</strong><br>
    <span class="text-muted text-size-small">
      ${a.status === "PENDING" ? `agendada ${fmtDateTime(a.scheduledAt)}${a.late ? " · atrasada" : ""}`
        : `${a.status === "DONE" ? "realizada" : "ignorada"} ${fmtDateTime(a.doneAt)}`}
      ${a.user ? ` · ${h(a.user.name)}` : ""}</span>
    ${a.notes ? `<div class="text-size-small mt-10">${h(a.notes)}</div>` : ""}
  </div>`;
}

PAGES.lead = {
  area: "Prospecção", title: "Lead",
  async render(id) {
    const l = await api(`/api/flow/leads/${id}`);
    const aba = state.leadAba || "historico";
    document.getElementById("crumbCurrent").textContent = l.name || "Lead";

    // O botão de executar age sobre a próxima atividade pendente — é o mesmo
    // objeto que a fila de Execução passa pro modal.
    const proxima = l.timeline.find((a) => a.status === "PENDING" && a.kind !== "CALL");
    // Etapa do lead mora no campo personalizado eleito pela empresa.
    const campoEtapa = state.stageField || null;
    const etapas = (state.stageOptions || []);
    const etapaAtual = campoEtapa ? (l.customFields || {})[campoEtapa.identifier] || "" : "";
    const filtro = state.leadFiltroTipo || "";
    const passos = l.timeline.filter((a) => !filtro
      || (filtro === "CALL" ? (a.kind === "CALL" || a.type === "CALL") : a.type === filtro));

    const historico = `
      <div class="toolbar">
        <select class="form-control" id="ltTipo">
          <option value="">Todos os tipos</option>
          ${Object.entries(TYPE_LABEL).map(([k, v]) =>
            `<option value="${k}"${filtro === k ? " selected" : ""}>${h(v)}</option>`).join("")}
        </select>
        <span class="spacer text-muted text-size-small">${passos.length} de ${l.timeline.length} eventos</span>
      </div>
      ${passos.length ? `<div class="timeline">${passos.map(passoTimeline).join("")}</div>`
        : emptyState("Nenhum evento no histórico com esse filtro.")}`;

    const dados = `<table class="table"><tbody>${[
      ["Empresa", h(l.company || "—")], ["Cargo", h(l.position || "—")],
      ["CNPJ", h(l.cnpj || "—")], ["Telefone", h(l.phone || "—")],
      ["E-mail", h(l.email || "—")], ["LinkedIn", h(l.linkedIn || "—")],
      ["Cidade", `${h(l.city || "—")}${l.state ? `/${h(l.state)}` : ""}`],
      ["Base", l.leadBase ? h(l.leadBase.name) : "—"],
      ["Melhor horário", `${l.bestHour}h`],
    ].map(([k, v]) => `<tr><td class="text-grey">${k}</td><td>${v}</td></tr>`).join("")}</tbody></table>`;

    const agendar = `
      <p class="text-muted text-size-small" style="margin-top:0">
        Atividade fora da cadência — para quando combinou algo com o lead que a
        sequência não prevê. Entra na fila de Execução como qualquer outra.</p>
      <div class="field-row">
        <div class="field"><label for="agTipo">Tipo</label>
          <select class="form-control" id="agTipo">
            ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
          </select></div>
        <div class="field"><label for="agQuando">Quando</label>
          <input class="form-control" type="datetime-local" id="agQuando"
            value="${new Date(Date.now() + 864e5 - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 16)}"></div>
      </div>
      <div class="field"><label for="agModelo">Atividade da biblioteca (opcional)</label>
        <select class="form-control" id="agModelo"><option value="">Nenhuma — atividade avulsa</option></select>
        <span class="help-block">Se escolher, o script e o modelo de mensagem dela vêm junto na hora de executar.</span></div>
      <div class="field"><label for="agNota">Observação</label>
        <textarea class="form-control" id="agNota" rows="3" placeholder="Por que esta atividade existe…"></textarea></div>
      <button class="btn btn-main btn-sm" id="agSalvar">Agendar</button>`;

    const anotacoes = `
      <textarea class="form-control" id="ltNotas" rows="6"
        placeholder="O que é importante lembrar sobre este lead…">${h(l.annotations || "")}</textarea>
      <button class="btn btn-main btn-sm mt-10" id="ltSalvarNotas">Salvar anotações</button>`;

    view.innerHTML = `
      <div class="panel panel-flat"><div class="panel-body">
        <div class="lead-page-head">
          <div>
            <h1 class="lead-page-title">${h(l.name)}</h1>
            <div class="text-muted">${h(l.company || "—")}${l.position ? ` · ${h(l.position)}` : ""}</div>
          </div>
          <div class="heading-elements">
            ${statusPill(l.status)}
            ${etapas.length ? `<select class="form-control input-sm" id="ltEtapa" aria-label="Etapa do lead" style="width:auto">
              <option value="">Sem etapa</option>
              ${etapas.map((e) => `<option value="${h(e)}"${etapaAtual === e ? " selected" : ""}>${h(e)}</option>`).join("")}
            </select>` : ""}
            ${l.phone ? `<button class="btn btn-default btn-sm" data-ligar>Registrar ligação</button>` : ""}
            ${proxima ? `<button class="btn btn-main btn-sm" data-exec>Executar ${h(TYPE_LABEL[proxima.type] || "atividade")}</button>` : ""}
            <button class="btn btn-success btn-sm" data-won>Ganho</button>
            <button class="btn btn-danger btn-sm" data-lost>Perdido</button>
            <button class="btn btn-default btn-sm" data-edit>Editar</button>
          </div>
        </div>
      </div></div>

      <div class="split">
        <div>
          ${panel("Lead", `<table class="table"><tbody>${[
            ["Situação", statusPill(l.status)],
            ["Cadência", l.cadence ? h(l.cadence.name) : "—"],
            ["Responsável", l.sdr ? h(l.sdr.name) : "—"],
            ["Cliente", l.client ? h(l.client.name) : "—"],
            ["Fit score", String(l.fitscore ?? 0)],
            ...(l.lostReason ? [["Motivo da perda", h(l.lostReason.name)]] : []),
          ].map(([k, v]) => `<tr><td class="text-grey">${k}</td><td>${v}</td></tr>`).join("")}</tbody></table>`)}
          ${(() => {
            const c = l.contadores;
            if (!c) return "";
            return panel("Atividade", `<table class="table"><tbody>${[
              ["Concluídas", c.concluidas],
              ["Pendentes", c.pendentes],
              ["Ligações", c.ligacoes],
              ["E-mails enviados", c.emailsEnviados],
              ["E-mails abertos", c.emailsAbertos
                ? `${c.emailsAbertos} <span class="text-muted text-size-small">(${Math.round(c.emailsAbertos / c.emailsEnviados * 100)}%)</span>`
                : "0"],
              ["Conversas", c.conversas],
              ...(c.proximaAtividade ? [["Próxima atividade", fmtDateTime(c.proximaAtividade)]] : []),
            ].map(([k, v]) => `<tr><td class="text-grey">${k}</td><td>${v}</td></tr>`).join("")}</tbody></table>`);
          })()}
          ${panel("CapiBLU", `
            <button class="btn btn-default btn-xs" data-enrich>Enriquecer</button>
            <button class="btn btn-default btn-xs" data-validate>Validar telefone</button>
            <button class="btn btn-default btn-xs" data-wa>Abrir WhatsApp</button>
            <div id="enrichOut" class="mt-10"></div>`)}
        </div>
        <div>
          <ul class="nav nav-tabs">
            ${[["historico", "Histórico"], ["agendar", "Agendar atividade"],
               ["dados", "Dados"], ["anotacoes", "Anotações"]].map(([k, v]) =>
              `<li${aba === k ? ' class="active"' : ""}><a data-laba="${k}">${v}</a></li>`).join("")}
          </ul>
          <div class="panel panel-flat"><div class="panel-body">
            ${aba === "historico" ? historico : aba === "agendar" ? agendar
              : aba === "dados" ? dados : anotacoes}
          </div></div>
        </div>
      </div>`;

    view.querySelectorAll("[data-laba]").forEach((a) => {
      a.onclick = () => { state.leadAba = a.dataset.laba; go(`lead/${id}`); };
    });
    const tipo = document.getElementById("ltTipo");
    if (tipo) tipo.onchange = (e) => { state.leadFiltroTipo = e.target.value; go(`lead/${id}`); };

    const agSalvar = document.getElementById("agSalvar");
    if (agSalvar) {
      // A biblioteca de atividades só é buscada quando a aba abre — a página
      // do lead não precisa dela para nada além deste formulário.
      api("/api/flow/activities").then((lista) => {
        const sel = document.getElementById("agModelo");
        if (!sel) return;
        const tipo = () => document.getElementById("agTipo").value;
        const preencher = () => {
          const compativeis = lista.filter((a) => a.type === tipo());
          sel.innerHTML = `<option value="">Nenhuma — atividade avulsa</option>` +
            compativeis.map((a) => `<option value="${a.id}">${h(a.name)}</option>`).join("");
        };
        preencher();
        document.getElementById("agTipo").onchange = preencher;
      }).catch(() => {});

      agSalvar.onclick = async () => {
        agSalvar.disabled = true;
        try {
          await api(`/api/flow/leads/${id}/activities`, { method: "POST", body: {
            type: document.getElementById("agTipo").value,
            scheduledAt: document.getElementById("agQuando").value,
            activityId: Number(document.getElementById("agModelo").value) || null,
            notes: document.getElementById("agNota").value,
          } });
          toast("Atividade agendada.", "ok");
          state.leadAba = "historico";
          go(`lead/${id}`);
        } catch (e) { toast(e.message, "err"); agSalvar.disabled = false; }
      };
    }

    const notas = document.getElementById("ltSalvarNotas");
    if (notas) notas.onclick = async () => {
      notas.disabled = true;
      try {
        await api(`/api/flow/leads/${id}`, { method: "PATCH",
          body: { annotations: document.getElementById("ltNotas").value } });
        toast("Anotações salvas.", "ok");
      } catch (e) { toast(e.message, "err"); }
      notas.disabled = false;
    };

    const selEtapa = document.getElementById("ltEtapa");
    if (selEtapa) selEtapa.onchange = async () => {
      selEtapa.disabled = true;
      try {
        await api(`/api/flow/leads/${id}/stage`, { method: "PUT", body: { stage: selEtapa.value } });
        toast(selEtapa.value ? `Etapa: ${selEtapa.value}.` : "Etapa removida.", "ok");
      } catch (e) { toast(e.message, "err"); }
      selEtapa.disabled = false;
    };

    const btLigar = view.querySelector("[data-ligar]");
    if (btLigar) btLigar.onclick = () => openRegistrarLigacao(l, () => go(`lead/${id}`));

    view.querySelector("[data-edit]").onclick = () => openLeadForm(l);
    const btExec = view.querySelector("[data-exec]");
    if (btExec) btExec.onclick = () => openExecuteModal(proxima);
    view.querySelector("[data-won]").onclick = async () => {
      try {
        await api(`/api/flow/execution/leads/${l.id}/outcome`, { method: "POST", body: { outcome: "WON" } });
        toast("Lead ganho.", "ok"); go(`lead/${id}`);
      } catch (e) { toast(e.message, "err"); }
    };
    view.querySelector("[data-lost]").onclick = () => openLostModal(l.id, () => go(`lead/${id}`));
    view.querySelector("[data-wa]").onclick = async () => {
      try {
        const conv = await api("/api/whatsapp/conversations", { method: "POST", body: { leadId: l.id } });
        state.waActive = conv.id; go("whatsapp");
      } catch (e) { toast(e.message, "err"); }
    };

    const out = document.getElementById("enrichOut");
    view.querySelector("[data-enrich]").onclick = async () => {
      out.innerHTML = `<span class="spinner"></span> consultando CapiBLU…`;
      try {
        const r = await api(`/api/capiblu/leads/${l.id}/enrich`, { method: "POST" });
        out.innerHTML = `<div class="alert alert-success alert-styled-left">
          ${r.updated.length ? `Campos atualizados: ${h(r.updated.join(", "))}.` : "Nada novo a preencher."}
          ${r.contacts.length} contato(s) encontrados na empresa.</div>`;
      } catch (e) { out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; }
    };
    view.querySelector("[data-validate]").onclick = async () => {
      out.innerHTML = `<span class="spinner"></span> validando telefone…`;
      try {
        const r = await api(`/api/capiblu/leads/${l.id}/validate-phone`, { method: "POST" });
        out.innerHTML = `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>`;
      } catch (e) { out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; }
    };
  },
};

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
    try {
      await api(`/api/flow/execution/leads/${l.id}/outcome`, { method: "POST", body: { outcome: "WON" } });
      m.close(); toast("Lead ganho.", "ok"); go(state.page);
    } catch (e) { toast(e.message, "err"); }
  };
  m.root.querySelector("[data-lost]").onclick = () => { m.close(); openLostModal(l.id, () => go(state.page)); };
  m.root.querySelector("[data-wa]").onclick = async () => {
    try {
      const conv = await api("/api/whatsapp/conversations", { method: "POST", body: { leadId: l.id } });
      m.close(); state.waActive = conv.id; go("whatsapp");
    } catch (e) { toast(e.message, "err"); }
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
    } catch (e) { out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; }
  };
  m.root.querySelector("[data-validate]").onclick = async () => {
    out.innerHTML = `<span class="spinner"></span> validando telefone…`;
    try {
      const r = await api(`/api/capiblu/leads/${l.id}/validate-phone`, { method: "POST" });
      out.innerHTML = `<div class="json-box">${h(JSON.stringify(r, null, 2))}</div>`;
    } catch (e) { out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; }
  };
}

/** Registrar uma ligação avulsa a partir do lead.
 *  No original é o botão "Ligar" do cabeçalho; aqui não há softphone, então o
 *  que existe é lançar o resultado — que é o que alimenta funil e ranking. */
/** Detalhe da ligação com o histórico de coaching.
 *  É o `modalCallDetails` do original menos gravação e transcrição, que
 *  dependem de telefonia — o resto (custo, resultado, lead, feedback) existe. */
async function openDetalheLigacao(id) {
  let d;
  try { d = await api(`/api/dialer/calls/${id}/detail`); }
  catch (e) { return toast(e.message, "err"); }

  const OUT = { MEANINGFUL: "Significativa", NOT_MEANINGFUL: "Não significativa",
                NO_CONTACT: "Sem contato" };
  const souDono = state.me && d.user && state.me.id === d.user.id;

  const listaFeedback = (fs) => fs.length ? fs.map((f) => `
    <div class="timeline-item">
      <strong>${h((f.author || {}).name || "—")}</strong>
      <span class="text-muted text-size-small ml-5">${fmtDateTime(f.createdAt)}${f.updatedAt ? " · editado" : ""}</span>
      ${f.readAt ? `<span class="pill green ml-5">lido</span>`
        : `<span class="pill amber ml-5">não lido</span>`}
      <div class="mt-10" style="white-space:pre-wrap">${h(f.text)}</div>
      ${!f.readAt && souDono ? `<button class="btn btn-default btn-xs mt-10" data-ler="${f.id}">Marcar como lido</button>` : ""}
    </div>`).join("") : emptyState("Nenhum feedback nesta ligação ainda.");

  const m = modal({
    title: `Ligação · ${d.receiverPhone || "—"}`, wide: true,
    body: `
      <div class="split">
        <div>
          <table class="table"><tbody>
            <tr><td class="text-grey">Quando</td><td>${fmtDateTime(d.originStarted)}</td></tr>
            <tr><td class="text-grey">Usuário</td><td>${h((d.user || {}).name || "—")}</td></tr>
            <tr><td class="text-grey">Origem</td><td>${h(d.originPhone || "—")}</td></tr>
            <tr><td class="text-grey">Destino</td><td>${h(d.receiverPhone || "—")}</td></tr>
            <tr><td class="text-grey">Tipo</td><td>${d.receiverType === "MOBILE" ? "Celular" : "Fixo"}</td></tr>
            <tr><td class="text-grey">Duração</td><td>${fmtDuration(d.receiverConnectedDuration)}</td></tr>
            <tr><td class="text-grey">Custo</td><td>${fmtMoney(d.receiverPrice)}</td></tr>
          </tbody></table>
          ${d.lead ? `<div class="detail-note">Lead:
            <a data-ir-lead="${d.lead.id}"><strong>${h(d.lead.name)}</strong></a>
            ${d.lead.company ? ` · ${h(d.lead.company)}` : ""}</div>` : ""}
          <div class="field mt-10"><label for="dlOut">Resultado</label>
            <select class="form-control" id="dlOut"${d.status === "CONNECTED" ? "" : " disabled"}>
              <option value="">—</option>
              ${Object.entries(OUT).map(([k, v]) => `<option value="${k}"${d.output === k ? " selected" : ""}>${v}</option>`).join("")}
            </select>
            <span class="help-block">${d.status === "CONNECTED"
              ? "Dá para reclassificar depois — foi ouvindo de novo que se descobre que não era significativa."
              : "A ligação não conectou, então não há resultado a classificar."}</span></div>
          <div class="alert alert-info alert-styled-left text-size-small">
            Gravação e transcrição dependem de telefonia, que ainda não está ligada.
          </div>
        </div>
        <div>
          <h4 style="margin:0 0 10px;font-size:13px">Coaching</h4>
          <div class="timeline" id="dlFeedbacks">${listaFeedback(d.feedbacks)}</div>
          ${nivelPeloMenos("gestor") ? `
            <div class="field mt-10">
              <textarea class="form-control" id="dlTexto" rows="3" placeholder="O que funcionou e o que faria diferente…"></textarea>
            </div>
            <button class="btn btn-main btn-sm" id="dlEnviar">Adicionar feedback</button>`
            : `<span class="text-muted text-size-small">Só gestor escreve feedback.</span>`}
        </div>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-fechar>Fechar</button>`,
  });

  m.root.querySelector("[data-fechar]").onclick = m.close;
  const irLead = m.root.querySelector("[data-ir-lead]");
  if (irLead) irLead.onclick = () => { m.close(); go(`lead/${irLead.dataset.irLead}`); };

  const sel = m.root.querySelector("#dlOut");
  if (sel && !sel.disabled) sel.onchange = async () => {
    try {
      await api(`/api/dialer/calls/${id}`, { method: "PATCH", body: { output: sel.value } });
      toast("Resultado atualizado.", "ok");
    } catch (e) { toast(e.message, "err"); }
  };

  const recarregar = async () => {
    const novo = await api(`/api/dialer/calls/${id}/detail`);
    m.root.querySelector("#dlFeedbacks").innerHTML = listaFeedback(novo.feedbacks);
    ligarLeitura();
  };
  const ligarLeitura = () => {
    m.root.querySelectorAll("[data-ler]").forEach((b) => {
      b.onclick = async () => {
        try {
          await api(`/api/dialer/calls/feedback/${b.dataset.ler}`, { method: "PATCH", body: { read: true } });
          await recarregar();
        } catch (e) { toast(e.message, "err"); }
      };
    });
  };
  ligarLeitura();

  const enviar = m.root.querySelector("#dlEnviar");
  if (enviar) enviar.onclick = async () => {
    const txt = m.root.querySelector("#dlTexto");
    if (!txt.value.trim()) return toast("Escreva o feedback.", "err");
    enviar.disabled = true;
    try {
      await api(`/api/dialer/calls/${id}/feedback`, { method: "POST", body: { text: txt.value } });
      txt.value = "";
      await recarregar();
      toast("Feedback enviado.", "ok");
    } catch (e) { toast(e.message, "err"); }
    enviar.disabled = false;
  };
}

function openRegistrarLigacao(lead, depois) {
  const m = modal({
    title: `Registrar ligação — ${lead.name}`,
    body: `
      <div class="field"><label for="rlFone">Número discado</label>
        <input class="form-control" id="rlFone" value="${h((lead.phone || "").split(",")[0].trim())}"></div>
      <div class="field-row">
        <div class="field"><label for="rlStatus">Situação</label>
          <select class="form-control" id="rlStatus">
            <option value="CONNECTED">Conectada</option>
            <option value="NOT_PERFORMED">Não conectada</option>
          </select></div>
        <div class="field"><label for="rlDur">Duração (segundos)</label>
          <input class="form-control" type="number" min="0" id="rlDur" value="0"></div>
      </div>
      <div class="field"><label for="rlOut">Resultado</label>
        <select class="form-control" id="rlOut">
          <option value="MEANINGFUL">Significativa</option>
          <option value="NOT_MEANINGFUL">Não significativa</option>
          <option value="NO_CONTACT">Sem contato</option>
        </select></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Registrar</button>`,
  });
  const status = m.root.querySelector("#rlStatus");
  const out = m.root.querySelector("#rlOut");
  // Resultado só faz sentido em ligação que conectou; deixar habilitado
  // convidaria a registrar "significativa" numa chamada que ninguém atendeu.
  const sincronizar = () => { out.disabled = status.value !== "CONNECTED"; };
  status.onchange = sincronizar;
  sincronizar();
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async (ev) => {
    const bt = ev.currentTarget;
    bt.disabled = true;
    try {
      await api("/api/dialer/calls", { method: "POST", body: {
        leadId: lead.id,
        receiverPhone: m.root.querySelector("#rlFone").value.trim(),
        status: status.value,
        output: status.value === "CONNECTED" ? out.value : "",
        duration: Number(m.root.querySelector("#rlDur").value) || 0,
      } });
      m.close(); toast("Ligação registrada.", "ok"); depois && depois();
    } catch (e) { toast(e.message, "err"); bt.disabled = false; }
  };
}

/** Editar um campo personalizado. O identificador fica de fora de propósito:
 *  é a chave do valor já gravado em cada lead e das merge tags dos modelos. */
function openCampoForm(campo) {
  const f = campo || {};
  const m = modal({
    title: `Editar campo — ${f.name || ""}`,
    body: `
      <div class="field"><label for="cpNome">Nome *</label>
        <input class="form-control" id="cpNome" value="${h(f.name || "")}"></div>
      <div class="field"><label for="cpIdent">Identificador</label>
        <input class="form-control" id="cpIdent" value="${h(f.identifier || "")}" disabled>
        <span class="help-block">Não muda: é a chave do valor já gravado em cada lead e das merge tags.</span></div>
      <div class="field"><label for="cpOrdem">Ordem</label>
        <input class="form-control" type="number" id="cpOrdem" value="${f.index || 0}"></div>
      <div class="field">
        <label><input type="checkbox" id="cpVisivel"${f.visible !== false ? " checked" : ""}> Visível no formulário do lead</label></div>
      <div class="field">
        <label><input type="checkbox" id="cpGanhar"${f.wonMandatory ? " checked" : ""}> Obrigatório para marcar como ganho</label></div>
      <div class="field">
        <label><input type="checkbox" id="cpPerder"${f.lostMandatory ? " checked" : ""}> Obrigatório para marcar como perdido</label></div>
      <div class="field"><label for="cpOpcoes">Opções, uma por linha</label>
        <textarea class="form-control" id="cpOpcoes" rows="4">${h((f.options || []).join("\n"))}</textarea>
        <span class="help-block">Só faz sentido em campo de escolha. É daqui que saem as etapas, se este for o campo do funil.</span></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async (ev) => {
    const bt = ev.currentTarget;
    const nome = m.root.querySelector("#cpNome").value.trim();
    if (!nome) return toast("O campo precisa de um nome.", "err");
    bt.disabled = true;
    try {
      await api(`/api/flow/new-lead-fields/${f.id}`, { method: "PATCH", body: {
        name: nome,
        index: Number(m.root.querySelector("#cpOrdem").value) || 0,
        visible: m.root.querySelector("#cpVisivel").checked,
        wonMandatory: m.root.querySelector("#cpGanhar").checked,
        lostMandatory: m.root.querySelector("#cpPerder").checked,
        options: m.root.querySelector("#cpOpcoes").value.split("\n"),
      } });
      m.close(); toast("Campo atualizado.", "ok"); go("ajustes");
    } catch (e) { toast(e.message, "err"); bt.disabled = false; }
  };
}

function openTeamForm(time, usuarios) {
  const t = time || {};
  const dentro = new Set((t.users || []).map((u) => u.id));
  const m = modal({
    title: t.id ? `Editar ${t.name}` : "Novo time",
    body: `
      <div class="field"><label for="tmNome">Nome do time *</label>
        <input class="form-control" id="tmNome" value="${h(t.name || "")}"></div>
      <div class="field"><label>Integrantes</label>
        <div class="chip-grid" id="tmGente">
          ${usuarios.map((u) => `<button type="button" class="chip${dentro.has(u.id) ? " active" : ""}"
            data-uid="${u.id}">${h(u.name)}</button>`).join("")}
        </div>
        <span class="help-block">Uma pessoa pertence a um time só — marcar aqui tira do time anterior.</span></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });
  m.root.querySelectorAll("#tmGente .chip").forEach((c) => {
    c.onclick = () => c.classList.toggle("active");
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async (ev) => {
    const bt = ev.currentTarget;
    const nome = m.root.querySelector("#tmNome").value.trim();
    if (!nome) return toast("Dê um nome ao time.", "err");
    bt.disabled = true;
    const corpo = { name: nome,
      userIds: [...m.root.querySelectorAll("#tmGente .chip.active")].map((c) => Number(c.dataset.uid)) };
    try {
      await api(t.id ? `/api/teams/${t.id}` : "/api/teams",
                { method: t.id ? "PATCH" : "POST", body: corpo });
      m.close(); toast("Time salvo.", "ok"); go("usuarios");
    } catch (e) { toast(e.message, "err"); bt.disabled = false; }
  };
}

function openLeadForm(lead) {
  const l = lead || {};
  const m = modal({
    title: l.id ? `Editar ${l.name}` : "Novo lead",
    body: `
      <div class="field-row">
        <div class="field"><label for="fName">Nome *</label><input class="form-control" id="fName" value="${h(l.name || "")}"></div>
        <div class="field"><label for="fPosition">Cargo</label><input class="form-control" id="fPosition" value="${h(l.position || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="fCompany">Empresa</label><input class="form-control" id="fCompany" value="${h(l.company || "")}"></div>
        <div class="field"><label for="fCnpj">CNPJ</label><input class="form-control" id="fCnpj" value="${h(l.cnpj || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="fPhone">Telefone</label><input class="form-control" id="fPhone" value="${h(l.phone || "")}"></div>
        <div class="field"><label for="fEmail">E-mail</label><input class="form-control" id="fEmail" value="${h(l.email || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="fCity">Cidade</label><input class="form-control" id="fCity" value="${h(l.city || "")}"></div>
        <div class="field"><label for="fState">UF</label><input class="form-control" id="fState" value="${h(l.state || "")}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="fClient">Cliente</label>
          <select class="form-control" id="fClient">${options(state.clients, l.client && l.client.id, { blank: "—" })}</select></div>
        <div class="field"><label for="fSdr">SDR</label>
          <select class="form-control" id="fSdr">${options(state.users, l.sdr && l.sdr.id, { blank: "—" })}</select></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="fCadence">Cadência</label>
          <select class="form-control" id="fCadence">${options(state.cadences, l.cadence && l.cadence.id, { blank: "—" })}</select></div>
        <div class="field"><label for="fHour">Melhor horário de contato</label>
          <input class="form-control" type="number" min="6" max="22" id="fHour" value="${l.bestHour || 18}"></div>
      </div>
      <div class="field"><label for="fNotes">Anotações</label><textarea class="form-control" id="fNotes">${h(l.annotations || "")}</textarea></div>
      ${(state.leadFields || []).length ? `<div class="sub-block">
        <h4>Campos personalizados</h4>
        <div class="field-row">
          ${(state.leadFields || []).map((c) => {
            const atual = (l.customFields || {})[c.identifier] || "";
            const opcoes = c.options || [];
            return `<div class="field"><label for="cf-${h(c.identifier)}">${h(c.name)}</label>
              ${opcoes.length
                ? `<select class="form-control" data-cf="${h(c.identifier)}" id="cf-${h(c.identifier)}">
                     <option value="">—</option>
                     ${opcoes.map((o) => `<option value="${h(o)}"${atual === o ? " selected" : ""}>${h(o)}</option>`).join("")}
                   </select>`
                : `<input class="form-control" data-cf="${h(c.identifier)}" id="cf-${h(c.identifier)}" value="${h(atual)}">`}
            </div>`;
          }).join("")}
        </div></div>` : ""}`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async (e) => {
    const g = (id) => m.root.querySelector(id).value.trim();
    const body = {
      name: g("#fName"), position: g("#fPosition"), company: g("#fCompany"),
      cnpj: g("#fCnpj"), phone: g("#fPhone"), email: g("#fEmail"),
      city: g("#fCity"), state: g("#fState"), annotations: g("#fNotes"),
      bestHour: Number(g("#fHour")) || 18,
      customFields: Object.fromEntries(
        [...m.root.querySelectorAll("[data-cf]")].map((el) => [el.dataset.cf, el.value])),
      clientId: Number(g("#fClient")) || null, sdrId: Number(g("#fSdr")) || null,
      cadenceId: Number(g("#fCadence")) || null,
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      if (l.id) await api(`/api/flow/leads/${l.id}`, { method: "PATCH", body });
      else await api("/api/flow/leads", { method: "POST", body });
      m.close(); toast("Lead salvo.", "ok"); go("leads");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
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
      // Clicar no número leva para a lista já filtrada — o overview do
      // original é porta de entrada, não só contagem.
      `<a data-drill="${c.id}" data-st="">${c.overview.total}</a>`,
      `<a data-drill="${c.id}" data-st="WAITING">${c.overview.waiting}</a>`,
      `<a data-drill="${c.id}" data-st="EXECUTING">${c.overview.executing + c.overview.onExtraActivity}</a>`,
      `<a data-drill="${c.id}" data-st="WON" style="color:#00a443">${c.overview.won}</a>`,
      `<a data-drill="${c.id}" data-st="LOST" style="color:#f44336">${c.overview.lost}</a>`,
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
        table(["Cadência", "Cliente", "Foco", "Prioridade", "Etapas", "Leads",
               "Esperando", "Em execução", "Ganhos", "Perdidos", "Conversão",
               "Responsáveis", "Situação", ""], rows, { scroll: true }))}`;

    const set = (k, v) => { state.cadFilter = { ...f, [k]: v }; go("cadencias"); };
    const q = document.getElementById("cq");
    let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => set("q", q.value), 350); };
    document.getElementById("cClient").onchange = (e) => set("client_id", e.target.value);
    document.getElementById("cFocus").onchange = (e) => set("focus", e.target.value);
    document.getElementById("cPrio").onchange = (e) => set("priority", e.target.value);
    document.getElementById("newCad").onclick = () => openCadenceForm();
    view.querySelectorAll("[data-drill]").forEach((a) => {
      a.onclick = () => {
        state.leadFilter = { page: 1, limit: 50, cadence_id: a.dataset.drill,
                             status: a.dataset.st || "" };
        go("leads");
      };
    });
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
      body: `<div class="field"><label for="stepAct">Atividade</label>
          <select class="form-control" id="stepAct">${options(acts, "")}</select></div>
        <div class="field" id="stepTplBox"><label for="stepTpl">Modelo de mensagem</label>
          <select class="form-control" id="stepTpl"></select>
          <span class="text-muted text-size-small" id="stepTplAviso"></span></div>
        <div class="field"><label for="stepDay">Dia da cadência</label>
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
    b.onclick = () => confirmDialog("Remover etapa", "Remover esta etapa da cadência?", async () => {
      try {
        await api(`/api/flow/cadences/${id}/steps/${b.dataset.delStep}`, { method: "DELETE" });
        toast("Etapa removida."); openCadenceDetail(id);
      } catch (e) { toast(e.message, "err"); }
    });
  });
}

function openCadenceForm(cad) {
  const c = cad || {};
  const m = modal({
    title: c.id ? `Editar ${c.name}` : "Nova cadência",
    body: `
      <div class="field"><label for="cName">Nome *</label><input class="form-control" id="cName" value="${h(c.name || "")}"></div>
      <div class="field"><label for="cDesc">Descrição</label><textarea class="form-control" id="cDesc">${h(c.description || "")}</textarea></div>
      <div class="field-row">
        <div class="field"><label for="cClientSel">Cliente</label>
          <select class="form-control" id="cClientSel">${options(state.clients, c.client && c.client.id, { blank: "—" })}</select></div>
        <div class="field"><label for="cFocusSel">Foco</label>
          <select class="form-control" id="cFocusSel">
            ${Object.entries(FOCUS_LABEL).map(([k, v]) => `<option value="${k}"${c.cadenceFocus === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="cPrioSel">Prioridade</label>
          <select class="form-control" id="cPrioSel">
            ${Object.entries(PRIORITY_LABEL).map(([k, v]) => `<option value="${k}"${c.priority === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
        <div class="field"><label for="cExec">Situação</label>
          <select class="form-control" id="cExec">
            <option value="true"${c.executing !== false ? " selected" : ""}>Ativa</option>
            <option value="false"${c.executing === false ? " selected" : ""}>Pausada</option>
          </select></div>
      </div>
      <div class="field"><label for="cUsers">Responsáveis</label>
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
  m.root.querySelector("[data-save]").onclick = async (e) => {
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
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      if (c.id) await api(`/api/flow/cadences/${c.id}`, { method: "PATCH", body });
      else await api("/api/flow/cadences", { method: "POST", body });
      m.close(); toast("Cadência salva.", "ok"); go("cadencias");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
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
       <button class="btn btn-default btn-xs" data-dup-act="${a.id}">Duplicar</button>
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
    view.querySelectorAll("[data-dup-act]").forEach((b) => {
      b.onclick = () => {
        const base = list.find((a) => String(a.id) === b.dataset.dupAct);
        // Sem `id` o formulário salva como nova — é o "criar a partir desta"
        // do original, que poupa reescrever script e assunto do zero.
        openActivityForm({ ...base, id: null, name: `${base.name} (cópia)` });
      };
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
      <div class="field"><label for="aName">Nome *</label><input class="form-control" id="aName" value="${h(a.name || "")}"></div>
      <div class="field-row">
        <div class="field"><label for="aTypeSel">Tipo</label>
          <select class="form-control" id="aTypeSel">
            ${Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}"${a.type === k ? " selected" : ""}>${v}</option>`).join("")}
          </select></div>
        <div class="field"><label for="aSocial">Rede (ponto social)</label>
          <select class="form-control" id="aSocial">
            <option value="">—</option>
            <option value="WHATSAPP"${a.socialNetwork === "WHATSAPP" ? " selected" : ""}>WhatsApp</option>
            <option value="LINKEDIN"${a.socialNetwork === "LINKEDIN" ? " selected" : ""}>LinkedIn</option>
          </select></div>
      </div>
      <div class="field"><label for="aInstr">Instrução / script</label>
        <textarea class="form-control" id="aInstr">${h(a.instruction || "")}</textarea></div>
      <div class="field"><label for="aSubject">Assunto do e-mail</label>
        <input class="form-control" id="aSubject" value="${h(tpl.subject || "")}"></div>
      <div class="field"><label for="aHtml">Corpo do e-mail (HTML)</label>
        <textarea class="form-control" id="aHtml">${h(tpl.html || "")}</textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async (e) => {
    const body = {
      name: m.root.querySelector("#aName").value.trim(),
      type: m.root.querySelector("#aTypeSel").value,
      socialNetwork: m.root.querySelector("#aSocial").value,
      instruction: m.root.querySelector("#aInstr").value,
      emailTemplate: { subject: m.root.querySelector("#aSubject").value,
                       html: m.root.querySelector("#aHtml").value },
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      if (a.id) await api(`/api/flow/activities/${a.id}`, { method: "PATCH", body });
      else await api("/api/flow/activities", { method: "POST", body });
      m.close(); toast("Atividade salva.", "ok"); go("atividades");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
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
       ${b.sourceQuery ? `<button class="btn btn-default btn-xs" data-query="${b.id}">Ver consulta</button>` : ""}
       ${nivelPeloMenos("admin") ? `<button class="btn btn-default btn-xs" data-del-base="${b.id}"
         data-nome="${h(b.name)}" data-n="${b.numberOfLeads}">Excluir</button>` : ""}`,
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
    view.querySelectorAll("[data-del-base]").forEach((b) => {
      const n = Number(b.dataset.n) || 0;
      b.onclick = () => confirmDialog("Excluir base",
        n ? `Excluir "${b.dataset.nome}" apaga também os ${n} leads importados por ela, com o histórico de cada um. Não dá pra desfazer.`
          : `Excluir a base "${b.dataset.nome}"?`,
        async () => {
          try {
            const r = await api(`/api/flow/lead-bases/${b.dataset.delBase}?com_leads=${n > 0}`,
                                { method: "DELETE" });
            toast(r.leadsApagados ? `Base e ${r.leadsApagados} leads apagados.` : "Base apagada.", "ok");
            go("bases");
          } catch (e) { toast(e.message, "err"); }
        });
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
        <div class="field"><label for="wizFile">Arquivo CSV</label>
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
        <div class="field"><label for="wizName">Nome da base *</label>
          <input class="form-control" id="wizName" value="[Importação CSV] - ${new Date().toLocaleDateString("pt-BR")}"></div>
        <div class="field-row">
          <div class="field"><label for="wizClient">Cliente</label>
            <select class="form-control" id="wizClient">${options(state.clients, "", { blank: "—" })}</select></div>
          <div class="field"><label for="wizSdr">SDR</label>
            <select class="form-control" id="wizSdr">${options(state.users, "", { blank: "—" })}</select></div>
        </div>
        <div class="field"><label for="wizCad">Colocar em cadência</label>
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
    body: `<div class="field"><label for="clName">Nome *</label><input class="form-control" id="clName" value="${h(c.name || "")}"></div>
      <div class="field-row">
        <div class="field"><label for="clColor">Cor</label><input class="form-control" type="color" id="clColor" value="${h(c.color || "#00a443")}"></div>
        <div class="field"><label for="clActive">Situação</label>
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
  m.root.querySelector("[data-save]").onclick = async (e) => {
    const body = { name: m.root.querySelector("#clName").value.trim(),
                   color: m.root.querySelector("#clColor").value,
                   active: m.root.querySelector("#clActive").value === "true" };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      if (c.id) await api(`/api/clients/${c.id}`, { method: "PATCH", body });
      else await api("/api/clients", { method: "POST", body });
      m.close(); toast("Cliente salvo.", "ok"); go("clientes");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
  };
}

/* ── Ligações ────────────────────────────────────────────────────────── */
PAGES.ligacoes = {
  area: "Ligações", title: "Painel de Ligações",
  async render() {
    // Ligações derrubadas: conectou e caiu em até 10s. Não é falha técnica, é
    // sinal de abordagem — e não aparecia em tela nenhuma.
    const qs = filtrosQS();
    const [ov, derrubadas] = await Promise.all([
      api(`/api/dialer/calls/statistics/overview${qs}`),
      api(`/api/dialer/calls/statistics/dropped${qs}`).catch(() => ({ data: [] })),
    ]);
    const o = ov.data[0];
    const best = o.bestHourToCall;
    const listaDerrubadas = derrubadas.data || [];
    view.innerHTML = `
      <div class="toolbar">${periodoControle()}${timeControle()}</div>
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
    ligarPeriodo(() => go("ligacoes"));
  },
};

/* ── estatísticas de ligação ──────────────────────────────────────────────
   Funil, volume e histórico: três telas que o Meetime tem em
   /statistics/dialer e que aqui não existiam (a auditoria deu 5%, 0% e 10%).
   Todas saem da mesma tabela de ligações, então vivem em abas. */

function variacaoSelo(v) {
  if (!v) return "";
  // Sem período anterior não há percentual — mostra só o absoluto em vez de
  // fingir um crescimento que ninguém consegue conferir.
  if (v.percentual === null) {
    return v.diferenca ? `<span class="pill grey">${v.diferenca > 0 ? "+" : ""}${v.diferenca}</span>` : "";
  }
  const sobe = v.percentual >= 0;
  return `<span class="pill ${sobe ? "green" : "red"}" title="${v.diferenca > 0 ? "+" : ""}${v.diferenca} contra o período anterior">
    ${sobe ? "▲" : "▼"} ${Math.abs(v.percentual)}%</span>`;
}

const CALL_STATUS_LABEL = {
  CONNECTED: "Conectada", NOT_PERFORMED: "Não realizada",
  NOT_ANSWERED: "Não atendida", BUSY: "Ocupado", FAILED: "Falhou",
};
const CALL_OUTPUT_LABEL = {
  MEANINGFUL: "Significativa", NOT_MEANINGFUL: "Não significativa",
  NO_CONTACT: "Sem contato", SEM_CLASSIFICACAO: "Sem classificação",
};

/** Linha acumulada de ligações — o `cumulative` do original. */
function grafLinha(serie, campo, cor, rotulo) {
  if (!serie.length) return emptyState("Sem ligações no período.");
  const W = 760, H = 240, padL = 42, padB = 26;
  const max = Math.max(1, ...serie.map((s) => s[campo]));
  const x = (i) => padL + (i * (W - padL - 10)) / Math.max(1, serie.length - 1);
  const y = (v) => H - padB - (v / max) * (H - padB - 14);
  const pts = serie.map((s, i) => `${x(i)},${y(s[campo])}`).join(" ");
  const grid = [...new Set([0, Math.round(max / 2), max])].map((v) => `
    <line x1="${padL}" y1="${y(v)}" x2="${W - 10}" y2="${y(v)}" stroke="#eee"/>
    <text x="6" y="${y(v) + 4}" font-size="11" fill="#999">${v}</text>`).join("");
  return `<div class="fb-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${h(rotulo)}">
      ${grid}
      <polygon points="${padL},${y(0)} ${pts} ${x(serie.length - 1)},${y(0)}" fill="${cor}22"/>
      <polyline points="${pts}" fill="none" stroke="${cor}" stroke-width="3"/>
      <text x="${padL}" y="${H - 6}" font-size="11" fill="#999">${fbDiaLegivel(serie[0].data)}</text>
      <text x="${W - 70}" y="${H - 6}" font-size="11" fill="#999">${fbDiaLegivel(serie[serie.length - 1].data)}</text>
    </svg></div>`;
}

PAGES["estatisticas-ligacoes"] = {
  area: "Estatísticas", title: "Ligações",
  async render() {
    const aba = state.estLigAba || "geral";
    const qs = filtrosQS();

    const abas = `<ul class="nav nav-tabs">
      ${[["geral", "Visão geral"], ["funil", "Funil"], ["detalhamento", "Detalhamento"],
         ["volume", "Volume"], ["historico", "Histórico"], ["horario", "Horário ideal"]]
        .map(([k, v]) => `<li${aba === k ? ' class="active"' : ""}><a data-estlig="${k}">${v}</a></li>`).join("")}
    </ul>`;

    let corpo = "";
    if (aba === "geral") {
      const [f, d] = await Promise.all([
        api(`/api/dialer/calls/statistics/funnel${qs}`),
        api(`/api/dialer/calls/statistics/distribution${qs}`),
      ]);
      corpo = `
        ${kpis([
          { value: f.atual.total, label: "Realizadas", tone: "info" },
          { value: f.atual.conectadas, label: "Conectadas", tone: "success" },
          { value: f.atual.significativas, label: "Significativas", tone: "success" },
          { value: `${f.taxas.conexao}%`, label: "Taxa de conexão" },
        ])}
        <div class="two-col mt-10">
          ${panel("Distribuição por status", bars(d.status.map((r) => ({
            label: CALL_STATUS_LABEL[r.chave] || r.chave, value: r.total,
            tone: r.chave === "CONNECTED" ? "success" : "warning" }))),
            { subtitle: "O que aconteceu com cada tentativa" })}
          ${panel("Resultado das conectadas", bars(d.resultado.map((r) => ({
            label: CALL_OUTPUT_LABEL[r.chave] || r.chave, value: r.total,
            tone: r.chave === "MEANINGFUL" ? "success" : "info" }))),
            { subtitle: "Como o SDR classificou a conversa" })}
        </div>`;
    } else if (aba === "funil") {
      const f = await api(`/api/dialer/calls/statistics/funnel${qs}`);
      const etapa = (rot, valor, chave, sub) => `
        <div class="kpi">
          <div class="number">${valor}</div>
          <div class="caption">${rot} ${variacaoSelo(f.comparacao[chave])}</div>
          ${sub ? `<div class="text-muted text-size-small mt-10">${sub}</div>` : ""}
        </div>`;
      corpo = `
        <div class="kpi-row" style="grid-template-columns:repeat(3,1fr)">
          ${etapa("Realizadas", f.atual.total, "total", "")}
          ${etapa("Conectadas", f.atual.conectadas, "conectadas", `${f.taxas.conexao}% das realizadas`)}
          ${etapa("Significativas", f.atual.significativas, "significativas", `${f.taxas.significancia}% das conectadas`)}
        </div>
        ${panel("Funil", bars([
          { label: "Realizadas", value: f.atual.total, tone: "info" },
          { label: "Conectadas", value: f.atual.conectadas, tone: "success" },
          { label: "Significativas", value: f.atual.significativas, tone: "success" },
        ]), { subtitle: `Comparado com ${fmtDate(f.periodoAnterior.since)} a ${fmtDate(f.periodoAnterior.until)}` })}`;
    } else if (aba === "detalhamento") {
      const st = state.estLigStatus || "";
      const c = await api(`/api/dialer/calls/statistics/cumulative${filtrosQS(st ? { status: st } : {})}`);
      const ultimo = c.data[c.data.length - 1] || { total: 0, conectadas: 0, significativas: 0 };
      corpo = `
        <div class="toolbar">
          <select class="form-control input-sm" id="elStatus">
            <option value="">Todas as ligações</option>
            ${Object.entries(CALL_STATUS_LABEL).map(([k, v]) =>
              `<option value="${k}"${st === k ? " selected" : ""}>${v}</option>`).join("")}
          </select>
        </div>
        ${kpis([
          { value: ultimo.total, label: "Acumulado no período", tone: "info" },
          { value: ultimo.conectadas, label: "Conectadas", tone: "success" },
          { value: ultimo.significativas, label: "Significativas", tone: "success" },
        ])}
        ${panel("Realizadas (acumulado)", grafLinha(c.data, "total", "#2196f3", "Ligações acumuladas"),
          { subtitle: "A série diária diz se hoje foi bom; a acumulada diz se o período está no ritmo" })}
        ${panel("Conectadas (acumulado)", grafLinha(c.data, "conectadas", "#00c850", "Conectadas acumuladas"))}`;
    } else if (aba === "volume") {
      const por = state.estLigPor || "user";
      const g = await api(`/api/dialer/calls/statistics/grouped${filtrosQS({ by: por })}`);
      corpo = `
        <div class="toolbar">
          <select class="form-control input-sm" id="elPor">
            <option value="user"${por === "user" ? " selected" : ""}>Por usuário</option>
            <option value="team"${por === "team" ? " selected" : ""}>Por time</option>
          </select>
        </div>
        ${panel("Como está o volume de ligações",
          table(["Quem", "Ligações", "Conectadas", "Conexão"],
            g.data.map((r) => ({ cells: [h(r.label), r.total, r.conectadas,
              `${r.total ? Math.round(r.conectadas / r.total * 100) : 0}%`] })),
            { empty: "Nenhuma ligação no período." }))}`;
    } else if (aba === "horario") {
      const b = await api(`/api/dialer/calls/statistics/best-hour${qs}`);
      const comVolume = b.data.filter((r) => r.total);
      corpo = `
        ${b.melhorHora === null ? "" : `<div class="alert alert-info alert-styled-left">
          A melhor hora para ligar é às <strong>${b.melhorHora}h</strong>:
          a maior taxa de conexão entre as horas com volume que sustente a conta
          (${b.melhorHoraLigacoes} ligações naquela hora, de ${b.total} no período).
          Horas com menos de ${b.volumeMinimo} ligações ficam de fora da escolha.</div>`}
        ${panel("Taxa de conexão por hora",
          bars(comVolume.map((r) => ({ label: `${r.hora}h`, value: r.conexao,
            tone: r.hora === b.melhorHora ? "success" : "info" }))),
          { subtitle: "Percentual de ligações que conectaram, hora a hora (horário local)" })}
        ${panel("Volume por hora",
          table(["Hora", "Ligações", "Conectadas", "Significativas", "Conexão"],
            comVolume.map((r) => ({ cells: [`${r.hora}h`, r.total, r.conectadas,
              r.significativas, `${r.conexao}%`] })),
            { empty: "Nenhuma ligação no período." }))}`;
    } else {
      const intv = state.estLigIntervalo || "day";
      const hst = await api(`/api/dialer/calls/statistics/history${filtrosQS({ interval: intv })}`);
      corpo = `
        <div class="toolbar">
          <select class="form-control input-sm" id="elIntv">
            <option value="day"${intv === "day" ? " selected" : ""}>Por dia</option>
            <option value="week"${intv === "week" ? " selected" : ""}>Por semana</option>
            <option value="month"${intv === "month" ? " selected" : ""}>Por mês</option>
          </select>
        </div>
        ${panel("Ligações ao longo do tempo",
          bars(hst.data.map((r) => ({ label: r.label, value: r.total, tone: "info" }))))}
        ${panel("Conectadas ao longo do tempo",
          bars(hst.data.map((r) => ({ label: r.label, value: r.conectadas, tone: "success" }))))}`;
    }

    view.innerHTML = `<div class="toolbar">${periodoControle()}${timeControle()}</div>${abas}
      <div class="mt-10">${corpo}</div>`;

    ligarPeriodo(() => go("estatisticas-ligacoes"));
    view.querySelectorAll("[data-estlig]").forEach((a) => {
      a.onclick = () => { state.estLigAba = a.dataset.estlig; go("estatisticas-ligacoes"); };
    });
    const por = document.getElementById("elPor");
    if (por) por.onchange = () => { state.estLigPor = por.value; go("estatisticas-ligacoes"); };
    const intv = document.getElementById("elIntv");
    if (intv) intv.onchange = () => { state.estLigIntervalo = intv.value; go("estatisticas-ligacoes"); };
    const st = document.getElementById("elStatus");
    if (st) st.onchange = () => { state.estLigStatus = st.value; go("estatisticas-ligacoes"); };
  },
};

PAGES["lista-ligacoes"] = {
  area: "Ligações", title: "Lista de Ligações",
  async render() {
    const f = state.callFilter || { page: 1 };
    const extra = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
    const res = await api(`/api/dialer/calls${filtrosQS(extra)}`);
    const OUT = { MEANINGFUL: ["Significativa", "green"], NOT_MEANINGFUL: ["Não significativa", "blue"],
                  NO_CONTACT: ["Sem contato", "amber"] };
    const rows = res.data.map((c) => {
      const [label, tone] = c.status === "CONNECTED" ? (OUT[c.output] || ["Conectada", "grey"]) : ["Não conectada", "red"];
      return { cells: [
        `<button class="btn btn-default btn-xs" data-star="${c.id}" data-on="${c.important ? 1 : 0}"
          title="${c.important ? "Desmarcar" : "Marcar como importante"}">${c.important ? "★" : "☆"}</button>`,
        `<span class="pill ${tone}">${label}</span>`,
        c.user ? h(c.user.name) : "—",
        c.flowLeadId
          ? `<a data-lead="${c.flowLeadId}">${h(c.flowLeadName || "—")}</a><br><span class="text-muted text-size-small">${h(c.flowLeadCompany || "")}</span>`
          : `${h(c.flowLeadName || "—")}<br><span class="text-muted text-size-small">${h(c.flowLeadCompany || "")}</span>`,
        h(c.originPhone || "—"),
        h(c.receiverPhone), fmtDateTime(c.originStarted), fmtDuration(c.receiverConnectedDuration),
        c.receiverType === "MOBILE" ? "Celular" : "Fixo",
        `<button class="btn btn-default btn-xs" data-det="${c.id}">Detalhes</button>`,
      ] };
    });
    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="cfQ" placeholder="Buscar por número, lead ou empresa" value="${h(f.q || "")}">
        <select class="form-control" id="cfUser">${options(state.users, f.user_id, { blank: "Todos os usuários" })}</select>
        <select class="form-control" id="cfOut">
          <option value="">Todos os resultados</option>
          ${Object.entries(OUT).map(([k, v]) => `<option value="${k}"${f.output === k ? " selected" : ""}>${v[0]}</option>`).join("")}
        </select>
        <select class="form-control input-sm" id="cfImp">
          <option value="">Todas</option>
          <option value="true"${f.important === "true" ? " selected" : ""}>Só importantes</option>
        </select>
        ${periodoControle()}${timeControle()}
        <span class="spacer"></span>
        <a class="btn btn-default btn-xs" href="/api/dialer/calls/export${filtrosQS(extra)}">Exportar</a>
        <a class="btn btn-default btn-xs" href="/api/reports/dropped-calls">Baixar derrubadas</a>
      </div>
      ${panel(`${res.pagination.totalRowCount} ligações`,
        table(["", "Situação", "Usuário", "Lead", "Origem", "Destino", "Data", "Duração", "Tipo", ""],
              rows, { scroll: true }),
        { actions: pager(res.pagination) })}`;
    const set = (k, v) => { state.callFilter = { ...f, [k]: v, page: 1 }; go("lista-ligacoes"); };
    document.getElementById("cfUser").onchange = (e) => set("user_id", e.target.value);
    document.getElementById("cfOut").onchange = (e) => set("output", e.target.value);
    document.getElementById("cfImp").onchange = (e) => set("important", e.target.value);
    const busca = document.getElementById("cfQ");
    let tb;
    busca.oninput = () => { clearTimeout(tb); tb = setTimeout(() => set("q", busca.value), 350); };
    ligarPeriodo(() => go("lista-ligacoes"));
    view.querySelectorAll("[data-lead]").forEach((a) => {
      a.onclick = () => go(`lead/${a.dataset.lead}`);
    });
    view.querySelectorAll("[data-det]").forEach((b) => {
      b.onclick = () => openDetalheLigacao(b.dataset.det);
    });
    view.querySelectorAll("[data-star]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        try {
          const r = await api(`/api/dialer/calls/${b.dataset.star}`, { method: "PATCH",
            body: { important: b.dataset.on !== "1" } });
          b.dataset.on = r.important ? "1" : "0";
          b.textContent = r.important ? "★" : "☆";
        } catch (e) { toast(e.message, "err"); }
        b.disabled = false;
      };
    });
    view.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => { state.callFilter = { ...f, page: Number(b.dataset.gotoPage) }; go("lista-ligacoes"); };
    });
  },
};

PAGES.extrato = {
  area: "Ligações", title: "Extrato",
  async render() {
    // O detalhamento por ligação sai da própria lista — o extrato do original
    // mostra os dois: o agregado por pessoa e a linha a linha que o explica.
    const [res, detalhe] = await Promise.all([
      api(`/api/dialer/calls/statements${filtrosQS()}`),
      api(`/api/dialer/calls${filtrosQS({ limit: 200 })}`).catch(() => ({ data: [] })),
    ]);
    const rows = res.data.map((r) => ({ cells: [
      r.user ? h(r.user.name) : "—", r.calls, r.minutes, fmtMoney(r.cost)] }));
    view.innerHTML = `
      <div class="toolbar">${periodoControle()}${timeControle()}</div>
      ${kpis([
        { value: res.meta.totalMinutes, label: "Minutos no período" },
        { value: fmtMoney(res.meta.totalCost), label: "Custo estimado", tone: "warning" },
        { value: fmtMoney(res.meta.pricePerMinute), label: "Preço por minuto" },
        { value: res.data.length, label: "Usuários com consumo", tone: "info" },
      ])}
      ${panel("Consumo por usuário", table(["Usuário", "Ligações", "Minutos", "Custo"], rows))}
      ${panel(`Detalhamento por ligação${detalhe.data.length >= 200 ? " (200 mais recentes)" : ""}`,
        table(["Data", "Usuário", "Destino", "Tipo", "Situação", "Duração", "Custo"],
          detalhe.data.map((c) => ({ cells: [
            fmtDateTime(c.originStarted),
            c.user ? h(c.user.name) : "—",
            h(c.receiverPhone || "—"),
            c.receiverType === "MOBILE" ? "Celular" : "Fixo",
            c.status === "CONNECTED" ? `<span class="pill green">Conectada</span>`
              : `<span class="pill red">Não conectada</span>`,
            fmtDuration(c.receiverConnectedDuration),
            fmtMoney(c.receiverPrice),
          ] })), { scroll: true, empty: "Nenhuma ligação no período." }),
        { subtitle: `Tarifa de ${fmtMoney(res.meta.pricePerMinute)} por minuto, cobrada só sobre o tempo conectado.` })}`;
    ligarPeriodo(() => go("extrato"));
  },
};

PAGES["dialer-ajustes"] = {
  area: "Ligações", title: "Ajustes",
  async render() {
    const cfg = await api("/api/dialer/configuration");
    state.dialerConfig = cfg;
    const aba = state.dialerAba || "geral";
    view.innerHTML = `
      <ul class="nav nav-tabs">
        ${[["geral", "Geral"], ["numeros", "Números"], ["gravacoes", "Gravações"]].map(([k, t]) =>
          `<li${aba === k ? ' class="active"' : ""}><a data-dcaba="${k}">${t}</a></li>`).join("")}
      </ul>
      <div id="dcBody" class="mt-10"></div>`;
    view.querySelectorAll("[data-dcaba]").forEach((a) => {
      a.onclick = () => { state.dialerAba = a.dataset.dcaba; go("dialer-ajustes"); };
    });
    const body = document.getElementById("dcBody");

    if (aba === "gravacoes") {
      // Honestidade: não há gravação porque não há telefonia. A tela existe
      // para dizer isso e para não inventar um botão que não grava nada.
      body.innerHTML = panel("Gravação de ligações", `
        <div class="alert alert-info alert-styled-left">
          O Bluutime não grava ligações: a gravação nasce na operadora, e o
          discador ainda não está ligado à Zenvia — falta um DID comprado e
          saldo na conta.
        </div>
        <p class="text-muted text-size-small">
          Quando a telefonia entrar, é aqui que ficam quem pode ouvir, quem pode
          apagar e por quanto tempo o áudio é guardado.</p>`);
      return;
    }

    if (aba === "numeros") {
      const lista = cfg.callerIdList || [];
      body.innerHTML = panel("Números de origem (bina)",
        `${lista.length ? `<table class="table table-striped">
          <thead><tr><th>Número</th><th>Rótulo</th><th style="width:110px">Padrão</th><th style="width:90px"></th></tr></thead>
          <tbody>${lista.map((n, i) => `<tr data-i="${i}">
            <td><input class="form-control input-sm" data-num value="${h(n.number)}"></td>
            <td><input class="form-control input-sm" data-lab value="${h(n.label)}" placeholder="Comercial, Suporte…"></td>
            <td><label><input type="radio" name="dcPadrao" data-def${n.default ? " checked" : ""}> padrão</label></td>
            <td><button class="btn btn-default btn-xs" data-remove="${i}">Remover</button></td>
          </tr>`).join("")}</tbody></table>`
          : emptyState("Nenhum número cadastrado — o SDR não tem de onde escolher a bina.")}
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <button class="btn btn-default btn-xs" id="dcAdd">Adicionar número</button>
          <span class="spacer"></span>
          <button class="btn btn-main btn-sm" id="dcSalvarNums">Salvar</button>
        </div>
        <p class="text-muted text-size-small mt-10">
          Aceita com ou sem o código do país: 47 99999-8888 vira +5547999998888.
          O número marcado como padrão é o que aparece escolhido para o SDR.</p>`);

      const ler = () => [...body.querySelectorAll("tbody tr")].map((tr) => ({
        number: tr.querySelector("[data-num]").value.trim(),
        label: tr.querySelector("[data-lab]").value.trim(),
        default: tr.querySelector("[data-def]").checked,
      })).filter((n) => n.number);
      const gravar = async (linhas, mensagem) => {
        try {
          state.dialerConfig = await api("/api/dialer/configuration",
            { method: "PATCH", body: { callerIdList: linhas } });
          toast(mensagem, "ok");
          go("dialer-ajustes");
        } catch (e) { toast(e.message, "err"); }
      };
      body.querySelectorAll("[data-remove]").forEach((b) => {
        b.onclick = () => {
          const i = Number(b.dataset.remove);
          const linhas = ler().filter((_, idx) => idx !== i);
          confirmDialog("Remover número",
            `O número ${lista[i].number} sai da lista de binas.`, () => gravar(linhas, "Número removido."));
        };
      });
      document.getElementById("dcAdd").onclick = () => {
        const tbody = body.querySelector("tbody");
        if (!tbody) return promptOne("Novo número", "Número com DDD",
          (v) => gravar([{ number: v, label: "", default: true }], "Número adicionado."), "Adicionar");
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><input class="form-control input-sm" data-num value=""></td>
          <td><input class="form-control input-sm" data-lab value="" placeholder="Comercial, Suporte…"></td>
          <td><label><input type="radio" name="dcPadrao" data-def> padrão</label></td>
          <td><button class="btn btn-default btn-xs" disabled>Remover</button></td>`;
        tbody.appendChild(tr);
        tr.querySelector("[data-num]").focus();
      };
      document.getElementById("dcSalvarNums").onclick = (e) => {
        e.currentTarget.disabled = true;
        gravar(ler(), "Números salvos.").finally(() => { e.currentTarget.disabled = false; });
      };
      return;
    }

    body.innerHTML = panel("Tipo de chamada", `
      <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
        <label><input type="checkbox" id="dcVoip"${cfg.voipEnabled ? " checked" : ""}> VOIP habilitado</label>
        <label><input type="checkbox" id="dcPhone"${cfg.phoneEnabled ? " checked" : ""}> Telefone habilitado</label>
      </div>
      <div class="field"><label class="text-muted text-size-small">Tipo padrão</label>
        <select class="form-control input-sm" id="dcDefault" style="max-width:200px">
          <option value="VOIP"${cfg.defaultType === "VOIP" ? " selected" : ""}>VOIP</option>
          <option value="PHONE"${cfg.defaultType === "PHONE" ? " selected" : ""}>Telefone</option>
        </select></div>
      <div class="toolbar mt-10" style="border:0;padding:0;background:none">
        <span class="spacer"></span>
        <button class="btn btn-main btn-sm" id="dcSalvar">Salvar</button>
      </div>`);

    document.getElementById("dcSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        state.dialerConfig = await api("/api/dialer/configuration", { method: "PATCH", body: {
          voipEnabled: document.getElementById("dcVoip").checked,
          phoneEnabled: document.getElementById("dcPhone").checked,
          defaultType: document.getElementById("dcDefault").value,
        } });
        toast("Configurações salvas.", "ok");
        go("dialer-ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
  },
};

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
        send.disabled = true; input.disabled = true;
        try {
          await api(`/api/whatsapp/conversations/${activeId}/messages`, { method: "POST", body: { body } });
          go("whatsapp");
        } catch (e) {
          toast(e.message, "err"); send.disabled = false; input.disabled = false;
        }
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
    const aba = state.estAba || "geral";
    const clientId = state.statClient || "";
    const abas = `<ul class="nav nav-tabs">
      ${[["geral", "Visão geral"], ["cadencias", "Distribuição nas cadências"],
         ["conversao", "Conversão por passo"], ["desempenho", "Desempenho"],
         ["email", "E-mail"], ["motivos", "Motivos de perda"],
         ["resposta", "Tempo de resposta"]].map(([k, v]) =>
        `<li${aba === k ? ' class="active"' : ""}><a data-estaba="${k}">${v}</a></li>`).join("")}
    </ul>`;
    const barra = `<div class="toolbar">
        <select class="form-control" id="sClient">${options(state.clients, clientId, { blank: "Todos os clientes" })}</select>
        ${periodoControle()}${timeControle()}
      </div>`;

    const ligar = () => {
      const c = document.getElementById("sClient");
      if (c) c.onchange = (e) => { state.statClient = e.target.value; go("estatisticas"); };
      ligarPeriodo(() => go("estatisticas"));
      view.querySelectorAll("[data-estaba]").forEach((a) => {
        a.onclick = () => { state.estAba = a.dataset.estaba; go("estatisticas"); };
      });
    };

    if (aba === "cadencias") {
      const co = await api(`/api/flow/statistics/cadence-overview${filtrosQS()}`);
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        ${panel("Onde os leads estão parados",
          table(["Cadência", "Total", "Em espera", "Prospectando", "Ganhos", "Perdidos", "Conversão"],
            co.data.map((c) => ({ cells: [
              h(c.name), c.total, c.porSituacao.WAITING,
              c.porSituacao.EXECUTING + c.porSituacao.ON_EXTRA_ACTIVITY,
              `<span class="pill green">${c.porSituacao.WON}</span>`,
              `<span class="pill red">${c.porSituacao.LOST}</span>`,
              `${c.conversao}%`] })),
            { scroll: true, empty: "Nenhuma cadência com lead." }),
          { subtitle: "A conversão mostra o resultado; isto mostra onde a base está agora." })}
      </div>`;
      return ligar();
    }

    if (aba === "conversao") {
      const cid = state.estCadencia || (state.cadences[0] && state.cadences[0].id);
      const dados = cid ? await api(`/api/flow/statistics/cadence-steps/${cid}${filtrosQS()}`).catch(() => null) : null;
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        <div class="toolbar">
          <select class="form-control" id="scCad">${options(state.cadences, cid)}</select>
          <span class="spacer text-muted text-size-small">
            Passo a passo só faz sentido dentro de uma cadência — o passo 3 de duas cadências não é a mesma coisa.</span>
        </div>
        ${!dados ? emptyState("Escolha uma cadência.") : `
          ${kpis([
            { value: dados.resumo.leads, label: "Leads na cadência" },
            { value: dados.resumo.finalizados, label: "Finalizados" },
            { value: `${dados.resumo.taxaEngajados}%`, label: "Engajados", tone: "info" },
            { value: `${dados.resumo.taxaGanhos}%`, label: "Ganhos", tone: "success" },
          ])}
          ${panel(`Passos de ${h(dados.cadence.name)}`,
            table(["Passo", "Dia", "Atividade", "Executados", "Engajadas", "Ganhos", "Engajamento"],
              dados.passos.map((p) => ({ cells: [p.passo, p.dia, h(p.atividade),
                p.executados, p.engajadas, p.ganhos, `${p.engajamento}%`] })),
              { scroll: true, empty: "Esta cadência não tem passos." }),
            { subtitle: "Engajamento começa a contar a partir de agora: até hoje a resposta do lead era usada para pausar a cadência e descartada." })}`}
      </div>`;
      ligar();
      const sc = document.getElementById("scCad");
      if (sc) sc.onchange = () => { state.estCadencia = sc.value; go("estatisticas"); };
      return;
    }

    if (aba === "motivos") {
      const por = state.estMotivoPor || "reason";
      const lr = await api(`/api/flow/statistics/lost-reasons${filtrosQS({ by: por })}`);
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        <div class="toolbar">
          <select class="form-control" id="smPor">
            ${[["reason", "Por motivo"], ["user", "Por usuário"], ["team", "Por time"], ["cadence", "Por cadência"]]
              .map(([k, v]) => `<option value="${k}"${por === k ? " selected" : ""}>${v}</option>`).join("")}
          </select>
        </div>
        ${panel("Por que os leads são perdidos",
          bars(lr.data.map((r) => ({ label: r.label, value: r.count, tone: "warning" }))))}
      </div>`;
      ligar();
      const sm = document.getElementById("smPor");
      if (sm) sm.onchange = () => { state.estMotivoPor = sm.value; go("estatisticas"); };
      return;
    }

    if (aba === "email") {
      const e = await api(`/api/flow/statistics/email${periodoQS()}`);
      const r = e.resumo;
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        ${!e.rastreioLigado ? `<div class="alert alert-info alert-styled-left">
          Rastreio de abertura e clique <strong>desligado</strong>. Envio e falha já são
          contados; abertura e clique só passam a contar depois de ligar
          <code>EMAIL_TRACK=1</code> — e valem daí para a frente, não retroativamente.</div>` : ""}
        ${kpis([
          { value: r.enviados, label: "Enviados" },
          { value: `${r.taxaAbertura}%`, label: `Abertos (${r.abertos})`, tone: "info" },
          { value: `${r.taxaClique}%`, label: `Clicados (${r.clicados})`, tone: "success" },
          { value: r.falhas + r.bloqueados, label: "Falhas e bloqueios", tone: "danger" },
        ])}
        ${panel("Por modelo de mensagem",
          table(["Modelo", "Enviados", "Abertos", "Abertura", "Clicados", "Clique"],
            e.porModelo.map((m) => ({ cells: [h(m.modelo), m.enviados, m.abertos,
              `${m.taxaAbertura}%`, m.clicados, `${m.taxaClique}%`] })),
            { empty: "Nenhum e-mail enviado no período." }),
          { subtitle: "Falha aqui é recusa do provedor no envio. Bounce que chega depois só apareceria com webhook do Resend — não está contado." })}
      </div>`;
      return ligar();
    }

    if (aba === "desempenho") {
      const d = await api(`/api/flow/statistics/performance${filtrosQS()}`);
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        ${kpis([
          { value: d.geral.atividades, label: "Atividades realizadas" },
          { value: d.geral.ganhos, label: "Leads ganhos", tone: "success" },
          { value: d.performances.length, label: "Vendedores no período", tone: "info" },
        ])}
        ${panel("Qual a eficiência dos vendedores",
          table(["Vendedor", "Atividades", "Execução geral", "Ligações", "Significativas", "Pesquisas", "Social", "E-mails", "Ganhos"],
            d.performances.map((p) => ({ cells: [
              h(p.user.name), p.atividades,
              `<span class="pill ${p.execucao >= 80 ? "green" : p.execucao >= 50 ? "amber" : "red"}">${p.execucao}%</span>`,
              p.ligacoes,
              `${p.significativas}${p.ligacoes ? ` <span class="text-muted text-size-small">(${p.taxaSignificativa}%)</span>` : ""}`,
              p.pesquisas, p.social, p.emails,
              `<strong>${p.ganhos}</strong>`] })),
            { scroll: true, empty: "Nenhuma atividade no período." }),
          { subtitle: "Execução geral é realizadas sobre atribuídas — atividade ignorada conta no total e não como executada. Abertura e clique de e-mail entram quando o rastreio estiver ligado." })}
      </div>`;
      return ligar();
    }

    if (aba === "resposta") {
      const r = await api(`/api/flow/statistics/response-time${filtrosQS()}`);
      view.innerHTML = `${barra}${abas}<div class="mt-10">
        ${kpis([
          { value: `${r.percentual}%`, label: `Abordados em até ${r.metaHoras}h`, tone: "success" },
          { value: `${r.mediaHoras}h`, label: "Tempo médio até a 1ª abordagem", tone: "info" },
          { value: r.abordados, label: "Leads abordados" },
          { value: r.naoAbordados, label: "Ainda sem abordagem", tone: "danger" },
        ])}
        ${panel("Por SDR",
          table(["SDR", "Abordados", "No prazo", "% no prazo", "Média"],
            r.ranking.map((u) => ({ cells: [h(u.label), u.abordados, u.dentro,
              `<span class="pill ${u.percentual >= 70 ? "green" : u.percentual >= 40 ? "amber" : "red"}">${u.percentual}%</span>`,
              `${u.mediaHoras}h`] })),
            { empty: "Nenhuma abordagem no período." }),
          { subtitle: `Conta o tempo entre o lead entrar e a primeira atividade realizada. Leads ainda não abordados ficam de fora da média — senão ignorar lead melhoraria o número.` })}
      </div>`;
      return ligar();
    }

    const s = await api(`/api/flow/statistics/summary${filtrosQS({ client_id: clientId })}`);
    const cadRows = s.cadences.map((c) => ({ cells: [
      h(c.name), c.client ? h(c.client.name) : "—",
      `<span class="pill">${h(PRIORITY_LABEL[c.priority])}</span>`,
      c.total, c.won, `${c.conversion}%`] }));

    view.innerHTML = `
      ${barra}${abas}
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
        ${painelOrigem(s.origins)}
      </div>
      ${panel("Conversão por cadência",
        table(["Cadência", "Cliente", "Prioridade", "Leads", "Ganhos", "Conversão"], cadRows))}`;

    ligar();
    ligarPainelOrigem(s.origins);
  },
};

PAGES.relatorios = {
  area: "Estatísticas", title: "Relatórios",
  async render() {
    const list = await api("/api/reports");
    const qs = periodoQS();
    const rows = list.map((r) => ({ cells: [
      `<strong>${h(r.name)}</strong>`, h(r.description),
      `<a class="btn btn-default btn-xs" href="/api/reports/${h(r.key)}${qs}">Baixar CSV</a>`] }));
    view.innerHTML = `
      <div class="toolbar">${periodoControle()}</div>
      ${panel("Relatórios", table(["Relatório", "Para que serve", ""], rows),
        { subtitle: "O período escolhido acima vale para o arquivo baixado. CSV com ponto-e-vírgula, compatível com Excel pt-BR." })}`;
    ligarPeriodo(() => go("relatorios"));
  },
};

/* ── Feedback de oportunidade ────────────────────────────────────────────
   Três abas, como no original: Pendentes, Respondidos e Qualificação. Os
   filtros são os mesmos nas três e viram chips removíveis no cabeçalho —
   antes a tela mostrava a empresa inteira sem jeito de recortar. */
const FB_FILTRO_VAZIO = { page: 1, per_page: 25 };

const FB_ROTULO = {
  de: "Ganho a partir de", ate: "Ganho até",
  respondido_de: "Respondido a partir de", respondido_ate: "Respondido até",
  reuniao_de: "Reunião a partir de", reuniao_ate: "Reunião até",
  cadence_id: "Cadência", user_id: "Vendedor", team_id: "Time",
  meeting: "Reunião", tag: "Qualificação", q: "Busca",
};

function fbFiltro() {
  return { ...FB_FILTRO_VAZIO, ...(state.fbFilter || {}) };
}

function fbAplicar(mudanca) {
  // Qualquer mudança de filtro volta para a página 1: continuar na página 4
  // de um resultado que agora tem uma página só devolve uma tela vazia.
  state.fbFilter = { ...fbFiltro(), ...mudanca, page: mudanca.page || 1 };
  go("feedback-oportunidade");
}

function fbQS(f, extra = {}) {
  const p = new URLSearchParams();
  Object.entries({ ...f, ...extra }).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) p.set(k, v);
  });
  return p.toString();
}

function fbValorLegivel(chave, valor, f) {
  if (chave === "cadence_id") return (state.cadences.find((c) => String(c.id) === String(valor)) || {}).name || valor;
  if (chave === "user_id") return (state.users.find((u) => String(u.id) === String(valor)) || {}).name || valor;
  if (chave === "team_id") return (state.teams.find((t) => String(t.id) === String(valor)) || {}).name || valor;
  if (chave === "meeting") return valor === "yes" ? "aconteceu" : "não aconteceu";
  if (chave === "tag") return `${valor} = ${f.tag_value === "0" ? "não" : "sim"}`;
  if (/^(de|ate|respondido_de|respondido_ate|reuniao_de|reuniao_ate)$/.test(chave)) return fmtDate(valor);
  return valor;
}

function fbChips(f) {
  const ativos = Object.keys(FB_ROTULO).filter((k) => f[k]);
  if (!ativos.length) return "";
  return `<div class="fb-chips">
    ${ativos.map((k) => `<span class="fb-chip">${h(FB_ROTULO[k])}: <strong>${h(fbValorLegivel(k, f[k], f))}</strong>
      <button type="button" data-fbtira="${k}" title="Remover filtro" aria-label="Remover filtro ${h(FB_ROTULO[k])}">×</button></span>`).join("")}
    <button type="button" class="btn btn-default btn-xs" data-fblimpa>Limpar tudo</button>
  </div>`;
}

/** Formata a chave do balde sem passar por `Date`.
 *
 * `fmtDate("2026-09-08")` lê a string como meia-noite UTC e mostra 07/09 aqui
 * no fuso de Brasília — o gráfico inteiro aparecia um dia atrasado. */
function fbDiaLegivel(chave) {
  const p = String(chave || "").split("-");
  if (p.length === 2) return `${p[1]}/${p[0]}`;
  if (p.length === 3) return `${p[2]}/${p[1]}/${p[0]}`;
  return chave;
}

function fbSerieChart(serie) {
  if (!serie.length) return emptyState("Sem feedbacks no recorte.");
  const W = 760, H = 200, padL = 34, padB = 26;
  const max = Math.max(1, ...serie.map((s) => s.respondidos + s.pendentes));
  const larg = (W - padL - 10) / serie.length;
  const barra = Math.max(4, Math.min(28, larg - 6));
  const alt = (v) => (v / max) * (H - padB - 14);
  // Ticks inteiros e sem repetição: com poucos feedbacks, arredondar frações
  // do máximo desenhava "0 · 1 · 1" na lateral.
  const ticks = [...new Set([0, Math.round(max / 2), max])];
  const grid = ticks.map((v) => {
    const yy = H - padB - alt(v);
    return `<line x1="${padL}" y1="${yy}" x2="${W - 10}" y2="${yy}" stroke="#eee"/>
            <text x="6" y="${yy + 4}" font-size="11" fill="#999">${v}</text>`;
  }).join("");
  const colunas = serie.map((s, i) => {
    const x = padL + i * larg + (larg - barra) / 2;
    const hr = alt(s.respondidos), hp = alt(s.pendentes);
    const titulo = `${fbDiaLegivel(s.data)} — ${s.respondidos} respondidos, ${s.pendentes} pendentes`;
    return `<g><title>${h(titulo)}</title>
      <rect x="${x}" y="${H - padB - hr}" width="${barra}" height="${hr}" fill="#00c850"/>
      <rect x="${x}" y="${H - padB - hr - hp}" width="${barra}" height="${hp}" fill="#ffc107"/></g>`;
  }).join("");
  // Sem altura fixa o SVG estica junto com a largura do painel e as barras
  // saem do cartão; o `.fb-chart` prende a altura como no gráfico de metas.
  return `<div class="fb-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Feedbacks por dia">
      ${grid}${colunas}
      <text x="${padL}" y="${H - 6}" font-size="11" fill="#999">${fbDiaLegivel(serie[0].data)}</text>
      <text x="${W - 70}" y="${H - 6}" font-size="11" fill="#999">${fbDiaLegivel(serie[serie.length - 1].data)}</text>
    </svg></div>
    <div class="legenda"><span><i style="background:#00c850"></i>Respondidos</span>
      <span><i style="background:#ffc107"></i>Pendentes</span></div>`;
}

PAGES["feedback-oportunidade"] = {
  area: "Estatísticas", title: "Feedback de oportunidade",
  async render() {
    const modo = state.feedbackAba || "pendentes";
    const f = fbFiltro();
    const status = modo === "respondidos" ? "filled" : "pending";
    const gestor = nivelPeloMenos("gestor");
    const [lista, stats] = await Promise.all([
      modo === "qualificacao" ? Promise.resolve({ items: [], total: 0, page: 1, perPage: 25 })
        : api(`/api/flow/deal-feedbacks?${fbQS(f, { status })}`),
      api(`/api/flow/statistics/deal-feedbacks?${fbQS({ ...f, page: "", per_page: "", tag: "", tag_value: "", q: "" })}`),
    ]);
    const totalPageCount = Math.max(1, Math.ceil(lista.total / (lista.perPage || 25)));

    const abas = [["pendentes", "Pendentes", stats.pending],
                  ["respondidos", "Respondidos", stats.filled],
                  ["qualificacao", "Qualificação", stats.tags.length]];

    view.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="fbQ" placeholder="Buscar lead ou empresa…" value="${h(f.q || "")}">
        <button class="btn btn-default btn-xs" id="fbFiltros">Filtros</button>
        ${modo === "qualificacao" ? "" : `
          <select class="form-control" id="fbPorPagina" title="Itens por página">
            ${[10, 25, 50, 100].map((n) => `<option value="${n}"${Number(f.per_page) === n ? " selected" : ""}>${n} por página</option>`).join("")}
          </select>`}
        ${gestor && modo !== "qualificacao"
          ? `<button class="btn btn-danger btn-xs" id="fbExcluir" disabled>Excluir selecionados</button>` : ""}
      </div>
      ${fbChips(f)}
      <ul class="nav nav-tabs">
        ${abas.map(([id, rotulo, n]) => `<li${modo === id ? ' class="active"' : ""}>
          <a data-fbmodo="${id}">${rotulo} <span class="badge${modo === id ? " badge-success" : ""}">${n}</span></a></li>`).join("")}
      </ul>
      <div id="fbBody" class="mt-10"></div>`;

    view.querySelectorAll("[data-fbmodo]").forEach((a) => {
      a.onclick = () => { state.feedbackAba = a.dataset.fbmodo; fbAplicar({}); };
    });
    view.querySelectorAll("[data-fbtira]").forEach((b) => {
      b.onclick = () => {
        const chave = b.dataset.fbtira;
        fbAplicar(chave === "tag" ? { tag: "", tag_value: "" } : { [chave]: "" });
      };
    });
    const limpa = view.querySelector("[data-fblimpa]");
    if (limpa) limpa.onclick = () => { state.fbFilter = { ...FB_FILTRO_VAZIO }; go("feedback-oportunidade"); };
    let tq;
    document.getElementById("fbQ").oninput = (e) => {
      clearTimeout(tq);
      const v = e.target.value;
      tq = setTimeout(() => fbAplicar({ q: v }), 350);
    };
    document.getElementById("fbFiltros").onclick = () => abrirFiltrosFeedback(f);
    const pp = document.getElementById("fbPorPagina");
    if (pp) pp.onchange = () => fbAplicar({ per_page: pp.value });

    const body = document.getElementById("fbBody");
    if (modo === "qualificacao") {
      body.innerHTML = `
        ${panel("Reuniões", grade([
          campo("Respondidos", stats.filled), campo("Pendentes", stats.pending),
          campo("Teve reunião", stats.meetingHappened),
          campo("Não teve reunião", stats.meetingNotHappened),
        ], 4))}
        ${panel("Qualificação", stats.tags.length ? stats.tags.map((t) => `
          <div class="qual-linha">
            <div class="qual-topo"><strong>${h(t.tag)}</strong>
              <span class="text-muted text-size-small">${t.total} resposta${t.total === 1 ? "" : "s"}</span></div>
            <div class="qual-barra" title="Sim: ${t.sim} · Não: ${t.nao}">
              <button type="button" class="qual-sim" style="width:${t.simPercentual}%"
                data-qual="${h(t.tag)}" data-v="1"
                title="Ver os ${t.sim} que responderam sim">${t.simPercentual >= 12 ? `${t.sim} sim` : ""}</button>
              <button type="button" class="qual-nao" style="width:${100 - t.simPercentual}%"
                data-qual="${h(t.tag)}" data-v="0"
                title="Ver os ${t.nao} que responderam não">${100 - t.simPercentual >= 12 ? `${t.nao} não` : ""}</button>
            </div>
          </div>`).join("") : emptyState("Nenhuma resposta de qualificação no recorte."),
          { subtitle: "Clique em um pedaço da barra para ver os feedbacks daquela resposta." })}
        ${panel("Feedbacks ao longo do tempo", fbSerieChart(stats.serie))}`;
      body.querySelectorAll("[data-qual]").forEach((b) => {
        b.onclick = () => {
          state.feedbackAba = "respondidos";
          fbAplicar({ tag: b.dataset.qual, tag_value: b.dataset.v });
        };
      });
      return;
    }

    const check = (id) => gestor ? `<input type="checkbox" class="fb-check" value="${id}">` : "";
    const cabecalho = gestor
      ? [`<input type="checkbox" id="fbTodos" title="Selecionar todos" aria-label="Selecionar todos">`]
      : [];

    if (modo === "pendentes") {
      body.innerHTML = `
        <p class="text-muted text-size-small">${lista.total} pendente${lista.total === 1 ? "" : "s"}${
          f.q || Object.keys(FB_ROTULO).some((k) => f[k]) ? " no recorte atual" : ""}.</p>
        ${table([...cabecalho, "Lead", "Empresa", "Cadência", "Dono do lead", "Vendedor", "Ganho em", ""],
          lista.items.map((x) => ({ cells: [
            ...(gestor ? [check(x.id)] : []),
            `<a data-lead="${x.leadId}">${h(x.leadName)}</a>`,
            h(x.company || "—"), x.cadence ? h(x.cadence.name) : "—",
            x.leadOwner ? h(x.leadOwner.name) : "—", x.user ? h(x.user.name) : "—",
            fmtDate(x.createdAt),
            `<button class="btn btn-main btn-xs" data-responder="${x.id}">Responder</button>
             <button class="btn btn-default btn-xs" data-fbinfo="${x.id}" title="Informações">i</button>`,
          ] })), { empty: f.q ? "Nenhum pendente com esse texto." : "Nenhum feedback pendente — tudo respondido." })}
        <div class="text-right mt-10">${pager({ page: lista.page, totalPageCount })}</div>`;
    } else {
      body.innerHTML = `
        <p class="text-muted text-size-small">${lista.total} respondido${lista.total === 1 ? "" : "s"}${
          f.q || Object.keys(FB_ROTULO).some((k) => f[k]) ? " no recorte atual" : ""}.</p>
        ${table([...cabecalho, "Lead", "Empresa", "Cadência", "Vendedor", "Resultado", "Reunião em",
                 "Qualificação", "Respondido em", ""],
          lista.items.map((x) => ({ cells: [
            ...(gestor ? [check(x.id)] : []),
            `<a data-lead="${x.leadId}">${h(x.leadName)}</a>`,
            h(x.company || "—"), x.cadence ? h(x.cadence.name) : "—",
            x.user ? h(x.user.name) : "—",
            x.meetingHappened === true ? `<span class="pill green">Aconteceu</span>`
              : x.meetingHappened === false ? `<span class="pill red">Não aconteceu</span>`
              : `<span class="pill grey">—</span>`,
            fmtDate(x.meetingAt),
            Object.entries(x.qualification || {}).map(([t, v]) =>
              `<span class="pill ${v ? "green" : "grey"}">${h(t)}</span>`).join(" ") || "—",
            fmtDate(x.filledAt),
            `<button class="btn btn-default btn-xs" data-fbinfo="${x.id}" title="Informações">i</button>`,
          ] })), { scroll: true, empty: "Nenhum feedback respondido no recorte." })}
        <div class="text-right mt-10">${pager({ page: lista.page, totalPageCount })}</div>
        ${panel("Feedbacks ao longo do tempo", fbSerieChart(stats.serie))}`;
    }

    body.querySelectorAll("[data-lead]").forEach((a) => {
      a.onclick = () => go(`lead/${a.dataset.lead}`);
    });
    body.querySelectorAll("[data-responder]").forEach((b) => {
      b.onclick = () => abrirFormFeedback(lista.items.find((x) => String(x.id) === b.dataset.responder));
    });
    body.querySelectorAll("[data-fbinfo]").forEach((b) => {
      b.onclick = () => abrirInfoFeedback(Number(b.dataset.fbinfo));
    });
    body.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => fbAplicar({ page: Number(b.dataset.gotoPage) });
    });

    const excluir = document.getElementById("fbExcluir");
    if (excluir) {
      const marcados = () => [...body.querySelectorAll(".fb-check:checked")].map((c) => Number(c.value));
      const sincronizar = () => { excluir.disabled = !marcados().length; };
      body.querySelectorAll(".fb-check").forEach((c) => { c.onchange = sincronizar; });
      const todos = document.getElementById("fbTodos");
      if (todos) todos.onchange = () => {
        body.querySelectorAll(".fb-check").forEach((c) => { c.checked = todos.checked; });
        sincronizar();
      };
      excluir.onclick = () => {
        const ids = marcados();
        confirmDialog("Excluir feedbacks",
          `${ids.length} feedback${ids.length === 1 ? "" : "s"} ${ids.length === 1 ? "será removido" : "serão removidos"} de vez. Isso não volta atrás.`,
          async () => {
            try {
              await api("/api/flow/deal-feedbacks", { method: "DELETE", body: { ids } });
              toast("Feedbacks excluídos.", "ok");
              go("feedback-oportunidade");
            } catch (e) { toast(e.message, "err"); }
          });
      };
    }
  },
};

function abrirFiltrosFeedback(f) {
  const data = (id, rotulo, valor) => `
    <div class="field"><label for="${id}">${rotulo}</label>
      <input type="date" class="form-control" id="${id}" value="${h(valor || "")}"></div>`;
  const m = modal({
    title: "Filtros",
    wide: true,
    body: `
      <div class="filtros-grid">
        ${data("fbDe", "Ganho a partir de", f.de)}${data("fbAte", "Ganho até", f.ate)}
        ${data("fbReuniaoDe", "Reunião a partir de", f.reuniao_de)}${data("fbReuniaoAte", "Reunião até", f.reuniao_ate)}
        ${data("fbRespDe", "Respondido a partir de", f.respondido_de)}${data("fbRespAte", "Respondido até", f.respondido_ate)}
        <div class="field"><label for="fbCad">Cadência</label>
          <select class="form-control" id="fbCad">${options(state.cadences, f.cadence_id, { blank: "Todas" })}</select></div>
        <div class="field"><label for="fbUser">Vendedor</label>
          <select class="form-control" id="fbUser">${options(state.users, f.user_id, { blank: "Todos" })}</select></div>
        <div class="field"><label for="fbTime">Time</label>
          <select class="form-control" id="fbTime">${options(state.teams, f.team_id, { blank: "Todos" })}</select></div>
        <div class="field"><label for="fbReuniao">Reunião</label>
          <select class="form-control" id="fbReuniao">
            <option value="">Tanto faz</option>
            <option value="yes"${f.meeting === "yes" ? " selected" : ""}>Aconteceu</option>
            <option value="no"${f.meeting === "no" ? " selected" : ""}>Não aconteceu</option>
          </select></div>
        <div class="field"><label for="fbIntervalo">Agrupar o gráfico por</label>
          <select class="form-control" id="fbIntervalo">
            ${[["dia", "Dia"], ["semana", "Semana"], ["mes", "Mês"]].map(([v, r]) =>
              `<option value="${v}"${(f.intervalo || "dia") === v ? " selected" : ""}>${r}</option>`).join("")}
          </select></div>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>Aplicar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = () => {
    const v = (id) => m.root.querySelector(`#${id}`).value;
    m.close();
    fbAplicar({
      de: v("fbDe"), ate: v("fbAte"),
      reuniao_de: v("fbReuniaoDe"), reuniao_ate: v("fbReuniaoAte"),
      respondido_de: v("fbRespDe"), respondido_ate: v("fbRespAte"),
      cadence_id: v("fbCad"), user_id: v("fbUser"), team_id: v("fbTime"),
      meeting: v("fbReuniao"), intervalo: v("fbIntervalo"),
    });
  };
}

async function abrirInfoFeedback(id) {
  let d;
  try {
    d = await api(`/api/flow/deal-feedbacks/${id}`);
  } catch (e) { return toast(e.message, "err"); }
  const linha = (rotulo, valor) => `<div class="info-linha"><span>${h(rotulo)}</span><strong>${valor}</strong></div>`;
  const resposta = (v) => v === true ? `<span class="pill green">Sim</span>`
    : v === false ? `<span class="pill grey">Não</span>`
    : `<span class="pill grey">Não respondida</span>`;
  const m = modal({
    title: `Informações — ${d.leadName}`,
    wide: true,
    body: `
      <div class="info-grid">
        ${linha("Empresa", h(d.company || "—"))}
        ${linha("Cadência", d.cadence ? h(d.cadence.name) : "—")}
        ${linha("Dono do lead", d.leadOwner ? h(d.leadOwner.name) : "—")}
        ${linha("Dono da oportunidade", d.user ? h(d.user.name) : "—")}
        ${linha("Ganho em", fmtDateTime(d.createdAt))}
        ${linha("Reunião em", d.meetingAt ? fmtDateTime(d.meetingAt) : "—")}
        ${linha("Respondido em", d.filledAt ? fmtDateTime(d.filledAt) : "—")}
        ${linha("Resultado", d.meetingHappened === true ? `<span class="pill green">Reunião aconteceu</span>`
          : d.meetingHappened === false ? `<span class="pill red">Reunião não aconteceu</span>`
          : `<span class="pill amber">Aguardando resposta</span>`)}
      </div>
      <h4 class="mt-10">Qualificação</h4>
      ${d.answers.length
        ? `<div class="info-grid">${d.answers.map((a) => linha(a.tag, resposta(a.value))).join("")}</div>`
        : `<p class="text-muted">Nenhuma pergunta de qualificação cadastrada em Ajustes.</p>`}
      <h4 class="mt-10">Observações</h4>
      <div style="white-space:pre-wrap">${d.notes ? h(d.notes) : `<span class="text-muted">Sem observações.</span>`}</div>`,
    footer: `<button class="btn btn-default btn-sm" data-lead-ir>Abrir o lead</button>
             <button class="btn btn-main btn-sm" data-close-info>Fechar</button>`,
  });
  m.root.querySelector("[data-close-info]").onclick = m.close;
  m.root.querySelector("[data-lead-ir]").onclick = () => { m.close(); go(`lead/${d.leadId}`); };
}

async function abrirFormFeedback(f) {
  const cfg = await api("/api/flow/deal-feedback/configuration");
  const m = modal({
    title: `Feedback — ${f.leadName}`,
    body: `
      <div class="field"><label>A reunião aconteceu?</label>
        <div class="chip-grid" id="fbReuniao">
          <button type="button" class="chip" data-v="1">Sim</button>
          <button type="button" class="chip" data-v="0">Não</button>
        </div></div>
      <div class="field"><label for="fbQuando">Data da reunião</label>
        <input type="date" class="form-control" id="fbQuando"></div>
      ${cfg.qualificationTags.map((t) => `
        <div class="field"><label><input type="checkbox" class="fb-tag" data-tag="${h(t)}"> ${h(t)}</label></div>`).join("")
        || `<p class="text-muted">Nenhuma pergunta de qualificação cadastrada em Ajustes.</p>`}
      <div class="field"><label for="fbNotes">Observações</label><textarea class="form-control" id="fbNotes" rows="2"></textarea></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Enviar</button>`,
  });
  let reuniao = null;
  m.root.querySelector("#fbReuniao").onclick = (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    m.root.querySelectorAll("#fbReuniao .chip").forEach((c) => c.classList.remove("active"));
    b.classList.add("active");
    reuniao = b.dataset.v === "1";
  };
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async () => {
    if (reuniao === null) return toast("Diga se a reunião aconteceu.", "err");
    const qualification = {};
    m.root.querySelectorAll(".fb-tag").forEach((c) => { qualification[c.dataset.tag] = c.checked; });
    const quando = m.root.querySelector("#fbQuando").value;
    try {
      await api(`/api/flow/deal-feedbacks/${f.id}`, { method: "POST", body: {
        meetingHappened: reuniao, qualification, notes: m.root.querySelector("#fbNotes").value.trim(),
        meetingAt: quando ? `${quando}T12:00:00` : "",
      } });
      m.close(); toast("Feedback enviado.", "ok"); go("feedback-oportunidade");
    } catch (e) { toast(e.message, "err"); }
  };
}

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
      return `<span class="token"><b>${h(item ? `${item.codigo} ${item.descricao}` : v)}</b><button type="button" data-rm="${h(v)}" title="Remover" aria-label="Remover">×</button></span>`;
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
    `<span class="token"><b>${h(achado.textContent)}</b><button type="button" data-rm="${h(codigo)}" title="Remover" aria-label="Remover">×</button></span>`);
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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
          <button class="btn btn-default btn-xs" id="pgPrev"${(res.offset || 0) <= 0 ? " disabled" : ""} title="Página anterior" aria-label="Página anterior">‹</button>
          <button class="btn btn-default btn-xs" id="pgNext"${hasMore ? "" : " disabled"} title="Próxima página" aria-label="Próxima página">›</button>` })}`;

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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
      <div class="field"><label for="pbName">Nome da base *</label>
        <input class="form-control" id="pbName" value="[CapiBLU] - ${new Date().toLocaleDateString("pt-BR")}"></div>
      <div class="field-row">
        <div class="field"><label for="pbClient">Cliente</label>
          <select class="form-control" id="pbClient">${options(state.clients, "", { blank: "—" })}</select></div>
        <div class="field"><label for="pbSdr">SDR responsável</label>
          <select class="form-control" id="pbSdr">${options(state.users, "", { blank: "—" })}</select></div>
      </div>
      <div class="field"><label for="pbCad">Colocar em cadência</label>
        <select class="form-control" id="pbCad">${options(state.cadences.filter((c) => c.executing), "", { blank: "Não iniciar agora" })}</select></div>
      <div class="field-row">
        <div class="field"><label for="pbMaxDec">Máx. decisores por empresa</label>
          <input class="form-control" type="number" id="pbMaxDec" value="3" min="0" max="10"></div>
        <div class="field"><label for="pbMaxTel">Máx. telefones por contato</label>
          <input class="form-control" type="number" id="pbMaxTel" value="3" min="1" max="5"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="pbTipoTel">Tipo de telefone</label>
          <select class="form-control" id="pbTipoTel">
            <option value="celular">Celular</option>
            <option value="celular_fixo">Celular e fixo</option>
            <option value="todos">Todos</option>
          </select></div>
        <div class="field"><label for="pbFonte">Fonte do telefone</label>
          <select class="form-control" id="pbFonte">
            <option value="assertiva">Assertiva</option>
            <option value="mk">Mk Buscas</option>
          </select></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="pbSocios">Sócios</label>
          <select class="form-control" id="pbSocios">
            <option value="todos">Todos os sócios</option>
            <option value="admin">Só sócio-administrador / diretor / presidente</option>
          </select></div>
        <div class="field"><label>Máx. sócios por empresa <span class="text-grey">(0 = sem limite)</span></label>
          <input class="form-control" type="number" id="pbMaxSocios" value="0" min="0" max="20"></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="pbDecFonte">Fonte dos decisores</label>
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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(ex.message || am.message)}</div>`;
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
  ["dossie", "Assertiva (telefone e sinais)", true],
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
          </div>` : dados ? (ativo === "dossie" ? renderDossieRico(dados) : renderPessoa(dados, ativo === "mk" ? "mk" : ativo))
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
      ? await api(`/api/capiblu/pessoas/${gente.cpfDireto}/dossie`)
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
              ? (ativo === "mk" ? renderPessoa(dados, "mk") : renderDossieRico(dados))
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
      <div class="field"><label for="loteClient">Cliente</label>
        <select class="form-control" id="loteClient">${options(state.clients, "", { blank: "— sem cliente —" })}</select></div>
      <div class="field"><label for="loteCad">Cadência</label>
        <select class="form-control" id="loteCad">${options(state.cadences, "", { blank: "— sem cadência —" })}</select></div>
      <div class="field"><label for="loteSdr">SDR responsável</label>
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
            <div class="field"><label for="vinDoc">${porEmpresa ? "CNPJ da empresa" : "CPF da pessoa"}</label>
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
            <div class="field"><label for="asQ">${h(meta[1])}</label>
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
            <div class="field"><label for="tPhone">Telefone com DDD</label>
              <input class="form-control input-xlg" id="tPhone" placeholder="41999998888"
                     value="${h(state.telPhone || "")}"></div>
            ${aba === "posse" ? `<div class="field"><label for="tDoc">CPF ou CNPJ</label>
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
      } catch (e) { out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; }
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
        <label for="pFile">Arquivo XLSX ou CSV</label>
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
    el.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
    el.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
          <div class="field"><label for="mFile">Planilha de exemplo (só o cabeçalho importa)</label>
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
        out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
    el.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
        <div class="field"><label for="dTipo">Tipo</label>
          <select class="form-control" id="dTipo">
            <option value="cnpj"${(state.dossieDoc || "").length === 14 ? " selected" : ""}>CNPJ</option>
            <option value="cpf"${(state.dossieDoc || "").length === 11 ? " selected" : ""}>CPF</option>
          </select></div>
        <div class="field"><label for="dDoc">Documento</label>
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
      out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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

/* ── Meu perfil ──────────────────────────────────────────────────────── */
PAGES["meu-perfil"] = {
  area: "Empresa", title: "Meu perfil",
  async render() {
    const me = state.me;
    const aba = state.perfilAba || "geral";
    view.innerHTML = `
      <ul class="nav nav-tabs">
        ${[["geral", "Dados"], ["senha", "Senha"]].map(([k, t]) =>
          `<li${aba === k ? ' class="active"' : ""}><a data-perfaba="${k}">${t}</a></li>`).join("")}
      </ul>
      <div id="perfBody" class="mt-10"></div>`;
    view.querySelectorAll("[data-perfaba]").forEach((a) => {
      a.onclick = () => { state.perfilAba = a.dataset.perfaba; go("meu-perfil"); };
    });
    const corpo = document.getElementById("perfBody");

    if (aba === "senha") {
      // A troca de senha existia só no menu do topo; no original ela é uma
      // aba do perfil, e as regras ficam escritas na tela.
      corpo.innerHTML = panel("Trocar minha senha", `
        <div class="field"><label for="psAtual">Senha atual</label>
          <input class="form-control" id="psAtual" type="password" autocomplete="current-password"></div>
        <div class="field"><label for="psNova">Nova senha</label>
          <input class="form-control" id="psNova" type="password" autocomplete="new-password"></div>
        <div class="field"><label for="psRepete">Repita a nova senha</label>
          <input class="form-control" id="psRepete" type="password" autocomplete="new-password"></div>
        <ul class="text-muted text-size-small" style="padding-left:18px;margin:0 0 14px">
          <li>Ao menos 8 caracteres.</li>
          <li>Pedimos a senha atual: é o que impede que uma sessão esquecida
              aberta vire troca de credencial por quem passar na mesa.</li>
          <li>Vale para o CapiBLU também — é o mesmo login.</li>
        </ul>
        <button class="btn btn-main btn-sm" id="psSalvar">Trocar senha</button>`);
      document.getElementById("psSalvar").onclick = async (e) => {
        const v = (id) => document.getElementById(id).value;
        if (v("psNova").length < 8) return toast("A nova senha precisa de ao menos 8 caracteres.", "err");
        if (v("psNova") !== v("psRepete")) return toast("As duas não são iguais.", "err");
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await api("/api/auth/change-password", { method: "POST", body: {
            senha_atual: v("psAtual"), nova_senha: v("psNova") } });
          toast("Senha alterada.", "ok");
          go("meu-perfil");
        } catch (err) { toast(err.message, "err"); btn.disabled = false; }
      };
      return;
    }

    corpo.innerHTML = `
      ${panel("Meu perfil", `
        <div class="text-center mb-20">
          <div style="width:78px;height:78px;border-radius:50%;margin:0 auto;overflow:hidden;
                      background:var(--body);display:flex;align-items:center;justify-content:center;
                      font-size:28px;color:var(--text)">
            ${me.avatarUrl ? `<img src="${h(me.avatarUrl)}" alt="" style="width:100%;height:100%;object-fit:cover">`
                           : h(me.initials || "?")}
          </div>
          <div class="mt-10"><label class="btn btn-default btn-xs" style="cursor:pointer">
            Trocar foto<input type="file" id="avatarInput" accept="image/*" hidden></label>
            <span class="text-muted text-size-small ml-5">JPG/PNG, até 4MB</span></div>
        </div>
        <div class="field"><label for="perfNome">Nome</label>
          <input class="form-control" id="perfNome" value="${h(me.name)}"></div>
        <div class="field"><label>E-mail</label>
          <input class="form-control" value="${h(me.email)}" disabled></div>
        <div class="field"><label>Assinatura de e-mail
          <span class="text-muted text-size-small">— entra no fim de todo e-mail enviado pela cadência</span></label>
          <textarea class="form-control" id="perfAssinatura" rows="4">${h(me.emailSignature || "")}</textarea></div>
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <span class="spacer"></span>
          <button class="btn btn-main btn-sm" id="perfSalvar">Atualizar dados</button>
        </div>`)}`;

    document.getElementById("avatarInput").onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const atualizado = await apiUpload("/api/me/avatar", file);
        state.me = { ...state.me, ...atualizado };
        renderNavAvatar();
        toast("Foto atualizada.", "ok");
        go("meu-perfil");
      } catch (err) { toast(err.message, "err"); }
    };
    document.getElementById("perfSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const atualizado = await api("/api/me", { method: "PATCH", body: {
          name: document.getElementById("perfNome").value.trim(),
          emailSignature: document.getElementById("perfAssinatura").value,
        } });
        state.me = { ...state.me, ...atualizado };
        document.getElementById("navUser").textContent = state.me.name;
        toast("Perfil atualizado.", "ok");
        go("meu-perfil");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
  },
};

/* ── Administração ───────────────────────────────────────────────────── */
/* ── Empresa ─────────────────────────────────────────────────────────────
   O original tem um hub de empresa com abas; aqui as três coisas viviam
   empilhadas na mesma página, sem busca e sem como remover alguém. */
const ROLE_LABEL = {
  ADMINISTRATOR: "Administrador", MANAGER: "Gestor",
  SDR: "SDR", SALESMAN: "Vendedor",
};

PAGES.usuarios = {
  area: "Empresa", title: "Empresa",
  async render() {
    const aba = state.empresaAba || "usuarios";
    const f = state.userFilter || { page: 1, per_page: 25 };
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v != null));
    const [users, teams, empresa] = await Promise.all([
      api(`/api/users?${qs}`), api("/api/teams"), api("/api/me/company")]);
    // O boot guarda a lista inteira para os dropdowns; a tela é paginada, e
    // sobrescrever aqui deixaria "transferir lead" com 25 nomes.
    const p = users.pagination;

    const abas = [["gerais", "Dados gerais"], ["usuarios", `Usuários`], ["times", `Times`]];
    view.innerHTML = `
      <ul class="nav nav-tabs">
        ${abas.map(([k, t]) => `<li${aba === k ? ' class="active"' : ""}><a data-emaba="${k}">${t}</a></li>`).join("")}
      </ul>
      <div id="emBody" class="mt-10"></div>`;
    view.querySelectorAll("[data-emaba]").forEach((a) => {
      a.onclick = () => { state.empresaAba = a.dataset.emaba; go("usuarios"); };
    });
    const body = document.getElementById("emBody");

    if (aba === "gerais") {
      body.innerHTML = panel("Dados da empresa", `
        <div class="field-row">
          <div class="field"><label for="emNome">Nome</label>
            <input class="form-control" id="emNome" value="${h(empresa.name || "")}"></div>
          <div class="field"><label for="emTel">Telefone</label>
            <input class="form-control" id="emTel" value="${h(empresa.phone || "")}"></div>
        </div>
        <div class="field"><label for="emSite">Site</label>
          <input class="form-control" id="emSite" value="${h(empresa.site || "")}"></div>
        ${nivelPeloMenos("admin") ? `<button class="btn btn-main btn-sm" id="emSalvar">Atualizar dados</button>`
          : `<span class="text-muted text-size-small">Só administrador edita os dados da empresa.</span>`}`);
      const salvarEmpresa = document.getElementById("emSalvar");
      if (salvarEmpresa) salvarEmpresa.onclick = async (ev) => {
        const bt = ev.currentTarget;
        bt.disabled = true;
        try {
          await api("/api/me/company", { method: "PATCH", body: {
            name: document.getElementById("emNome").value,
            phone: document.getElementById("emTel").value,
            site: document.getElementById("emSite").value,
          } });
          toast("Dados da empresa atualizados.", "ok");
        } catch (e) { toast(e.message, "err"); }
        bt.disabled = false;
      };
      return;
    }

    if (aba === "times") {
      body.innerHTML = panel("Times", table(["Time", "Integrantes", ""],
        teams.map((t) => ({ cells: [
          h(t.name),
          t.users.map((u) => h(u.name)).join(", ") || "—",
          `<button class="btn btn-default btn-xs" data-edit-team="${t.id}">Editar</button>
           <button class="btn btn-default btn-xs" data-del-team="${t.id}" data-nome="${h(t.name)}">Remover</button>`,
        ] })), { empty: "Nenhum time ainda." }),
        { actions: nivelPeloMenos("admin") ? `<button class="btn btn-main btn-xs" id="newTeam">Criar time</button>` : "" });
      const novoTime = document.getElementById("newTeam");
      if (novoTime) novoTime.onclick = () => openTeamForm(null, state.users);
      body.querySelectorAll("[data-edit-team]").forEach((b) => {
        b.onclick = () => openTeamForm(teams.find((t) => String(t.id) === b.dataset.editTeam), state.users);
      });
      body.querySelectorAll("[data-del-team]").forEach((b) => {
        b.onclick = () => confirmDialog("Remover time",
          `Remover o time "${b.dataset.nome}"? As pessoas continuam, só ficam sem time.`,
          async () => {
            try {
              await api(`/api/teams/${b.dataset.delTeam}`, { method: "DELETE" });
              toast("Time removido.", "ok"); go("usuarios");
            } catch (e) { toast(e.message, "err"); }
          });
      });
      return;
    }

    const admin = nivelPeloMenos("admin");
    const rows = users.data.map((u) => ({ cells: [
      `<div class="media-left"><div class="lead-avatar-dot ${u.online ? "success" : ""}">${h(u.initials)}</div></div>
       <div class="media-body"><strong>${h(u.name)}</strong><br>
       <span class="text-muted text-size-small">${h(u.email)}</span></div>`,
      u.roles.map((r) => `<span class="pill">${h(ROLE_LABEL[r] || r)}</span>`).join(" ") || "—",
      u.team ? h(u.team.name) : "—",
      u.dailyGoal ?? "—",
      // O cadastro só está completo quando existe login no CapiBLU — é ele
      // que deixa a pessoa entrar nas duas ferramentas.
      u.temLogin === false ? `<span class="pill amber" title="Sem conta no CapiBLU: não consegue entrar">Sem login</span>`
        : u.temLogin === true ? `<span class="pill green">Tem login</span>` : "—",
      u.leads ?? "—",
      u.active ? `<span class="pill green">Ativo</span>` : `<span class="pill grey">Inativo</span>`,
      `<button class="btn btn-default btn-xs" data-edit-user="${u.id}">Editar</button>
       ${admin ? `<button class="btn btn-default btn-xs" data-del-user="${u.id}" data-nome="${h(u.name)}">Excluir</button>` : ""}`,
    ] }));

    body.innerHTML = `
      <div class="toolbar">
        <input class="form-control grow" id="uQ" placeholder="Buscar por nome ou e-mail…" value="${h(f.q || "")}">
        <select class="form-control" id="uTime">${options(teams, f.team_id, { blank: "Todos os times" })}</select>
        <select class="form-control" id="uPapel">
          <option value="">Todos os papéis</option>
          ${Object.entries(ROLE_LABEL).map(([k, v]) =>
            `<option value="${k}"${f.role === k ? " selected" : ""}>${v}</option>`).join("")}
        </select>
        <select class="form-control" id="uAtivo">
          <option value="">Ativos e inativos</option>
          <option value="true"${f.active === "true" ? " selected" : ""}>Só ativos</option>
          <option value="false"${f.active === "false" ? " selected" : ""}>Só inativos</option>
        </select>
        <span class="spacer"></span>
        ${admin ? `<button class="btn btn-main btn-xs" id="newUser">Novo usuário</button>` : ""}
      </div>
      ${panel(`Usuários (${p.totalRowCount})`,
        table(["Usuário", "Papéis", "Time", "Meta diária", "Login", "Leads", "Situação", ""], rows,
          { scroll: true, empty: f.q ? "Ninguém com esse nome ou e-mail." : "Nenhum usuário." }),
        { actions: pager(p) })}`;

    const setFilter = (key, value) => {
      state.userFilter = { ...f, [key]: value, page: 1 };
      go("usuarios");
    };
    let tu;
    document.getElementById("uQ").oninput = (e) => {
      clearTimeout(tu);
      const v = e.target.value;
      tu = setTimeout(() => setFilter("q", v), 350);
    };
    document.getElementById("uTime").onchange = (e) => setFilter("team_id", e.target.value);
    document.getElementById("uPapel").onchange = (e) => setFilter("role", e.target.value);
    document.getElementById("uAtivo").onchange = (e) => setFilter("active", e.target.value);
    view.querySelectorAll("[data-goto-page]").forEach((b) => {
      b.onclick = () => { state.userFilter = { ...f, page: Number(b.dataset.gotoPage) }; go("usuarios"); };
    });

    const novo = document.getElementById("newUser");
    if (novo) novo.onclick = () => openUserForm();
    body.querySelectorAll("[data-edit-user]").forEach((b) => {
      b.onclick = () => openUserForm(users.data.find((u) => String(u.id) === b.dataset.editUser));
    });
    body.querySelectorAll("[data-del-user]").forEach((b) => {
      b.onclick = () => confirmDialog("Excluir usuário",
        `${b.dataset.nome} sai da empresa de vez. Quem tem lead ou atividade no nome não pode ser excluído — nesse caso, inative.`,
        async () => {
          try {
            await api(`/api/users/${b.dataset.delUser}`, { method: "DELETE" });
            toast("Usuário excluído.", "ok"); go("usuarios");
          } catch (e) { toast(e.message, "err"); }
        });
    });
  },
};

// O hub tem nome próprio no original; o item de menu continua apontando para
// "usuarios", então as duas rotas levam à mesma tela.
PAGES.empresa = PAGES.usuarios;

function openUserForm(user) {
  const u = user || {};
  const ROLES = ["ADMINISTRATOR", "MANAGER", "SDR", "SALESMAN"];
  const m = modal({
    title: u.id ? `Editar ${u.name}` : "Novo usuário",
    body: `<div class="field"><label for="uName">Nome *</label><input class="form-control" id="uName" value="${h(u.name || "")}"></div>
      <div class="field"><label for="uEmail">E-mail *</label>
        <input class="form-control" id="uEmail" value="${h(u.email || "")}"${u.id ? " disabled" : ""}></div>
      <div class="field"><label for="uRoles">Papéis</label>
        <select class="form-control" id="uRoles" multiple size="4">
          ${ROLES.map((r) => `<option value="${r}"${(u.roles || []).includes(r) ? " selected" : ""}>${r}</option>`).join("")}
        </select></div>
      <div class="field-row">
        <div class="field"><label for="uGoal">Meta diária</label>
          <input class="form-control" type="number" id="uGoal" value="${u.dailyGoal || 170}"></div>
        <div class="field"><label for="uActive">Situação</label>
          <select class="form-control" id="uActive">
            <option value="true"${u.active !== false ? " selected" : ""}>Ativo</option>
            <option value="false"${u.active === false ? " selected" : ""}>Inativo</option>
          </select></div>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-save>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-save]").onclick = async (e) => {
    const body = {
      name: m.root.querySelector("#uName").value.trim(),
      roles: [...m.root.querySelector("#uRoles").selectedOptions].map((o) => o.value),
      dailyGoal: Number(m.root.querySelector("#uGoal").value),
      active: m.root.querySelector("#uActive").value === "true",
    };
    if (!body.name) return toast("O nome é obrigatório.", "err");
    if (!u.id) {
      body.email = m.root.querySelector("#uEmail").value.trim();
      if (!body.email) return toast("O e-mail é obrigatório.", "err");
    }
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      if (u.id) await api(`/api/users/${u.id}`, { method: "PATCH", body });
      else await api("/api/users", { method: "POST", body });
      m.close(); toast("Usuário salvo.", "ok"); go("usuarios");
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
  };
}

/* ── Integrações ─────────────────────────────────────────────────────────
   Antes cada integração era um liga/desliga que não ligava nada — inclusive
   cinco CRMs que ninguém vai usar. Agora o hub mostra as quatro que existem
   de verdade, cada uma com a sua tela de detalhe e o estado real. */
const CANAL_ESTADO = {
  CONNECTED: ["green", "Conectado"], DISCONNECTED: ["amber", "Desconectado"],
  NOT_CONFIGURED: ["grey", "Não configurado"], ERROR: ["red", "Com erro"],
};
const selo = (estado) => {
  const [tom, rotulo] = CANAL_ESTADO[estado] || ["grey", estado || "—"];
  return `<span class="pill ${tom}">${h(rotulo)}</span>`;
};

PAGES.integracoes = {
  area: "Integrações", title: "Integrações",
  async render() {
    const alvo = state.integracaoAberta || "";
    const [canais, capi] = await Promise.all([
      api("/api/envio/canais").catch(() => ({ sendingEnabled: false, channels: [] })),
      api("/api/capiblu/status").catch(() => ({ available: false, tools: [], areas: [] })),
    ]);
    const canal = (k) => canais.channels.find((c) => c.channel === k) || {};

    if (alvo) return detalheIntegracao(alvo, { canais, capi, canal });

    const cartao = (chave, nome, oque, estado, extra) => `
      <div class="tool-card">
        <h4>${h(nome)}</h4><div class="what">${h(oque)}</div>
        <div class="mt-10">${estado}</div>
        ${extra ? `<div class="mt-10 text-muted text-size-small">${extra}</div>` : ""}
        <div class="mt-10"><button class="btn btn-default btn-xs" data-int="${chave}">Detalhes</button></div>
      </div>`;

    view.innerHTML = `
      ${canais.sendingEnabled ? "" : `<div class="alert alert-info alert-styled-left">
        O envio está <strong>desligado</strong> (<code>BLUUTIME_SEND</code>): mensagens de
        cadência ficam registradas como simuladas até alguém soltar o freio de mão.</div>`}
      ${panel("Integrações", `<div class="tool-grid">
        ${cartao("capiblu", "CapiBLU", "Dados, enriquecimento e prospecção",
          capi.available ? `<span class="pill green">Ativo</span>` : `<span class="pill red">Indisponível</span>`,
          `${capi.tools.length} ferramentas em ${capi.areas.length} áreas`)}
        ${cartao("email", "E-mail (Resend)", "Envio de e-mail da cadência",
          selo(canal("EMAIL").state), h(canal("EMAIL").from || ""))}
        ${cartao("whatsapp", "WhatsApp", "Mensagem e conversa pelo número da BLU",
          selo(canal("WHATSAPP").state), h(canal("WHATSAPP").provider || ""))}
        ${cartao("zenvia", "Zenvia", "SMS e telefonia (voz)",
          selo(canal("SMS").state), "Voz depende de DID e saldo")}
      </div>`, { subtitle: "As três que a BLU decidiu usar, mais o WhatsApp" })}
      ${panel("Fora de escopo", `
        <p class="text-muted">Os CRMs que o Meetime integra — Pipedrive, Salesforce, RD Station,
        HubSpot, Ploomes — e o Google Agenda ficaram de fora por decisão de escopo. O que existia
        aqui era um botão que só virava um booleano no banco, sem credencial, sem mapeamento de
        campo e sem sincronizar nada; tirei da tela em vez de deixar parecendo que funciona.</p>
        <p class="text-muted text-size-small">Quem precisa mandar evento para um CRM usa
        <a data-page="integracoes-webhooks" style="cursor:pointer;text-decoration:underline">webhooks</a> —
        é assim que o LEAD.WON já chega na Ploomes hoje.</p>`)}
      ${panel("Webhooks e API", `<div class="tool-grid">
        <div class="tool-card"><h4>Webhooks</h4>
          <div class="what">Eventos do Bluutime empurrados para fora</div>
          <div class="mt-10"><button class="btn btn-default btn-xs" data-int="webhooks">Gerenciar</button></div></div>
        <div class="tool-card"><h4>Token de API</h4>
          <div class="what">Acesso programático às rotas do Bluutime</div>
          <div class="mt-10"><button class="btn btn-default btn-xs" data-page="contas">Abrir contas de acesso</button></div></div>
      </div>`)}`;

    view.querySelectorAll("[data-int]").forEach((b) => {
      b.onclick = () => { state.integracaoAberta = b.dataset.int; go("integracoes"); };
    });
  },
};

async function detalheIntegracao(chave, ctx) {
  const voltar = `<div class="toolbar">
      <button class="btn btn-default btn-xs" id="intVoltar">‹ Integrações</button></div>`;
  const fechar = () => {
    document.getElementById("intVoltar").onclick = () => {
      state.integracaoAberta = ""; go("integracoes");
    };
  };

  if (chave === "capiblu") {
    const c = ctx.capi;
    view.innerHTML = `${voltar}
      ${panel("CapiBLU", `
        <div class="stat-line">
          <span><b>${c.available ? "Ativo" : "Indisponível"}</b>Serviço de dados</span>
          <span><b>${c.tools.length}</b>Ferramentas expostas</span>
          <span><b>${c.areas.length}</b>Áreas</span>
        </div>
        ${c.available
          ? `<p class="text-muted mt-10">O serviço roda no mesmo processo do Bluutime: as
             consultas de empresa, sócio, telefone e enriquecimento não saem pela rede.</p>`
          : `<div class="alert alert-danger alert-styled-left mt-10">${h(c.error || "")}</div>`}`,
        { actions: `<button class="btn btn-default btn-xs" data-page="capiblu-ferramentas">Ver ferramentas</button>` })}`;
    return fechar();
  }

  if (chave === "email") {
    const e = ctx.canal("EMAIL");
    const dom = await api("/api/flow/email/domains").catch(() => ({ configurado: false, dominios: [] }));
    view.innerHTML = `${voltar}
      ${panel("E-mail (Resend)", `
        <div class="info-grid">
          <div class="info-linha"><span>Estado</span><strong>${selo(e.state)}</strong></div>
          <div class="info-linha"><span>Remetente</span><strong>${h(e.from || "—")}</strong></div>
          <div class="info-linha"><span>Servidor</span><strong>${h(e.host || "—")}</strong></div>
          <div class="info-linha"><span>Envio real</span><strong>${ctx.canais.sendingEnabled
            ? `<span class="pill green">ligado</span>` : `<span class="pill amber">desligado</span>`}</strong></div>
        </div>
        ${e.reason ? `<div class="alert alert-info alert-styled-left mt-10">${h(e.reason)}</div>` : ""}`,
        { actions: `<button class="btn btn-default btn-xs" id="emTeste">Enviar teste</button>` })}
      ${panel("Domínios verificados", dom.configurado
        ? table(["Domínio", "Situação", "Região", "Envio", "Criado", ""],
            (dom.dominios || []).map((d) => ({ cells: [
              `<strong>${h(d.nome)}</strong>`,
              d.status === "verified" ? `<span class="pill green">verificado</span>`
                : `<span class="pill amber">${h(d.status)}</span>`,
              h(d.regiao || "—"), h(d.envio || "—"), h(d.criado || "—"),
              `<button class="btn btn-default btn-xs" data-dns="${h(d.nome)}">Ver DNS</button>`,
            ] })), { empty: "Nenhum domínio no Resend." })
        : `<div class="alert alert-info alert-styled-left">${h(dom.motivo || "Resend não configurado.")}</div>`,
        { subtitle: "Lidos do Resend na hora — a tela não guarda cópia" })}`;
    fechar();
    const teste = document.getElementById("emTeste");
    if (teste) teste.onclick = () => promptOne("Enviar e-mail de teste", "Para qual endereço?",
      async (para) => {
        try {
          const r = await api("/api/envio/teste", { method: "POST", body: { channel: "EMAIL", to: para } });
          toast(r.status === "SENT" ? "E-mail enviado." : `Registrado como ${r.status}.`, "ok");
        } catch (err) { toast(err.message, "err"); }
      }, "Enviar", state.me.email);
    view.querySelectorAll("[data-dns]").forEach((b) => {
      b.onclick = () => {
        const d = (dom.dominios || []).find((x) => x.nome === b.dataset.dns);
        const m = modal({ wide: true, title: `DNS de ${d.nome}`,
          body: table(["Tipo", "Nome", "Valor"], (d.registros || []).map((r) => ({ cells: [
            h(r.tipo), `<code>${h(r.nome)}</code>`,
            `<code style="word-break:break-all">${h(r.valor)}</code>`] })), { scroll: true }),
          footer: `<button class="btn btn-main btn-sm" data-close-dns>Fechar</button>` });
        m.root.querySelector("[data-close-dns]").onclick = m.close;
      };
    });
    return;
  }

  if (chave === "whatsapp") {
    const w = ctx.canal("WHATSAPP");
    view.innerHTML = `${voltar}
      ${panel("WhatsApp", `
        <div class="info-grid">
          <div class="info-linha"><span>Estado</span><strong>${selo(w.state)}</strong></div>
          <div class="info-linha"><span>Provedor</span><strong>${h(w.provider || "—")}</strong></div>
          <div class="info-linha"><span>Instância</span><strong>${h(w.instance || "—")}</strong></div>
          <div class="info-linha"><span>Envio real</span><strong>${ctx.canais.sendingEnabled
            ? `<span class="pill green">ligado</span>` : `<span class="pill amber">desligado</span>`}</strong></div>
        </div>
        ${w.reason ? `<div class="alert alert-info alert-styled-left mt-10">${h(w.reason)}</div>` : ""}
        <p class="text-muted text-size-small mt-10">Parear é ler um QR code com o celular
        que vai atender. A sessão fica no provedor, não aqui.</p>`,
        { actions: `<button class="btn btn-default btn-xs" data-page="envio">Parear número</button>
                    <button class="btn btn-default btn-xs" data-page="whatsapp">Ver conversas</button>` })}`;
    return fechar();
  }

  if (chave === "zenvia") {
    const s = ctx.canal("SMS");
    const z = await api("/api/integrations/zenvia/status").catch((e) => ({ erro: e.message }));
    view.innerHTML = `${voltar}
      ${panel("Zenvia — SMS", `
        <div class="info-grid">
          <div class="info-linha"><span>Estado</span><strong>${selo(s.state)}</strong></div>
          <div class="info-linha"><span>Remetente</span><strong>${h(s.from || "—")}</strong></div>
        </div>
        ${s.reason ? `<div class="alert alert-info alert-styled-left mt-10">${h(s.reason)}</div>` : ""}`)}
      ${panel("Zenvia — Voz (telefonia)", !z.configurado
        ? `<div class="alert alert-info alert-styled-left">${h(z.motivo || z.erro || "Sem token de voz.")}</div>`
        : `<div class="info-grid">
            <div class="info-linha"><span>Saldo</span><strong>${z.saldo == null ? "—"
              : `R$ ${Number(z.saldo).toFixed(2).replace(".", ",")}`}</strong></div>
            <div class="info-linha"><span>Números (DID)</span><strong>${(z.dids || []).length}</strong></div>
          </div>
          ${z.erro ? `<div class="alert alert-danger alert-styled-left mt-10">${h(z.erro)}</div>` : ""}
          ${z.podeLigar
            ? `<div class="alert alert-success alert-styled-left mt-10">Conta pronta para ligar.</div>`
            : `<div class="alert alert-info alert-styled-left mt-10">
                Falta ${[!(z.dids || []).length && "comprar um número (DID)",
                         !(z.saldo >= (z.saldoMinimo || 1))
                           && `colocar saldo (hoje R$ ${Number(z.saldo || 0).toFixed(2).replace(".", ",")})`]
                        .filter(Boolean).join(" e ")}.
                Enquanto isso o discador registra a ligação, mas não disca.</div>`}`,
        { subtitle: "Lido da Zenvia na hora" })}`;
    return fechar();
  }

  // webhooks
  const hooks = await api("/api/webhooks");
  const souAdmin = nivelPeloMenos("admin");
  view.innerHTML = `${voltar}
    ${panel("Webhooks", table(["Eventos", "URL de destino", "Situação", "Criado", ""],
      hooks.map((w) => ({ cells: [
        w.events.map((e) => `<span class="pill">${h(e)}</span>`).join(" "),
        `<code style="word-break:break-all">${h(w.targetUrl)}</code>`,
        w.enabled ? `<span class="pill green">Ativo</span>` : `<span class="pill grey">Inativo</span>`,
        fmtDate(w.created),
        souAdmin ? `<button class="btn btn-default btn-xs" data-hook-toggle="${w.id}" data-on="${w.enabled ? 1 : 0}">
                      ${w.enabled ? "Desativar" : "Ativar"}</button>
                    <button class="btn btn-default btn-xs" data-del-hook="${w.id}">Remover</button>`
                 : `<span class="text-muted text-size-small">—</span>`] })),
      { scroll: true, empty: "Nenhum webhook." })
      + (souAdmin ? "" : `<div class="alert alert-info alert-styled-left mt-10">
           Só administradores gerenciam webhooks.</div>`),
      { actions: souAdmin ? `<button class="btn btn-main btn-xs" id="newHook">Novo webhook</button>` : "" })}`;
  fechar();
  // O PATCH existia no backend desde sempre, mas não havia botão: um webhook
  // com destino fora do ar só podia ser removido, nunca pausado.
  view.querySelectorAll("[data-hook-toggle]").forEach((b) => {
    b.onclick = async () => {
      try {
        await api(`/api/webhooks/${b.dataset.hookToggle}`, { method: "PATCH",
          body: { enabled: b.dataset.on !== "1" } });
        toast("Webhook atualizado.", "ok"); go("integracoes");
      } catch (e) { toast(e.message, "err"); }
    };
  });
  view.querySelectorAll("[data-del-hook]").forEach((b) => {
    b.onclick = () => confirmDialog("Remover webhook", "Remover este webhook?", async () => {
      try {
        await api(`/api/webhooks/${b.dataset.delHook}`, { method: "DELETE" });
        toast("Webhook removido."); go("integracoes");
      } catch (e) { toast(e.message, "err"); }
    });
  });
  const newHookBtn = document.getElementById("newHook");
  if (newHookBtn) newHookBtn.onclick = () => {
    const m = modal({
      title: "Novo webhook",
      body: `<div class="field"><label for="whUrl">URL de destino *</label>
          <input class="form-control" id="whUrl" placeholder="https://..."></div>
        <div class="field"><label for="whEvents">Eventos</label>
          <select class="form-control" id="whEvents" multiple size="7">
            <option value="LEAD.WON" selected>LEAD.WON</option>
            <option value="LEAD.LOST">LEAD.LOST</option>
            <option value="LEAD.CREATED">LEAD.CREATED</option>
            <option value="LEAD.REPLIED">LEAD.REPLIED</option>
            <option value="ACTIVITY.DONE">ACTIVITY.DONE</option>
            <option value="MESSAGE.SENT">MESSAGE.SENT</option>
            <option value="BASE.IMPORTED">BASE.IMPORTED</option>
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
}

// Rota direta para a aba de webhooks, usada pelo texto do "fora de escopo".
PAGES["integracoes-webhooks"] = {
  area: "Integrações", title: "Webhooks",
  async render() { state.integracaoAberta = "webhooks"; return PAGES.integracoes.render(); },
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

const DIAS_SEMANA = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]];

PAGES.ajustes = {
  area: "Prospecção", title: "Ajustes",
  async render() {
    const [cfg, reasons, fields, holidays, fitscore, feedbackCfg, permCfg, emailCfg] = await Promise.all([
      api("/api/flow/configuration"), api("/api/flow/lost-reasons"),
      api("/api/flow/new-lead-fields"), api("/api/flow/configuration/holidays"),
      api("/api/flow/fitscore"), api("/api/flow/deal-feedback/configuration"),
      api("/api/flow/permissions/configuration"), api("/api/flow/email/configuration")]);
    const camposPersonalizados = fields.filter((f) => f.customField);

    view.innerHTML = `
      ${panel("Configurações gerais", `
        <div class="filter-row" style="grid-template-columns:1fr 2fr">
          <div><label class="text-muted text-size-small">Meta diária padrão da empresa</label>
            <input class="form-control" type="number" min="1" id="cfgDailyGoal" value="${cfg.defaultDailyGoal}"></div>
          <div><label class="text-muted text-size-small">Dias úteis <span class="text-grey">— a fila não agenda fora deles</span></label>
            <div class="chip-grid" id="cfgDias">
              ${DIAS_SEMANA.map(([v, t]) => `<button type="button" class="chip${cfg.workingDays.includes(v) ? " active" : ""}" data-v="${v}">${t}</button>`).join("")}
            </div></div>
        </div>
        <div class="toolbar" style="border:0;padding:8px 0;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="cfgABS"${cfg.accountBasedSalesEnabled ? " checked" : ""}>
            Vendas por conta <span class="text-muted text-size-small">— mesmo domínio de e-mail cai sempre com o mesmo vendedor</span></label>
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="cfgImport"${cfg.regularUserCanImportLeadList ? " checked" : ""}>
            Vendedor comum pode importar lista de leads</label>
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="cfgFila"${cfg.smartQueueEnabled ? " checked" : ""}>
            Fila inteligente <span class="text-muted text-size-small">— prioriza quem tem mais chance de responder</span></label>
        </div>
        <div class="field"><label class="text-muted text-size-small">Blacklist de domínios de e-mail
          <span class="text-grey">— um por linha; lead desses domínios é perdido automaticamente</span></label>
          <textarea class="form-control" id="cfgBlacklist" rows="3" placeholder="concorrente.com.br">${h(cfg.blacklist.join("\n"))}</textarea></div>
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <span class="spacer"></span>
          <button class="btn btn-main btn-sm" id="cfgSalvar">Salvar configurações</button>
        </div>`)}

      ${panel("Metas diárias", table(["Usuário", "Atividades por dia"],
        cfg.usersGoals.map((g) => {
          const u = state.users.find((x) => x.id === g.userId);
          return { cells: [h(u ? u.name : g.userId), g.dailyGoal] };
        })), { subtitle: `Padrão da empresa: ${cfg.defaultDailyGoal} atividades/dia` })}

      ${panel("Permissões", `
        <div class="alert alert-info alert-styled-left">
          Gestor e admin sempre têm acesso total. Estas chaves controlam o que um vendedor comum (SDR) pode fazer
          além da própria carteira. "Importar lista de leads" já fica em Configurações gerais, acima.
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="permVisivel"${permCfg.leadsVisibleAll ? " checked" : ""}>
            Ver e acessar leads de outros usuários</label>
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="permAdd"${permCfg.leadsAddManual ? " checked" : ""}>
            Adicionar leads individualmente</label>
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="permStats"${permCfg.statisticsAccess ? " checked" : ""}>
            Acessar a aba de Estatísticas</label>
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="permDel"${permCfg.leadsDelete ? " checked" : ""}>
            Apagar leads <span class="text-muted text-size-small">— só os da própria carteira, e a ação não tem volta</span></label>
        </div>
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <span class="spacer"></span>
          <button class="btn btn-main btn-sm" id="permSalvar">Salvar</button>
        </div>`)}

      ${panel("Motivos de perda",
        table(["Motivo", ""], reasons.map((r) => ({ cells: [h(r.name),
          `<button class="btn btn-default btn-xs" data-edit-reason="${r.id}" data-nome="${h(r.name)}">Editar</button>
           <button class="btn btn-default btn-xs" data-del-reason="${r.id}">Remover</button>`] }))),
        { actions: `<button class="btn btn-main btn-xs" id="newReason">Adicionar</button>` })}

      ${panel("Campos do lead",
        table(["Campo", "Identificador", "Tipo", "Visível", "Obrig. p/ ganhar", "Obrig. p/ perder", ""],
          fields.map((f) => ({ cells: [h(f.name), `<code>${h(f.identifier)}</code>`,
            f.customField ? `<span class="pill green">Personalizado</span>` : `<span class="pill grey">Nativo</span>`,
            f.customField ? (f.visible ? "Sim" : "Não") : "Sim",
            f.wonMandatory ? "Sim" : "—", f.lostMandatory ? "Sim" : "—",
            f.customField ? `<button class="btn btn-default btn-xs" data-edit-field="${f.id}">Editar</button>` : ""] }))),
        { actions: `<button class="btn btn-main btn-xs" id="newField">Novo campo</button>` })}

      ${panel("Etapa do lead (funil)", `
        <p class="text-muted text-size-small" style="margin-top:0">
          A etapa não é um cadastro à parte: escolha um campo personalizado e as
          opções dele viram as etapas, com aba e contagem na lista de Leads.</p>
        <div class="field-row">
          <div class="field"><label for="cfgEtapaCampo">Campo que representa a etapa</label>
            <select class="form-control" id="cfgEtapaCampo">
              <option value="">Nenhum — funil desligado</option>
              ${camposPersonalizados.map((f) => `<option value="${f.id}"${String(cfg.leadStageFieldId) === String(f.id) ? " selected" : ""}>${h(f.name)}</option>`).join("")}
            </select></div>
          <div class="field"><label for="cfgRespMeta">Meta de tempo de resposta (horas)</label>
            <input class="form-control" type="number" min="1" id="cfgRespMeta" value="${cfg.responseTimeGoalHours || 24}">
            <span class="help-block">Entre o lead entrar e a primeira abordagem. Vale na aba Tempo de resposta das estatísticas.</span></div>
          <div class="field"><label for="cfgEtapaOpcoes">Etapas, uma por linha</label>
            <textarea class="form-control" id="cfgEtapaOpcoes" rows="4" placeholder="Conexão&#10;Qualificação&#10;Reunião marcada">${h((camposPersonalizados.find((f) => String(f.id) === String(cfg.leadStageFieldId)) || {}).options?.join("\n") || "")}</textarea></div>
        </div>
        <button class="btn btn-main btn-sm" id="cfgEtapaSalvar">Salvar etapas</button>`)}

      ${panel("Lead scoring (fitscore)", `
        ${table(["Campo", "Condição", "Valor", "Pontos", ""], fitscore.map((r) => ({ cells: [
          h(r.fieldName || "—"), r.expressionType === "LIKE" ? "Contém" : "Igual a",
          h(r.targetValue), r.score,
          `<button class="btn btn-default btn-xs" data-del-fit="${r.id}">Remover</button>`,
        ] })), { empty: "Nenhuma regra ainda — todo lead pontua 0." })}
        <div class="filter-row mt-10" style="grid-template-columns:2fr 1.3fr 1.5fr 0.8fr auto">
          <div><label class="text-muted text-size-small">Campo</label>
            <select class="form-control input-sm" id="fitCampo">
              ${camposPersonalizados.map((f) => `<option value="${f.id}">${h(f.name)}</option>`).join("")}
            </select></div>
          <div><label class="text-muted text-size-small">Condição</label>
            <select class="form-control input-sm" id="fitTipo">
              <option value="EQUALS">Igual a</option><option value="LIKE">Contém</option>
            </select></div>
          <div><label class="text-muted text-size-small">Valor</label>
            <input class="form-control input-sm" id="fitValor" placeholder="ex.: gold"></div>
          <div><label class="text-muted text-size-small">Pontos</label>
            <input class="form-control input-sm" type="number" id="fitPontos" value="1"></div>
          <div style="align-self:end"><button class="btn btn-main btn-sm" id="fitAdd">Adicionar regra</button></div>
        </div>`,
        { subtitle: camposPersonalizados.length
            ? "Some os pontos das regras que baterem — dá pra priorizar lead por características dele, não só por atraso."
            : "Crie um campo personalizado abaixo antes de montar uma regra de pontuação." })}

      ${panel("Feedback de oportunidade", `
        <div class="alert alert-info alert-styled-left">
          Quando um lead vira ganho, o vendedor responsável recebe uma pendência pra dizer se a reunião aconteceu
          e qualificar o lead pelas perguntas abaixo. Acompanhe as respostas em
          <a data-page="feedback-oportunidade">Estatísticas &gt; Feedback de oportunidade</a>.
        </div>
        <div class="toolbar" style="border:0;padding:0 0 8px;background:none;flex-wrap:wrap;gap:14px">
          <label><input type="checkbox" id="dfEnabled"${feedbackCfg.dealFeedbackEnabled ? " checked" : ""}>
            Ativar feedback de oportunidade</label>
        </div>
        <div class="field"><label class="text-muted text-size-small">Perguntas de qualificação — uma por linha</label>
          <textarea class="form-control" id="dfTags" rows="4"
            placeholder="Possui orçamento para contratar a solução?">${h(feedbackCfg.qualificationTags.join("\n"))}</textarea></div>
        <div class="field"><label class="text-muted text-size-small">Automação — cadência para quem respondeu "não tive reunião"</label>
          <select class="form-control input-sm" id="dfCadencia">
            <option value="">Nenhuma — não reencaminha</option>
            ${state.cadences.map((c) => `<option value="${c.id}"${feedbackCfg.automationCadenceId === c.id ? " selected" : ""}>${h(c.name)}</option>`).join("")}
          </select></div>
        <div class="toolbar mt-10" style="border:0;padding:0;background:none">
          <span class="spacer"></span>
          <button class="btn btn-main btn-sm" id="dfSalvar">Salvar</button>
        </div>`)}

      ${panel("Calendário de trabalho",
        table(["Feriado", "Data"], holidays.map((x) => ({ cells: [h(x.name || "—"), fmtDate(x.date)] }))),
        { subtitle: `Dias úteis: ${cfg.workingDays.map((v) => DIAS_SEMANA.find(([d]) => d === v)[1]).join(", ")}. `
                    + "A fila não agenda atividade fora deles.",
          actions: `<button class="btn btn-main btn-xs" id="newHoliday">Adicionar feriado</button>` })}

      ${panel("E-mail — remetente", `
        <div class="alert alert-info alert-styled-left">
          Nome e endereço que aparecem como remetente nos e-mails de cadência. Trocar o endereço exige
          verificar o domínio de novo (checa o registro SPF por DNS).
        </div>
        <div class="filter-row" style="grid-template-columns:1fr 1fr">
          <div><label class="text-muted text-size-small">Nome do remetente</label>
            <input class="form-control" id="emlNome" value="${h(emailCfg.fromName)}" placeholder="BLU Sales Group"></div>
          <div><label class="text-muted text-size-small">E-mail do remetente</label>
            <input class="form-control" id="emlEndereco" value="${h(emailCfg.fromAddress)}" placeholder="contato@suaempresa.com.br"></div>
        </div>
        <div class="toolbar mt-10" style="border:0;padding:0;background:none;gap:10px">
          <span id="emlBadge">${emailCfg.domainVerified
              ? `<span class="pill green">Domínio verificado</span>`
              : `<span class="pill amber">Domínio não verificado</span>`}</span>
          <span class="spacer"></span>
          <button class="btn btn-default btn-sm" id="emlVerificar">Verificar domínio</button>
          <button class="btn btn-main btn-sm" id="emlSalvar">Salvar</button>
        </div>`)}
      ${panel("Domínios de envio (whitelabel)",
        `<div id="dominiosBox">${LOADING}</div>`,
        { subtitle: "Estado real dos domínios no provedor de envio. Cadastrar ou remover domínio se faz no painel do provedor — é recurso da conta que paga a fatura." })}`;

    // Carrega depois de pintar a tela: a consulta sai para fora e não pode
    // segurar o resto de Ajustes.
    (async () => {
      const box = document.getElementById("dominiosBox");
      if (!box) return;
      try {
        const d = await api("/api/flow/email/domains");
        if (!d.configurado || d.motivo) {
          box.innerHTML = `<div class="alert alert-info alert-styled-left">${h(d.motivo)}</div>`;
          return;
        }
        box.innerHTML = d.dominios.length ? d.dominios.map((dom) => `
          <div class="sub-block">
            <h4>${h(dom.nome)}
              <span class="pill ${dom.status === "verified" ? "green" : dom.status === "failed" ? "red" : "amber"}">${h(dom.status)}</span>
              ${dom.envio === "enabled" ? `<span class="pill green">envio liberado</span>` : `<span class="pill grey">envio bloqueado</span>`}
              <span class="text-muted text-size-small">${h(dom.regiao || "")} · desde ${h(dom.criado || "—")}</span>
            </h4>
            ${table(["Registro", "Nome", "Valor", "Situação"],
              dom.registros.map((r) => ({ cells: [
                `<span class="pill">${h(r.tipo || "")}</span>`,
                `<code class="text-size-small">${h(r.nome || "")}</code>`,
                `<code class="text-size-small" style="word-break:break-all">${h(r.valor || "")}</code>`,
                `<span class="pill ${r.status === "verified" ? "green" : "amber"}">${h(r.status || "—")}</span>`,
              ] })), { scroll: true, empty: "Sem registros DNS informados pelo provedor." })}
          </div>`).join("") : emptyState("Nenhum domínio cadastrado no provedor.");
      } catch (e) {
        box.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
      }
    })();

    document.getElementById("cfgDias").onclick = (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      b.classList.toggle("active");
    };
    document.getElementById("cfgSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      const dias = [...view.querySelectorAll("#cfgDias .chip.active")].map((b) => Number(b.dataset.v));
      if (!dias.length) return toast("Marque ao menos um dia útil.", "err");
      btn.disabled = true;
      try {
        await api("/api/flow/configuration", { method: "PATCH", body: {
          defaultDailyGoal: Number(document.getElementById("cfgDailyGoal").value) || 170,
          accountBasedSalesEnabled: document.getElementById("cfgABS").checked,
          regularUserCanImportLeadList: document.getElementById("cfgImport").checked,
          smartQueueEnabled: document.getElementById("cfgFila").checked,
          workingDays: dias,
          blacklist: document.getElementById("cfgBlacklist").value.split("\n").map((s) => s.trim()).filter(Boolean),
        } });
        toast("Configurações salvas.", "ok");
        go("ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    document.getElementById("cfgEtapaSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const fid = document.getElementById("cfgEtapaCampo").value;
        await api("/api/flow/configuration", { method: "PATCH", body: {
          leadStageFieldId: fid || null,
          responseTimeGoalHours: Number(document.getElementById("cfgRespMeta").value) || 24,
        } });
        if (fid) {
          await api(`/api/flow/new-lead-fields/${fid}`, { method: "PATCH",
            body: { options: document.getElementById("cfgEtapaOpcoes").value.split("\n") } });
        }
        const et = await api("/api/flow/lead-stages");
        state.stageField = et.field;
        state.stageOptions = et.options;
        toast("Etapas salvas.", "ok");
        go("ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    document.getElementById("dfSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await api("/api/flow/deal-feedback/configuration", { method: "PATCH", body: {
          dealFeedbackEnabled: document.getElementById("dfEnabled").checked,
          qualificationTags: document.getElementById("dfTags").value.split("\n").map((s) => s.trim()).filter(Boolean),
          automationCadenceId: Number(document.getElementById("dfCadencia").value) || null,
        } });
        toast("Configurações salvas.", "ok");
        go("ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    document.getElementById("permSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await api("/api/flow/permissions/configuration", { method: "PATCH", body: {
          leadsVisibleAll: document.getElementById("permVisivel").checked,
          leadsAddManual: document.getElementById("permAdd").checked,
          leadsDelete: document.getElementById("permDel").checked,
          statisticsAccess: document.getElementById("permStats").checked,
        } });
        toast("Permissões salvas.", "ok");
        go("ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    document.getElementById("emlSalvar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await api("/api/flow/email/configuration", { method: "PATCH", body: {
          fromName: document.getElementById("emlNome").value.trim(),
          fromAddress: document.getElementById("emlEndereco").value.trim(),
        } });
        toast("Remetente salvo.", "ok");
        go("ajustes");
      } catch (err) { toast(err.message, "err"); btn.disabled = false; }
    };
    document.getElementById("emlVerificar").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const r = await api("/api/flow/email/configuration/verify", { method: "POST" });
        document.getElementById("emlBadge").innerHTML = r.domainVerified
          ? `<span class="pill green">Domínio verificado</span>`
          : `<span class="pill amber">Domínio não verificado</span>`;
        toast(r.message, r.domainVerified ? "ok" : "err");
      } catch (err) { toast(err.message, "err"); }
      btn.disabled = false;
    };
    view.querySelectorAll("[data-del-reason]").forEach((b) => {
      b.onclick = () => confirmDialog("Remover motivo", "Remover este motivo de perda?", async () => {
        try {
          await api(`/api/flow/lost-reasons/${b.dataset.delReason}`, { method: "DELETE" });
          toast("Motivo removido."); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      });
    });
    view.querySelectorAll("[data-edit-reason]").forEach((b) => {
      b.onclick = () => promptOne("Editar motivo de perda", "Motivo", async (v) => {
        await api(`/api/flow/lost-reasons/${b.dataset.editReason}`, { method: "PATCH", body: { name: v } });
        toast("Motivo atualizado.", "ok"); go("ajustes");
      }, "Salvar", b.dataset.nome);
    });
    view.querySelectorAll("[data-edit-field]").forEach((b) => {
      b.onclick = () => openCampoForm(fields.find((f) => String(f.id) === b.dataset.editField));
    });
    document.getElementById("newReason").onclick = () => promptOne("Novo motivo de perda", "Motivo", async (v) => {
      await api("/api/flow/lost-reasons", { method: "POST", body: { name: v } });
      state.lostReasons = await api("/api/flow/lost-reasons");
      toast("Motivo adicionado.", "ok"); go("ajustes");
    }, "Adicionar");
    document.getElementById("newField").onclick = () => {
      const m = modal({
        title: "Novo campo personalizado",
        body: `<div class="field"><label for="cfName">Nome *</label><input class="form-control" id="cfName"></div>
          <div class="field"><label for="cfIdent">Identificador *</label>
            <input class="form-control" id="cfIdent" placeholder="ex.: segmento"></div>
          <div class="field"><label for="cfType">Tipo</label>
            <select class="form-control" id="cfType">
              <option value="STRING">Texto</option><option value="NUMBER">Número</option>
              <option value="DATE">Data</option></select></div>
          <div class="field">
            <label><input type="checkbox" id="cfWon"> Obrigatório para marcar como ganho</label>
            <label><input type="checkbox" id="cfLost"> Obrigatório para marcar como perdido</label>
          </div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
                 <button class="btn btn-main btn-sm" data-save>Criar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-save]").onclick = async () => {
        const nome = m.root.querySelector("#cfName").value.trim();
        const ident = m.root.querySelector("#cfIdent").value.trim();
        if (!nome || !ident) return toast("Nome e identificador são obrigatórios.", "err");
        try {
          await api("/api/flow/new-lead-fields", { method: "POST", body: {
            name: nome,
            identifier: ident,
            dataType: m.root.querySelector("#cfType").value,
            wonMandatory: m.root.querySelector("#cfWon").checked,
            lostMandatory: m.root.querySelector("#cfLost").checked } });
          m.close(); toast("Campo criado.", "ok"); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      };
    };
    view.querySelectorAll("[data-del-fit]").forEach((b) => {
      b.onclick = () => confirmDialog("Remover regra", "Remover esta regra de fitscore?", async () => {
        try {
          await api(`/api/flow/fitscore/${b.dataset.delFit}`, { method: "DELETE" });
          toast("Regra removida."); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      });
    });
    const fitBtn = document.getElementById("fitAdd");
    if (fitBtn) fitBtn.onclick = async () => {
      const valor = document.getElementById("fitValor").value.trim();
      if (!valor) return toast("Preencha o valor da regra.", "err");
      try {
        await api("/api/flow/fitscore", { method: "POST", body: {
          fieldId: Number(document.getElementById("fitCampo").value),
          expressionType: document.getElementById("fitTipo").value,
          targetValue: valor,
          score: Number(document.getElementById("fitPontos").value) || 1,
        } });
        toast("Regra adicionada.", "ok"); go("ajustes");
      } catch (e) { toast(e.message, "err"); }
    };
    document.getElementById("newHoliday").onclick = () => {
      const m = modal({
        title: "Adicionar feriado",
        body: `<div class="field"><label for="hDate">Data</label><input class="form-control" type="date" id="hDate"></div>
          <div class="field"><label for="hName">Descrição</label><input class="form-control" id="hName"></div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
                 <button class="btn btn-main btn-sm" data-save>Adicionar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-save]").onclick = async () => {
        const data = m.root.querySelector("#hDate").value;
        const nome = m.root.querySelector("#hName").value.trim();
        if (!data || !nome) return toast("Data e descrição são obrigatórias.", "err");
        try {
          await api("/api/flow/configuration/holidays", { method: "POST", body: {
            date: data,
            name: nome } });
          m.close(); toast("Feriado adicionado.", "ok"); go("ajustes");
        } catch (e) { toast(e.message, "err"); }
      };
    };
  },
};

function promptOne(title, label, onOk, okLabel = "Salvar", valor = "") {
  const m = modal({
    title,
    body: `<div class="field"><label for="promptVal">${h(label)}</label><input class="form-control" id="promptVal" value="${h(valor)}"></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button>
             <button class="btn btn-main btn-sm" data-ok>${h(okLabel)}</button>`,
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
        `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
     <button class="btn btn-default btn-xs ct-toggle" data-id="${u.id}" data-ativo="${u.ativo}" data-nome="${h(u.email)}">${u.ativo ? "Desativar" : "Reativar"}</button>`,
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
    const trocar = async () => {
      const ativo = b.dataset.ativo !== "true";
      try {
        await api(`/api/admin/users/${b.dataset.id}`, { method: "PATCH", body: { ativo } });
        toast(ativo ? "Conta reativada." : "Conta desativada.", "ok");
        go("contas");
      } catch (e) { toast(e.message, "err"); }
    };
    b.onclick = () => {
      if (b.dataset.ativo === "true") {
        confirmDialog("Desativar conta", `Desativar o acesso de ${b.dataset.nome}? A pessoa não consegue mais entrar.`, trocar);
      } else {
        trocar();
      }
    };
  });
}

function novaConta() {
  const m = modal({
    title: "Nova conta de acesso",
    body: `
      <div class="field"><label for="ncNome">Nome</label><input class="form-control" id="ncNome"></div>
      <div class="field"><label for="ncEmail">E-mail</label>
        <input class="form-control" id="ncEmail" type="email"></div>
      <div class="field"><label>Senha provisória <span class="text-grey">(mínimo 8 caracteres)</span></label>
        <input class="form-control" id="ncSenha" type="password"></div>
      <div class="field"><label for="ncRole">Perfil</label>
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
    `<button class="btn btn-default btn-xs gr-del" data-id="${g.id}" data-nome="${h(g.nome || g.name)}">Excluir</button>`,
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
    }, "Criar");
  out.querySelectorAll(".gr-del").forEach((b) => {
    b.onclick = () => confirmDialog("Excluir grupo",
      `Excluir o grupo "${b.dataset.nome}"? As contas dele ficam sem grupo.`, async () => {
        try {
          await api(`/api/admin/grupos/${b.dataset.id}`, { method: "DELETE" });
          toast("Grupo excluído.", "ok"); go("contas");
        } catch (e) { toast(e.message, "err"); }
      });
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
             <div class="field"><label for="tnUser">Age em nome de</label>
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
    b.onclick = () => confirmDialog("Revogar token",
      "Revogar este token? Quem usa essa integração perde acesso na hora.", async () => {
        try {
          await api(`/api/admin/tokens/${b.dataset.id}`, { method: "DELETE" });
          toast("Token revogado.", "ok"); go("contas");
        } catch (e) { toast(e.message, "err"); }
      });
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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
  }
}

function editarModelo(t) {
  const novo = !t;
  const m = modal({
    wide: true,
    title: novo ? "Novo modelo" : `Editar “${t.name}”`,
    body: `
      <div class="field-row">
        <div class="field"><label for="tmNome">Nome</label>
          <input class="form-control" id="tmNome" value="${h(t ? t.name : "")}"></div>
        <div class="field"><label for="tmCanal">Canal</label>
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
      <div class="field"><label for="tmCorpo">Mensagem</label>
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
        `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
      <div class="field"><label for="etDest">${eEmail ? "E-mail" : "Telefone com DDD"}</label>
        <input class="form-control" id="etDest" placeholder="${eEmail ? "voce@blusalesgroup.com.br" : "41999999999"}"></div>
      <div class="field"><label for="etCorpo">Mensagem</label>
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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
    out.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
    alvo.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>` + antes;
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
  if (bloco === "dossie") return renderDossieRico(r);
  return tabelaGenerica(r);
}

/** Dossiê rico do funil novo (Assertiva por trás): telefone ordenado por
 *  chance de alguém atender — não-perturbe sempre por último, com o motivo
 *  ao lado — mais situação do CPF, óbito provável, PPE e vínculo por área.
 *  Sem isso o SDR discava do topo da lista e caía direto no número que a
 *  própria Assertiva já avisava pra não usar. */
function renderDossieRico(d) {
  if (!d || d.status === "error") {
    return `<div class="alert alert-danger alert-styled-left">${h((d && d.message) || "Falha ao consultar.")}</div>`;
  }
  const id = d.identificacao || {};
  const doc = d.dossie || {};
  if (!id.cpf) {
    return `<div class="alert alert-info alert-styled-left">
      <strong>Não consegui identificar o CPF.</strong><br>
      <span class="text-muted text-size-small">${h(id.porque || id.situacao || "sem motivo registrado")}</span>
    </div>`;
  }
  if (doc.status && doc.status !== "ok") {
    return `<div class="alert alert-danger alert-styled-left">CPF encontrado, mas os dados não vieram: ${h(doc.message || doc.status)}</div>`;
  }
  const tels = doc.telefones || [];
  const vinc = doc.vinculos || [];
  const bloco = (titulo, corpo) => corpo
    ? `<div class="sub-block"><h4>${h(titulo)}</h4>${corpo}</div>` : "";
  const telLinha = (t) => {
    const num = String(t.display || t.numero || t.telefone || "").replace(/\D/g, "");
    const bloqueado = !!t.nao_perturbe;
    return `<div style="display:flex;align-items:baseline;gap:10px;padding:5px 0;
                border-bottom:1px solid #eee${bloqueado ? ";opacity:.55" : ""}">
      <strong style="font-family:monospace">${h(num || t.display || "—")}</strong>
      ${t.whatsapp ? '<span class="pill green">whatsapp</span>' : ""}
      <span class="text-muted text-size-small">${h(t.porque || "")}</span>
    </div>`;
  };
  return `
    ${id.forte === false ? `<div class="alert alert-info alert-styled-left">
        <strong>Sinal fraco — confira antes de ligar.</strong> Este é o candidato de maior
        nota, não uma identificação confirmada.
        ${(id.alternativas || []).length ? `<div class="text-muted text-size-small mt-5">
          Outros possíveis: ${id.alternativas.map((a) => `${h(a.nome || a.cpf)} (${h(a.forca)})`).join(" · ")}</div>` : ""}
      </div>` : ""}
    ${grade([
      campo("Nome", doc.nome), campo("CPF", fmtCPF(id.cpf)),
      campo("Idade", doc.idade), campo("Situação do CPF", doc.situacao_cpf),
      campo("Óbito provável", doc.obito_provavel ? "sim" : ""),
      campo("PPE", doc.ppe ? "pessoa politicamente exposta" : ""),
    ])}
    <div class="text-muted text-size-small mt-5">identificado por <strong>${h(id.situacao || "")}</strong>
      ${id.confianca ? ` · confiança ${h(id.confianca)}` : ""}${id.porque ? ` · ${h(id.porque)}` : ""}</div>
    ${bloco(`Telefones (${tels.length}) — melhor primeiro`, tels.length
      ? tels.map(telLinha).join("") : `<span class="text-muted">Nenhum telefone na base.</span>`)}
    ${bloco("E-mails", (doc.emails || []).length ? h(doc.emails.join(" · ")) : "")}
    ${bloco(`Histórico profissional (${vinc.length})`, vinc.length
      ? table(["Empresa", "Cargo", "Desde", ""], vinc.slice(0, 8).map((v) => ({ cells: [
          h(v.razao || "—"), h(v.cargo || "sem CBO"),
          h(v.desde ? String(v.desde).slice(0, 10) : "—"),
          v.tipo === "societario" ? `<span class="pill grey">sócio</span>` : "",
        ] })), { scroll: true })
      : `<span class="text-muted text-size-small">Sem vínculo no cadastro — acontece com
         empresa aberta há pouco, PJ, ou quem trocou de emprego recentemente.</span>`)}
    ${bloco("Endereço", (doc.enderecos || []).length ? h(endereco(doc.enderecos[0])) : "")}`;
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
    alvo.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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
      <div class="field"><label for="msAtual">Senha atual</label>
        <input class="form-control" id="msAtual" type="password"></div>
      <div class="field"><label>Nova senha <span class="text-grey">(mínimo 8)</span></label>
        <input class="form-control" id="msNova" type="password"></div>
      <div class="field"><label for="msRepete">Repita a nova senha</label>
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
    el.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`;
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

  const tom = p.estado === "ERRO" ? "alert-danger" : p.estado === "PRONTO" ? "alert-success" : "alert-info";
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
