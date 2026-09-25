"use strict";
/* ── Academia BLU ───────────────────────────────────────────────────────
   Três peças, nesta ordem:

   1. Modo treino — enquanto uma missão roda, o `fetch` passa por aqui: a fila
      de Execução vira um lead de treino e toda escrita (concluir atividade,
      marcar ganho, salvar lead) responde "ok" sem tocar no servidor. Quem está
      aprendendo pode clicar em tudo sem medo.
   2. Tour — destaca um elemento, trava o resto da tela e só avança quando a
      pessoa faz o que o passo pede. Clicar fora sacode o balão em vez de
      deixar a pessoa se perder.
   3. Wiki gamificada — capítulos do fluxo do SDR/BDR, quiz por capítulo,
      missões (os tours) e conquistas. O XP é calculado no servidor.

   Depende dos globais do app.js: PAGES, go, api, h, toast, state, view. */

/* ── movimento ─────────────────────────────────────────────────────── */
const ACAD_REDUZIR = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Anima com a Motion quando ela carregou; senão, com a Web Animations API.
 *  Keyframes em forma de propriedade → lista (`{opacity:[0,1]}`), que as duas
 *  entendem; duração em segundos, como na Motion. */
function acadAnimar(el, keyframes, opts = {}) {
  if (!el) return Promise.resolve();
  const o = { duration: 0.35, ease: "easeOut", ...opts };
  if (ACAD_REDUZIR) o.duration = 0.001;
  const M = window.Motion;
  if (M && M.animate) {
    const conf = { duration: o.duration, delay: o.delay || 0 };
    if (o.spring && !ACAD_REDUZIR) { conf.type = "spring"; conf.bounce = o.bounce ?? 0.35; conf.duration = o.duration; }
    else conf.ease = o.ease === "easeOut" ? [0.22, 1, 0.36, 1] : o.ease;
    if (o.repeat) conf.repeat = o.repeat;
    return M.animate(el, keyframes, conf).finished || Promise.resolve();
  }
  const a = el.animate(keyframes, { duration: o.duration * 1000, delay: (o.delay || 0) * 1000,
    easing: "cubic-bezier(.22,1,.36,1)", fill: "forwards", iterations: o.repeat === Infinity ? Infinity : 1 + (o.repeat || 0) });
  return a.finished.catch(() => {});
}

function acadConfete(origem) {
  if (ACAD_REDUZIR) return;
  const r = origem ? origem.getBoundingClientRect() : { left: innerWidth / 2, top: innerHeight / 3, width: 0, height: 0 };
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const cores = ["#1B5E4B", "#E0A53B", "#9A3324", "#3B7EA1", "#7E57C2", "#2F6B4F"];
  for (let i = 0; i < 46; i++) {
    const p = document.createElement("i");
    p.className = "acad-confete";
    p.style.background = cores[i % cores.length];
    p.style.left = `${cx}px`; p.style.top = `${cy}px`;
    document.body.appendChild(p);
    const ang = Math.random() * Math.PI * 2, dist = 90 + Math.random() * 220;
    const dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist - 120;
    acadAnimar(p, {
      transform: ["translate(-50%,-50%) rotate(0deg)", `translate(${dx}px,${dy + 260}px) rotate(${Math.random() * 720}deg)`],
      opacity: [1, 1, 0],
    }, { duration: 1.3 + Math.random() * 0.6, ease: "easeOut" }).then(() => p.remove());
  }
}

/* ── progresso (servidor) ──────────────────────────────────────────── */
const Academia = {
  dados: null,          // resposta de /api/academia/me
  _salvando: null,

  async carregar() {
    try { this.dados = await api("/api/academia/me"); }
    catch { this.dados = null; }
    return this.dados;
  },

  get prog() {
    return (this.dados && this.dados.progresso) || { lidos: [], quizzes: {}, missoes: [], tourOferecido: false };
  },

  async salvar(mudar, { avisarNivel = true } = {}) {
    // Sem o progresso carregado, salvar mandaria uma lista vazia e apagaria o
    // que a pessoa já fez. Carrega antes; se não der, não salva.
    if (!this.dados) await this.carregar();
    if (!this.dados) {
      toast("Não consegui carregar seu progresso da Academia; esta conquista não foi registrada.", "err");
      return 0;
    }
    const antes = this.dados ? this.dados.xp : 0;
    const nivelAntes = this.dados ? this.dados.nivel.nome : "";
    const p = JSON.parse(JSON.stringify(this.prog));
    mudar(p);
    try {
      this.dados = await api("/api/academia/me", { method: "PUT", body: { progresso: p } });
    } catch (e) {
      toast("Não consegui salvar seu progresso: " + e.message, "err");
      return 0;
    }
    const ganho = this.dados.xp - antes;
    if (ganho > 0) acadXp(ganho);
    this.subiuPara = nivelAntes && this.dados.nivel.nome !== nivelAntes ? this.dados.nivel.nome : "";
    if (this.subiuPara && avisarNivel) acadSubiuNivel(this.subiuPara);
    acadAtualizarChip();
    return ganho;
  },

  // Sem o aviso de nível: o modal da missão mostra os dois juntos (um modal
  // substitui o outro, e o de nível sumia na hora).
  concluiuMissao(id) { return this.salvar((p) => { if (!p.missoes.includes(id)) p.missoes.push(id); }, { avisarNivel: false }); },
  leu(cap) { return this.salvar((p) => { if (!p.lidos.includes(cap)) p.lidos.push(cap); }); },
  respondeu(cap, acertos, total) {
    return this.salvar((p) => {
      const atual = p.quizzes[cap];
      // Fica a melhor tentativa: refazer o quiz nunca tira XP de ninguém.
      if (!atual || acertos / total > atual.acertos / atual.total) p.quizzes[cap] = { acertos, total };
    });
  },
};

function acadXp(ganho) {
  const el = document.createElement("div");
  el.className = "acad-xp-voa";
  el.textContent = `+${ganho} XP`;
  document.body.appendChild(el);
  acadAnimar(el, { transform: ["translate(-50%, 30px) scale(.6)", "translate(-50%, -10px) scale(1.15)", "translate(-50%, -60px) scale(1)"],
                   opacity: [0, 1, 0] }, { duration: 1.6 }).then(() => el.remove());
}

function acadSubiuNivel(nome) {
  const m = modal({
    title: "Você subiu de nível",
    body: `<div class="acad-nivel-up">
        <div class="acad-medalha" id="acadMedalha">★</div>
        <p class="acad-nivel-nome">${h(nome)}</p>
        <p class="text-muted">Continue a trilha para chegar ao próximo nível.</p>
      </div>`,
    footer: `<button class="btn btn-main btn-sm" data-ok>Continuar</button>`,
  });
  m.root.querySelector("[data-ok]").onclick = m.close;
  const med = m.root.querySelector("#acadMedalha");
  acadAnimar(med, { transform: ["scale(0) rotate(-40deg)", "scale(1) rotate(0deg)"] }, { spring: true, duration: 0.8, bounce: 0.5 });
  acadConfete(med);
}

function acadAtualizarChip() {
  const chip = document.getElementById("acadChip");
  if (!chip || !Academia.dados) return;
  chip.innerHTML = `<span class="acad-chip-nivel">${h(Academia.dados.nivel.nome)}</span> <b>${Academia.dados.xp}</b> XP`;
}

/* ── modo treino ───────────────────────────────────────────────────── */
const TREINO_LEAD = {
  id: 900001, name: "Mariana Souza", company: "Construtora Horizonte", phone: "(11) 98765-4321",
  email: "mariana@construtorahorizonte.com.br", bestHour: 10, status: "EXECUTING", client: null,
  cadence: { id: 0, name: "Treino · Outbound [BLU]", priority: "HIGH" },
};

function treinoFila() {
  const agora = new Date();
  const base = (id, type, channel, nome, dia, ordem, extra = {}) => ({
    id, type, channel, extra: false, late: false, scheduledAt: agora.toISOString(),
    passo: { dia, ordem }, tentativas: 0, score: 90 - id % 10, lead: TREINO_LEAD,
    activity: { name: nome, instruction: "", emailTemplate: null }, ...extra,
  });
  const itens = [
    base(900001, "SEARCH", "SEARCH", "Pesquisa e validação", 1, 1, { activity: { name: "Pesquisa e validação",
      instruction: "PESQUISA\n- Entenda qual foi a objeção, o produto vendido e se já houve reunião.\n- Entenda o processo comercial e a maturidade do cliente.\nAnote tudo no campo de anotações e releia antes de cada nova ligação." } }),
    base(900002, "E_MAIL", "EMAIL", "E-mail 1 · apresentação", 1, 2, { activity: { name: "E-mail 1 · apresentação", instruction: "" } }),
    base(900003, "CALL", "CALL", "Ligação 1", 1, 3, { activity: { name: "Ligação 1",
      instruction: "ABERTURA\n1. Alegria na voz. Seja simpático com o lead.\n2. Valide o e-mail: pergunte se ele viu o e-mail ou o WhatsApp.\n3. Rapport leve: reconheça a correria do dia a dia antes de entrar no assunto." } }),
  ];
  return itens.filter((a) => !Treino.feitas.has(a.id));
}

const TREINO_EMAIL = {
  canal: "EMAIL", para: TREINO_LEAD.email, temModelo: true, faltando: [], bloqueio: "",
  assunto: "Mariana, sua equipe está trabalhando mesmo?",
  corpo: "Olá, Mariana, tudo bem?\n\nSeja sincera: enquanto você lê este e-mail, você sabe o que a equipe da Construtora Horizonte está fazendo, ou está apenas supondo?\n\nAjudamos empresas a aumentar a produtividade e ter visibilidade real do trabalho das equipes, presenciais, remotas ou híbridas.\n\nPosso te mostrar em 20 minutos esta semana?\n\nAbraço,",
};

