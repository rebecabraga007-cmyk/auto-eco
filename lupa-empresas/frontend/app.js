// Lupa de Empresas - frontend vanilla JS

const API = ""; // mesma origem (backend serve o frontend)

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function situacaoClass(sit) {
  const s = (sit || "").toLowerCase();
  if (s.includes("ativa")) return "ativa";
  if (s.includes("baixada")) return "baixada";
  if (s.includes("suspensa")) return "suspensa";
  if (s.includes("inapta") || s.includes("nula")) return "inativa";
  return "neutra";
}

function onlyDigits(s) { return (s || "").replace(/\D/g, ""); }

// ---------------- Search page ----------------

function initSearchPage() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const btn = document.getElementById("search-btn");
  const results = document.getElementById("results");
  const hint = document.getElementById("empty-hint");

  async function runSearch(q) {
    q = (q || "").trim();
    if (!q) return;
    if (hint) hint.style.display = "none";

    btn.disabled = true;
    results.innerHTML = '<div class="loading-inline"><span class="spinner"></span> Buscando empresas...</div>';

    try {
      const resp = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
      const data = await resp.json();
      renderResults(results, data);
    } catch (err) {
      results.innerHTML = '<div class="msg error">Erro ao buscar. Verifique se o backend esta rodando.</div>';
    } finally {
      btn.disabled = false;
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch(input.value);
  });

  document.querySelectorAll(".chip-example").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.getAttribute("data-q");
      runSearch(input.value);
    });
  });
}

function renderResults(container, data) {
  const list = (data && data.results) || [];
  if (!list.length) {
    const msg = (data && data.message) || "Nenhum resultado encontrado.";
    const cls = data && data.status === "error" ? "msg error" : "msg";
    container.innerHTML = `<div class="${cls}">${esc(msg)}</div>`;
    return;
  }

  container.innerHTML = list.map((c) => {
    const cnpj = onlyDigits(c.cnpj);
    const sitClass = situacaoClass(c.situacao);
    return `
      <div class="card" data-cnpj="${esc(cnpj)}">
        <h3>${esc(c.razao_social || "(sem razao social)")}</h3>
        ${c.nome_fantasia ? `<div class="fantasy">${esc(c.nome_fantasia)}</div>` : ""}
        <div class="meta">
          <span class="cnpj">${esc(c.cnpj)}</span>
          ${(c.municipio || c.uf) ? `<span>${esc(c.municipio)}${c.uf ? " / " + esc(c.uf) : ""}</span>` : ""}
          ${c.situacao ? `<span class="badge ${sitClass}">${esc(c.situacao)}</span>` : ""}
        </div>
      </div>`;
  }).join("");

  container.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => {
      const cnpj = card.getAttribute("data-cnpj");
      window.location.href = `company.html?cnpj=${encodeURIComponent(cnpj)}`;
    });
  });
}

// ---------------- Company detail page ----------------

function initCompanyPage() {
  const params = new URLSearchParams(window.location.search);
  const cnpj = onlyDigits(params.get("cnpj") || "");
  const root = document.getElementById("company-detail");

  if (!cnpj || cnpj.length !== 14) {
    root.innerHTML = '<div class="msg error">CNPJ invalido.</div>';
    return;
  }

  loadCompany(cnpj, root);
}

async function loadCompany(cnpj, root) {
  let data;
  try {
    const resp = await fetch(`${API}/api/company/${cnpj}`);
    data = await resp.json();
    if (!resp.ok || data.status !== "ok") {
      root.innerHTML = `<div class="msg error">${esc(data.message || "Empresa nao encontrada.")}</div>`;
      return;
    }
  } catch (err) {
    root.innerHTML = '<div class="msg error">Erro ao carregar a empresa.</div>';
    return;
  }

  renderCompany(root, cnpj, data.company);
  initConexoesBotao();
  autoLoadSocioPhones(data.company.qsa || []);
  // SOMENTE agora (pagina de detalhe carregada) dispara o scraping.
  loadEmployees(cnpj);
}

