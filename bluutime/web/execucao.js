"use strict";
/* ── Execução ────────────────────────────────────────────────────────────
   Refeita contra a gravação da rotina do BDR (22/09/2026), tela a tela:

   - a página: faixa "Você está prospectando…" com Iniciar novos leads, "Meu
     progresso hoje" com o número grande e o troféu do objetivo diário, e o
     painel Execução com a chave do modo rápido, os leads aguardando a primeira
     ligação e a tabela ATIVIDADES (x DE y) com os cinco filtros do original;
   - a execução de uma atividade em tela dividida: painel do lead à esquerda,
     navegador "‹ 1 de N ›" no topo e a atividade no centro (pesquisa, editor
     de e-mail, discador com a tela de chamada e os quatro botões de
     classificação);
   - a barra "Atividade completada" com Agendar atividade extra, Ganho e
     Perdido; o ganho em dois passos (campos obrigatórios, depois o resumo); o
     perdido com Agendar nova prospecção; e o modal Iniciar novos leads.

   A fila continua ordenada por score no servidor — é a diferença do Bluutime —
   mas a tela não mostra mais o número: o BDR só precisa seguir a ordem.

   Depende dos globais do app.js (api, go, h, modal, toast, state, view…). */

const EXEC_PREF_PADRAO = { rapido: true, quentes: true, abertos: { quentes: true, atividades: true } };