function treinoPrevia(q) {
  const a = Math.min(q, 148), b = Math.max(0, q - a);
  const hoje = new Date();
  const uteis = [];
  for (let d = new Date(hoje); uteis.length < 5; d.setDate(d.getDate() + 1)) {
    if (d.getDay() !== 0 && d.getDay() !== 6) uteis.push(d.toISOString().slice(0, 10));
  }
  return {
    quantidade: a + b, novasAtividadesHoje: (a + b) * 3, totalDisponiveis: 3010,
    objetivoDiario: 200, feitasHoje: 43 + Treino.feitas.size, pendentesHoje: treinoFila().length,
    cadencias: [
      { id: 1, name: "Start Xone (Ganhos ZV)", priority: "HIGH", disponiveis: 148, selecionados: a, atividadesHoje: a * 3, marcada: true },
      { id: 2, name: "Start Xone (Ganhos MV)", priority: "MEDIUM", disponiveis: 2862, selecionados: b, atividadesHoje: b * 3, marcada: true },
    ],
    previsao: uteis.map((dia, i) => ({ dia, CALL: i ? 12 + i * 2 + (i === 2 ? a + b : 0) : 5 + a + b,
      SEARCH: i ? 0 : a + b, E_MAIL: i === 1 ? a + b : 1, SOCIAL_POINT: i === 3 ? 2 : 0, MEETING: 0 })),
  };
}

function treinoLeadDetalhe() {
  const fila = treinoFila();
  const nomes = { 900001: ["SEARCH", "Pesquisa e validação"], 900002: ["E_MAIL", "E-mail 1 · apresentação"], 900003: ["CALL", "Ligação 1"] };
  const agora = new Date().toISOString();
  const timeline = Object.keys(nomes).map(Number).map((id) => ({
    id, type: nomes[id][0], status: Treino.feitas.has(id) ? "DONE" : "PENDING", scheduledAt: agora,
    doneAt: Treino.feitas.has(id) ? agora : null, notes: "", late: false, extra: false, activity: { name: nomes[id][1] },
  }));
  const cf = {};
  (state.leadFields || []).filter((f) => f.wonMandatory).forEach((f) => { cf[f.identifier] = ""; });
  return { ...TREINO_LEAD, firstName: "Mariana", position: "Diretora comercial", linkedIn: "", annotations: "",
    customFields: cf, createdAt: agora,
    prospeccoes: [{ id: 1, cadencia: TREINO_LEAD.cadence.name, inicio: agora, fim: null }],
    contadores: { concluidas: 3 - fila.length, pendentes: fila.length, ligacoes: 0 }, timeline };
}