function fieldHtml(label, value) {
  if (value === undefined || value === null || value === "") return "";
  return `<div class="field"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}

function fmtDate(d) {
  if (!d) return "";
  const parts = String(d).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : d;
}

function fmtMoney(v) {
  if (v === undefined || v === null || v === "") return "";
  const n = Number(v);
  if (isNaN(n)) return v;
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtCnpj(digits) {
  const d = onlyDigits(digits);
  if (d.length !== 14) return digits;
  return `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12,14)}`;
}

function fmtCpf(digits) {
  const d = onlyDigits(digits);
  if (d.length !== 11) return digits;
  return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9,11)}`;
}

function renderCompany(root, cnpj, c) {
  const endereco = [
    [c.descricao_tipo_de_logradouro, c.logradouro].filter(Boolean).join(" "),
    c.numero,
    c.complemento,
    c.bairro,
  ].filter(Boolean).join(", ");
  const cidadeUf = [c.municipio, c.uf].filter(Boolean).join(" / ");
  const cep = c.cep ? String(c.cep).replace(/(\d{5})(\d{3})/, "$1-$2") : "";

  const tel1 = c.ddd_telefone_1 || "";
  const tel2 = c.ddd_telefone_2 || "";

  const cnaesSec = Array.isArray(c.cnaes_secundarios) ? c.cnaes_secundarios : [];
  const qsa = Array.isArray(c.qsa) ? c.qsa : [];

  root.innerHTML = `
    <div class="section">
      <h1 class="company-title">${esc(c.razao_social || "")}</h1>
      <p class="company-sub">
        ${c.nome_fantasia ? esc(c.nome_fantasia) + " &middot; " : ""}
        ${esc(fmtCnpj(cnpj))}
        ${c.descricao_situacao_cadastral ? ` &middot; <span class="badge ${situacaoClass(c.descricao_situacao_cadastral)}">${esc(c.descricao_situacao_cadastral)}</span>` : ""}
      </p>

      <p>
        <button type="button" id="btn-conexoes" data-cnpj="${esc(cnpj)}"
                title="Sócios, possíveis decisores e empresas ligadas — com telefone. 1 consulta Assertiva.">
          🔗 Buscar conexões (Assertiva)
        </button>
      </p>
      <div id="conexoes-box"></div>

      <h2>Dados da Empresa</h2>
      <div class="grid">
        ${fieldHtml("Natureza Juridica", c.natureza_juridica)}
        ${fieldHtml("Porte", c.porte)}
        ${fieldHtml("Capital Social", fmtMoney(c.capital_social))}
        ${fieldHtml("Data de Abertura", fmtDate(c.data_inicio_atividade))}
        ${fieldHtml("Situacao Cadastral", c.descricao_situacao_cadastral)}
        ${fieldHtml("Data da Situacao", fmtDate(c.data_situacao_cadastral))}
        ${fieldHtml("E-mail", c.email)}
        ${fieldHtml("Telefone 1", tel1)}
        ${fieldHtml("Telefone 2", tel2)}
      </div>

      <div class="subhead">CNAE Principal</div>
      <div class="chips">
        ${c.cnae_fiscal ? `<span class="chip">${esc(c.cnae_fiscal)} - ${esc(c.cnae_fiscal_descricao || "")}</span>` : '<span class="value">-</span>'}
      </div>

      ${cnaesSec.length ? `
      <div class="subhead">CNAEs Secundarios</div>
      <div class="chips">
        ${cnaesSec.map((x) => `<span class="chip">${esc(x.codigo)} - ${esc(x.descricao || "")}</span>`).join("")}
      </div>` : ""}

      <div class="subhead">Endereco</div>
      <div class="grid">
        ${fieldHtml("Logradouro", endereco)}
        ${fieldHtml("Cidade / UF", cidadeUf)}
        ${fieldHtml("CEP", cep)}
      </div>

      ${qsa.length ? `
      <div class="subhead">Quadro Societario (QSA)</div>
      <div class="people">
        ${qsa.map((s, idx) => {
          const cpfRaw = s.cpf_completo || "";
          const cpf = cpfRaw ? fmtCpf(cpfRaw) : (s.cnpj_cpf_do_socio || "");
          const cpfCls = cpfRaw ? "cpf-resolved" : "cpf-masked";
          const nome = esc(s.nome_socio || s.nome || "");
          const sid = `socio-${idx}`;
          return `
          <div class="person" id="${sid}">
            <span class="name">${nome}</span>
            <span class="role">${esc(s.qualificacao_socio || s.qual || "")}</span>
            ${cpf ? `<span class="cpf-tag ${cpfCls}">CPF: ${esc(cpf)}</span>` : ""}
            <div class="socio-actions">
              ${cpfRaw
                ? `<span class="socio-phone" id="phone-${sid}">⏳ buscando tel…</span>
                   <span class="dzap-badge" id="dzap-${sid}" title=""></span>
                   <button class="btn-copiar" onclick="copiarCpf(this,'${cpfRaw}')" title="Copiar CPF">📋 Copiar CPF</button>
                   <button class="btn-ver-mais" onclick="verMaisSocio('${sid}','${cpfRaw}','')">Ver mais</button>`
                : `<button class="btn-ver-mais" onclick="verMaisSocio('${sid}','','${s.nome_socio||s.nome||''}')">Ver mais</button>`
              }
            </div>
            <div class="socio-detail" id="detail-${sid}" style="display:none"></div>
          </div>`;
        }).join("")}
      </div>` : ""}
    </div>

    <div class="section" id="employees-section">
      <h2>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
        Funcionarios (LinkedIn)
      </h2>
      <div id="employees-body">
        <div class="loading-inline"><span class="spinner"></span> Buscando funcionarios no LinkedIn...</div>
      </div>
    </div>
  `;
}