function execPrefs() {
  try {
    return { ...EXEC_PREF_PADRAO, ...JSON.parse(localStorage.getItem("bluutime.exec") || "{}") };
  } catch {
    // localStorage bloqueado (janela anônima): funciona com o padrão.
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

const TIPO_CAIXA = { CALL: "LIGAÇÃO", E_MAIL: "E-MAIL", SEARCH: "PESQUISA", SOCIAL_POINT: "SOCIAL POINT", MEETING: "REUNIÃO" };
const TIPO_ICONE_EXEC = { CALL: "☎", E_MAIL: "✉", SEARCH: "⌕", SOCIAL_POINT: "❝", MEETING: "▦" };
const TIPO_NOME = { CALL: "Ligação", E_MAIL: "E-mail", SEARCH: "Pesquisa", SOCIAL_POINT: "Social Point", MEETING: "Reunião" };

/* ── a página ──────────────────────────────────────────────────────── */
PAGES.execucao = {
  area: "Prospecção", title: "Execução de cadência",
  async render() {
    const senha = go.senha;
    const f = state.queueFilter || {};
    const prefs = execPrefs();
    const qs = new URLSearchParams(Object.entries({
      q: f.q, type: f.type, cadence_id: f.cadence_id, lead_base_id: f.lead_base_id, sdr_id: f.sdr_id,
    }).filter(([, v]) => v));
    const [res, quentes, geral, bases] = await Promise.all([
      api(`/api/flow/execution/queue?${qs}`),
      prefs.quentes ? api("/api/flow/hot-leads").catch(() => ({ data: [] })) : Promise.resolve({ data: [] }),
      api("/api/flow/execution/overall").catch(() => null),
      state.execBases ? Promise.resolve(state.execBases)
        : api("/api/flow/lead-bases").then((r) => (state.execBases = r.data || r)).catch(() => []),
    ]);
    if (!naVez(senha)) return;

    // Status e passo são filtros sobre a fila que já chegou: não justificam
    // outra ida ao servidor a cada clique.
    const agora = Date.now();
    const todos = res.data;
    const visiveis = todos.filter((a) => {
      if (f.status === "late" && !a.late) return false;
      if (f.status === "ontime" && a.late) return false;
      if (f.status === "today" && new Date(a.scheduledAt).toDateString() !== new Date(agora).toDateString()) return false;
      if (f.passo && String(a.extra ? "extra" : (a.passo && a.passo.dia)) !== String(f.passo)) return false;
      return true;
    });
    state.execVisiveis = visiveis;
    const extras = visiveis.filter((a) => a.extra);
    const daCadencia = visiveis.filter((a) => !a.extra);
    const dias = [...new Set(todos.filter((a) => a.passo).map((a) => a.passo.dia))].sort((x, y) => x - y);
    const filtrando = ["q", "type", "cadence_id", "lead_base_id", "status", "passo", "sdr_id"].some((k) => f[k]);

    const feitas = geral ? geral.hoje.feitas : 0;
    const total = feitas + todos.filter((a) => new Date(a.scheduledAt).getTime() <= agora + 864e5).length;
    const meta = geral ? geral.hoje.meta : 0;
    const pctFeito = total ? Math.min(100, (feitas / total) * 100) : 0;

    const linha = (a) => {
      const hojeData = new Date(a.scheduledAt).toDateString() === new Date(agora).toDateString();
      return `
      <tr class="exec-linha${a.late ? " atrasada" : ""}" data-act="${a.id}">
        <td class="exec-col-ativ">
          ${a.extra ? `<span class="exec-quando ${a.late ? "atraso" : "prazo"}">${a.late ? "Atrasada" : hojeData ? "Hoje" : fmtDateTime(a.scheduledAt).slice(0, 5)}</span>` : ""}
          <span class="exec-tipo">${h(a.extra ? TIPO_NOME[a.type] || a.type : TIPO_CAIXA[a.type] || a.type)}</span>
        </td>
        <td class="exec-col-cad">
          <div>${h(a.lead.cadence ? a.lead.cadence.name : "—")}</div>
          <div class="exec-sub">${h(passoRotulo(a))}${a.late && !a.extra ? ` · <span class="exec-atraso-txt">atrasada</span>` : ""}</div>
        </td>
        <td class="exec-col-lead">
          <div class="exec-lead">
            <span class="exec-av">${h((a.lead.name || "?").trim().charAt(0).toUpperCase())}</span>
            <div><a class="exec-lead-nome" data-lead="${a.lead.id}">${h(a.lead.name)}</a>
              <div class="exec-sub">${h(a.lead.company || "")}</div></div>
          </div>
        </td>
        <td class="exec-col-acao">
          <div class="exec-acao">
            <button class="exec-executar" data-exec="${a.id}"><span>${TIPO_ICONE_EXEC[a.type] || "▶"}</span> Executar</button>
            <button class="exec-mais" data-mais="${a.id}" aria-label="Mais ações">▾</button>
            <div class="exec-menu" id="em-${a.id}" hidden>
              <a data-m-pular="${a.id}">Pular atividade</a>
              <a data-m-adiar="${a.id}">Adiar</a>
              <a data-m-extra="${a.id}">Agendar atividade extra</a>
              <a data-m-ganho="${a.lead.id}">Ganho</a>
              <a data-m-perdido="${a.lead.id}">Perdido</a>
              ${a.lead.status === "ON_EXTRA_ACTIVITY" ? `<a data-m-retomar="${a.lead.id}">Retomar cadência</a>` : ""}
              <a data-m-abrir="${a.lead.id}">Abrir lead</a>
            </div>
          </div>
        </td>
      </tr>`;
    };

    const vazio = filtrando
      ? `<div class="exec-vazio"><b>Não há nada por aqui.</b><span>Tente limpar os filtros de busca.</span></div>`
      : (geral && geral.prospectando)
        ? `<div class="exec-vazio"><b>Você completou todas as atividades para hoje!</b><span>Não há pendências por aqui.</span></div>`
        : `<div class="exec-vazio"><b>Adicione atividades e busque seu objetivo diário</b><span>Inicie novos leads para adicionar atividades aqui.</span></div>`;

    const sel = (id, rot, itens, atual) => `<select class="exec-filtro${atual ? " ativo" : ""}" id="${id}" aria-label="${rot}">
        <option value="">${rot}</option>${itens.map(([v, r]) => `<option value="${h(v)}"${String(atual) === String(v) ? " selected" : ""}>${h(r)}</option>`).join("")}</select>`;

    view.innerHTML = `
      <div class="exec-faixa" id="execFaixa">
        <span>Você está prospectando <b>${geral ? geral.prospectando : "—"} leads</b> e existem
          <b>${geral ? (geral.disponiveis || 0).toLocaleString("pt-BR") : "—"} leads disponíveis</b> para serem iniciados</span>
        <button class="btn btn-main btn-sm" id="btnIniciarNovos">Iniciar novos leads</button>
      </div>

      <div class="exec-painel" id="painelProgresso">
        <div class="exec-painel-topo"><h2>Meu progresso hoje</h2>
          <span class="dica-icone" title="Atividades finalizadas hoje sobre o total do dia (finalizadas + pendentes).">i</span></div>
        <div class="exec-progresso">
          <div class="exec-prog-num">
            <div><span class="exec-grande">${feitas}</span><span class="exec-de"> / ${total} atividades</span></div>
            <div class="exec-barra"><span class="fin" style="width:${pctFeito}%"></span></div>
            <div class="exec-legenda"><span><i class="fin"></i>Finalizado</span><span><i class="pen"></i>Pendente</span></div>
          </div>
          <div class="exec-objetivo">
            <span class="exec-trofeu${geral && geral.bateuMeta ? " ok" : ""}">🏆</span>
            <div><b>Objetivo diário (${meta || "—"})</b>
              <div class="exec-sub">${geral && geral.bateuMeta
                ? "Objetivo alcançado. Tudo o que vier agora é bônus."
                : meta ? "Para alcançar seu objetivo diário, adicione atividades à lista iniciando novos leads."
                       : "Sem objetivo definido. Peça ao gestor para configurar sua meta diária."}</div></div>
          </div>
        </div>
      </div>

      <div class="exec-painel exec-execucao">
        <div class="exec-abas">
          <span class="exec-aba ativa">Execução</span>
          <span class="spacer"></span>
          <label class="exec-rapido" id="toggleRapido" title="O lead não será puxado no modo de Execução rápida se já estiver com alguém">
            Modo Execução rápida
            <input type="checkbox" id="chkRapido"${prefs.rapido ? " checked" : ""}><span class="exec-chave"></span>
          </label>
          <button class="exec-engrenagem" id="execPrefs" title="Configurações da execução" aria-label="Configurações da execução">⚙ ▾</button>
        </div>

        <div class="exec-secao">
          <button class="exec-secao-titulo" data-secao="quentes">
            <span class="exec-raio">⚡</span> LEADS AGUARDANDO A PRIMEIRA LIGAÇÃO (${quentes.data.length})
            <span class="exec-caret">${prefs.abertos.quentes ? "▾" : "▸"}</span>
            <span class="dica-icone" title="Leads em prospecção que ainda não receberam nenhuma ligação. Os mais antigos vêm primeiro.">?</span>
          </button>
          ${prefs.abertos.quentes ? (quentes.data.length ? `
            <div class="exec-quentes">
              <div class="exec-quentes-acoes">
                <label class="text-size-small"><input type="checkbox" id="hotTodos"> Selecionar todos</label>
                <button class="btn btn-default btn-xs" id="hotTransferir" disabled>Transferir selecionados</button>
              </div>
              ${table(["", "Lead", "Empresa", "Telefone", "Esperando há", ""],
                quentes.data.map((l) => ({ cells: [
                  `<input type="checkbox" class="hot-check" value="${l.id}" aria-label="Selecionar ${h(l.name)}">`,
                  `<a data-lead="${l.id}"><strong>${h(l.name)}</strong></a>`, h(l.company || "—"), h(l.phone || "—"),
                  l.horasEsperando >= 48 ? `<span class="pill red">${Math.round(l.horasEsperando / 24)} dias</span>`
                    : l.horasEsperando >= 24 ? `<span class="pill amber">1 dia</span>`
                    : l.horasEsperando >= 1 ? `<span class="pill">${Math.round(l.horasEsperando)}h</span>`
                    : `<span class="pill green">${Math.max(1, Math.round((l.horasEsperando || 0) * 60))} min</span>`,
                  `<button class="btn btn-default btn-xs" data-lead="${l.id}">Abrir</button>`,
                ] })), { scroll: true })}
            </div>`
            : `<p class="exec-nenhum">Nenhum lead por aqui. Você pode personalizar quais leads aparecem aqui clicando no menu de configuração no canto superior direito deste painel.</p>`) : ""}
        </div>

        <div class="exec-secao">
          <div class="exec-secao-linha">
            <button class="exec-secao-titulo" data-secao="atividades">
              <span>☰</span> ATIVIDADES (${visiveis.length} DE ${res.meta.total})
              <span class="exec-caret">${prefs.abertos.atividades ? "▾" : "▸"}</span>
            </button>
            ${filtrando ? `<a class="exec-limpar" id="limparFiltros">Limpar filtros</a>` : ""}
          </div>
          ${prefs.abertos.atividades ? `
            <div class="exec-filtros" id="execFiltros">
              ${sel("fStatus", "Status", [["late", "Atrasadas"], ["today", "Para hoje"], ["ontime", "No prazo"]], f.status)}
              ${sel("fTipo", "Atividade", Object.entries(TIPO_NOME), f.type)}
              ${sel("fCad", "Cadência", (state.cadences || []).map((c) => [c.id, c.name]), f.cadence_id)}
              ${sel("fPasso", "Passo", [["extra", "Atividade extra"], ...dias.map((d) => [d, `Dia ${d}`])], f.passo)}
              ${sel("fBase", "Lista de importação", (bases || []).map((b) => [b.id, b.name]), f.lead_base_id)}
              ${nivelPeloMenos("gestor") ? sel("fSdr", "Responsável", (state.users || []).map((u) => [u.id, u.name]), f.sdr_id) : ""}
              <div class="exec-busca"><span>🔍</span><input id="fBusca" placeholder="Nome, email ou telefone" value="${h(f.q || "")}"></div>
            </div>
            ${visiveis.length ? `<div class="table-responsive"><table class="exec-tabela">
              <thead><tr><th>Atividade</th><th>Cadência</th><th>Lead</th><th></th></tr></thead>
              <tbody>
                ${extras.length ? `<tr class="exec-grupo"><td colspan="4">Atividades Extras <span>(${extras.length})</span></td></tr>${extras.map(linha).join("")}` : ""}
                ${daCadencia.length ? `<tr class="exec-grupo"><td colspan="4">Atividades das Cadências <span>(${daCadencia.length})</span></td></tr>${daCadencia.map(linha).join("")}` : ""}
              </tbody></table></div>` : vazio}` : ""}
        </div>
      </div>`;

    ligarExecucaoPagina(visiveis, prefs);
  },
};

function ligarExecucaoPagina(visiveis, prefs) {
  const setFiltro = (k, v) => { state.queueFilter = { ...(state.queueFilter || {}), [k]: v }; go("execucao"); };
  document.getElementById("btnIniciarNovos").onclick = () => openIniciarNovosLeads();
  document.getElementById("chkRapido").onchange = (e) => {
    salvarExecPrefs({ ...execPrefs(), rapido: e.target.checked });
    toast(e.target.checked ? "Modo Execução rápida ligado." : "Modo Execução rápida desligado.");
  };
  document.getElementById("execPrefs").onclick = () => abrirPrefsExecucao();
  view.querySelectorAll("[data-secao]").forEach((b) => {
    b.onclick = (e) => {
      if (e.target.closest(".dica-icone")) return;
      const p = execPrefs();
      p.abertos = { ...p.abertos, [b.dataset.secao]: !p.abertos[b.dataset.secao] };
      salvarExecPrefs(p);
      go("execucao");
    };
  });
  const limpar = document.getElementById("limparFiltros");
  if (limpar) limpar.onclick = () => { state.queueFilter = {}; go("execucao"); };
  [["fStatus", "status"], ["fTipo", "type"], ["fCad", "cadence_id"], ["fPasso", "passo"], ["fBase", "lead_base_id"], ["fSdr", "sdr_id"]]
    .forEach(([id, k]) => { const el = document.getElementById(id); if (el) el.onchange = () => setFiltro(k, el.value); });
  const busca = document.getElementById("fBusca");
  if (busca) {
    let t;
    busca.oninput = () => { clearTimeout(t); t = setTimeout(() => setFiltro("q", busca.value), 350); };
  }

  // Leads aguardando a primeira ligação: seleção em massa para redistribuir.
  const hotBtn = document.getElementById("hotTransferir");
  if (hotBtn) {
    const marcados = () => [...view.querySelectorAll(".hot-check:checked")].map((c) => Number(c.value));
    const sinc = () => {
      const n = marcados().length;
      hotBtn.disabled = !n;
      hotBtn.textContent = n ? `Transferir ${n} selecionado(s)` : "Transferir selecionados";
    };
    view.querySelectorAll(".hot-check").forEach((c) => { c.onchange = sinc; });
    document.getElementById("hotTodos").onchange = (e) => {
      view.querySelectorAll(".hot-check").forEach((c) => { c.checked = e.target.checked; });
      sinc();
    };
    hotBtn.onclick = () => {
      const ids = marcados();
      const m = modal({
        title: `Transferir ${ids.length} lead(s)`,
        body: `<div class="field"><label for="hotSdr">Novo responsável</label>
          <select class="form-control" id="hotSdr">${options((state.users || []).filter((u) => u.active !== false), "", { blank: "—" })}</select></div>`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button><button class="btn btn-main btn-sm" data-ok>Transferir</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = m.close;
      m.root.querySelector("[data-ok]").onclick = async () => {
        const sdrId = Number(m.root.querySelector("#hotSdr").value);
        if (!sdrId) return toast("Escolha o responsável.", "err");
        try {
          await api("/api/flow/leads/bulk", { method: "POST", body: { leadIds: ids, action: "transfer", sdrId } });
          m.close(); toast("Leads transferidos.", "ok"); go("execucao");
        } catch (e) { toast(e.message, "err"); }
      };
    };
  }

  const achar = (id) => visiveis.find((a) => String(a.id) === String(id));
  view.querySelectorAll("[data-exec]").forEach((b) => {
    b.onclick = () => {
      const i = visiveis.findIndex((a) => String(a.id) === b.dataset.exec);
      abrirExecucaoTela(visiveis, i, { rapido: execPrefs().rapido });
    };
  });
  view.querySelectorAll("[data-mais]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const menu = document.getElementById(`em-${b.dataset.mais}`);
      view.querySelectorAll(".exec-menu").forEach((m) => { if (m !== menu) m.hidden = true; });
      menu.hidden = !menu.hidden;
    };
  });
  document.addEventListener("click", () => view.querySelectorAll(".exec-menu").forEach((m) => { m.hidden = true; }), { once: true });
  view.querySelectorAll("[data-m-pular]").forEach((a) => {
    a.onclick = async () => {
      try {
        await api(`/api/flow/execution/activities/${a.dataset.mPular}/execute`, { method: "POST", body: { skip: true } });
        toast("Atividade pulada."); go("execucao");
      } catch (e) { toast(e.message, "err"); }
    };
  });
  view.querySelectorAll("[data-m-adiar]").forEach((a) => { a.onclick = () => adiarAtividade(achar(a.dataset.mAdiar)); });
  view.querySelectorAll("[data-m-extra]").forEach((a) => {
    a.onclick = () => openAtividadeExtra(achar(a.dataset.mExtra).lead, () => go("execucao"));
  });
  view.querySelectorAll("[data-m-ganho]").forEach((a) => { a.onclick = () => openWonFlow(Number(a.dataset.mGanho), () => go("execucao")); });
  view.querySelectorAll("[data-m-perdido]").forEach((a) => { a.onclick = () => openLostModal(Number(a.dataset.mPerdido), () => go("execucao")); });
  view.querySelectorAll("[data-m-retomar]").forEach((a) => {
    a.onclick = async () => {
      try {
        const r = await api(`/api/flow/execution/leads/${a.dataset.mRetomar}/resume`, { method: "POST", body: {} });
        toast(`${r.resumed} atividade(s) retomada(s).`, "ok"); go("execucao");
      } catch (e) { toast(e.message, "err"); }
    };
  });
  view.querySelectorAll("[data-m-abrir]").forEach((a) => { a.onclick = () => go(`lead/${a.dataset.mAbrir}`); });
  view.querySelectorAll("[data-lead]").forEach((a) => { a.onclick = () => openLeadModal(Number(a.dataset.lead)); });
}

function abrirPrefsExecucao() {
  const p = execPrefs();
  const linha = (id, rotulo, ligado, ajuda) => `
    <div class="field"><label><input type="checkbox" id="${id}"${ligado ? " checked" : ""}> ${rotulo}</label>
      <div class="text-muted text-size-small" style="margin-left:22px">${ajuda}</div></div>`;
  const m = modal({
    title: "Configurações da execução",
    body: `
      ${linha("pRapido", "Modo Execução rápida", p.rapido,
              "Ao concluir uma atividade, a próxima já abre. Se o lead não atende, você segue sem voltar para a lista.")}
      ${linha("pQuentes", "Mostrar leads aguardando a primeira ligação", p.quentes,
              "Desligado, a tela carrega mais rápido e fica só com as atividades.")}
      <p class="text-muted text-size-small">As configurações ficam só neste navegador.</p>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button><button class="btn btn-main btn-sm" data-ok>Salvar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = () => {
    salvarExecPrefs({ ...p, rapido: m.root.querySelector("#pRapido").checked, quentes: m.root.querySelector("#pQuentes").checked });
    m.close(); go("execucao");
  };
}

/** Reagenda a atividade — o servidor encaixa na próxima janela útil. */
function adiarAtividade(act, depois) {
  if (!act) return;
  const amanha = new Date(Date.now() + 864e5);
  const m = modal({
    title: `Adiar atividade de ${act.lead.name}`,
    body: `<div class="field"><label for="adQuando">Nova data e hora</label>
        <input class="form-control" type="datetime-local" id="adQuando"
               value="${amanha.toISOString().slice(0, 11)}${String(act.lead.bestHour || 9).padStart(2, "0")}:00"></div>
      <span class="text-muted text-size-small">Fora do expediente, o servidor empurra para a próxima abertura.</span>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button><button class="btn btn-main btn-sm" data-ok>Adiar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async () => {
    const v = m.root.querySelector("#adQuando").value;
    if (!v) return toast("Escolha a data.", "err");
    try {
      const r = await api(`/api/flow/execution/activities/${act.id}/reschedule`,
        { method: "POST", body: { scheduledAt: new Date(v).toISOString() } });
      m.close();
      toast(r.adjusted ? `Ajustado para a próxima janela útil: ${r.scheduledLocal.replace("T", " ")}.` : "Atividade adiada.", "ok");
      (depois || (() => go("execucao")))();
    } catch (e) { toast(e.message, "err"); }
  };
}

/* ── execução em tela dividida ─────────────────────────────────────── */
/** Compatível com quem já chamava o modal antigo (página do lead). */
function openExecuteModal(act, fila = null) {
  if (!act) return;
  abrirExecucaoTela([act], 0, { rapido: false, aoFechar: fila && fila.proximo });
}

const Exec = { itens: [], i: 0, rapido: false, feitas: new Set(), raiz: null, lead: null, aoFechar: null };

function abrirExecucaoTela(itens, i, { rapido = false, aoFechar = null } = {}) {
  if (!itens.length || i < 0) return;
  fecharExecucaoTela(true);
  Object.assign(Exec, { itens, i, rapido, feitas: new Set(), aoFechar, lead: null });
  const raiz = document.createElement("div");
  raiz.className = "exec-tela";
  raiz.id = "execTela";
  raiz.innerHTML = `
    <aside class="exec-lateral" id="execLateral"></aside>
    <div class="exec-palco">
      <div class="exec-nav">
        <button type="button" data-nav="-1" aria-label="Atividade anterior">‹</button>
        <span id="execNavTxt"></span>
        <button type="button" data-nav="1" aria-label="Próxima atividade">›</button>
        <span class="exec-nav-mais">
          <button type="button" id="execNavMais" aria-label="Mais ações">⋮</button>
          <div class="exec-menu" id="execNavMenu" hidden>
            <a data-t-pular>Pular atividade</a><a data-t-adiar>Adiar</a>
            <a data-t-abrir>Abrir lead em nova guia</a><a data-t-sair>Sair da execução</a>
          </div>
        </span>
      </div>
      <div class="exec-centro" id="execCentro"></div>
    </div>`;
  document.body.appendChild(raiz);
  document.body.classList.add("exec-aberta");
  Exec.raiz = raiz;
  raiz.querySelectorAll("[data-nav]").forEach((b) => { b.onclick = () => irExec(Exec.i + Number(b.dataset.nav)); });
  const menu = raiz.querySelector("#execNavMenu");
  raiz.querySelector("#execNavMais").onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  raiz.addEventListener("click", (e) => { if (!e.target.closest(".exec-nav-mais")) menu.hidden = true; });
  raiz.querySelector("[data-t-pular]").onclick = async () => {
    const a = Exec.itens[Exec.i];
    try {
      await api(`/api/flow/execution/activities/${a.id}/execute`, { method: "POST", body: { skip: true } });
      toast("Atividade pulada."); concluirExec(a, false);
    } catch (e) { toast(e.message, "err"); }
  };
  raiz.querySelector("[data-t-adiar]").onclick = () => {
    const a = Exec.itens[Exec.i];
    adiarAtividade(a, () => { Exec.feitas.add(a.id); proximaOuSai(); });
  };
  raiz.querySelector("[data-t-abrir]").onclick = () => window.open(`#lead/${Exec.itens[Exec.i].lead.id}`, "_blank");
  raiz.querySelector("[data-t-sair]").onclick = () => fecharExecucaoTela();
  Exec._tecla = (e) => {
    if (e.key === "Escape" && !document.querySelector("#modalRoot .modal-card") && !document.getElementById("acadTour")) fecharExecucaoTela();
  };
  document.addEventListener("keydown", Exec._tecla);
  desenharExec();
}

function fecharExecucaoTela(silencioso) {
  if (Exec._timer) clearInterval(Exec._timer);
  if (Exec._tecla) document.removeEventListener("keydown", Exec._tecla);
  if (Exec.raiz) Exec.raiz.remove();
  Exec.raiz = null;
  document.body.classList.remove("exec-aberta");
  if (!silencioso) {
    const cb = Exec.aoFechar;
    Exec.aoFechar = null;
    if (cb) cb(); else if (rota(state.page).nome === "execucao") go("execucao");
  }
}

function irExec(n) {
  const pend = Exec.itens.map((a, k) => k).filter((k) => !Exec.feitas.has(Exec.itens[k].id));
  if (!pend.length) return fecharExecucaoTela();
  if (n < 0 || n >= Exec.itens.length) return;
  if (Exec.feitas.has(Exec.itens[n].id)) {
    // Pula as já feitas na direção pedida.
    const dir = n > Exec.i ? 1 : -1;
    let k = n;
    while (k >= 0 && k < Exec.itens.length && Exec.feitas.has(Exec.itens[k].id)) k += dir;
    if (k < 0 || k >= Exec.itens.length) return;
    n = k;
  }
  Exec.i = n;
  desenharExec();
}

async function desenharExec() {
  if (Exec._timer) clearInterval(Exec._timer);
  const a = Exec.itens[Exec.i];
  const pendentes = Exec.itens.filter((x) => !Exec.feitas.has(x.id));
  const pos = pendentes.findIndex((x) => x.id === a.id) + 1;
  Exec.raiz.querySelector("#execNavTxt").textContent = `${pos} de ${pendentes.length}`;
  const centro = Exec.raiz.querySelector("#execCentro");
  centro.innerHTML = `<div class="exec-card"><span class="spinner"></span></div>`;
  desenharLateral(a);
  if (a.type === "CALL") return cartaoLigacao(centro, a);
  if (a.channel === "EMAIL" || a.channel === "WHATSAPP") return cartaoMensagem(centro, a);
  return cartaoSimples(centro, a);
}

/* painel do lead, à esquerda */
async function desenharLateral(a, aba) {
  const lat = Exec.raiz && Exec.raiz.querySelector("#execLateral");
  if (!lat) return;
  aba = aba || Exec.abaLateral || "historico";
  Exec.abaLateral = aba;
  if (!Exec.lead || Exec.lead.id !== a.lead.id) {
    lat.innerHTML = `<div class="exec-lat-topo"><h3>${h(a.lead.name)}</h3><div class="exec-sub">${h(a.lead.company || "")}</div></div><div class="exec-lat-corpo"><span class="spinner"></span></div>`;
    try { Exec.lead = await api(`/api/flow/leads/${a.lead.id}`); }
    catch (e) { lat.querySelector(".exec-lat-corpo").innerHTML = `<p class="text-muted">${h(e.message)}</p>`; return; }
    if (!Exec.raiz || Exec.itens[Exec.i].lead.id !== a.lead.id) return;
  }
  const l = Exec.lead;
  const c = l.contadores || {};
  const anteriores = Math.max(0, (l.prospeccoes || []).length - 1);
  const atividades = (l.timeline || []).filter((x) => x.kind !== "CALL" && x.kind !== "DELIVERY");
  const feitas = atividades.filter((x) => x.status === "DONE" || x.status === "SKIPPED");
  const ocultar = !!Exec.ocultarFeitas;
  const abas = [["dados", "👤", "Dados"], ["historico", "⟲", "Histórico"], ["anotacoes", "✎", "Anotações"], ["proximas", "≡", "Próximas atividades"]];
  let corpo = "";
  if (aba === "dados") {
    const cf = l.customFields || {};
    const camposP = (state.leadFields || []).filter((f) => (cf[f.identifier] || "").trim());
    corpo = `
      <div class="exec-lat-sec">GERAL</div>
      ${[["Primeiro nome", l.firstName], ["Nome completo", l.name], ["Empresa", l.company], ["Cargo", l.position], ["E-mail", l.email]]
        .map(([r, v]) => `<div class="exec-lat-campo"><label>${r}</label><div>${h(v || "—")}</div></div>`).join("")}
      <div class="exec-lat-sec">TELEFONE(S)</div>
      <div class="exec-lat-campo"><div>${l.phone ? h(l.phone) : `<span class="text-muted">Nenhum telefone informado</span>`}</div></div>
      <div class="exec-lat-sec">CAMPOS PERSONALIZADOS</div>
      ${camposP.length ? camposP.map((f) => `<div class="exec-lat-campo"><label>${h(f.name)}</label><div>${h(cf[f.identifier])}</div></div>`).join("")
        : `<div class="exec-lat-campo"><span class="text-muted">Nenhum campo informado</span></div>`}
      <div class="exec-lat-sec">SOCIAL</div>
      <div class="exec-lat-campo">${l.linkedIn ? `<a href="${h(l.linkedIn)}" target="_blank" rel="noopener">LinkedIn</a>` : `<span class="text-muted">Nenhuma rede social informada</span>`}</div>
      <button class="exec-lapis" id="latEditar" title="Editar lead" aria-label="Editar lead">✎</button>`;
  } else if (aba === "anotacoes") {
    corpo = `<div class="exec-lat-sec">ANOTAÇÕES DO LEAD</div>
      <textarea class="form-control" id="latNotas" rows="10">${h(l.annotations || "")}</textarea>
      <button class="btn btn-main btn-xs mt-10" id="latSalvarNotas">Salvar anotações</button>`;
  } else if (aba === "proximas") {
    const prox = atividades.filter((x) => x.status === "PENDING");
    corpo = prox.length ? prox.map((x) => `<div class="exec-hist"><span class="exec-hist-ic">${TIPO_ICONE_EXEC[x.type] || "•"}</span>
        <div><b>${h((x.activity && x.activity.name) || TIPO_NOME[x.type] || x.type)}</b><div class="exec-sub">${fmtDateTime(x.scheduledAt)}${x.late ? " · atrasada" : ""}</div></div></div>`).join("")
      : `<p class="text-muted">Nenhuma atividade futura.</p>`;
  } else {
    const lista = ocultar ? atividades.filter((x) => x.status === "PENDING") : atividades;
    corpo = `<label class="exec-ocultar"><input type="checkbox" id="latOcultar"${ocultar ? " checked" : ""}> Ocultar atividades completadas (${feitas.length})</label>
      ${lista.slice().reverse().map((x) => `<div class="exec-hist${x.status === "PENDING" ? " pendente" : ""}">
        <span class="exec-hist-ic">${TIPO_ICONE_EXEC[x.type] || "•"}</span>
        <div class="exec-hist-txt">
          <div class="exec-hist-cab"><b>${h((x.activity && x.activity.name) || TIPO_NOME[x.type] || x.type)}</b>
            <span class="exec-sub">${fmtDateTime(x.doneAt || x.scheduledAt).slice(0, 5)}${x.status === "DONE" ? " ✓" : ""}</span></div>
          ${x.status === "PENDING" ? `<span class="exec-agora">${x.id === a.id ? "AGORA" : "PENDENTE"}</span>`
            : x.notes ? `<div class="exec-nota">${h(x.notes)}</div>` : `<div class="exec-sub">Nenhuma anotação</div>`}
        </div></div>`).join("") || `<p class="text-muted">Nenhuma atividade.</p>`}`;
  }
  lat.innerHTML = `
    <div class="exec-lat-topo">
      <div class="exec-lat-nome"><span class="exec-av grande">${h((l.name || "?").charAt(0).toUpperCase())}</span>
        <div><h3>${h(l.name)}</h3><div class="exec-sub">${h(l.company || "")}</div></div></div>
      ${anteriores ? `<span class="exec-anteriores">${anteriores} PROSPEC${anteriores > 1 ? "ÇÕES" : "ÇÃO"} ANTERIOR${anteriores > 1 ? "ES" : ""}</span>` : ""}
      <div class="exec-sub">⚑ ${h(l.cadence ? l.cadence.name : "Sem cadência")}</div>
      <div class="exec-sub">☰ ${c.concluidas || 0} de ${(c.concluidas || 0) + (c.pendentes || 0)} atividades completadas</div>
    </div>
    <div class="exec-lat-abas">${abas.map(([k, ic, t]) => `<button type="button" class="${k === aba ? "ativa" : ""}" data-lataba="${k}" title="${t}" aria-label="${t}">${ic}</button>`).join("")}</div>
    <div class="exec-lat-corpo">${corpo}</div>`;
  lat.querySelectorAll("[data-lataba]").forEach((b) => { b.onclick = () => desenharLateral(a, b.dataset.lataba); });
  const oc = lat.querySelector("#latOcultar");
  if (oc) oc.onchange = () => { Exec.ocultarFeitas = oc.checked; desenharLateral(a, "historico"); };
  const ed = lat.querySelector("#latEditar");
  if (ed) ed.onclick = () => openLeadForm(l);
  const sn = lat.querySelector("#latSalvarNotas");
  if (sn) sn.onclick = async () => {
    try {
      await api(`/api/flow/leads/${l.id}`, { method: "PATCH", body: { annotations: lat.querySelector("#latNotas").value } });
      Exec.lead = null; toast("Anotações salvas.", "ok"); desenharLateral(a, "anotacoes");
    } catch (e) { toast(e.message, "err"); }
  };
}

const merge = (a, t) => (t || "").replace(/\{\{firstName\}\}/g, (a.lead.name || "").split(" ")[0]).replace(/\{\{company\}\}/g, a.lead.company || "");

function cabecalhoCartao(a, icone, cor) {
  return `<button type="button" class="exec-fechar" data-fechar aria-label="Fechar">×</button>
    <div class="exec-card-ic" style="--cor:${cor}">${icone}</div>
    <h3 class="exec-card-tit">${h((a.activity && a.activity.name) || TIPO_NOME[a.type] || a.type)}</h3>`;
}

/* pesquisa, social (LinkedIn) e reunião */
function cartaoSimples(centro, a) {
  const cores = { SEARCH: "#C0392B", SOCIAL_POINT: "#7e57c2", MEETING: "#1B5480" };
  const instr = merge(a, a.activity && a.activity.instruction);
  centro.innerHTML = `<div class="exec-card">
      ${cabecalhoCartao(a, TIPO_ICONE_EXEC[a.type] || "•", cores[a.type] || "#1B5480")}
      <label class="exec-rot">${h(TIPO_NOME[a.type] || "Instruções")}:</label>
      <div class="exec-instr">${instr ? h(instr) : `<span class="text-muted">Esta atividade não tem instruções.</span>`}</div>
      <label class="exec-rot" for="execNotes">Anotações:</label>
      <textarea class="form-control" id="execNotes" rows="5" placeholder="Anotações"></textarea>
      <div class="exec-card-pe"><button class="exec-feita" id="execFeita">Marcar como feita <span>✓</span></button></div>
    </div>`;
  centro.querySelector("[data-fechar]").onclick = () => fecharExecucaoTela();
  centro.querySelector("#execFeita").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      await api(`/api/flow/execution/activities/${a.id}/execute`, { method: "POST", body: { notes: centro.querySelector("#execNotes").value } });
      concluirExec(a);
    } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
  };
}

/* e-mail e WhatsApp: editor com o modelo da etapa */
async function cartaoMensagem(centro, a) {
  let pv;
  try { pv = await api(`/api/envio/atividades/${a.id}/previa`); }
  catch (e) { pv = { canal: a.channel, para: a.lead.email || a.lead.phone, temModelo: false, assunto: "", corpo: "", bloqueio: "", erro: e.message }; }
  if (Exec.itens[Exec.i] !== a) return;
  const email = pv.canal === "EMAIL";
  centro.innerHTML = `<div class="exec-compose">
      <div class="exec-compose-topo"><span id="cpTitulo">${h(pv.assunto || (email ? "Novo e-mail" : "Mensagem de WhatsApp"))}</span>
        <button type="button" class="exec-fechar claro" data-fechar aria-label="Fechar">×</button></div>
      ${pv.bloqueio ? `<div class="alert alert-warning alert-styled-left exec-compose-alerta">${h(pv.bloqueio)}</div>` : ""}
      ${!pv.temModelo ? `<div class="alert alert-info alert-styled-left exec-compose-alerta">Este passo não tem modelo de mensagem. Escreva o texto abaixo ou marque a atividade como feita.</div>` : ""}
      <div class="exec-compose-linha"><label for="cpPara">Para:</label><input id="cpPara" value="${h(pv.para || "")}">${email ? `<span class="exec-cc">Cc Cco</span>` : ""}</div>
      ${email ? `<div class="exec-compose-linha"><label for="cpAssunto">Assunto:</label><input id="cpAssunto" value="${h(pv.assunto || "")}"></div>` : ""}
      <textarea id="cpCorpo" class="exec-compose-corpo" rows="12">${h(pv.corpo || "")}</textarea>
      <div class="exec-compose-pe">
        <label class="text-size-small"><input type="checkbox" id="cpFora"> Enviar fora da janela de 9h–18h</label>
        <span class="spacer"></span>
        ${!pv.temModelo ? `<button class="btn btn-default btn-sm" id="cpFeita">Marcar como feita</button>` : ""}
        <button class="btn btn-main btn-sm" id="cpEnviar"${pv.temModelo ? "" : " disabled"}>➤ Enviar</button>
      </div>
      ${email ? `<p class="exec-compose-nota">O e-mail sai pela caixa integrada. Sem integração, a entrega fica registrada como simulada.</p>` : ""}
    </div>`;
  centro.querySelector("[data-fechar]").onclick = () => fecharExecucaoTela();
  const assunto = centro.querySelector("#cpAssunto");
  if (assunto) assunto.oninput = () => { centro.querySelector("#cpTitulo").textContent = assunto.value || "Novo e-mail"; };
  const feita = centro.querySelector("#cpFeita");
  if (feita) feita.onclick = async () => {
    try {
      await api(`/api/flow/execution/activities/${a.id}/execute`, { method: "POST", body: { notes: centro.querySelector("#cpCorpo").value } });
      concluirExec(a);
    } catch (e) { toast(e.message, "err"); }
  };
  const enviar = centro.querySelector("#cpEnviar");
  const disparar = async (forcar) => {
    enviar.disabled = true;
    enviar.innerHTML = `<span class="spinner"></span> enviando…`;
    try {
      const r = await api(`/api/envio/atividades/${a.id}`, { method: "POST", body: {
        forcar, foraDaJanela: centro.querySelector("#cpFora").checked,
        para: centro.querySelector("#cpPara").value.trim(),
        assunto: assunto ? assunto.value : undefined, corpo: centro.querySelector("#cpCorpo").value,
      } });
      const d = r.delivery;
      if (d.status === "BLOCKED") { toast(d.error, "err"); enviar.disabled = false; enviar.textContent = "➤ Enviar"; return; }
      toast(d.status === "SENT" ? "Mensagem enviada." : "Registrado como simulado: o canal de envio não está ligado.", d.status === "SENT" ? "ok" : "");
      concluirExec(a);
    } catch (e) {
      const faltando = /variáveis sem valor/i.test(e.message);
      toast(e.message, "err");
      enviar.disabled = false;
      enviar.textContent = faltando ? "Enviar mesmo assim" : "➤ Enviar";
      if (faltando) enviar.onclick = () => disparar(true);
    }
  };
  enviar.onclick = () => disparar(false);
}

/* ligação: discar → em chamada → classificar */
function telefonesDoLead(lead) {
  return String(lead.phone || "").split(/[,;/|]+/).map((t) => t.trim()).filter(Boolean);
}
const soDigitos = (t) => String(t || "").replace(/\D/g, "");
function fmtTel(t) {
  const d = soDigitos(t).replace(/^55(?=\d{10,11}$)/, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return t;
}

function cartaoLigacao(centro, a, estado = { fase: "discar", numero: "", notas: "", seg: 0 }) {
  const cfg = state.dialerConfig || {};
  const origens = cfg.callerIdList || (cfg.callerIds || []).map((n) => ({ number: n, label: "" }));
  const tels = telefonesDoLead(a.lead);
  const script = merge(a, a.activity && a.activity.instruction);
  if (!estado.numero) estado.numero = tels[0] ? fmtTel(tels[0]) : "";
  if (Exec._timer) clearInterval(Exec._timer);

  if (estado.fase === "discar") {
    centro.innerHTML = `<div class="exec-discador">
        <button type="button" class="exec-fechar" data-fechar aria-label="Fechar">×</button>
        <div class="exec-bina">Bina inteligente ativa <span class="dica-icone" title="O número de origem é escolhido para parecer local ao lead.">?</span></div>
        <h3>Realizar Ligação</h3>
        <div class="exec-num">
          <span class="exec-bandeira" aria-hidden="true">🇧🇷</span>
          <input id="dNumero" value="${h(estado.numero)}" placeholder="(DDD) + Número" inputmode="tel" list="dTels">
          <datalist id="dTels">${tels.map((t) => `<option value="${h(fmtTel(t))}">`).join("")}</datalist>
        </div>
        <div class="exec-num-erro" id="dErro" hidden></div>
        <div class="exec-teclado">${[["1", ""], ["2", "ABC"], ["3", "DEF"], ["4", "GHI"], ["5", "JKL"], ["6", "MNO"], ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"], ["*", ""], ["0", "+"], ["#", ""]]
          .map(([n, l]) => `<button type="button" data-tecla="${n}"><b>${n}</b><small>${l}</small></button>`).join("")}</div>
        <button class="exec-ligar" id="dLigar">Ligar</button>
        <button class="exec-cancelar" id="dCancelar">Cancelar</button>
        ${script ? `<details class="exec-roteiro" open><summary>Roteiro da ligação</summary><div>${h(script)}</div></details>` : ""}
      </div>`;
    const inp = centro.querySelector("#dNumero");
    centro.querySelector("[data-fechar]").onclick = () => fecharExecucaoTela();
    centro.querySelectorAll("[data-tecla]").forEach((b) => { b.onclick = () => { inp.value += b.dataset.tecla; inp.focus(); }; });
    centro.querySelector("#dCancelar").onclick = () => fecharExecucaoTela();
    centro.querySelector("#dLigar").onclick = () => {
      const d = soDigitos(inp.value).replace(/^55(?=\d{10,11}$)/, "");
      const erro = centro.querySelector("#dErro");
      // O discador não completa com um dígito a menos — melhor dizer antes.
      if (d.length < 10 || d.length > 11) {
        erro.hidden = false;
        erro.textContent = "Número incompleto: informe DDD + número (10 ou 11 dígitos).";
        inp.focus();
        return;
      }
      const tel = document.createElement("a");
      tel.href = `tel:+55${d}`;
      // Entrega ao softphone instalado; sem softphone, nada acontece. No modo
      // treino da Academia não disca de verdade.
      if (!(typeof Treino !== "undefined" && Treino.ativo)) tel.click();
      cartaoLigacao(centro, a, { ...estado, fase: "chamada", numero: fmtTel(d), inicio: Date.now(), seg: 0 });
    };
    return;
  }

  if (estado.fase === "chamada") {
    centro.innerHTML = `<div class="exec-chamada">
        <div class="exec-chamada-esq">
          <div class="exec-origem">Origem: <select id="cOrigem" aria-label="Número de origem">${origens.length
            ? origens.map((n) => `<option value="${h(n.number)}"${n.default ? " selected" : ""}>${h(n.label || "Bina inteligente")} · ${h(n.number)}</option>`).join("")
            : `<option value="">Bina inteligente</option>`}</select></div>
          <div class="exec-sinais">Áudio ◉ · Internet ▂▄▆</div>
          <div class="exec-sub">Chamando telefone destino</div>
          <div class="exec-destino">${h(estado.numero)}</div>
          <div class="exec-tempo" id="cTempo">00:00</div>
          <div class="exec-botoes-chamada">
            <button type="button" class="enc" id="cEncerrar" title="Encerrar ligação" aria-label="Encerrar ligação">✆</button>
            <button type="button" title="Teclado" aria-label="Teclado" disabled>⌗</button>
            <button type="button" id="cMudo" title="Mudo" aria-label="Mudo">🎤</button>
          </div>
          <label class="exec-gravar">Salvar gravação <input type="checkbox" id="cGravar" checked><span class="exec-chave"></span></label>
        </div>
        <div class="exec-chamada-dir">
          <b>Bloco de anotações</b>
          <div class="exec-sub">Você poderá salvar suas anotações ao finalizar a chamada</div>
          <textarea id="cNotas" class="form-control" rows="11" placeholder="Faça anotações que possam auxiliar a sua comunicação com o cliente.">${h(estado.notas || "")}</textarea>
          <a class="exec-relatar" id="cRelatar">Relatar um problema</a>
        </div>
      </div>`;
    const tempo = centro.querySelector("#cTempo");
    const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    Exec._timer = setInterval(() => { estado.seg = Math.round((Date.now() - estado.inicio) / 1000); tempo.textContent = fmt(estado.seg); }, 500);
    const mudo = centro.querySelector("#cMudo");
    mudo.onclick = () => mudo.classList.toggle("ativo");
    centro.querySelector("#cRelatar").onclick = () => toast("Problema registrado. Informe o suporte se persistir.");
    centro.querySelector("#cEncerrar").onclick = () => {
      clearInterval(Exec._timer);
      cartaoLigacao(centro, a, { ...estado, fase: "classificar", notas: centro.querySelector("#cNotas").value,
        origem: centro.querySelector("#cOrigem").value });
    };
    return;
  }

  // classificar
  const OPCOES = [
    ["MEANINGFUL", "Significativa", "↑"], ["NOT_MEANINGFUL", "Não Significativa", "↓"],
    ["BUSY", "Cliente Ocupado", "⊖"], ["NO_CONTACT", "Sem contato", "⊘"],
  ];
  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  centro.innerHTML = `<div class="exec-chamada">
      <div class="exec-chamada-esq">
        <div class="exec-origem">Origem: Bina inteligente</div>
        <div class="exec-tempo fim">${fmt(estado.seg)}</div>
        <div class="exec-finalizada">⊘ Ligação finalizada</div>
        <div class="exec-destino peq">${h(estado.numero)}</div>
      </div>
      <div class="exec-chamada-dir">
        <b>Bloco de anotações</b>
        <div class="exec-sub">Você poderá salvar suas anotações ao finalizar a chamada</div>
        <textarea id="cNotas" class="form-control" rows="6" placeholder="Faça anotações que possam auxiliar a sua comunicação com o cliente.">${h(estado.notas || "")}</textarea>
      </div>
      <div class="exec-classif">
        <div class="exec-classif-topo"><b>Qual foi a importância dessa ligação no seu ciclo de vendas?</b>
          <span class="exec-link-ajuda" title="Significativa: a conversa avançou. Não significativa: falou sem avanço. Cliente ocupado: pediu outro momento. Sem contato: ninguém certo atendeu.">Entenda sobre a classificação da ligação</span></div>
        <div class="exec-classif-botoes">${OPCOES.map(([k, r, ic]) =>
          `<button type="button" class="exec-classe c-${k}" data-classe="${k}"><span>${ic}</span>${r}</button>`).join("")}</div>
        <div class="exec-classif-pe">
          <a class="exec-relatar" id="cRelatar">Relatar um problema</a>
          <span class="spacer"></span>
          <span class="exec-refazer">
            <button class="btn btn-default btn-sm" id="cRefazer">Refazer chamada</button>
            <button class="btn btn-default btn-sm" id="cRefazerMais" aria-label="Mais opções de chamada">▾</button>
            <div class="exec-menu cima" id="cRefazerMenu" hidden>
              <a data-refazer="mesmo">Ligar para o mesmo número</a><a data-refazer="novo">Ligar para novo número</a>
            </div>
          </span>
          <button class="btn btn-main btn-sm" id="cFinalizar" disabled>Finalizar</button>
        </div>
      </div>
    </div>`;
  let classe = "";
  centro.querySelectorAll("[data-classe]").forEach((b) => {
    b.onclick = () => {
      classe = b.dataset.classe;
      centro.querySelectorAll("[data-classe]").forEach((x) => x.classList.toggle("marcada", x === b));
      centro.querySelector("#cFinalizar").disabled = false;
    };
  });
  centro.querySelector("#cRelatar").onclick = () => toast("Problema registrado. Informe o suporte se persistir.");
  const registrar = async (cls) => {
    const body = { leadId: a.lead.id, userId: state.me.id, duration: estado.seg, receiverPhone: estado.numero, originPhone: estado.origem || "" };
    if (cls === "BUSY") Object.assign(body, { status: "BUSY", output: "" });
    else if (cls) Object.assign(body, { status: "CONNECTED", output: cls });
    else Object.assign(body, { status: "NOT_PERFORMED", output: "" });
    return api("/api/dialer/calls", { method: "POST", body });
  };
  const menu = centro.querySelector("#cRefazerMenu");
  centro.querySelector("#cRefazerMais").onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  const refazer = async (novo) => {
    // A tentativa conta como ligação: é o que o extrato e o funil de ligações medem.
    try { await registrar(classe); } catch (e) { return toast(e.message, "err"); }
    const notas = centro.querySelector("#cNotas").value;
    cartaoLigacao(centro, a, { fase: "discar", numero: novo ? "" : estado.numero, notas, seg: 0 });
    if (novo) setTimeout(() => { const i = centro.querySelector("#dNumero"); if (i) { i.value = ""; i.focus(); } }, 0);
  };
  centro.querySelector("#cRefazer").onclick = () => refazer(false);
  menu.querySelectorAll("[data-refazer]").forEach((x) => { x.onclick = () => refazer(x.dataset.refazer === "novo"); });
  centro.querySelector("#cFinalizar").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      await registrar(classe);
      await api(`/api/flow/execution/activities/${a.id}/execute`, { method: "POST", body: { notes: centro.querySelector("#cNotas").value } });
      concluirExec(a);
    } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
  };
}

/* depois de cada atividade */
function concluirExec(a, mostrarBarra = true) {
  Exec.feitas.add(a.id);
  Exec.lead = null; // o histórico mudou
  if (mostrarBarra) barraPosAtividade(a);
  proximaOuSai();
}

function proximaOuSai() {
  const resta = Exec.itens.findIndex((x, k) => k > Exec.i && !Exec.feitas.has(x.id));
  const antes = Exec.itens.findIndex((x) => !Exec.feitas.has(x.id));
  if (Exec.rapido && (resta >= 0 || antes >= 0)) {
    Exec.i = resta >= 0 ? resta : antes;
    return desenharExec();
  }
  if (!Exec.rapido || (resta < 0 && antes < 0)) {
    if (resta < 0 && antes < 0 && Exec.itens.length > 1) toast("Você concluiu as atividades desta lista.", "ok");
    fecharExecucaoTela();
  }
}

function barraPosAtividade(a) {
  let barra = document.getElementById("execBarra");
  if (!barra) {
    barra = document.createElement("div");
    barra.id = "execBarra";
    barra.className = "exec-barra-pos";
    document.body.appendChild(barra);
  }
  barra.innerHTML = `
    <span>Atividade completada: <b>${h(TIPO_NOME[a.type] || a.type)}</b> <a data-b-lead>(${h(a.lead.name)})</a></span>
    <span class="spacer"></span>
    <button class="btn btn-default btn-sm" data-b-extra>＋ Agendar atividade extra</button>
    <button class="btn btn-success btn-sm" data-b-ganho>Ganho</button>
    <button class="btn btn-danger btn-sm" data-b-perdido>Perdido</button>
    <button class="exec-barra-x" data-b-fechar aria-label="Fechar">×</button>`;
  const refresh = () => { if (!Exec.raiz && rota(state.page).nome === "execucao") go("execucao"); };
  barra.querySelector("[data-b-lead]").onclick = () => window.open(`#lead/${a.lead.id}`, "_blank");
  barra.querySelector("[data-b-extra]").onclick = () => openAtividadeExtra(a.lead, () => { barra.remove(); refresh(); });
  barra.querySelector("[data-b-ganho]").onclick = () => openWonFlow(a.lead.id, () => { barra.remove(); pularLeadNaTela(a.lead.id); refresh(); });
  barra.querySelector("[data-b-perdido]").onclick = () => openLostModal(a.lead.id, () => { barra.remove(); pularLeadNaTela(a.lead.id); refresh(); });
  barra.querySelector("[data-b-fechar]").onclick = () => barra.remove();
}

/** Lead fechado (ganho/perdido) não tem mais atividade: some da navegação. */
function pularLeadNaTela(leadId) {
  if (!Exec.raiz) return;
  Exec.itens.forEach((x) => { if (x.lead.id === leadId) Exec.feitas.add(x.id); });
  if (Exec.itens[Exec.i] && Exec.itens[Exec.i].lead.id === leadId) proximaOuSai();
  else desenharExec();
}

/* ── atividade extra ───────────────────────────────────────────────── */
async function openAtividadeExtra(lead, depois) {
  if (!lead) return;
  const biblioteca = await api("/api/flow/activities").then((r) => r.data || r).catch(() => []);
  const amanha = new Date(Date.now() + 864e5);
  const valorPadrao = `${amanha.getFullYear()}-${String(amanha.getMonth() + 1).padStart(2, "0")}-${String(amanha.getDate()).padStart(2, "0")}T09:00`;
  const m = modal({
    title: "Adicionar Atividade Extra",
    body: `
      <div class="exec-form-linha"><label for="aeQuando">* Data e hora:</label>
        <input class="form-control" type="datetime-local" id="aeQuando" value="${valorPadrao}"></div>
      <div class="exec-form-linha"><label for="aeTipo">* Tipo da atividade:</label>
        <select class="form-control" id="aeTipo">${Object.entries(TIPO_NOME).map(([k, v]) => `<option value="${k}"${k === "CALL" ? " selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="exec-form-linha"><label for="aeModelo">Utilizar instruções de uma atividade <span class="dica-icone" title="Copia o roteiro de uma atividade da biblioteca.">?</span></label>
        <select class="form-control" id="aeModelo"><option value="">Não utilizar</option>${(biblioteca || []).map((x) => `<option value="${x.id}" data-tipo="${h(x.type)}">${h(x.name)}</option>`).join("")}</select></div>
      <div class="exec-form-linha"><label for="aeNotas">Anotações:</label>
        <textarea class="form-control" id="aeNotas" rows="4" placeholder="Adicionar anotação na atividade"></textarea></div>
      <p class="text-muted text-size-small">A atividade entra no topo da sua fila na data escolhida: em azul no prazo, em vermelho se atrasar.</p>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button><button class="btn btn-success btn-sm" data-ok>✓ Agendar</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const modelo = m.root.querySelector("#aeModelo");
  modelo.onchange = () => {
    const opt = modelo.selectedOptions[0];
    if (opt && opt.dataset.tipo) m.root.querySelector("#aeTipo").value = opt.dataset.tipo;
  };
  m.root.querySelector("[data-ok]").onclick = async (e) => {
    const v = m.root.querySelector("#aeQuando").value;
    if (!v) return toast("Escolha a data e a hora.", "err");
    e.currentTarget.disabled = true;
    try {
      await api(`/api/flow/leads/${lead.id}/activities`, { method: "POST", body: {
        type: m.root.querySelector("#aeTipo").value, scheduledAt: new Date(v).toISOString(),
        activityId: Number(modelo.value) || null, notes: m.root.querySelector("#aeNotas").value } });
      m.close(); toast("Atividade extra agendada.", "ok"); depois && depois();
    } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
  };
}

/* ── ganho: campos obrigatórios, depois o resumo ───────────────────── */
async function openWonFlow(leadId, depois) {
  let l;
  try { l = await api(`/api/flow/leads/${leadId}`); } catch (e) { return toast(e.message, "err"); }
  const obrigatorios = (state.leadFields || []).filter((f) => f.wonMandatory);
  if (obrigatorios.length) {
    const cf = l.customFields || {};
    const campo = (f) => f.options && f.options.length
      ? `<select class="form-control" data-cf="${h(f.identifier)}"><option value="">Procurar…</option>${f.options.map((o) => `<option${cf[f.identifier] === o ? " selected" : ""}>${h(o)}</option>`).join("")}</select>`
      : f.identifier && /bdr|respons/i.test(f.name) && (state.users || []).length
        ? `<select class="form-control" data-cf="${h(f.identifier)}"><option value="">Procurar…</option>${state.users.map((u) => `<option${cf[f.identifier] === u.name ? " selected" : ""}>${h(u.name)}</option>`).join("")}</select>`
        : `<input class="form-control" data-cf="${h(f.identifier)}" value="${h(cf[f.identifier] || "")}">`;
    const ok = await new Promise((resolve) => {
      const m = modal({
        title: "Campos obrigatórios",
        body: `<p class="text-muted">É necessário preencher todos os campos para poder dar ganho no lead.</p>
          <div class="exec-lat-sec">CAMPOS PERSONALIZADOS</div>
          ${obrigatorios.map((f) => `<div class="field"><label>👤 ${h(f.name)}:</label>${campo(f)}</div>`).join("")}`,
        footer: `<button class="btn btn-default btn-sm" data-cancel>Cancelar</button><button class="btn btn-success btn-sm" data-ok>Salvar</button>`,
      });
      m.root.querySelector("[data-cancel]").onclick = () => { m.close(); resolve(false); };
      m.root.querySelector("[data-close]").onclick = () => { m.close(); resolve(false); };
      m.root.querySelector("[data-ok]").onclick = async (e) => {
        const valores = Object.fromEntries([...m.root.querySelectorAll("[data-cf]")].map((el) => [el.dataset.cf, el.value.trim()]));
        const vazio = obrigatorios.find((f) => !valores[f.identifier]);
        if (vazio) return toast(`Preencha "${vazio.name}".`, "err");
        e.currentTarget.disabled = true;
        try {
          await api(`/api/flow/leads/${leadId}`, { method: "PATCH", body: { customFields: { ...(l.customFields || {}), ...valores } } });
          m.close(); resolve(true);
        } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
      };
    });
    if (!ok) return;
  }
  const c = l.contadores || {};
  const run = (l.prospeccoes || []).filter((p) => !p.fim).pop() || (l.prospeccoes || []).slice(-1)[0];
  const inicio = run && run.inicio ? new Date(run.inicio) : new Date(l.createdAt || Date.now());
  const dias = Math.max(1, Math.ceil((Date.now() - inicio.getTime()) / 864e5));
  const m = modal({
    title: `Marcar como ganho (${l.name})`,
    wide: true,
    body: `<div class="exec-ganho-num">
        <div><b>☰ ${(c.concluidas || 0) + (c.pendentes || 0)}</b><span>atividades planejadas</span></div>
        <div class="ok"><b>✓ ${c.concluidas || 0}</b><span>atividades completadas</span></div>
        <div><b>▦ ${dias}</b><span>dia${dias > 1 ? "s" : ""} em prospecção</span></div>
      </div>
      <div class="exec-lat-sec">ANOTAÇÕES</div>
      <textarea class="form-control" id="gNotas" rows="7" placeholder="Resumo da reunião marcada. Ex.: BANT — orçamento, quem decide, necessidade, prazo."></textarea>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Fechar</button><button class="btn btn-success btn-sm" data-ok>Marcar como ganho</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  m.root.querySelector("[data-ok]").onclick = async (e) => {
    const nota = m.root.querySelector("#gNotas").value.trim();
    e.currentTarget.disabled = true;
    try {
      // As anotações do ganho se somam às do lead em vez de apagá-las.
      const body = { outcome: "WON" };
      if (nota) body.annotations = [l.annotations, `[Ganho ${new Date().toLocaleDateString("pt-BR")}] ${nota}`].filter(Boolean).join("\n\n");
      await api(`/api/flow/execution/leads/${leadId}/outcome`, { method: "POST", body });
      m.close(); toast("Lead marcado como ganho.", "ok"); depois && depois();
    } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
  };
}

/* ── perdido: motivo, anotação e nova prospecção ───────────────────── */
async function openLostModal(leadId, depois) {
  const l = await api(`/api/flow/leads/${leadId}`).catch(() => ({ id: leadId, name: "", annotations: "" }));
  const amanha = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  const m = modal({
    title: `Marcar como perdido${l.name ? ` (${l.name})` : ""}`,
    wide: true,
    body: `
      <div class="exec-lat-sec">MOTIVO DE PERDA</div>
      <select class="form-control" id="lostReason">${options(state.lostReasons, "", { blank: "Selecione o motivo da perda" })}</select>
      <div class="exec-lat-sec">ANOTAÇÕES</div>
      <textarea class="form-control" id="lostNotes" rows="5"></textarea>
      <div class="exec-nova">
        <label class="exec-nova-chave"><input type="checkbox" id="lostNova"><span class="exec-chave"></span> AGENDAR NOVA PROSPECÇÃO</label>
        <span class="exec-sub" id="lostNovaEstado">(Desativado)</span>
      </div>
      <div class="exec-nova-campos" id="lostNovaCampos" hidden>
        <div class="field-row">
          <div class="field"><label for="lostData">Data de início</label><input type="date" class="form-control" id="lostData" min="${amanha}"></div>
          <div class="field"><label for="lostCad">Cadência</label><select class="form-control" id="lostCad">${options(state.cadences, l.cadence && l.cadence.id, { blank: "Procurar por cadência" })}</select></div>
        </div>
        <p class="exec-sub">ⓘ Uma nova prospecção será iniciada na data e cadência especificadas e você permanecerá como responsável pelo lead.</p>
      </div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Fechar</button><button class="btn btn-danger btn-sm" data-ok>Marcar como perdido</button>`,
  });
  const q = (s) => m.root.querySelector(s);
  q("[data-cancel]").onclick = m.close;
  const nova = q("#lostNova");
  const sinc = () => {
    q("#lostNovaCampos").hidden = !nova.checked;
    q("#lostNovaEstado").textContent = nova.checked ? "(Ativado)" : "(Desativado)";
  };
  nova.onchange = sinc;
  // "Reaproveitamento" é o motivo que existe para reagendar: liga a chave sozinho.
  q("#lostReason").onchange = () => {
    const nome = (q("#lostReason").selectedOptions[0] || {}).textContent || "";
    if (/reaproveit/i.test(nome) && !/ruim/i.test(nome)) { nova.checked = true; sinc(); }
  };
  q("[data-ok]").onclick = async (e) => {
    const reason = q("#lostReason").value;
    if (!reason) return toast("Escolha o motivo da perda.", "err");
    const body = { outcome: "LOST", lostReasonId: Number(reason) };
    const nota = q("#lostNotes").value.trim();
    if (nota) body.annotations = [l.annotations, `[Perdido ${new Date().toLocaleDateString("pt-BR")}] ${nota}`].filter(Boolean).join("\n\n");
    if (nova.checked) {
      if (!q("#lostData").value || !Number(q("#lostCad").value)) return toast("Informe a data de início e a cadência da nova prospecção.", "err");
      body.reprospect = { date: q("#lostData").value, cadenceId: Number(q("#lostCad").value) };
    }
    e.currentTarget.disabled = true;
    try {
      await api(`/api/flow/execution/leads/${leadId}/outcome`, { method: "POST", body });
      m.close();
      toast(nova.checked ? `Lead perdido. Nova prospecção agendada para ${new Date(body.reprospect.date + "T12:00").toLocaleDateString("pt-BR")}.` : "Lead marcado como perdido.");
      depois && depois();
    } catch (err) { toast(err.message, "err"); e.currentTarget.disabled = false; }
  };
}

/* ── Iniciar novos leads ───────────────────────────────────────────── */
async function openIniciarNovosLeads() {
  let marcadas = null; // null = todas (padrão do servidor)
  let qtd = 1;
  const m = modal({
    title: "Iniciar novos leads",
    wide: true,
    body: `<div id="inlCorpo"><span class="spinner"></span></div>`,
    footer: `<button class="btn btn-default btn-sm" data-cancel>Fechar</button><button class="btn btn-main btn-sm" data-ok disabled>Iniciar leads</button>`,
  });
  m.root.querySelector("[data-cancel]").onclick = m.close;
  const corpo = m.root.querySelector("#inlCorpo");
  const ok = m.root.querySelector("[data-ok]");
  let ultimo = null;
  let seq = 0;

  const carregar = async () => {
    const minha = ++seq;
    const qs = new URLSearchParams({ quantidade: qtd });
    if (marcadas) qs.set("cadence_ids", [...marcadas].join(","));
    let r;
    try { r = await api(`/api/flow/execution/start-preview?${qs}`); }
    catch (e) { corpo.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(e.message)}</div>`; return; }
    if (minha !== seq) return;
    ultimo = r;
    desenhar(r);
  };

  const desenhar = (r) => {
    const cores = { CALL: "var(--ok)", SEARCH: "#8a8a8a", E_MAIL: "#00acc1", SOCIAL_POINT: "#7e57c2", MEETING: "var(--blu-mid)" };
    const max = Math.max(1, ...r.previsao.map((d) => ["CALL", "SEARCH", "E_MAIL", "SOCIAL_POINT", "MEETING"].reduce((s, k) => s + (d[k] || 0), 0)));
    const nomeDia = (iso, i) => i === 0 ? "Hoje" : new Date(iso + "T12:00").toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");
    corpo.innerHTML = `
      ${r.objetivoDiario ? `<div class="inl-preencher">✦ Preencha automaticamente para buscar seu objetivo diário de atividades (${r.objetivoDiario}) hoje.
        <a id="inlPreencher">Preencher</a></div>` : ""}
      <div class="inl-bloco">
        <div><b>Leads a iniciar</b><div class="exec-sub">Após o início, as atividades da cadência do lead serão disponibilizadas para execução</div></div>
        <div class="inl-qtd">
          <span class="inl-play">▶</span>
          <input type="number" id="inlQtd" min="1" max="${Math.max(1, r.totalDisponiveis)}" value="${qtd}"> <span>lead</span>
          <div class="exec-sub">Novas atividades para hoje: <b>${r.novasAtividadesHoje}</b> atividades</div>
        </div>
      </div>
      <details class="inl-cad" ${marcadas ? "open" : ""}>
        <summary><b>Selecione cadências ou listas de importação</b> <span class="text-muted">(opcional)</span></summary>
        <p class="exec-sub">Por padrão os leads são selecionados automaticamente de acordo com as cadências que você participa e suas prioridades.</p>
        ${r.cadencias.length ? `<table class="exec-tabela inl-tab"><thead><tr><th></th><th>Cadência</th><th>Selecionados/Disponíveis</th><th>Atividades para hoje</th></tr></thead>
          <tbody>${r.cadencias.map((c) => `<tr>
            <td><input type="checkbox" data-inlcad="${c.id}"${c.marcada ? " checked" : ""} aria-label="${h(c.name)}"></td>
            <td><span class="inl-prio p-${h(c.priority)}" title="Prioridade ${h(PRIORITY_LABEL[c.priority] || c.priority)}">${PRIORIDADE_SETA[c.priority] || "→"}</span> ${h(c.name)}</td>
            <td>${c.selecionados}/${c.disponiveis}</td><td>${c.atividadesHoje}</td></tr>`).join("")}</tbody></table>
          <p class="exec-sub">* Os leads são selecionados proporcionalmente de acordo com a prioridade da cadência.</p>`
          : `<p class="text-muted">Nenhuma cadência com leads disponíveis para você agora.</p>`}
      </details>
      <div class="inl-prev">
        <b>Previsão de atividades futuras</b>
        <div class="exec-sub">A previsão inclui tanto atividades da cadência quanto extras e é atualizada sempre que houver leads iniciados, finalizados ou alterações na cadência.</div>
        <div class="inl-grafico">${r.previsao.map((d, i) => {
          const tot = ["CALL", "SEARCH", "E_MAIL", "SOCIAL_POINT", "MEETING"].reduce((s, k) => s + (d[k] || 0), 0);
          return `<div class="inl-col" title="${nomeDia(d.dia, i)}: ${tot} atividades">
            <div class="inl-pilha" style="height:${(tot / max) * 100}%">${["SEARCH", "E_MAIL", "SOCIAL_POINT", "MEETING", "CALL"].map((k) => d[k]
              ? `<i style="flex:${d[k]};background:${cores[k]}" title="${TIPO_NOME[k]}: ${d[k]}"></i>` : "").join("")}</div>
            <span class="inl-tot">${tot}</span><span class="inl-dia">${nomeDia(d.dia, i)}</span></div>`;
        }).join("")}</div>
        <div class="inl-legenda">${["CALL", "SEARCH", "E_MAIL", "SOCIAL_POINT"].map((k) => `<span><i style="background:${cores[k]}"></i>${TIPO_NOME[k]}</span>`).join("")}</div>
      </div>`;
    ok.disabled = !r.quantidade;
    const inp = corpo.querySelector("#inlQtd");
    let t;
    inp.oninput = () => { clearTimeout(t); t = setTimeout(() => { qtd = Math.max(1, Number(inp.value) || 1); carregar(); }, 300); };
    corpo.querySelectorAll("[data-inlcad]").forEach((c) => {
      c.onchange = () => {
        marcadas = new Set([...corpo.querySelectorAll("[data-inlcad]:checked")].map((x) => Number(x.dataset.inlcad)));
        if (!marcadas.size) { toast("Deixe ao menos uma cadência marcada.", "err"); c.checked = true; marcadas.add(Number(c.dataset.inlcad)); }
        carregar();
      };
    });
    const pre = corpo.querySelector("#inlPreencher");
    if (pre) pre.onclick = async () => {
      // Quantos leads fecham o objetivo de hoje: o que falta dividido pelas
      // atividades que cada lead novo gera hoje.
      const falta = r.objetivoDiario - r.feitasHoje - r.pendentesHoje;
      if (falta <= 0) return toast("Com a fila atual você já alcança o objetivo de hoje.", "ok");
      const um = await api(`/api/flow/execution/start-preview?quantidade=10${marcadas ? `&cadence_ids=${[...marcadas].join(",")}` : ""}`);
      const porLead = um.quantidade ? um.novasAtividadesHoje / um.quantidade : 0;
      if (!porLead) return toast("As cadências disponíveis não geram atividades para hoje.", "err");
      qtd = Math.min(r.totalDisponiveis, Math.ceil(falta / porLead));
      carregar();
    };
  };

  ok.onclick = async () => {
    if (!ultimo || !ultimo.quantidade) return;
    ok.disabled = true;
    ok.innerHTML = `<span class="spinner"></span> iniciando…`;
    try {
      const r = await api("/api/flow/execution/start-leads", { method: "POST", body: {
        quantidade: ultimo.quantidade, cadenceIds: marcadas ? [...marcadas] : [] } });
      m.close();
      toast(`${r.iniciados} lead(s) iniciado(s) · ${r.atividades} atividades agendadas.`, "ok");
      go("execucao");
    } catch (e) { toast(e.message, "err"); ok.disabled = false; ok.textContent = "Iniciar leads"; }
  };
  carregar();
}