const Treino = {
  ativo: false,
  feitas: new Set(),
  _fetch: null,

  ligar() {
    if (this.ativo) return;
    this.ativo = true;
    this.feitas = new Set();
    this._fetch = window.fetch;
    const original = this._fetch;
    const resposta = (obj) => Promise.resolve(new Response(JSON.stringify(obj),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    window.fetch = (input, init = {}) => {
      const url = typeof input === "string" ? input : input.url;
      const metodo = (init.method || (typeof input === "string" ? "GET" : input.method) || "GET").toUpperCase();
      const caminho = url.replace(location.origin, "");
      if (!caminho.startsWith("/api/") || caminho.startsWith("/api/academia/") || caminho.startsWith("/api/auth/")) {
        return original(input, init);
      }
      if (metodo === "GET") {
        if (caminho.startsWith("/api/flow/execution/queue")) {
          const data = treinoFila();
          return resposta({ data, meta: { total: data.length, late: 0, onTime: data.length, extras: 0 } });
        }
        if (caminho.startsWith("/api/flow/execution/overall")) {
          const feitas = 43 + Treino.feitas.size;
          return resposta({ prospectando: 38, disponiveis: 3010, bateuMeta: false,
            hoje: { meta: 200, feitas, percentual: Math.round(feitas / 2), ignoradas: 0 } });
        }
        if (caminho.startsWith("/api/flow/hot-leads")) return resposta({ data: [] });
        if (caminho.startsWith(`/api/flow/leads/${TREINO_LEAD.id}`)) return resposta(treinoLeadDetalhe());
        if (/\/api\/envio\/atividades\/9000\d\d\/previa/.test(caminho)) return resposta(TREINO_EMAIL);
        if (caminho.startsWith("/api/flow/execution/start-preview")) {
          const q = Number(new URLSearchParams(caminho.split("?")[1] || "").get("quantidade")) || 1;
          return resposta(treinoPrevia(q));
        }
        return original(input, init);
      }
      // Escrita: nada sai daqui. A atividade "feita" some da fila de treino.
      const feita = caminho.match(/\/api\/flow\/execution\/activities\/(\d+)\/execute/)
                 || caminho.match(/\/api\/envio\/atividades\/(\d+)/);
      if (feita) Treino.feitas.add(Number(feita[1]));
      return resposta({ ok: true, id: 900099, resumed: 0, treino: true,
        delivery: { status: "SIMULATED", error: "" } });
    };
    document.body.classList.add("acad-treinando");
    let faixa = document.getElementById("acadFaixa");
    if (!faixa) {
      faixa = document.createElement("div");
      faixa.id = "acadFaixa";
      faixa.className = "acad-faixa";
      faixa.innerHTML = `<b>Modo treino</b> · o lead e a fila são de mentira e nada do que você fizer é salvo.`;
      document.body.appendChild(faixa);
    }
    acadAnimar(faixa, { transform: ["translateY(-100%)", "translateY(0)"] }, { duration: 0.4 });
  },

  desligar() {
    if (!this.ativo) return;
    this.ativo = false;
    window.fetch = this._fetch;
    document.body.classList.remove("acad-treinando");
    const faixa = document.getElementById("acadFaixa");
    if (faixa) acadAnimar(faixa, { transform: ["translateY(0)", "translateY(-100%)"] }, { duration: 0.3 }).then(() => faixa.remove());
  },
};

/* ── tour ──────────────────────────────────────────────────────────── */
/* Um passo:
     page      rota para abrir antes (opcional)
     alvo      seletor ou função que devolve o elemento destacado (sem alvo = balão central)
     abrir     seletor de um .dropdown para manter aberto enquanto o passo dura
     acao      "clique" (padrão com alvo) · "proximo" · "digitar" · "escolher"
     avancaEm  seletor clicado que avança (padrão: o próprio alvo)
     minimo    no "digitar", quantos caracteres liberam o avanço
     valida    função (el) → true quando o passo está cumprido
     titulo, texto, dica */
const Tour = {
  missao: null, i: 0, el: null, raf: 0, limpar: [],

  iniciar(id) {
    const m = MISSOES.find((x) => x.id === id);
    if (!m) return;
    this.sair(true);
    this.missao = m;
    this.i = 0;
    if (m.treino !== false) {
      Treino.ligar();
      // A tela aberta ainda mostra a fila real: redesenha com a de treino.
      if (["execucao", "leads"].includes(rota(state.page).nome)) go(rota(state.page).nome);
    }
    this._montar();
    this._passo();
  },

  _montar() {
    const raiz = document.createElement("div");
    raiz.id = "acadTour";
    raiz.innerHTML = `
      <div class="acad-bloco" data-b="t"></div><div class="acad-bloco" data-b="b"></div>
      <div class="acad-bloco" data-b="l"></div><div class="acad-bloco" data-b="r"></div>
      <div class="acad-anel" hidden></div>
      <div class="acad-balao" role="dialog" aria-live="polite">
        <div class="acad-balao-topo">
          <span class="acad-balao-missao"></span>
          <button type="button" class="acad-sair" title="Sair do tour" aria-label="Sair do tour">×</button>
        </div>
        <div class="acad-pontos"></div>
        <h4 class="acad-balao-titulo"></h4>
        <div class="acad-balao-texto"></div>
        <div class="acad-dica" hidden><span class="acad-dica-rot">Sugestão</span><span class="acad-dica-txt"></span></div>
        <div class="acad-balao-pe">
          <button type="button" class="btn btn-default btn-xs acad-voltar">Voltar</button>
          <span class="acad-espera"></span>
          <button type="button" class="btn btn-main btn-xs acad-prox">Próximo</button>
        </div>
      </div>`;
    document.body.appendChild(raiz);
    this.raiz = raiz;
    this.balao = raiz.querySelector(".acad-balao");
    this.anel = raiz.querySelector(".acad-anel");
    raiz.querySelector(".acad-sair").onclick = () => this.sair();
    raiz.querySelector(".acad-voltar").onclick = () => this._ir(this.i - 1);
    raiz.querySelector(".acad-prox").onclick = () => this._ir(this.i + 1);
    // Clique fora do alvo: a tela está travada. Em vez de ignorar em silêncio,
    // o balão sacode e o anel pulsa, apontando de novo onde clicar.
    raiz.querySelectorAll(".acad-bloco").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        acadAnimar(this.balao, { transform: ["translateX(0)", "translateX(-10px)", "translateX(9px)", "translateX(-6px)", "translateX(0)"] }, { duration: 0.4 });
        if (!this.anel.hidden) acadAnimar(this.anel, { transform: ["scale(1)", "scale(1.12)", "scale(1)"] }, { duration: 0.45 });
      });
    });
    this._tecla = (e) => {
      if (e.key === "Escape") this.sair();
      if (e.key === "Enter" && this._passoAtual() && this._passoAtual().acao === "proximo"
          && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) this._ir(this.i + 1);
    };
    document.addEventListener("keydown", this._tecla);
    acadAnimar(this.balao, { opacity: [0, 1], transform: ["translateY(14px) scale(.96)", "translateY(0) scale(1)"] }, { spring: true, duration: 0.5 });
  },

  _passoAtual() { return this.missao && this.missao.passos[this.i]; },

  _ir(n) {
    if (!this.missao) return;
    this.limpar.forEach((f) => f()); this.limpar = [];
    if (n >= this.missao.passos.length) return this._fim();
    this.i = Math.max(0, n);
    this._passo();
  },

  async _passo() {
    const p = this._passoAtual();
    const b = this.balao;
    // `se`: passo que só vale em certas condições (ex.: o modal de campos
    // obrigatórios, que só existe se a empresa configurou algum).
    if (p.se) {
      await new Promise((r) => setTimeout(r, 500));
      if (this._passoAtual() !== p) return;
      if (!p.se()) return this._ir(this.i + 1);
    }
    document.querySelectorAll(".dropdown.acad-aberto").forEach((d) => d.classList.remove("acad-aberto"));
    if (p.page && rota(state.page).nome !== p.page) go(p.page);
    b.querySelector(".acad-balao-missao").textContent = this.missao.titulo;
    b.querySelector(".acad-pontos").innerHTML = this.missao.passos.map((_, k) =>
      `<i class="${k < this.i ? "feito" : k === this.i ? "atual" : ""}"></i>`).join("");
    b.querySelector(".acad-balao-titulo").textContent = p.titulo;
    b.querySelector(".acad-balao-texto").innerHTML = p.texto;
    const dica = b.querySelector(".acad-dica");
    dica.hidden = !p.dica;
    if (p.dica) b.querySelector(".acad-dica-txt").innerHTML = p.dica;
    b.querySelector(".acad-voltar").hidden = this.i === 0 || !!p.semVoltar;
    const acao = p.acao || (p.alvo ? "clique" : "proximo");
    const prox = b.querySelector(".acad-prox");
    prox.hidden = acao !== "proximo";
    prox.textContent = this.i === this.missao.passos.length - 1 ? "Concluir" : "Próximo";
    const espera = b.querySelector(".acad-espera");
    espera.textContent = acao === "clique" ? "Clique no destaque" : acao === "digitar" ? "Preencha o campo" : acao === "escolher" ? "Escolha uma opção" : "";

    this.el = null;
    if (p.alvo) {
      espera.textContent = "Carregando…";
      const el = await this._esperar(p.alvo);
      if (this._passoAtual() !== p) return; // o usuário saiu ou mudou de passo enquanto esperava
      if (!el) {
        espera.textContent = "";
        b.querySelector(".acad-balao-texto").innerHTML = p.texto +
          `<p class="acad-sumiu">Não encontrei esse ponto da tela agora. Você pode seguir para o próximo passo.</p>`;
        prox.hidden = false;
        this._posicionar();
        return;
      }
      espera.textContent = acao === "clique" ? "Clique no destaque" : acao === "digitar" ? "Preencha o campo" : acao === "escolher" ? "Escolha uma opção" : "";
      if (p.abrir) {
        const dd = el.closest(".dropdown");
        if (dd) dd.classList.add("acad-aberto");
      }
      this.el = el;
      el.scrollIntoView({ block: "center", behavior: ACAD_REDUZIR ? "auto" : "smooth" });
      this._ligarAcao(p, el, acao);
    }
    this._loop();
    acadAnimar(b.querySelector(".acad-balao-titulo"), { opacity: [0, 1], transform: ["translateY(6px)", "translateY(0)"] }, { duration: 0.3 });
    acadAnimar(b.querySelector(".acad-balao-texto"), { opacity: [0, 1] }, { duration: 0.35, delay: 0.05 });
    if (p.dica) acadAnimar(dica, { opacity: [0, 1], transform: ["translateX(-8px)", "translateX(0)"] }, { duration: 0.4, delay: 0.12 });
  },

  _esperar(alvo) {
    const achar = () => {
      const el = typeof alvo === "function" ? alvo() : document.querySelector(alvo);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      // Dentro de dropdown fechado o elemento existe mas não tem tamanho.
      if (!r.width && !r.height) {
        const dd = el.closest(".dropdown");
        if (dd) { dd.classList.add("acad-aberto"); return el; }
        return null;
      }
      return el;
    };
    return new Promise((ok) => {
      const t0 = Date.now();
      const tentar = () => {
        const el = achar();
        if (el) return ok(el);
        if (Date.now() - t0 > 10000) return ok(null);
        setTimeout(tentar, 120);
      };
      tentar();
    });
  },

  _ligarAcao(p, el, acao) {
    if (acao === "clique") {
      const sel = p.avancaEm;
      const ouvir = (e) => {
        const alvoClique = sel ? e.target.closest(sel) : (el.contains(e.target) ? el : null);
        if (!alvoClique) return;
        // Deixa o app tratar o clique (abrir o modal, trocar de tela) e só
        // depois procura o alvo do passo seguinte.
        setTimeout(() => this._ir(this.i + 1), 260);
      };
      document.addEventListener("click", ouvir, true);
      this.limpar.push(() => document.removeEventListener("click", ouvir, true));
    }
    if (acao === "digitar" || acao === "escolher") {
      el.focus({ preventScroll: true });
      const conferir = () => {
        const v = String(el.value || "").trim();
        const ok = p.valida ? p.valida(el) : acao === "escolher" ? !!v : v.length >= (p.minimo || 1);
        const prox = this.balao.querySelector(".acad-prox");
        prox.hidden = !ok;
        if (ok) {
          this.balao.querySelector(".acad-espera").textContent = "Pronto!";
          if (acao === "escolher") setTimeout(() => this._passoAtual() === p && this._ir(this.i + 1), 450);
        }
      };
      el.addEventListener("input", conferir);
      el.addEventListener("change", conferir);
      this.limpar.push(() => { el.removeEventListener("input", conferir); el.removeEventListener("change", conferir); });
      conferir();
    }
  },

  _loop() {
    cancelAnimationFrame(this.raf);
    const passo = () => { this._posicionar(); this.raf = requestAnimationFrame(passo); };
    this.raf = requestAnimationFrame(passo);
  },

  _posicionar() {
    if (!this.raiz) return;
    const W = innerWidth, H = innerHeight, pad = 6;
    const bl = (k) => this.raiz.querySelector(`[data-b="${k}"]`);
    const el = this.el && document.contains(this.el) ? this.el : null;
    if (!el) {
      // Sem alvo: véu inteiro, balão no meio.
      Object.assign(bl("t").style, { left: 0, top: 0, width: `${W}px`, height: `${H}px` });
      ["b", "l", "r"].forEach((k) => Object.assign(bl(k).style, { width: 0, height: 0 }));
      this.anel.hidden = true;
      Object.assign(this.balao.style, { left: `${(W - this.balao.offsetWidth) / 2}px`, top: `${Math.max(20, (H - this.balao.offsetHeight) / 2)}px` });
      return;
    }
    const r = el.getBoundingClientRect();
    const x = Math.max(0, r.left - pad), y = Math.max(0, r.top - pad);
    const w = Math.min(W - x, r.width + pad * 2), hh = Math.min(H - y, r.height + pad * 2);
    Object.assign(bl("t").style, { left: 0, top: 0, width: `${W}px`, height: `${y}px` });
    Object.assign(bl("b").style, { left: 0, top: `${y + hh}px`, width: `${W}px`, height: `${Math.max(0, H - y - hh)}px` });
    Object.assign(bl("l").style, { left: 0, top: `${y}px`, width: `${x}px`, height: `${hh}px` });
    Object.assign(bl("r").style, { left: `${x + w}px`, top: `${y}px`, width: `${Math.max(0, W - x - w)}px`, height: `${hh}px` });
    this.anel.hidden = false;
    Object.assign(this.anel.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${hh}px` });
    // Balão: embaixo se couber, senão em cima, senão ao lado.
    const bw = this.balao.offsetWidth, bh = this.balao.offsetHeight, gap = 14;
    let top = y + hh + gap, left = Math.min(Math.max(12, x + w / 2 - bw / 2), W - bw - 12);
    if (top + bh > H - 12) top = y - bh - gap;
    if (top < 12) {
      top = Math.min(Math.max(12, y), H - bh - 12);
      left = x + w + gap + bw < W ? x + w + gap : Math.max(12, x - bw - gap);
    }
    Object.assign(this.balao.style, { left: `${left}px`, top: `${top}px` });
  },

  async _fim() {
    const m = this.missao;
    this.sair(true);
    const ja = Academia.prog.missoes.includes(m.id);
    const ganho = await Academia.concluiuMissao(m.id);
    const proxima = MISSOES.find((x) => !Academia.prog.missoes.includes(x.id));
    const md = modal({
      title: "Missão concluída",
      body: `<div class="acad-nivel-up">
          <div class="acad-medalha" id="acadMedalha">✓</div>
          <p class="acad-nivel-nome">${h(m.titulo)}</p>
          <p class="text-muted">${ja ? "Você refez esta missão. O XP só conta na primeira vez." : `+${ganho} XP na sua conta.`}</p>
          ${Academia.subiuPara ? `<p class="acad-subiu">★ Você subiu para <b>${h(Academia.subiuPara)}</b></p>` : ""}
          ${m.resumo ? `<div class="acad-resumo">${m.resumo}</div>` : ""}
        </div>`,
      footer: `<button class="btn btn-default btn-sm" data-wiki>Ver a trilha</button>
               ${proxima ? `<button class="btn btn-main btn-sm" data-prox>Próxima missão: ${h(proxima.titulo)}</button>` : ""}`,
    });
    const med = md.root.querySelector("#acadMedalha");
    acadAnimar(med, { transform: ["scale(0)", "scale(1)"] }, { spring: true, duration: 0.7, bounce: 0.55 });
    acadConfete(med);
    md.root.querySelector("[data-wiki]").onclick = () => { md.close(); go("academia"); };
    const bp = md.root.querySelector("[data-prox]");
    if (bp) bp.onclick = () => { md.close(); Tour.iniciar(proxima.id); };
  },

  sair(silencioso) {
    cancelAnimationFrame(this.raf);
    this.limpar.forEach((f) => f()); this.limpar = [];
    if (this._tecla) document.removeEventListener("keydown", this._tecla);
    document.querySelectorAll(".dropdown.acad-aberto").forEach((d) => d.classList.remove("acad-aberto"));
    const raiz = this.raiz;
    this.raiz = null; this.el = null;
    const tinhaMissao = this.missao;
    this.missao = null;
    if (raiz) raiz.remove();
    // A tela de execução e a barra podem estar mostrando o lead de treino.
    if (typeof fecharExecucaoTela === "function" && Exec.raiz) fecharExecucaoTela(true);
    const barra = document.getElementById("execBarra");
    if (barra && Treino.ativo) barra.remove();
    if (Treino.ativo) {
      Treino.desligar();
      // A tela aberta ainda mostra a fila de treino: redesenha com a real.
      if (["execucao", "leads"].includes(rota(state.page).nome)) go(rota(state.page).nome);
    }
    if (!silencioso && tinhaMissao) toast("Tour encerrado. Você pode retomar pela Academia.");
  },
};

/* ── missões (os tours) ────────────────────────────────────────────── */
const naLinha = (id, sel) => () => document.querySelector(`.exec-linha[data-act="${id}"] ${sel}`);
const menuAberto = (sel) => () => document.querySelector(`.exec-menu:not([hidden]) ${sel}`);
const MISSOES = [
  {
    id: "execucao", titulo: "Primeiro dia: a tela de Execução", icone: "▶", capitulo: "rotina",
    resumo: "O dia do BDR mora em Prospecção › Execução: o sistema monta a fila a partir das cadências e você executa.",
    passos: [
      { titulo: "Bem-vindo à operação", semVoltar: true,
        texto: `<p>Nesta missão você vai conhecer a tela em que um BDR passa quase o dia inteiro.</p>
                <p>Estamos em <b>modo treino</b>: a fila tem um lead de mentira e nada do que você clicar é salvo.</p>`,
        dica: "Use <kbd>Enter</kbd> para avançar os passos informativos e <kbd>Esc</kbd> para sair." },
      { alvo: '.navbar [data-page="execucao"]', abrir: true, titulo: "Prospecção › Execução",
        texto: "Todo dia começa aqui. Clique em <b>Execução</b>, dentro do menu Prospecção.",
        dica: "Guarde este caminho. É a primeira tela que você abre ao chegar." },
      { page: "execucao", alvo: "#execFaixa", acao: "proximo", titulo: "Sua carteira",
        texto: "Quantos leads você está prospectando e quantos estão disponíveis para começar. O botão <b>Iniciar novos leads</b> puxa mais para a sua fila." },
      { alvo: "#painelProgresso", acao: "proximo", titulo: "Meu progresso hoje",
        texto: "O número grande são as atividades que você já finalizou hoje, sobre o total do dia. Ao lado, o <b>objetivo diário</b> (na BLU, 200).",
        dica: "Se a barra não anda até o meio da tarde, falta lead na sua fila. Puxe mais em <b>Iniciar novos leads</b>." },
      { alvo: "#toggleRapido", acao: "proximo", titulo: "Modo Execução rápida",
        texto: "Ligado, as atividades abrem uma atrás da outra. Se o lead não atende, o sistema já leva você para a próxima.",
        dica: "É o jeito mais rápido de bater a meta. Desligado, você volta para a lista a cada atividade." },
      { alvo: () => document.querySelector(".exec-linha"), acao: "proximo", titulo: "Uma atividade da lista",
        texto: "Cada linha é uma atividade: o tipo, a cadência e o passo, e o lead. As <b>Atividades Extras</b>, agendadas na mão, aparecem num grupo separado, acima das da cadência.",
        dica: "A lista já vem na ordem de prioridade. Na dúvida, siga a ordem." },
      { alvo: "#execFiltros", acao: "proximo", titulo: "Filtros",
        texto: "Status, tipo de atividade, cadência, passo e lista de importação, além da busca por nome, e-mail ou telefone." },
      { alvo: "#btnIniciarNovos", acao: "proximo", titulo: "Iniciar novos leads",
        texto: "Quando a fila acaba, é por aqui que você puxa leads novos. Tem uma missão só para ele.",
        dica: "Puxe só o que consegue trabalhar: cada lead novo gera pesquisa, e-mail e ligações nos próximos dias." },
    ],
  },
  {
    id: "iniciar", titulo: "Iniciar novos leads", icone: "＋", capitulo: "rotina",
    resumo: "Escolha quantos leads puxar olhando a previsão dos próximos dias: puxar demais hoje entope a semana.",
    passos: [
      { page: "execucao", alvo: "#btnIniciarNovos", titulo: "Abrir Iniciar novos leads", semVoltar: true,
        texto: "Clique em <b>Iniciar novos leads</b>." },
      { alvo: ".inl-bloco", acao: "proximo", titulo: "Leads a iniciar",
        texto: "Digite quantos leads quer puxar. Logo abaixo aparece quantas atividades novas isso cria para <b>hoje</b>.",
        dica: "O atalho <b>Preencher</b> calcula quantos leads faltam para chegar no objetivo diário." },
      { alvo: ".inl-cad", acao: "proximo", titulo: "Cadências",
        texto: "Por padrão o sistema escolhe as cadências pela prioridade. Abra esta seção se quiser puxar só de uma cadência ou lista." },
      { alvo: ".inl-prev", acao: "proximo", titulo: "Previsão de atividades futuras",
        texto: "As barras mostram quantas atividades você terá em cada um dos próximos dias. Mude a quantidade e veja a previsão mudar." },
      { alvo: ".modal-card [data-ok]", titulo: "Iniciar", texto: "Clique em <b>Iniciar leads</b>. No treino, nada é gravado." },
    ],
  },
  {
    id: "pesquisa", titulo: "Pesquisa e validação", icone: "⌕", capitulo: "cadencia",
    resumo: "Todo lead começa pela pesquisa. O que você anota aqui aparece em todas as ligações seguintes.",
    passos: [
      { page: "execucao", alvo: naLinha(900001, "[data-exec]"), titulo: "Executar a pesquisa", semVoltar: true,
        texto: "O primeiro passo de toda cadência é pesquisar o lead. Clique em <b>Executar</b> na atividade de pesquisa da Mariana." },
      { alvo: "#execLateral", acao: "proximo", titulo: "O painel do lead",
        texto: "À esquerda fica o lead: cadência, quantas atividades já foram feitas e as abas de dados, histórico, anotações e próximas atividades.",
        dica: "O histórico mostra as anotações das atividades anteriores em amarelo. Leia antes de cada contato." },
      { alvo: ".exec-card", acao: "proximo", titulo: "O roteiro da pesquisa",
        texto: "O roteiro diz o que descobrir: objeção, produto vendido, se já houve reunião, processo comercial e maturidade do cliente." },
      { alvo: "#execNotes", acao: "digitar", minimo: 10, titulo: "Anote o que encontrou",
        texto: "Escreva o que você descobriu sobre a empresa (pelo menos uma frase).",
        dica: "Ex.: <i>“Construtora de médio porte, 3 obras ativas em SP, sem CRM. Decisora: Mariana (diretora comercial).”</i>" },
      { alvo: "#execFeita", titulo: "Marcar como feita",
        texto: "Clique em <b>Marcar como feita</b>. A pesquisa sai da fila e, no modo rápido, a próxima atividade já abre." },
    ],
  },
  {
    id: "email", titulo: "O e-mail da cadência", icone: "✉", capitulo: "cadencia",
    resumo: "O texto vem do modelo da cadência e pode ser ajustado. Sem a caixa de e-mail integrada, nada sai de verdade.",
    passos: [
      { page: "execucao", alvo: naLinha(900002, "[data-exec]"), titulo: "Executar o e-mail", semVoltar: true,
        texto: "Clique em <b>Executar</b> na atividade de e-mail." },
      { alvo: ".exec-compose", acao: "proximo", titulo: "O e-mail vem pronto",
        texto: "Destinatário, assunto e corpo saem do modelo da etapa, já com o nome do lead e da empresa.",
        dica: "Atenção: se a sua caixa de e-mail não estiver integrada, a atividade conta como feita mas nenhum e-mail sai. Confira em <b>Canais e entregas</b>." },
      { alvo: "#cpCorpo", acao: "proximo", titulo: "Ajuste se precisar",
        texto: "Você pode mudar o texto antes de enviar. Uma frase com o que você achou na pesquisa faz diferença." },
      { alvo: "#cpEnviar", titulo: "Enviar", texto: "Clique em <b>Enviar</b>. No treino o envio é simulado." },
    ],
  },
  {
    id: "ligacao", titulo: "Ligação e classificação", icone: "☎", capitulo: "ligacao",
    resumo: "Toda ligação termina classificada. É essa classificação que alimenta as métricas de contato.",
    passos: [
      { page: "execucao", alvo: naLinha(900003, "[data-exec]"), titulo: "Abrir a ligação", semVoltar: true,
        texto: "Clique em <b>Executar</b> na atividade de ligação." },
      { alvo: ".exec-roteiro", acao: "proximo", titulo: "O roteiro de abertura",
        texto: "Alegria na voz, validar se o lead viu o e-mail ou o WhatsApp, rapport leve. Leia antes de discar.",
        dica: "Releia as anotações da pesquisa no painel da esquerda. Nada queima mais um lead do que perguntar o que já estava anotado." },
      { alvo: ".exec-num", acao: "proximo", titulo: "O número",
        texto: "O número precisa estar <b>completo</b>: DDD + número. Com um dígito a menos, o discador não completa.",
        dica: "O lead tem mais de um telefone? Clique no campo para escolher outro." },
      { alvo: "#dLigar", titulo: "Ligar", texto: "Clique em <b>Ligar</b>. No treino não sai ligação de verdade." },
      { alvo: "#cNotas", acao: "digitar", minimo: 5, titulo: "Bloco de anotações",
        texto: "Durante a chamada, anote o que for dito: objeção, próximo passo, melhor horário.",
        dica: "Uma linha basta: <i>“Pediu retorno quinta às 10h, quer ver case de construtora.”</i>" },
      { alvo: "#cEncerrar", titulo: "Encerrar", texto: "Clique no botão vermelho para encerrar a ligação." },
      { alvo: ".exec-classif-botoes", avancaEm: "[data-classe]", titulo: "Como foi a ligação?",
        texto: "<b>Significativa</b>: a conversa avançou. <b>Não significativa</b>: falou sem avanço. <b>Cliente ocupado</b>: pediu outro momento. <b>Sem contato</b>: ninguém certo atendeu.",
        dica: "Não atendeu? Use <b>Refazer chamada ▾ › Ligar para novo número</b> antes de desistir." },
      { alvo: "#cFinalizar", titulo: "Finalizar",
        texto: "Clique em <b>Finalizar</b>. A ligação e as anotações ficam no histórico do lead." },
      { alvo: "#execBarra", acao: "proximo", titulo: "E agora?",
        texto: "Depois de cada atividade aparece esta barra: <b>Agendar atividade extra</b>, <b>Ganho</b> ou <b>Perdido</b>. Se não for o caso, feche e siga." },
    ],
  },
  {
    id: "extra", titulo: "Agendar uma atividade extra", icone: "⏱", capitulo: "cadencia",
    resumo: "O lead pediu outro horário? A atividade extra entra no topo da fila: azul no prazo, vermelha se atrasar.",
    passos: [
      { page: "execucao", alvo: () => document.querySelector(".exec-linha [data-mais]"), titulo: "Mais ações", semVoltar: true,
        texto: "Clique na setinha ao lado de <b>Executar</b>." },
      { alvo: menuAberto("[data-m-extra]"), titulo: "Agendar atividade extra",
        texto: "Clique em <b>Agendar atividade extra</b>.",
        dica: "Depois de concluir uma atividade, o mesmo botão aparece na barra de baixo." },
      { alvo: "#aeQuando", acao: "proximo", titulo: "Quando",
        texto: "Escolha o dia e a hora que o lead pediu. Por padrão, amanhã às 9h." },
      { alvo: "#aeTipo", acao: "proximo", titulo: "Tipo", texto: "Ligação, e-mail, pesquisa, social point ou reunião." },
      { alvo: "#aeNotas", acao: "digitar", minimo: 5, titulo: "Lembrete",
        texto: "Escreva o que você precisa lembrar na hora.", dica: "Ex.: <i>“Ela pediu para ligar depois da reunião de obra.”</i>" },
      { alvo: ".modal-card [data-ok]", titulo: "Agendar", texto: "Clique em <b>Agendar</b>." },
    ],
  },
  {
    id: "perdido", titulo: "Quando não dá: Perdido com motivo", icone: "✕", capitulo: "perdido",
    resumo: "Perder um lead com o motivo certo é o que faz o gráfico de motivos de perda servir para alguma coisa.",
    passos: [
      { page: "execucao", alvo: () => document.querySelector(".exec-linha [data-mais]"), titulo: "Mais ações", semVoltar: true,
        texto: "Quando o lead não tem fit, ele sai como <b>perdido</b>. Clique na setinha ao lado de <b>Executar</b>." },
      { alvo: menuAberto("[data-m-perdido]"), titulo: "Perdido", texto: "Clique em <b>Perdido</b>." },
      { alvo: "#lostReason", acao: "escolher", titulo: "Escolha o motivo",
        texto: "O motivo precisa ser o verdadeiro. Ele vira o gráfico de motivos de perda que a gestão usa.",
        dica: "Sem estrutura, fora do ICP, não consegui contato… Se a hora foi ruim mas o lead é bom, o motivo é <b>Reaproveitamento</b>." },
      { alvo: ".exec-nova", acao: "proximo", titulo: "Agendar nova prospecção",
        texto: "Ligue esta chave quando o lead é bom mas o momento não: escolha a data e a cadência, e ele volta sozinho para a sua fila.",
        dica: "Perda definitiva (sem estrutura, LGPD opt-out) não tem agendamento." },
      { alvo: "#lostNotes", acao: "proximo", titulo: "Anotação",
        texto: "Conte em uma linha por que perdeu. Quem pegar este lead no futuro vai agradecer." },
      { alvo: ".modal-card [data-ok]", titulo: "Marcar como perdido", texto: "Clique em <b>Marcar como perdido</b>." },
    ],
  },
  {
    id: "ganho", titulo: "Reunião marcada: Ganho", icone: "★", capitulo: "ganho",
    resumo: "Ganho é reunião marcada. Pede os campos obrigatórios e o BANT, e entra na hora na meta do mês.",
    passos: [
      { page: "execucao", alvo: () => document.querySelector(".exec-linha [data-mais]"), titulo: "Mais ações", semVoltar: true,
        texto: "Marcou a reunião? Clique na setinha ao lado de <b>Executar</b>." },
      { alvo: menuAberto("[data-m-ganho]"), titulo: "Ganho", texto: "Clique em <b>Ganho</b>." },
      { se: () => !!document.querySelector(".modal-card [data-cf]"), alvo: ".modal-card", avancaEm: ".modal-card [data-ok]",
        titulo: "Campos obrigatórios",
        texto: "Preencha <b>Cargo da pessoa que marcou</b> e <b>BDR responsável</b> e clique em <b>Salvar</b>.",
        dica: "É por esses campos que a gestão filtra os ganhos por cargo e por BDR." },
      { alvo: ".exec-ganho-num", acao: "proximo", titulo: "O resumo da prospecção",
        texto: "Atividades planejadas, completadas e quantos dias o lead ficou em prospecção." },
      { alvo: "#gNotas", acao: "digitar", minimo: 10, titulo: "O BANT",
        texto: "Registre orçamento, quem decide, a necessidade e o prazo. O vendedor vai ler isto antes da reunião.",
        dica: "Na BLU, a gravação da ligação é transcrita e o resumo com o BANT vem do assistente de IA." },
      { alvo: ".modal-card [data-ok]", titulo: "Marcar como ganho", texto: "Clique em <b>Marcar como ganho</b>." },
    ],
  },
  {
    id: "novo-lead", titulo: "Cadastrar um lead na mão", icone: "✎", capitulo: "rotina",
    resumo: "Lead manual precisa de nome, empresa, e-mail e cadência. Com início imediato, ele já cai na sua fila.",
    passos: [
      { page: "leads", alvo: "#newLead", titulo: "Adicionar", semVoltar: true,
        texto: "Em <b>Prospecção › Leads</b>, clique em <b>Adicionar</b>." },
      { alvo: "#fInicio", acao: "proximo", titulo: "Início imediato ou aguardar?",
        texto: "<b>Início imediato</b>: o lead entra direto na sua fila de execução. <b>Aguardar início</b>: ele espera até alguém puxá-lo em Iniciar novos leads.",
        dica: "Marque <b>Adicionar como lead inbound</b> quando foi o lead que procurou a BLU." },
      { alvo: "#fCadence", acao: "escolher", titulo: "Cadência",
        texto: "Escolha a cadência. Ela decide a sequência de pesquisa, e-mails e ligações." },
      { alvo: "#fEmail", acao: "digitar", valida: (el) => /.+@.+\..+/.test(el.value), titulo: "E-mail",
        texto: "Digite um e-mail válido.", dica: "É para esse endereço que a cadência vai mandar os e-mails." },
      { alvo: "#fCompany", acao: "digitar", minimo: 2, titulo: "Empresa", texto: "Digite a empresa." },
      { alvo: "#fName", acao: "digitar", minimo: 3, titulo: "Nome completo",
        texto: "Digite o nome completo. O primeiro nome é preenchido sozinho — é ele que vai nos e-mails." },
      { alvo: "#lfVerMais", acao: "proximo", titulo: "+ Ver mais",
        texto: "Cargo, site, estado, cidade, telefones e campos personalizados ficam aqui. Preencha o telefone completo se tiver: sem ele não dá para ligar." },
      { alvo: ".modal-card [data-save]", titulo: "Salvar", texto: "Clique em <b>Salvar</b>. No treino, nada é gravado." },
    ],
  },
  {
    id: "numeros", titulo: "Olhando os seus números", icone: "◫", capitulo: "metricas", treino: false,
    resumo: "Dashboard para a meta do mês, Estatísticas para entender onde a conversão trava.",
    passos: [
      { page: "dashboard", alvo: () => document.querySelector("#view .panel"), acao: "proximo", titulo: "Dashboard", semVoltar: true,
        texto: "Aqui você vê as oportunidades do mês contra a meta, o ranking e os motivos de perda.",
        dica: "Olhe no começo e no fim do dia. Estar abaixo da linha da meta no dia 15 é o aviso para puxar mais leads." },
      { alvo: '.navbar [data-page="estatisticas"]', abrir: true, titulo: "Estatísticas › Prospecção",
        texto: "Clique em <b>Prospecção</b>, dentro de Estatísticas." },
      { page: "estatisticas", alvo: () => document.querySelector("#view .panel") || document.querySelector("#view"), acao: "proximo", titulo: "Estatísticas",
        texto: "Leads finalizados, engajados, ganhos, desempenho por passo e motivos de perda, filtrados por período e cadência." },
    ],
  },
];

/* ── conteúdo da wiki ──────────────────────────────────────────────── */
const CAPITULOS = [
  {
    id: "papeis", titulo: "SDR e BDR: quem faz o quê", icone: "◎",
    corpo: `
      <p>Os dois fazem pré-venda: o trabalho deles é transformar contato em <b>reunião marcada</b> para o time de vendas. O que muda é de onde vem o lead.</p>
      <div class="acad-dupla">
        <div><h5>SDR · inbound</h5><p>Atende quem levantou a mão: preencheu formulário, pediu contato, baixou material. O que mais pesa é o <b>tempo de resposta</b>: lead inbound esfria em minutos.</p>
          <p class="text-muted">No sistema: lead marcado como <i>inbound</i>, métrica “Resposta inbound”, bloco “Leads aguardando a primeira ligação”.</p></div>
        <div><h5>BDR · outbound</h5><p>Vai atrás de quem ainda não conhece a BLU. Trabalha por <b>cadência</b>: pesquisa, e-mail, WhatsApp e ligações ao longo de vários dias.</p>
          <p class="text-muted">No sistema: fila de Execução, Iniciar novos leads, objetivo diário de atividades.</p></div>
      </div>
      <p>Na prática da BLU as duas funções usam as mesmas telas. O que você vai aprender aqui vale para as duas.</p>
      <h5>O que conta como sucesso</h5>
      <p><b>Ganho = reunião marcada.</b> Não é venda fechada: é a reunião agendada com a pessoa certa. É esse número que vai para a meta de oportunidades do mês.</p>`,
    quiz: [
      { p: "O que é um “ganho” para o SDR/BDR?", o: ["Venda fechada", "Reunião marcada", "Lead que respondeu o e-mail"], c: 1 },
      { p: "Qual métrica pesa mais para o SDR inbound?", o: ["Tempo de resposta", "Número de e-mails enviados", "Tamanho da carteira"], c: 0 },
      { p: "Como o BDR outbound organiza o contato com cada lead?", o: ["Liga uma vez e desiste", "Por cadência, com vários passos em dias diferentes", "Só por WhatsApp"], c: 1 },
    ],
  },
  {
    id: "rotina", titulo: "A rotina do dia", icone: "▶",
    corpo: `
      <ol class="acad-passos">
        <li><b>Abra Prospecção › Execução.</b> O sistema já montou a fila do dia a partir das cadências.</li>
        <li><b>Confira o progresso.</b> A meta é o objetivo diário de atividades (na BLU, 200). Se a fila não dá para chegar lá, puxe leads em <b>Iniciar novos leads</b>.</li>
        <li><b>Execute a fila.</b> De preferência no <b>Modo Execução rápida</b>: uma atividade abre atrás da outra e, se o lead não atende, você já está na próxima.</li>
        <li><b>Resolva cada lead.</b> Ao fim de cada atividade: concluir, agendar uma atividade extra, marcar ganho ou perdido.</li>
        <li><b>Olhe os números.</b> No Dashboard, oportunidades do mês contra a meta. Nas Estatísticas, onde a conversão trava.</li>
      </ol>
      <h5>Iniciar novos leads</h5>
      <p>Cada lead novo gera trabalho para os próximos dias (pesquisa, e-mails, ligações). Antes de puxar, veja a previsão de atividades: puxar demais hoje entope a sua semana.</p>
      <h5>Cadastrar um lead na mão</h5>
      <p>Em <b>Prospecção › Leads › Adicionar</b>. Obrigatório: nome, empresa, e-mail e cadência. <i>Início imediato</i> coloca o lead na sua fila na hora; <i>aguardar início</i> deixa ele esperando até você puxar.</p>`,
    quiz: [
      { p: "Qual é a primeira tela que o BDR abre ao chegar?", o: ["Dashboard", "Prospecção › Execução", "Lista de Leads"], c: 1 },
      { p: "O que o Modo Execução rápida faz quando o lead não atende?", o: ["Encerra a fila", "Leva você para a próxima atividade", "Marca o lead como perdido"], c: 1 },
      { p: "Por que não puxar leads demais de uma vez?", o: ["O sistema bloqueia", "Cada lead gera atividades nos próximos dias e entope a semana", "Os leads somem depois de 24h"], c: 1 },
    ],
  },
  {
    id: "cadencia", titulo: "Cadência e atividades", icone: "⌕",
    corpo: `
      <p>Cadência é a sequência de contatos com um lead, passo a passo, em dias diferentes. Cada passo vira uma <b>atividade</b> na sua fila no dia certo.</p>
      <table class="acad-tabela"><thead><tr><th>Atividade</th><th>O que fazer</th></tr></thead><tbody>
        <tr><td>Pesquisa</td><td>Sempre o primeiro passo. Descubra objeção, produto vendido, se já houve reunião, processo comercial e maturidade. Anote tudo: as anotações aparecem em todas as ligações seguintes.</td></tr>
        <tr><td>E-mail</td><td>O texto vem do modelo da cadência. Você pode ajustar antes de enviar. <b>Sem a caixa de e-mail integrada, o e-mail não sai</b> mesmo com a atividade marcada como feita.</td></tr>
        <tr><td>Social Point</td><td>Mensagem no WhatsApp ou LinkedIn. Registre o que mandou.</td></tr>
        <tr><td>Ligação</td><td>O coração da cadência. Tem capítulo próprio.</td></tr>
      </tbody></table>
      <h5>Atividade extra</h5>
      <p>É a atividade fora da cadência, que você agenda na mão: o lead pediu para ligar amanhã às 9h, por exemplo. Ela aparece no topo da fila, <span class="acad-azul">em azul</span> enquanto está no prazo e <span class="acad-vermelho">em vermelho</span> quando atrasa.</p>`,
    quiz: [
      { p: "Qual é sempre o primeiro passo de uma cadência?", o: ["Ligação", "Pesquisa e validação", "E-mail"], c: 1 },
      { p: "O que acontece com o e-mail se a caixa não estiver integrada?", o: ["Sai pelo e-mail da empresa", "A atividade conta como feita, mas nada é enviado", "O sistema avisa e bloqueia"], c: 1 },
      { p: "Uma atividade extra em vermelho significa…", o: ["Que está atrasada", "Que é prioridade máxima", "Que o lead está perdido"], c: 0 },
    ],
  },
  {
    id: "ligacao", titulo: "A ligação", icone: "☎",
    corpo: `
      <h5>Antes de discar</h5>
      <ul><li>Releia as anotações da pesquisa.</li><li>Leia o roteiro de abertura: alegria na voz, validar se o lead viu o e-mail ou o WhatsApp, rapport leve.</li>
          <li>Confira o número: ele precisa estar <b>completo</b> (DDD + número). Com um dígito a menos, o discador não completa.</li></ul>
      <h5>Classificação: toda ligação termina com uma</h5>
      <table class="acad-tabela"><thead><tr><th>Classificação</th><th>Quando usar</th></tr></thead><tbody>
        <tr><td>Significativa</td><td>A conversa avançou: interesse, próximo passo, reunião.</td></tr>
        <tr><td>Não significativa</td><td>Falou com a pessoa, mas sem avanço.</td></tr>
        <tr><td>Cliente ocupado</td><td>A pessoa certa atendeu e pediu outro momento.</td></tr>
        <tr><td>Sem contato</td><td>Ninguém atendeu ou não era a pessoa certa.</td></tr>
      </tbody></table>
      <h5>Não atendeu?</h5>
      <p>Tente outro número do lead. Se continuar sem resposta, marque <i>sem contato</i> e siga. Se ele pediu outro horário, agende uma <b>atividade extra</b>.</p>
      <h5>A gravação</h5>
      <p>A ligação fica gravada no histórico do lead. Na BLU, quando a ligação vira reunião, a gravação é transcrita e o resumo com o BANT vai para as anotações do ganho.</p>`,
    quiz: [
      { p: "O discador não completou a chamada. Qual a causa mais comum?", o: ["Número incompleto", "Lead perdido", "Cadência pausada"], c: 0 },
      { p: "Falou com o decisor, mas ele não quis avançar. Classificação:", o: ["Significativa", "Não significativa", "Sem contato"], c: 1 },
      { p: "O lead pediu para ligar amanhã às 9h. O que fazer?", o: ["Marcar perdido", "Agendar uma atividade extra", "Esperar a cadência"], c: 1 },
    ],
  },
  {
    id: "ganho", titulo: "Ganho: reunião marcada", icone: "★",
    corpo: `
      <p>Marcou a reunião, é <b>ganho</b>. O lead sai da cadência, as atividades pendentes são descartadas e ele entra na meta de oportunidades do mês.</p>
      <h5>O que registrar</h5>
      <ul><li><b>Cargo da pessoa que marcou</b> e <b>BDR responsável</b>: são campos obrigatórios e é por eles que a gestão filtra os ganhos.</li>
          <li><b>BANT</b> nas anotações: Budget (orçamento), Authority (quem decide), Need (a dor), Timing (prazo).</li></ul>
      <h5>Da ligação ao BANT</h5>
      <ol class="acad-passos"><li>Baixe a gravação no histórico do lead.</li><li>Transcreva o áudio.</li><li>Peça ao assistente de IA o resumo e o BANT.</li><li>Cole nas anotações do ganho.</li></ol>
      <p class="text-muted">O vendedor que vai à reunião lê essas anotações. Um BANT bem escrito é o que faz a reunião acontecer.</p>`,
    quiz: [
      { p: "O que o “A” do BANT significa?", o: ["Agenda", "Autoridade (quem decide)", "Atendimento"], c: 1 },
      { p: "Que campos são obrigatórios para dar o ganho?", o: ["CNPJ e telefone", "Cargo da pessoa que marcou e BDR responsável", "Cidade e estado"], c: 1 },
      { p: "O que acontece com as atividades pendentes quando o lead vira ganho?", o: ["Continuam na fila", "São descartadas", "Viram atividades extras"], c: 1 },
    ],
  },
  {
    id: "perdido", titulo: "Perdido e reaproveitamento", icone: "✕",
    corpo: `
      <p>Lead sem fit sai como <b>perdido</b>, sempre com um motivo. O motivo vira o gráfico de motivos de perda: se ele estiver errado, a gestão decide com base em dado errado.</p>
      <h5>Motivos mais usados</h5>
      <ul><li><b>Lead sem estrutura</b>: empresa pequena demais para a solução.</li><li><b>Não consegui contato</b>: esgotou as tentativas.</li>
          <li><b>Lead rejeitou a prospecção</b>: disse não.</li><li><b>Lead fora do ICP</b>, <b>duplicado</b> ou <b>inválido</b>.</li>
          <li><b>LGPD opt-out</b>: pediu para não ser contatado. Nunca recupere este lead.</li></ul>
      <h5>Reaproveitamento</h5>
      <p>Se o momento foi ruim mas o lead é bom, use o motivo <b>Reaproveitamento</b> e agende uma nova prospecção: escolha a data e a cadência. Na data marcada, o lead volta sozinho para a sua fila. Perda definitiva não tem agendamento.</p>`,
    quiz: [
      { p: "O lead é bom, mas pediu para falar só daqui a 3 meses. Motivo:", o: ["Lead sem estrutura", "Reaproveitamento, com nova prospecção agendada", "Não consegui contato"], c: 1 },
      { p: "O que nunca fazer com um lead em LGPD opt-out?", o: ["Registrar o motivo", "Recuperar e contatar de novo", "Anotar a data"], c: 1 },
      { p: "Por que o motivo de perda precisa ser o verdadeiro?", o: ["Porque vira o gráfico que a gestão usa para decidir", "Porque bloqueia o lead", "Porque conta XP"], c: 0 },
    ],
  },
  {
    id: "metricas", titulo: "Seus números", icone: "◫",
    corpo: `
      <table class="acad-tabela"><thead><tr><th>Métrica</th><th>O que é</th><th>Onde ver</th></tr></thead><tbody>
        <tr><td>Objetivo diário</td><td>Atividades feitas no dia contra a meta (200 na BLU)</td><td>Execução</td></tr>
        <tr><td>Oportunidades</td><td>Ganhos (reuniões) no mês contra a meta mensal</td><td>Dashboard</td></tr>
        <tr><td>Taxa de conversão</td><td>Ganhos sobre leads finalizados</td><td>Dashboard, Estatísticas</td></tr>
        <tr><td>Motivos de perda</td><td>Por que os leads saíram</td><td>Dashboard › Insights</td></tr>
        <tr><td>Ligações significativas</td><td>Ligações que avançaram, sobre o total</td><td>Estatísticas</td></tr>
        <tr><td>On time</td><td>Atividades feitas no dia em que estavam agendadas</td><td>Estatísticas (gestão)</td></tr>
      </tbody></table>
      <p>Você vê os seus números. A gestão vê o time inteiro e cada BDR individualmente.</p>`,
    quiz: [
      { p: "Onde você acompanha as oportunidades do mês contra a meta?", o: ["Execução", "Dashboard", "Lista de Leads"], c: 1 },
      { p: "O que é “on time”?", o: ["Ligação atendida na hora", "Atividade feita no dia em que estava agendada", "Lead que respondeu rápido"], c: 1 },
      { p: "Taxa de conversão é…", o: ["Ganhos sobre leads finalizados", "E-mails abertos sobre enviados", "Ligações sobre atividades"], c: 0 },
    ],
  },
  {
    id: "armadilhas", titulo: "Armadilhas que custam caro", icone: "!",
    corpo: `
      <ul class="acad-armadilhas">
        <li><b>E-mail “enviado” que não saiu.</b> Sem a caixa integrada, a atividade conclui e nada é enviado. Confira seu canal em <i>Canais e entregas</i>.</li>
        <li><b>Telefone incompleto.</b> Um dígito a menos e o discador não completa. Corrija o número no lead antes de ligar.</li>
        <li><b>Pesquisa sem anotação.</b> Ligar sem saber o que já foi descoberto queima o lead. Anote sempre.</li>
        <li><b>Perdido com motivo errado.</b> Distorce o gráfico que a gestão usa. Escolha o motivo verdadeiro.</li>
        <li><b>Ganho sem BANT.</b> O vendedor chega na reunião às cegas. Registre orçamento, autoridade, necessidade e prazo.</li>
        <li><b>WhatsApp fora do sistema.</b> Mensagem mandada pelo celular e não registrada some do histórico do lead.</li>
      </ul>`,
    quiz: [
      { p: "Você marcou a atividade de e-mail como feita e o lead diz que não recebeu. Primeira suspeita:", o: ["Caixa de e-mail não integrada", "Lead mentiu", "Cadência errada"], c: 0 },
      { p: "Mandou WhatsApp pelo celular. O que fazer?", o: ["Nada", "Registrar no lead", "Marcar ganho"], c: 1 },
      { p: "Qual destes NÃO é uma armadilha?", o: ["Ligar sem ler a pesquisa", "Registrar o BANT no ganho", "Perder com motivo genérico"], c: 1 },
    ],
  },
];

const GLOSSARIO = [
  ["Atividade extra", "Atividade agendada na mão, fora da cadência. Azul no prazo, vermelha atrasada."],
  ["BANT", "Budget, Authority, Need, Timing: orçamento, quem decide, a dor e o prazo."],
  ["BDR", "Pré-vendas outbound: prospecta quem ainda não procurou a empresa."],
  ["Cadência", "Sequência de passos (pesquisa, e-mail, social, ligação) distribuídos em dias."],
  ["Ganho", "Reunião marcada. Conta na meta de oportunidades do mês."],
  ["ICP", "Perfil de cliente ideal. Lead fora do ICP não deve seguir na cadência."],
  ["Iniciar novos leads", "Puxar leads que estão esperando para a sua fila de execução."],
  ["Inbound", "Lead que procurou a empresa. Precisa de resposta rápida."],
  ["Ligação significativa", "Ligação em que a conversa avançou."],
  ["Modo Execução rápida", "Executa a fila em sequência, sem voltar para a lista."],
  ["Objetivo diário", "Meta de atividades por dia (200 na BLU)."],
  ["On time", "Atividade feita no dia em que estava agendada."],
  ["Outbound", "Prospecção ativa: a iniciativa do contato é nossa."],
  ["Perdido", "Lead que saiu da cadência sem reunião, sempre com um motivo."],
  ["Reaproveitamento", "Motivo de perda que agenda uma nova prospecção numa data e cadência."],
  ["SDR", "Pré-vendas inbound: qualifica quem levantou a mão."],
  ["Social Point", "Passo de mensagem por WhatsApp ou LinkedIn."],
];

const CONQUISTAS = [
  { id: "primeira", nome: "Primeiro passo", desc: "Concluir qualquer missão", icone: "◉", ok: (p) => p.missoes.length >= 1 },
  { id: "pesquisador", nome: "Pesquisador", desc: "Missão Pesquisa e validação", icone: "⌕", ok: (p) => p.missoes.includes("pesquisa") },
  { id: "voz", nome: "Voz de ouro", desc: "Missão Ligação e classificação", icone: "☎", ok: (p) => p.missoes.includes("ligacao") },
  { id: "cacador", nome: "Caçador de reuniões", desc: "Missão Ganho", icone: "★", ok: (p) => p.missoes.includes("ganho") },
  { id: "semmedo", nome: "Sem medo do não", desc: "Missão Perdido com motivo", icone: "✕", ok: (p) => p.missoes.includes("perdido") },
  { id: "leitor", nome: "Leitor voraz", desc: "Ler todos os capítulos", icone: "▤", ok: (p) => p.lidos.length >= CAPITULOS.length },
  { id: "gabarito", nome: "Gabaritou", desc: "Acertar tudo em todos os quizzes", icone: "✓",
    ok: (p) => CAPITULOS.every((c) => p.quizzes[c.id] && p.quizzes[c.id].acertos === p.quizzes[c.id].total) },
  { id: "formado", nome: "Formado pela Academia", desc: "Concluir todas as missões", icone: "◆", ok: (p) => MISSOES.every((m) => p.missoes.includes(m.id)) },
];

/* ── página da Academia ────────────────────────────────────────────── */
PAGES.academia = {
  area: "Academia", title: "Trilha do SDR/BDR",
  async render(aba = "trilha", arg) {
    const senha = go.senha;
    const d = await Academia.carregar();
    if (!naVez(senha)) return;
    if (!d) {
      view.innerHTML = panel("Academia", `<div class="alert alert-danger alert-styled-left">Não consegui carregar seu progresso.</div>`);
      return;
    }
    const p = d.progresso;
    const cat = d.catalogo;
    const totalXp = CAPITULOS.length * (cat.capitulos.papeis.leitura + cat.capitulos.papeis.quiz)
      + Object.values(cat.missoes).reduce((a, b) => a + b, 0);
    const prox = d.nivel.proximo;
    const faixa = prox ? Math.min(100, Math.round(((d.xp - d.nivel.desde) / (prox.xp - d.nivel.desde)) * 100)) : 100;
    const abas = [["trilha", "Trilha"], ["missoes", "Missões"], ["conquistas", "Conquistas"], ["glossario", "Glossário"]]
      .concat(nivelPeloMenos("gestor") ? [["time", "Time"]] : []);

    view.innerHTML = `
      <div class="acad-topo">
        <div class="acad-perfil">
          <div class="acad-avatar" id="acadAvatar">${h(state.me.initials || "·")}</div>
          <div class="acad-perfil-txt">
            <span class="acad-eyebrow">Academia BLU</span>
            <h1>${h(d.nivel.nome)}</h1>
            <div class="acad-barra" title="${d.xp} XP"><span id="acadBarra" style="width:0%"></span></div>
            <div class="text-muted text-size-small">${d.xp} XP${prox ? ` · faltam ${prox.xp - d.xp} para <b>${h(prox.nome)}</b>` : " · nível máximo"} · ${Math.round((d.xp / totalXp) * 100)}% da trilha</div>
          </div>
        </div>
        <div class="acad-topo-acoes">
          <button class="btn btn-main" id="acadComecar">▶ ${p.missoes.length ? "Continuar" : "Começar"} o tour guiado</button>
        </div>
      </div>
      <ul class="nav nav-tabs acad-abas">
        ${abas.map(([k, r]) => `<li${k === aba ? ' class="active"' : ""}><a data-acad-aba="${k}">${r}</a></li>`).join("")}
      </ul>
      <div id="acadCorpo"></div>`;

    acadAnimar(document.getElementById("acadBarra"), { width: ["0%", `${faixa}%`] }, { duration: 1.1, delay: 0.15 });
    acadAnimar(document.getElementById("acadAvatar"), { transform: ["scale(.7)", "scale(1)"] }, { spring: true, duration: 0.6 });
    view.querySelectorAll("[data-acad-aba]").forEach((a) => { a.onclick = () => go(`academia/${a.dataset.acadAba}`); });
    document.getElementById("acadComecar").onclick = () => {
      const m = MISSOES.find((x) => !p.missoes.includes(x.id)) || MISSOES[0];
      Tour.iniciar(m.id);
    };

    const corpo = document.getElementById("acadCorpo");
    if (aba === "capitulo") return acadCapitulo(corpo, arg);
    if (aba === "missoes") return acadMissoes(corpo, p, cat);
    if (aba === "conquistas") return acadConquistas(corpo, p);
    if (aba === "glossario") return acadGlossario(corpo);
    if (aba === "time") return acadTime(corpo);
    return acadTrilha(corpo, p, cat);
  },
};

function acadTrilha(corpo, p, cat) {
  const primeiroAberto = CAPITULOS.findIndex((c) => !p.lidos.includes(c.id));
  corpo.innerHTML = `
    <p class="acad-intro">Oito capítulos com o ciclo completo do SDR/BDR, na ordem em que as coisas acontecem. Leia, responda o quiz e faça a missão de cada um.</p>
    <ol class="acad-trilha">
      ${CAPITULOS.map((c, i) => {
        const lido = p.lidos.includes(c.id);
        const q = p.quizzes[c.id];
        const missoes = MISSOES.filter((m) => m.capitulo === c.id);
        const feitasM = missoes.filter((m) => p.missoes.includes(m.id)).length;
        const estado = lido && q && feitasM === missoes.length ? "completo" : i === primeiroAberto ? "atual" : lido ? "andamento" : "";
        return `<li class="acad-no ${estado}" data-cap="${c.id}">
          <div class="acad-no-icone">${estado === "completo" ? "✓" : h(c.icone)}</div>
          <div class="acad-no-txt">
            <span class="acad-eyebrow">Capítulo ${i + 1}</span>
            <h3>${h(c.titulo)}</h3>
            <div class="acad-selos">
              <span class="acad-selo${lido ? " ok" : ""}">${lido ? "Lido" : `Leitura +${cat.capitulos[c.id].leitura} XP`}</span>
              <span class="acad-selo${q ? " ok" : ""}">${q ? `Quiz ${q.acertos}/${q.total}` : `Quiz até +${cat.capitulos[c.id].quiz} XP`}</span>
              ${missoes.map((m) => `<span class="acad-selo${p.missoes.includes(m.id) ? " ok" : ""}">Missão: ${h(m.titulo)}</span>`).join("")}
            </div>
          </div>
          <button class="btn btn-default btn-sm">${lido ? "Rever" : "Abrir"}</button>
        </li>`;
      }).join("")}
    </ol>`;
  const nos = [...corpo.querySelectorAll(".acad-no")];
  const M = window.Motion;
  nos.forEach((n, i) => acadAnimar(n, { opacity: [0, 1], transform: ["translateY(12px)", "translateY(0)"] },
    { duration: 0.4, delay: M && M.stagger ? i * 0.05 : 0 }));
  nos.forEach((n) => { n.onclick = () => go(`academia/capitulo/${n.dataset.cap}`); });
}

function acadCapitulo(corpo, id) {
  const i = CAPITULOS.findIndex((c) => c.id === id);
  const c = CAPITULOS[i];
  if (!c) return go("academia");
  const p = Academia.prog;
  const lido = p.lidos.includes(c.id);
  const missoes = MISSOES.filter((m) => m.capitulo === c.id);
  corpo.innerHTML = `
    <div class="acad-cap">
      <a class="acad-voltar-trilha" data-acad-aba="trilha">‹ Trilha</a>
      <span class="acad-eyebrow">Capítulo ${i + 1} de ${CAPITULOS.length}</span>
      <h2>${h(c.titulo)}</h2>
      <div class="acad-cap-corpo">${c.corpo}</div>
      <div class="acad-cap-acoes">
        <button class="btn ${lido ? "btn-default" : "btn-main"}" id="acadLido"${lido ? " disabled" : ""}>${lido ? "✓ Capítulo lido" : "Marcar como lido"}</button>
        ${missoes.map((m) => `<button class="btn btn-default" data-missao="${m.id}">▶ Missão: ${h(m.titulo)}</button>`).join("")}
      </div>
      <div class="acad-quiz" id="acadQuiz"></div>
      <div class="acad-cap-nav">
        ${i > 0 ? `<a data-cap-ir="${CAPITULOS[i - 1].id}">‹ ${h(CAPITULOS[i - 1].titulo)}</a>` : "<span></span>"}
        ${i < CAPITULOS.length - 1 ? `<a data-cap-ir="${CAPITULOS[i + 1].id}">${h(CAPITULOS[i + 1].titulo)} ›</a>` : ""}
      </div>
    </div>`;
  corpo.querySelector("[data-acad-aba]").onclick = () => go("academia");
  corpo.querySelectorAll("[data-cap-ir]").forEach((a) => { a.onclick = () => go(`academia/capitulo/${a.dataset.capIr}`); });
  corpo.querySelectorAll("[data-missao]").forEach((b) => { b.onclick = () => Tour.iniciar(b.dataset.missao); });
  const bl = document.getElementById("acadLido");
  bl.onclick = async () => {
    bl.disabled = true;
    await Academia.leu(c.id);
    bl.textContent = "✓ Capítulo lido";
    bl.className = "btn btn-default";
    acadAnimar(bl, { transform: ["scale(1)", "scale(1.08)", "scale(1)"] }, { duration: 0.35 });
  };
  acadQuiz(document.getElementById("acadQuiz"), c);
  acadAnimar(corpo.querySelector(".acad-cap"), { opacity: [0, 1], transform: ["translateY(10px)", "translateY(0)"] }, { duration: 0.4 });
}

function acadQuiz(caixa, c) {
  const anterior = Academia.prog.quizzes[c.id];
  const respostas = new Array(c.quiz.length).fill(null);
  caixa.innerHTML = `
    <h3>Quiz do capítulo ${anterior ? `<span class="acad-selo ok">Melhor: ${anterior.acertos}/${anterior.total}</span>` : ""}</h3>
    ${c.quiz.map((q, qi) => `
      <fieldset class="acad-q" data-q="${qi}">
        <legend>${qi + 1}. ${h(q.p)}</legend>
        ${q.o.map((o, oi) => `<label class="acad-op"><input type="radio" name="q${qi}" value="${oi}"> <span>${h(o)}</span></label>`).join("")}
      </fieldset>`).join("")}
    <button class="btn btn-main" id="acadResponder" disabled>Conferir respostas</button>
    <div class="acad-resultado" id="acadResultado" hidden></div>`;
  const btn = caixa.querySelector("#acadResponder");
  caixa.querySelectorAll("input[type=radio]").forEach((r) => {
    r.onchange = () => {
      respostas[Number(r.name.slice(1))] = Number(r.value);
      btn.disabled = respostas.some((x) => x === null);
    };
  });
  btn.onclick = async () => {
    let acertos = 0;
    c.quiz.forEach((q, qi) => {
      const fs = caixa.querySelector(`[data-q="${qi}"]`);
      fs.querySelectorAll(".acad-op").forEach((l, oi) => {
        l.classList.toggle("certa", oi === q.c);
        l.classList.toggle("errada", oi === respostas[qi] && oi !== q.c);
      });
      if (respostas[qi] === q.c) acertos++;
      else acadAnimar(fs, { transform: ["translateX(0)", "translateX(-6px)", "translateX(5px)", "translateX(0)"] }, { duration: 0.35 });
    });
    btn.disabled = true;
    const res = caixa.querySelector("#acadResultado");
    res.hidden = false;
    res.innerHTML = acertos === c.quiz.length
      ? `<b>Gabaritou!</b> ${acertos} de ${c.quiz.length}.`
      : `${acertos} de ${c.quiz.length}. As respostas certas estão marcadas. <a id="acadRefazer">Refazer</a>`;
    acadAnimar(res, { opacity: [0, 1], transform: ["scale(.95)", "scale(1)"] }, { spring: true, duration: 0.45 });
    if (acertos === c.quiz.length) acadConfete(res);
    await Academia.respondeu(c.id, acertos, c.quiz.length);
    const refazer = caixa.querySelector("#acadRefazer");
    if (refazer) refazer.onclick = () => acadQuiz(caixa, c);
  };
}

function acadMissoes(corpo, p, cat) {
  corpo.innerHTML = `
    <p class="acad-intro">Cada missão é um tour guiado que trava a tela e mostra onde clicar. As missões de execução rodam em <b>modo treino</b>, com um lead de mentira.</p>
    <div class="acad-cards">
      ${MISSOES.map((m, i) => {
        const feita = p.missoes.includes(m.id);
        return `<div class="acad-card${feita ? " feita" : ""}">
          <div class="acad-card-icone">${feita ? "✓" : h(m.icone)}</div>
          <span class="acad-eyebrow">Missão ${i + 1} · ${m.passos.length} passos · +${cat.missoes[m.id]} XP</span>
          <h3>${h(m.titulo)}</h3>
          <p class="text-muted">${h(m.resumo)}</p>
          <button class="btn ${feita ? "btn-default" : "btn-main"} btn-sm" data-missao="${m.id}">${feita ? "Refazer" : "Começar"}</button>
        </div>`;
      }).join("")}
    </div>`;
  corpo.querySelectorAll("[data-missao]").forEach((b) => { b.onclick = () => Tour.iniciar(b.dataset.missao); });
  corpo.querySelectorAll(".acad-card").forEach((c, i) =>
    acadAnimar(c, { opacity: [0, 1], transform: ["translateY(14px)", "translateY(0)"] }, { duration: 0.4, delay: i * 0.05 }));
}

function acadConquistas(corpo, p) {
  corpo.innerHTML = `<div class="acad-medalhas">
    ${CONQUISTAS.map((c) => {
      const ok = c.ok(p);
      return `<div class="acad-conquista${ok ? " ok" : ""}">
        <div class="acad-conquista-icone">${h(c.icone)}</div>
        <b>${h(c.nome)}</b><span class="text-muted text-size-small">${h(c.desc)}</span>
        <span class="acad-selo${ok ? " ok" : ""}">${ok ? "Conquistada" : "Bloqueada"}</span>
      </div>`;
    }).join("")}
  </div>`;
  corpo.querySelectorAll(".acad-conquista.ok .acad-conquista-icone").forEach((el, i) =>
    acadAnimar(el, { transform: ["scale(.4) rotate(-30deg)", "scale(1) rotate(0)"] }, { spring: true, duration: 0.6, delay: i * 0.07 }));
}

function acadGlossario(corpo) {
  corpo.innerHTML = `
    <div class="busca-linha" style="margin-bottom:14px"><span class="busca-icone">🔍</span>
      <input id="acadGlossBusca" placeholder="Procurar termo"></div>
    <dl class="acad-glossario">${GLOSSARIO.map(([t, d]) => `<div data-termo="${h(t.toLowerCase())} ${h(d.toLowerCase())}"><dt>${h(t)}</dt><dd>${h(d)}</dd></div>`).join("")}</dl>`;
  const busca = document.getElementById("acadGlossBusca");
  busca.oninput = () => {
    const q = busca.value.trim().toLowerCase();
    corpo.querySelectorAll("[data-termo]").forEach((el) => { el.hidden = q && !el.dataset.termo.includes(q); });
  };
}

async function acadTime(corpo) {
  corpo.innerHTML = LOADING;
  const r = await api("/api/academia/time").catch((e) => ({ erro: e.message }));
  if (r.erro) { corpo.innerHTML = `<div class="alert alert-danger alert-styled-left">${h(r.erro)}</div>`; return; }
  corpo.innerHTML = r.data.length ? table(["Pessoa", "Nível", "XP", "Capítulos", "Quizzes", "Missões", "Última atividade"],
    r.data.map((u) => ({ cells: [
      h(u.nome), `<span class="acad-selo">${h(u.nivel)}</span>`, `<b>${u.xp}</b>`,
      `${u.lidos}/${r.totais.capitulos}`, `${u.quizzes}/${r.totais.capitulos}`, `${u.missoes}/${r.totais.missoes}`,
      u.atualizadoEm ? fmtDateTime(u.atualizadoEm) : "—",
    ] })))
    : emptyState("Ninguém começou a trilha ainda.", "Quem entrar na Academia aparece aqui com o progresso.");
}

/* ── entrada: chip de XP no menu e oferta do tour no primeiro acesso ── */
async function acadIniciar() {
  const d = await Academia.carregar();
  if (!d) return;
  acadAtualizarChip();
  const p = d.progresso;
  if (!p.tourOferecido && !p.missoes.length) {
    await Academia.salvar((x) => { x.tourOferecido = true; });
    const m = modal({
      title: "Bem-vindo ao Bluutime",
      body: `<div class="acad-nivel-up">
          <div class="acad-medalha" id="acadMedalha">▶</div>
          <p class="acad-nivel-nome">Quer um tour guiado?</p>
          <p class="text-muted">Em poucos minutos você faz o ciclo completo de um SDR/BDR: da fila de execução à reunião marcada. Tudo em modo treino, sem risco de mexer em lead de verdade.</p>
        </div>`,
      footer: `<button class="btn btn-default btn-sm" data-depois>Depois</button>
               <button class="btn btn-main btn-sm" data-ok>Começar o tour</button>`,
    });
    acadAnimar(m.root.querySelector("#acadMedalha"), { transform: ["scale(0)", "scale(1)"] }, { spring: true, duration: 0.7, bounce: 0.5 });
    m.root.querySelector("[data-depois]").onclick = () => { m.close(); toast("O tour fica na Academia, no menu de cima."); };
    m.root.querySelector("[data-ok]").onclick = () => { m.close(); Tour.iniciar("execucao"); };
  }
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-tour-iniciar]");
  if (t) { e.preventDefault(); Tour.iniciar(t.dataset.tourIniciar || "execucao"); }
});