function autoLoadSocioPhones(qsa) {
  qsa.forEach((s, idx) => {
    const cpfRaw = s.cpf_completo || "";
    if (!cpfRaw) return;
    const sid = `socio-${idx}`;
    const nomeSocio = s.nome_socio || s.nome || "";
    fetch(`${API}/api/person/${cpfRaw}/mk`)
      .then(r => r.json())
      .then(mk => {
        const span = document.getElementById(`phone-${sid}`);
        if (!span) return;
        const d = (mk.data || {});
        const tels = d.telefones || [];
        if (!tels.length) { span.textContent = "sem tel"; return; }
        const best = tels[0];
        const num = best.ddd ? `(${best.ddd}) ${best.telefone}` : best.telefone;
        const raw = best.ddd ? `${best.ddd}${best.telefone}` : best.telefone;
        span.textContent = num;
        span.classList.add("phone-ready");

        // Validação donodozap em background
        const badge = document.getElementById(`dzap-${sid}`);
        if (!badge) return;
        badge.textContent = "⏳";
        badge.title = "Validando no DonoDoZap…";
        const nomeMk = d.nome || d.name || nomeSocio;
        fetch(`${API}/api/phone/${encodeURIComponent(raw)}/donodozap?nome=${encodeURIComponent(nomeMk)}`)
          .then(r => r.json())
          .then(v => {
            if (v.confidence === "high") {
              badge.textContent = "✅";
              badge.title = `Alta confiança — confirmado como "${v.match}" no DonoDoZap`;
              badge.className = "dzap-badge dzap-ok";
            } else if (v.status === "ok") {
              badge.textContent = "⚠️";
              badge.title = `Telefone encontrado, mas nome não bate. Titulares: ${(v.names || []).slice(0, 3).join(", ")}`;
              badge.className = "dzap-badge dzap-warn";
            } else {
              badge.textContent = "❓";
              badge.title = v.message || "Não encontrado no DonoDoZap";
              badge.className = "dzap-badge dzap-unknown";
            }
          })
          .catch(() => { badge.textContent = ""; });
      })
      .catch(() => {
        const span = document.getElementById(`phone-${sid}`);
        if (span) span.textContent = "–";
      });
  });
}

function copiarCpf(btn, cpf) {
  const txt = String(cpf || "").replace(/\D/g, "");
  const done = () => {
    const old = btn.textContent;
    btn.textContent = "✅ Copiado!";
    btn.classList.add("copiado");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("copiado"); }, 1500);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(done).catch(() => fallbackCopy(txt, done));
  } else {
    fallbackCopy(txt, done);
  }
}
function fallbackCopy(txt, done) {
  const ta = document.createElement("textarea");
  ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {}
  ta.remove();
}

async function verMaisSocio(sid, cpf, nome) {
  const detail = document.getElementById(`detail-${sid}`);
  if (!detail) return;
  if (detail.style.display !== "none") {
    detail.style.display = "none";
    return;
  }
  detail.style.display = "block";
  detail.innerHTML = `<span class="spinner-sm"></span> Consultando Mk…`;

  try {
    let mk, jbr;
    if (cpf) {
      [mk, jbr] = await Promise.all([
        fetch(`${API}/api/person/${cpf}/mk`).then(r => r.json()),
        fetch(`${API}/api/person/${cpf}`).then(r => r.json()),
      ]);
    } else {
      mk = { status: "unavailable" };
      jbr = null;
    }

    const d = (mk.data || {});
    const nome_display = (d.nome || d.name || (jbr && jbr.pessoa && jbr.pessoa.nome) || nome || "").toUpperCase();
    const nasc = jbr && jbr.pessoa && jbr.pessoa.nascimento;
    const sexo = jbr && jbr.pessoa && jbr.pessoa.sexo;

    const tels = d.telefones || [];
    const enderecos = d.enderecos || [];
    const empresas = d.empresas || d.empregos || [];

    const header = `<div class="socio-detail-header">
      ${nome_display ? `<strong>${esc(nome_display)}</strong>` : ""}
      ${nasc ? ` &middot; Nasc: ${fmtDate(nasc)}` : ""}
      ${sexo ? ` &middot; ${sexo === "M" ? "Masculino" : "Feminino"}` : ""}
      ${cpf ? ` &middot; CPF: ${fmtCpf(cpf)}` : ""}
    </div>`;

    let telHtml = "";
    if (tels.length) {
      telHtml = `<div class="socio-section-title">📞 Telefones</div>
        <div class="socio-pills">${tels.map(t => {
          const num = t.ddd ? `(${t.ddd}) ${t.telefone}` : t.telefone;
          const wa = t.whatsapp ? " 🟢" : "";
          return `<span class="socio-pill">${esc(num)}${wa}</span>`;
        }).join("")}</div>`;
    }

    let endHtml = "";
    if (enderecos.length) {
      endHtml = `<div class="socio-section-title">📍 Endereços</div>
        <div class="socio-pills">${enderecos.map(e => {
          const parts = [e.cidade, e.uf, e.bairro].filter(Boolean);
          return `<span class="socio-pill">${esc(parts.join(", "))}</span>`;
        }).join("")}</div>`;
    }

    let empHtml = "";
    if (empresas.length) {
      empHtml = `<div class="socio-section-title">🏢 Empresas/Empregos</div>
        <div class="socio-pills">${empresas.slice(0, 8).map(e => {
          const label = typeof e === "string" ? e : (e.nome || e.empresa || e.name || JSON.stringify(e));
          return `<span class="socio-pill">${esc(label)}</span>`;
        }).join("")}</div>`;
    }

    const empty = !tels.length && !enderecos.length && !empresas.length;
    detail.innerHTML = header + telHtml + endHtml + empHtml + (empty ? `<span class="socio-empty">Sem dados enriquecidos disponíveis.</span>` : "");

  } catch (err) {
    detail.innerHTML = `<span class="socio-empty">Erro ao consultar Mk: ${esc(String(err).slice(0, 80))}</span>`;
  }
}

async function loadEmployees(cnpj) {
  const body = document.getElementById("employees-body");
  if (!body) return;

  try {
    const resp = await fetch(`${API}/api/company/${cnpj}/employees`);
    const data = await resp.json();

    if (data.status === "blocked") {
      body.innerHTML = `<div class="warning">${esc(data.message || "LinkedIn bloqueou a requisicao.")}</div>`;
      return;
    }

    const list = data.employees || [];
    const sourceLabel = data.source === "brightdata" ? "Bright Data" : (data.source === "google" ? "Google" : "");
    const sourceBadge = sourceLabel ? `<div class="source-badge">Fonte: ${esc(sourceLabel)} &middot; ${list.length} resultado(s)</div>` : "";

    const co = data.company || null;
    let coHtml = "";
    if (co && co.name) {
      const bits = [];
      if (co.industries) bits.push(esc(co.industries));
      if (co.headquarters) bits.push(esc(co.headquarters));
      if (co.employees_in_linkedin) bits.push(`${Number(co.employees_in_linkedin).toLocaleString("pt-BR")} funcionarios no LinkedIn`);
      const link = co.linkedin_url ? ` &middot; <a href="${esc(co.linkedin_url)}" target="_blank" rel="noopener">ver no LinkedIn</a>` : "";
      coHtml = `<div class="linkedin-company"><strong>${esc(co.name)}</strong>${bits.length ? " &middot; " + bits.join(" &middot; ") : ""}${link}</div>`;
    }

    if (!list.length) {
      body.innerHTML = sourceBadge + coHtml + `<div class="warning">${esc(data.message || "Nenhum funcionario publico em destaque.")}</div>`;
      return;
    }

    body.innerHTML = sourceBadge + coHtml + `<div class="people">${list.map((e) => `
      <div class="person">
        ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.name)}</a>` : `<span class="name">${esc(e.name)}</span>`}
        ${e.title ? `<span class="role">${esc(e.title)}</span>` : ""}
        ${e.cpf ? `<span class="cpf-tag cpf-resolved">CPF: ${esc(fmtCpf(e.cpf))}</span>` : (e.cpf_status === "ambiguous" ? `<span class="cpf-tag cpf-masked">CPF: vários homônimos</span>` : "")}
      </div>`).join("")}</div>`;
  } catch (err) {
    body.innerHTML = '<div class="warning">Erro ao buscar funcionarios no LinkedIn.</div>';
  }
}

// ── Conexões da empresa (Assertiva): sócios, possíveis decisores e empresas
// ligadas, cada um com telefone e flag de WhatsApp. Custa 1 consulta, então é
// opt-in por botão — nunca dispara sozinho ao abrir a página.
function initConexoesBotao() {
  const btn = document.getElementById("btn-conexoes");
  if (!btn) return;
  btn.addEventListener("click", () => carregarConexoes(btn.dataset.cnpj, btn));
}

async function carregarConexoes(cnpj, btn) {
  const box = document.getElementById("conexoes-box");
  const rotulo = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Buscando conexoes...";
  box.innerHTML = '<div class="loading-inline"><span class="spinner"></span> Consultando a Assertiva...</div>';
  try {
    const d = await fetch(`${API}/api/company/${onlyDigits(cnpj)}/conexoes`).then((r) => r.json());
    box.innerHTML = conexoesHtml(d);
  } catch (e) {
    box.innerHTML = `<div class="msg error">Erro ao buscar conexoes: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = rotulo;
  }
}

function conexoesHtml(d) {
  if (d.status === "unavailable") return `<div class="msg">${esc(d.message || "Assertiva nao configurada.")}</div>`;
  if (d.status === "not_found" || !d.total) return '<div class="msg">Nenhuma conexao encontrada para este CNPJ.</div>';
  if (d.status !== "ok") return `<div class="msg error">${esc(d.message || "Falha ao consultar conexoes.")}</div>`;

  const linhas = (d.conexoes || []).map((c) => {
    const doc = onlyDigits(c.documento || "");
    const docFmt = doc.length === 11 ? fmtCpf(doc) : doc.length === 14 ? fmtCnpj(doc) : (c.documento || "");
    const zap = c.whatsapp ? " (WhatsApp)" : "";
    const np = c.naoPerturbe ? " (nao perturbe)" : "";
    return `<tr>
      <td>${esc(c.relacao || c.tipoRelacao || "-")}</td>
      <td>${esc(c.nomeOuRazaoSocial || "-")}</td>
      <td>${esc(docFmt)}</td>
      <td>${esc(c.cargo || "")}</td>
      <td>${c.telefone ? esc(c.telefone) + zap + np : "-"}</td>
    </tr>`;
  }).join("");

  return `
    <div class="subhead">Conexoes na Assertiva — ${d.total} (${d.com_telefone} com telefone)</div>
    <table class="table">
      <thead><tr><th>Relacao</th><th>Nome</th><th>Documento</th><th>Cargo</th><th>Telefone</th></tr></thead>
      <tbody>${linhas}</tbody>
    </table>`;
}
