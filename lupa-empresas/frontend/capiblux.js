// ══════════════════════════════════════════════════════
//  CapiBLU — frontend logic
// ══════════════════════════════════════════════════════

const API = '';  // same origin

// ── Menu hambúrguer (sidebar colapsa em telas pequenas) ──────────────
(function initHamburger() {
  const btn = document.getElementById('hamburger-btn');
  const sidebar = document.getElementById('sidebar');
  if (!btn || !sidebar) return;
  btn.addEventListener('click', () => {
    const open = sidebar.classList.toggle('mobile-open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
})();

// ── Tab navigation ──────────────────────────────────
let _prospAutoLoaded = false;
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    // Ao abrir Prospecção pela 1ª vez, já mostra uma lista (empresas ativas) —
    // igual à Datastone, que carrega resultados sem precisar pesquisar nada.
    if (tab === 'prospec' && !_prospAutoLoaded && typeof prospBuscar === 'function') {
      _prospAutoLoaded = true;
      prospBuscar();
    }
    if (tab === 'admin' && typeof admCarregar === 'function') admCarregar();
    if (tab === 'inicio' && typeof inicioCarregar === 'function') inicioCarregar();
    fetch(`${API}/api/navlog`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tab }) }).catch(() => {});
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.remove('mobile-open');
  });
});

// ── Utils ────────────────────────────────────────────
function fmtCpf(v) {
  const d = v.replace(/\D/g, '').slice(0, 11);
  return d.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4')
          .replace(/(\d{3})(\d{3})(\d{3})$/, '$1.$2.$3')
          .replace(/(\d{3})(\d{3})$/, '$1.$2')
          .replace(/(\d{3})$/, '$1');
}
function fmtCnpj(v) {
  const d = v.replace(/\D/g, '').slice(0, 14);
  return d.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');
}
function onlyDigits(s) { return (s || '').replace(/\D/g, ''); }
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function spinner() {
  return `<div class="spinner-wrap"><div class="spinner"></div><span>Consultando…</span></div>`;
}
function fmtPhone(raw) {
  const d = onlyDigits(raw);
  if (d.length === 11) return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
  return raw;
}
// Traduz o termo cru da Receita pra português claro — nunca mostrar "BAIXADA"/"INAPTA" sozinho.
function situacaoClara(sit) {
  const s = (sit || '').toLowerCase();
  if (s.includes('ativa') || s.includes('regular')) return 'Em atividade';
  if (s.includes('baixa')) return 'Fechada';
  if (s.includes('suspens')) return 'Suspensa na Receita';
  if (s.includes('inapt')) return 'Inapta na Receita';
  if (s.includes('nula')) return 'Cadastro anulado';
  return sit || 'Situação desconhecida';
}
function badgeSit(sit) {
  const s = (sit || '').toLowerCase();
  const label = situacaoClara(sit);
  if (s.includes('ativa') || s.includes('regular')) return `<span class="badge badge-ativa">${esc(label)}</span>`;
  if (s.includes('baixa') || s.includes('inapt') || s.includes('suspens')) return `<span class="badge badge-inativa">${esc(label)}</span>`;
  return `<span class="badge badge-neutra">${esc(label)}</span>`;
}
function scoreColor(n) {
  if (n >= 700) return 'var(--green)';
  if (n >= 400) return 'var(--amber)';
  return 'var(--red)';
}

// ── CPF input mask ───────────────────────────────────
document.getElementById('cpf-q').addEventListener('input', e => {
  const cur = e.target.selectionStart;
  e.target.value = fmtCpf(e.target.value);
});

// ── Accordion helper ─────────────────────────────────
function makeAccordion(icon, title, count, bodyHtml) {
  const id = 'acc-' + Math.random().toString(36).slice(2);
  return `
  <div class="accordion">
    <div class="accordion-head" onclick="toggleAcc('${id}')">
      <span class="accordion-title">${icon} ${esc(title)} ${count > 0 ? `<span class="acc-count">${count}</span>` : ''}</span>
      <span class="accordion-chevron" id="chev-${id}">▼</span>
    </div>
    <div class="accordion-body" id="${id}">
      ${count === 0 ? '<p class="empty-section">Nenhum dado encontrado.</p>' : bodyHtml}
    </div>
  </div>`;
}
window.toggleAcc = function(id) {
  const body = document.getElementById(id);
  const head = body.previousElementSibling;
  const chev = document.getElementById('chev-' + id);
  body.classList.toggle('open');
  head.classList.toggle('open');
};

// ══════════════════════════════════════════════════════
//  MÓDULO EMPRESA
// ══════════════════════════════════════════════════════
const empQ   = document.getElementById('emp-q');
const empBtn = document.getElementById('emp-btn');
const empRes = document.getElementById('emp-results');

async function searchEmpresa() {
  const q = empQ.value.trim();
  if (!q) return;
  empBtn.disabled = true;
  empRes.innerHTML = spinner();
  try {
    const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();
    renderEmpresas(data);
    const listaEmp = Array.isArray(data) ? data : (data?.companies || data?.results || []);
    logBusca('Empresa', q, `${listaEmp.length} empresa${listaEmp.length === 1 ? '' : 's'}`);
  } catch(e) {
    empRes.innerHTML = `<p class="msg error">Erro ao consultar: ${esc(e.message)}</p>`;
  } finally {
    empBtn.disabled = false;
  }
}

function renderEmpresas(data) {
  if (!data || data.error) {
    empRes.innerHTML = `<p class="msg error">${esc(data?.message || data?.error || 'Erro desconhecido')}</p>`;
    return;
  }
  const list = Array.isArray(data) ? data : (data.companies || data.results || []);
  if (!list.length) {
    empRes.innerHTML = `<p class="msg">Nenhuma empresa encontrada${data?.message ? ': ' + esc(data.message) : '.'}</p>`;
    return;
  }
  const termoRaw = empQ.value.trim();
  const termo = /^[\d.\/\-]+$/.test(termoRaw) ? '' : esc(termoRaw);
  const rows = list.map(emp => {
    const cnpj = fmtCnpj(emp.cnpj || emp.tax_id || '');
    const razao = emp.razao_social || emp.company_name || '';
    const fantasia = emp.nome_fantasia || '';
    const cidade = emp.municipio || emp.city || '';
    const uf = emp.uf || emp.state || '';
    const sit = emp.descricao_situacao_cadastral || emp.status || emp.situacao_cadastral || '';
    return `
    <a class="result-row" href="company.html?cnpj=${onlyDigits(cnpj)}" target="_blank">
      <div>
        <div class="result-name">${esc(razao)}</div>
        <div class="result-meta mono">${esc(cnpj)}</div>
        ${cidade ? `<div class="result-meta">📍 ${esc(cidade)}${uf ? '/' + esc(uf) : ''}</div>` : ''}
        ${fantasia && fantasia !== razao ? `<div class="result-fantasy">${esc(fantasia)}</div>` : ''}
      </div>
      <div class="result-actions">
        ${badgeSit(sit)}
        <button class="btn-secondary" onclick="event.preventDefault(); event.stopPropagation(); exportarDossie('cnpj','${onlyDigits(cnpj)}', this)">📄 PDF</button>
        <span class="result-link">Ver detalhes →</span>
      </div>
    </a>`;
  }).join('');
  empRes.innerHTML = `
    <div class="results-head">
      <h2>${list.length} empresa${list.length === 1 ? '' : 's'}${termo ? ` com "${termo}" no nome` : ''}</h2>
      <span class="results-head-note">Fonte: Receita Federal</span>
    </div>
    <div class="result-list">${rows}</div>
    <div class="dica">
      <div class="dica-title">"Fechada", "suspensa", "em atividade" — o que muda pra mim?</div>
      <div class="dica-body">Só empresa em atividade compra. As outras aparecem porque o sócio pode ter aberto uma empresa nova — abra os detalhes para ver.</div>
    </div>`;
}

empBtn.addEventListener('click', searchEmpresa);
empQ.addEventListener('keydown', e => e.key === 'Enter' && searchEmpresa());
document.querySelectorAll('.chip-ex').forEach(c => {
  c.addEventListener('click', () => { empQ.value = c.dataset.val; searchEmpresa(); });
});

// ══════════════════════════════════════════════════════
//  MÓDULO PESSOA / CPF
// ══════════════════════════════════════════════════════
const cpfQ   = document.getElementById('cpf-q');
const cpfBtn = document.getElementById('cpf-btn');
const cpfRes = document.getElementById('cpf-results');

async function searchCpf() {
  const raw = onlyDigits(cpfQ.value);
  if (raw.length < 11) { cpfRes.innerHTML = `<p class="msg error">CPF inválido.</p>`; return; }
  cpfBtn.disabled = true;
  cpfRes.innerHTML = spinner();
  try {
    const [jbrRes, mkRes] = await Promise.all([
      fetch(`${API}/api/person/${raw}`).then(r => r.json()),
      fetch(`${API}/api/person/${raw}/mk`).then(r => r.json()),
    ]);
    renderPessoa(raw, jbrRes, mkRes);
    const nomeAchado = jbrRes?.pessoa?.nome || mkRes?.data?.DadosBasicos?.nome || '';
    logBusca('CPF', fmtCpf(raw), nomeAchado ? `Encontrado: ${nomeAchado}` : 'Sem dados encontrados');
  } catch(e) {
    cpfRes.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    cpfBtn.disabled = false;
  }
}

function renderPessoa(cpf, jbr, mk) {
  const jbrP = jbr?.pessoa || {};
  const mkD  = mk?.data || {};
  const db   = mkD.DadosBasicos || {};
  const de   = mkD.DadosEconomicos || {};
  const prof = mkD.profissao || {};

  const nome     = db.nome || jbrP.nome || '—';
  const nasc     = db.dataNascimento || jbrP.nascimento || '—';
  const sexo     = (db.sexo || jbrP.sexo || '').replace(' - ', '/');
  const mae      = db.nomeMae || '—';
  const sit      = (db.situacaoCadastral || {}).descricaoSituacaoCadastral || jbr?.status || '—';
  const ec       = db.estadoCivil || '';
  const obito    = (db.obito || {}).obito || '';
  const esc_     = db.escolaridade || '';
  const renda    = de.renda ? `R$ ${de.renda}` : '—';
  const faixaRenda = (de.poderAquisitivo || {}).faixaPoderAquisitivo || '';
  const scoreVal = parseInt((de.score || {}).scoreCSBA) || 0;
  const scoreLabel = (de.score || {}).scoreCSBAFaixaRisco || '';
  const mosaic   = (de.serasaMosaic || {}).descricaoMosaicNovo || (de.serasaMosaic || {}).descricaoMosaic || '';
  const cbo      = prof.cboDescricao && !prof.cboDescricao.toLowerCase().includes('sem') ? prof.cboDescricao : '';

  const sitGood = sit.toLowerCase().includes('regular') || sit.toLowerCase().includes('ativa');
  const sitBad  = sit.toLowerCase().includes('suspens') || sit.toLowerCase().includes('cancelad');
  const obitoMort = obito && obito !== 'NÃO' && obito !== 'NÃO' && obito !== 'NAO';

  // Idade a partir de dd/mm/aaaa (quando disponível).
  let idade = null;
  if (nasc !== '—' && /^\d{2}\/\d{2}\/\d{4}$/.test(nasc)) {
    const [d, m, y] = nasc.split('/').map(Number);
    const hoje = new Date();
    idade = hoje.getFullYear() - y - ((hoje.getMonth() + 1 < m || (hoje.getMonth() + 1 === m && hoje.getDate() < d)) ? 1 : 0);
  }
  const sitClara = sit === '—' ? '' : (
    sitGood ? `CPF regular na Receita` : sitBad ? `CPF suspenso na Receita` : `CPF ${sit.toLowerCase()}`
  );

  // Cabeçalho (nome + CPF/idade/nascimento à esquerda; situação + protocolo à direita).
  let banner = `
  <div class="person-header">
    <div>
      <h2>${esc(nome)}</h2>
      <div class="cpf-num">${fmtCpf(cpf)}${idade !== null ? ` · ${idade} anos` : ''}${nasc !== '—' ? ` · nascida em ${esc(nasc)}` : ''}</div>
    </div>
    <div class="person-header-right">
      ${sitClara ? `<span class="badge ${sitGood ? 'badge-ativa' : sitBad ? 'badge-inativa' : 'badge-neutra'}">${esc(sitClara)}</span>` : ''}
      ${obitoMort ? `<span class="badge badge-inativa">Óbito registrado</span>` : ''}
      <button class="btn-secondary" onclick="exportarDossie('cpf','${onlyDigits(cpf)}', this)">📄 Exportar PDF</button>
      <span class="person-header-note">consultado agora</span>
    </div>
  </div>`;

  // Métricas explicadas (mãe, renda, score) — cada uma diz o que significa, não só o número.
  let infoCards = `<div class="metric-grid">`;
  infoCards += `
    <div class="metric-cell">
      <div class="metric-label">Nome da mãe</div>
      <div class="metric-value">${esc(mae)}</div>
      <div class="metric-sub">Serve para confirmar que é a pessoa certa.</div>
    </div>`;
  if (renda !== '—') infoCards += `
    <div class="metric-cell">
      <div class="metric-label">Renda estimada</div>
      <div class="metric-value mono">${esc(renda)}</div>
      <div class="metric-sub">${faixaRenda ? esc(faixaRenda) + '. ' : ''}Estimativa, não é salário confirmado.</div>
    </div>`;
  if (scoreVal) {
    const pct = Math.min(scoreVal, 1000) / 10;
    infoCards += `
    <div class="metric-cell">
      <div class="metric-label">Score de crédito</div>
      <div class="metric-value mono">${scoreVal} <span style="font-family:'IBM Plex Sans',sans-serif;font-size:13px;font-weight:600;color:${scoreColor(scoreVal)}">${esc(scoreLabel || '')}</span></div>
      <div class="metric-bar"><div class="metric-bar-fill" style="width:${pct}%;background:${scoreColor(scoreVal)}"></div></div>
      <div class="metric-sub">Vai de 0 a 1000. Quanto maior, menor o risco de inadimplência.</div>
    </div>`;
  }
  if (mosaic) infoCards += `<div class="metric-cell"><div class="metric-label">Perfil Mosaic</div><div class="metric-value">${esc(mosaic)}</div></div>`;
  if (cbo)    infoCards += `<div class="metric-cell"><div class="metric-label">Profissão declarada</div><div class="metric-value">${esc(cbo)}</div></div>`;
  if (esc_)   infoCards += `<div class="metric-cell"><div class="metric-label">Escolaridade</div><div class="metric-value">${esc(esc_)}</div></div>`;
  infoCards += `</div>`;

  // Endereços
  const enderecos = mkD.enderecos || [];
  const endHtml = enderecos.length ? `
  <table class="data-table">
    <thead><tr><th>Logradouro</th><th>Bairro</th><th>Cidade/UF</th><th>CEP</th></tr></thead>
    <tbody>${enderecos.map(e => `
      <tr>
        <td>${esc((e.tipoLogradouro||'')+' '+(e.logradouro||'')+' '+(e.logradouroNumero||'')+' '+(e.complemento||''))}</td>
        <td>${esc(e.bairro||'')}</td>
        <td>${esc((e.cidade||'')+'/'+(e.uf||''))}</td>
        <td>${esc(e.cep||'')}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '';

  // Telefones
  const telefones = mkD.telefones || [];
  const telHtml = telefones.length ? `
  <div style="margin-bottom:10px">
    <button class="btn-secondary" onclick="verificarTelefonesCpf('${cpf}')">Conferir se os telefones são dela</button>
    <span class="tel-verify-hint">confere, na base de telefone reverso, se cada número realmente aponta pra este CPF</span>
  </div>
  <table class="data-table" id="tel-verify-table">
    <thead><tr><th>Telefone</th><th>Tipo</th><th>Operadora</th><th>Tem WhatsApp?</th><th>É dela mesmo?</th></tr></thead>
    <tbody>${telefones.map(t => {
      const raw = onlyDigits(t.telefone||t.numero||'');
      return `
      <tr>
        <td class="td-phone">${esc(fmtPhone(t.telefone||t.numero||''))}</td>
        <td>${esc(t.tipo||'')}</td>
        <td>${esc(t.operadora||'')}</td>
        <td>${t.whatsapp ? 'Sim' : 'Não sabemos'}</td>
        <td class="tel-verify-cell" data-raw="${raw}">Não conferido</td>
      </tr>`;}).join('')}
    </tbody>
  </table>` : '';

  // Emails
  const emails = mkD.emails || [];
  const emailHtml = emails.length ? `
  <table class="data-table">
    <thead><tr><th>Email</th><th>Qualidade</th><th>Pessoal</th></tr></thead>
    <tbody>${emails.map(e => `
      <tr>
        <td>${esc(e.email||'')}</td>
        <td>${esc(e.qualidade||'')}</td>
        <td>${e.emailPessoal === 'SIM' ? '✅' : '—'}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '';

  // Empresas
  const empresas = mkD.empresas || [];
  const empHtml = empresas.length ? `
  <table class="data-table">
    <thead><tr><th>CNPJ</th><th>Relação</th><th>Admissão</th><th>Saída</th></tr></thead>
    <tbody>${empresas.map(e => `
      <tr>
        <td><a href="company.html?cnpj=${onlyDigits(e.cnpj||'')}" target="_blank" style="color:var(--blue-mid)">${esc(fmtCnpj(e.cnpj||''))}</a></td>
        <td>${esc(e.relacao||e.tipoRelacao||'')}</td>
        <td>${esc(e.admissao||'')}</td>
        <td>${esc(e.demissao === '31/12/9999' ? 'Atual' : (e.demissao||''))}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '';

  // Parentes
  const parentes = mkD.parentes || [];
  const parHtml = parentes.length ? `
  <table class="data-table">
    <thead><tr><th>Nome</th><th>CPF</th><th>Grau</th></tr></thead>
    <tbody>${parentes.map(p => `
      <tr>
        <td>${esc(p.nomeParente||'')}</td>
        <td class="td-phone">${esc(fmtCpf(p.cpfParente||''))}</td>
        <td>${esc(p.grauParentesco||'')}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '';

  // Vizinhos
  const vizinhos = mkD.vizinhos || [];
  const vizHtml = vizinhos.length ? `
  <table class="data-table">
    <thead><tr><th>Nome</th><th>Nascimento</th><th>CPF</th><th>Sexo</th></tr></thead>
    <tbody>${vizinhos.map(v => `
      <tr>
        <td>${esc(v.nome||'')}</td>
        <td>${esc(v.dataNascimento||'')}</td>
        <td class="td-phone">${esc(fmtCpf(v.cpf||''))}</td>
        <td>${(v.sexo||'').includes('F') ? '♀' : (v.sexo||'').includes('M') ? '♂' : '—'}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '';

  // Perfil de consumo (flags true)
  const pc = mkD.perfilConsumo || {};
  const pcTrue = Object.entries(pc).filter(([,v]) => v === true).map(([k]) =>
    k.replace(/_/g,' ').replace('possui ','✅ ').replace('credito','crédito')
  );
  const pcProb = Object.entries(pc).filter(([,v]) => typeof v === 'string' && v.includes('%')).map(([k,v]) =>
    `<span style="font-size:.8rem;background:var(--gray-100);padding:3px 10px;border-radius:6px;display:inline-block;margin:2px">${k.replace(/_/g,' ')}: ${v.replace(' de probabilidade positiva.','')}</span>`
  );
  const pcHtml = (pcTrue.length || pcProb.length) ? `
  <div style="padding:14px 16px">
    ${pcTrue.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">${pcTrue.map(x=>`<span style="background:var(--green-soft);color:var(--green);padding:3px 12px;border-radius:999px;font-size:.8rem">${esc(x)}</span>`).join('')}</div>` : ''}
    ${pcProb.length ? `<div style="display:flex;flex-wrap:wrap;gap:4px">${pcProb.join('')}</div>` : ''}
  </div>` : '';

  // Benefícios
  const benef = mkD.beneficios || [];
  const benefComRecebimento = benef.filter(b => parseInt(b.totalParcelasRecebidas) > 0);
  const benefHtml = benefComRecebimento.length ? `
  <table class="data-table">
    <thead><tr><th>Benefício</th><th>Parcelas</th><th>Total</th></tr></thead>
    <tbody>${benefComRecebimento.map(b => `
      <tr><td>${esc(b.beneficio)}</td><td>${esc(b.totalParcelasRecebidas)}</td><td>${esc(b.totalRecebido)}</td></tr>`).join('')}
    </tbody>
  </table>` : '';

  const unavailable = mk?.status === 'unavailable';

  cpfRes.innerHTML = banner + infoCards +
    makeAccordion('📍', 'Endereços', enderecos.length, endHtml) +
    makeAccordion('📞', 'Telefones', telefones.length, telHtml) +
    makeAccordion('✉️', 'Emails', emails.length, emailHtml) +
    makeAccordion('🏢', 'Empresas / QSA', empresas.length, empHtml) +
    makeAccordion('👨‍👩‍👧', 'Parentes', parentes.length, parHtml) +
    makeAccordion('🏘️', 'Vizinhos', vizinhos.length, vizHtml) +
    (pcHtml ? makeAccordion('🛍️', 'Perfil de Consumo', pcTrue.length + pcProb.length, pcHtml) : '') +
    (benefComRecebimento.length ? makeAccordion('🏛️', 'Benefícios', benefComRecebimento.length, benefHtml) : '') +
    (unavailable ? `<p class="msg" style="font-size:.85rem">ℹ️ Mk Buscas não configurada — dados enriquecidos indisponíveis.</p>` : '');

  // Auto-open telefones e endereços
  document.querySelectorAll('.accordion-head')[0]?.click(); // endereços
  document.querySelectorAll('.accordion-head')[1]?.click(); // telefones
}

function infoCard(label, value, sub) {
  return `<div class="info-card">
    <div class="ic-label">${label}</div>
    <div class="ic-value">${esc(value)}</div>
    ${sub ? `<div class="ic-sub">${esc(sub)}</div>` : ''}
  </div>`;
}

cpfBtn.addEventListener('click', searchCpf);
cpfQ.addEventListener('keydown', e => e.key === 'Enter' && searchCpf());

// ══════════════════════════════════════════════════════
//  MÓDULO NOME
// ══════════════════════════════════════════════════════
const nomeQ   = document.getElementById('nome-q');
const nomeBtn = document.getElementById('nome-btn');
const nomeRes = document.getElementById('nome-results');

// Quantos "outros" carregar de início; "Ver mais" busca mais sob demanda.
const OUTROS_PAGE = 10;

// Estado da busca por nome (para paginação do "Ver mais" / "Buscar todos")
const nomeState = {
  q: '', sexo: '', anoMin: 0, anoMax: 0,
  exactCpfs: new Set(),
  outros: [],        // acumulado (todos os broad já buscados, incl. exatos)
  totalBroad: 0,     // total de matches broad no servidor
  fetched: 0,        // quantas linhas broad já buscamos (offset)
};

function nomeFilters(lista) {
  let p = lista || [];
  const { sexo, anoMin, anoMax } = nomeState;
  if (sexo) p = p.filter(x => (x.sexo || '').toUpperCase().startsWith(sexo));
  if (anoMin) p = p.filter(x => parseInt((x.nascimento || '').slice(-4)) >= anoMin);
  if (anoMax) p = p.filter(x => parseInt((x.nascimento || '').slice(-4)) <= anoMax);
  return p;
}

async function searchNome() {
  const q = nomeQ.value.trim();
  if (!q) return;
  const limit = document.getElementById('nome-limit').value;

  nomeState.q = q;
  nomeState.sexo = document.getElementById('nome-sexo').value;
  nomeState.anoMin = parseInt(document.getElementById('nome-ano-min').value) || 0;
  nomeState.anoMax = parseInt(document.getElementById('nome-ano-max').value) || 0;
  nomeState.outros = [];
  nomeState.fetched = 0;
  nomeState.totalBroad = 0;

  nomeBtn.disabled = true;
  nomeRes.innerHTML = spinner();
  try {
    // Exato (nome_norm=) + primeira página broad (JANINE% AND %SAMPAIO%)
    const exactUrl = `${API}/api/person/name-search?q=${encodeURIComponent(q)}&broad=false&limit=${limit}`;
    const outrosUrl = `${API}/api/person/name-search?q=${encodeURIComponent(q)}&broad=true&limit=${OUTROS_PAGE}&offset=0`;

    const [exactRes, outrosRes] = await Promise.all([
      fetch(exactUrl).then(r => r.json()),
      fetch(outrosUrl).then(r => r.json()),
    ]);

    if (exactRes.status !== 'ok' && outrosRes.status !== 'ok') {
      nomeRes.innerHTML = `<p class="msg error">${esc(exactRes.message || outrosRes.message || 'Erro')}</p>`;
      return;
    }

    nomeState.exactCpfs = new Set((exactRes.pessoas || []).map(p => p.cpf));
    nomeState.outros = outrosRes.pessoas || [];
    nomeState.fetched = nomeState.outros.length;
    nomeState.totalBroad = outrosRes.total || nomeState.outros.length;

    const exatos = nomeFilters(exactRes.pessoas || []);
    renderNome(exatos, q);
    const total = exatos.length + outrosFiltrados().length;
    logBusca('Nome', q, `${total} candidato${total === 1 ? '' : 's'}`);
  } catch(e) {
    nomeRes.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    nomeBtn.disabled = false;
  }
}

// "Outros" = broad que não são match exato, com filtros aplicados
function outrosFiltrados() {
  return nomeFilters(nomeState.outros.filter(p => !nomeState.exactCpfs.has(p.cpf)));
}

function renderNome(exatos, q) {
  const outros = outrosFiltrados();
  if (!exatos.length && !outros.length) {
    nomeRes.innerHTML = `<p class="msg">Nenhum resultado encontrado.</p>`;
    return;
  }

  const tabsHtml = `
  <div class="res-tabs">
    <button class="res-tab active" onclick="switchResTab('exatos')" id="rtab-exatos">
      Nome exato <span class="res-tab-count">${exatos.length}</span>
    </button>
    <button class="res-tab" onclick="switchResTab('outros')" id="rtab-outros">
      Outros sobrenomes <span class="res-tab-count">${nomeState.totalBroad}</span>
    </button>
  </div>`;

  const rankBar = prefix => `
    <div class="rank-bar">
      <button id="rank-btn-${prefix}" class="btn-secondary" onclick="calcularRanking('${prefix}')">Calcular ranking</button>
      <button id="rank-btn-agr-${prefix}" class="btn-secondary" title="Também consulta a Assertiva por CPF — mais completo, custa 2 consultas por pessoa" onclick="calcularRanking('${prefix}', true)">Ranking agressivo</button>
      <span id="rank-note-${prefix}" class="rank-note"></span>
    </div>`;

  nomeRes.innerHTML = tabsHtml +
    (exatos.length > 1 ? rankBar('exatos') : '') +
    `<div id="rpanel-exatos">${renderPessoaCards(exatos, 'ex')}</div>` +
    rankBar('outros') +
    `<div id="rpanel-outros" style="display:none">${renderOutrosPanel()}</div>`;
}

// Painel "outros" com cards + controle de "Ver mais" / "Buscar todos"
function renderOutrosPanel() {
  const outros = outrosFiltrados();
  const cards = renderPessoaCards(outros, 'ou');
  // Ainda há mais linhas broad no servidor?
  const restante = nomeState.totalBroad - nomeState.fetched;
  let controls = '';
  if (restante > 0) {
    const opts = [10, 25, 50, 100].filter(n => n <= restante);
    if (!opts.length || opts[opts.length - 1] < restante) opts.push(restante); // garante opção exata p/ o resto
    const btns = opts.map(n =>
      `<button class="btn-ver-mais" onclick="loadMoreOutros(${n})">+${n}</button>`
    ).join('');
    controls = `
      <div class="outros-more">
        <span class="outros-more-info">Mostrando ${nomeState.fetched} de ${nomeState.totalBroad}.</span>
        <div class="outros-more-btns">
          ${btns}
          <button class="btn-ver-mais btn-todos" onclick="loadMoreOutros('all')">Buscar todos (${nomeState.totalBroad})</button>
        </div>
      </div>`;
  } else {
    controls = `<div class="outros-more"><span class="outros-more-info">Todos os ${nomeState.totalBroad} resultados carregados.</span></div>`;
  }
  return cards + controls;
}

window.loadMoreOutros = async function(qtd) {
  const panel = document.getElementById('rpanel-outros');
  if (!panel) return;
  const restante = nomeState.totalBroad - nomeState.fetched;
  const n = qtd === 'all' ? restante : Math.min(qtd, restante);
  if (n <= 0) return;

  // Feedback no botão clicado
  const info = panel.querySelector('.outros-more-info');
  if (info) info.textContent = 'Carregando…';

  try {
    const url = `${API}/api/person/name-search?q=${encodeURIComponent(nomeState.q)}&broad=true&limit=${n}&offset=${nomeState.fetched}`;
    const res = await fetch(url).then(r => r.json());
    const novos = res.pessoas || [];
    nomeState.outros = nomeState.outros.concat(novos);
    nomeState.fetched += novos.length;
    if (res.total) nomeState.totalBroad = res.total;
    panel.innerHTML = renderOutrosPanel();
    document.getElementById('rtab-outros').querySelector('.res-tab-count').textContent = nomeState.totalBroad;
  } catch(e) {
    if (info) info.textContent = 'Erro ao carregar mais.';
  }
};

window.switchResTab = function(tab) {
  ['exatos', 'outros'].forEach(t => {
    document.getElementById('rtab-' + t)?.classList.toggle('active', t === tab);
    const panel = document.getElementById('rpanel-' + t);
    if (panel) panel.style.display = t === tab ? '' : 'none';
  });
};

function renderPessoaCards(pessoas, prefix) {
  if (!pessoas.length) return `<p class="msg" style="padding:32px 0">Nenhum resultado.</p>`;
  return pessoas.map((p, i) => {
    const id = prefix + '-' + i;
    const cpfFmt = fmtCpf(p.cpf || '');
    const sexoIcon = (p.sexo || '').toUpperCase().startsWith('M') ? '♂' : (p.sexo || '').toUpperCase().startsWith('F') ? '♀' : '';
    return `
    <div class="card-person" id="card-${id}" data-cpf="${esc(p.cpf || '')}">
      <div class="card-person-header" onclick="togglePerson('${id}', '${p.cpf}')">
        <div>
          <div class="person-name">${esc(p.nome)}</div>
          <div class="person-meta">${sexoIcon} ${esc(p.sexo || '')} · 🎂 ${esc(p.nascimento || '—')}</div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="person-cpf">${esc(cpfFmt)}</span>
          <span class="person-chevron" id="chev-np-${id}">▼</span>
        </div>
      </div>
      <div class="card-person-body" id="body-${id}">
        <div id="mk-${id}" style="padding-top:12px"><p class="msg" style="padding:12px">Carregando dados Mk Buscas…</p></div>
      </div>
    </div>`;
  }).join('');
}

window.togglePerson = async function(id, cpf) {
  const body = document.getElementById('body-' + id);
  const head = body.previousElementSibling;
  const chev = document.getElementById('chev-np-' + id);
  const mkDiv = document.getElementById('mk-' + id);
  const isOpen = body.classList.contains('open');

  body.classList.toggle('open');
  head.classList.toggle('open');

  if (!isOpen && mkDiv.dataset.loaded !== '1') {
    mkDiv.dataset.loaded = '1';
    try {
      const [jbrRes, mkRes] = await Promise.all([
        fetch(`${API}/api/person/${cpf}`).then(r => r.json()),
        fetch(`${API}/api/person/${cpf}/mk`).then(r => r.json()),
      ]);
      renderPessoaInline(mkDiv, cpf, jbrRes, mkRes);
    } catch(e) {
      mkDiv.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
    }
  }
  // Se o ranking agressivo já consultou a Assertiva pra esse CPF (antes ou depois
  // de abrir o card), mostra TODOS os dados dela aqui — não só usados na nota.
  // Checado toda vez que abre (não só na 1ª vez), pra pegar quando o ranking roda depois.
  const as = window._assertivaPorCpf && window._assertivaPorCpf[cpf];
  if (!isOpen && as && mkDiv.dataset.asLoaded !== '1') {
    mkDiv.dataset.asLoaded = '1';
    const box = document.createElement('div');
    box.className = 'rank-assertiva-extra';
    box.innerHTML = `<h3 style="font-weight:600;font-size:.95rem;margin:18px 0 10px">🎯 Assertiva (usada no ranking agressivo)</h3>` +
      (as.status === 'ok' ? montarHtmlAssertiva(as.data || {}, 'cpf') : `<p class="msg error">${esc(as.message || 'Falha na consulta Assertiva.')}</p>`);
    mkDiv.appendChild(box);
  }
};

function renderPessoaInline(container, cpf, jbr, mk) {
  const mkD = mk?.data || {};
  const db  = mkD.DadosBasicos || {};
  const de  = mkD.DadosEconomicos || {};

  const sit = (db.situacaoCadastral || {}).descricaoSituacaoCadastral || '';
  const mae = db.nomeMae || '—';
  const ec  = db.estadoCivil || '';
  const renda = de.renda ? `R$ ${de.renda}` : '';
  const scoreVal = parseInt((de.score || {}).scoreCSBA) || 0;
  const scoreLabel = (de.score || {}).scoreCSBAFaixaRisco || '';
  const telefones = mkD.telefones || [];
  const emails = mkD.emails || [];
  const enderecos = mkD.enderecos || [];
  const empresas = mkD.empresas || [];
  const parentes = mkD.parentes || [];

  let html = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:12px">`;
  html += `<div class="info-card"><div class="ic-label">👩 Mãe</div><div class="ic-value" style="font-size:.9rem">${esc(mae)}</div></div>`;
  if (sit) html += `<div class="info-card"><div class="ic-label">📋 Situação CPF</div><div class="ic-value" style="font-size:.9rem">${badgeSit(sit)}</div></div>`;
  if (ec)  html += `<div class="info-card"><div class="ic-label">💍 Estado Civil</div><div class="ic-value" style="font-size:.9rem">${esc(ec)}</div></div>`;
  if (renda) html += `<div class="info-card"><div class="ic-label">💰 Renda</div><div class="ic-value" style="font-size:.9rem">${esc(renda)}</div></div>`;
  if (scoreVal) html += `<div class="info-card"><div class="ic-label">📊 Score</div><div class="ic-value" style="font-size:.9rem;color:${scoreColor(scoreVal)}">${scoreVal} — ${esc(scoreLabel)}</div></div>`;
  html += `</div>`;

  if (telefones.length) {
    html += `<div style="margin-bottom:10px"><strong style="font-size:.82rem;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em">📞 Telefones</strong>
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">
    ${telefones.map(t => `<span style="background:var(--blue-soft);color:var(--blue-dark);padding:4px 12px;border-radius:6px;font-size:.85rem;font-weight:600">${esc(fmtPhone(t.telefone||t.numero||''))}</span>`).join('')}
    </div></div>`;
  }

  if (emails.length) {
    html += `<div style="margin-bottom:10px"><strong style="font-size:.82rem;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em">✉️ Emails</strong>
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">
    ${emails.map(e => `<span style="background:var(--gray-100);color:var(--gray-700);padding:4px 12px;border-radius:6px;font-size:.83rem">${esc(e.email||'')}</span>`).join('')}
    </div></div>`;
  }

  if (enderecos.length) {
    html += `<div style="margin-bottom:10px"><strong style="font-size:.82rem;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em">📍 Endereços</strong>
    <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">
    ${enderecos.map(e => `<span style="font-size:.83rem;color:var(--gray-700)">📍 ${esc([e.logradouro,e.logradouroNumero,e.bairro,e.cidade,e.uf].filter(Boolean).join(', '))}</span>`).join('')}
    </div></div>`;
  }

  if (empresas.length) {
    html += `<div style="margin-bottom:10px"><strong style="font-size:.82rem;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em">🏢 Vínculos</strong>
    <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">
    ${empresas.map(e => `<span style="font-size:.83rem;color:var(--gray-700)">🏢 ${esc(fmtCnpj(e.cnpj||''))} — ${esc(e.relacao||'')} (${esc(e.admissao||'')})</span>`).join('')}
    </div></div>`;
  }

  if (parentes.length) {
    html += `<div><strong style="font-size:.82rem;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em">👨‍👩‍👧 Parentes</strong>
    <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">
    ${parentes.map(p => `<span style="font-size:.83rem;color:var(--gray-700)">👤 ${esc(p.nomeParente||'')} (${esc(p.grauParentesco||'')}) — ${esc(fmtCpf(p.cpfParente||''))}</span>`).join('')}
    </div></div>`;
  }

  if (mk?.status === 'unavailable') {
    html = `<p class="msg" style="padding:8px;font-size:.85rem">ℹ️ Mk Buscas não configurada.</p>` + html;
  }

  container.innerHTML = html;
}

nomeBtn.addEventListener('click', searchNome);
nomeQ.addEventListener('keydown', e => e.key === 'Enter' && searchNome());

(function initNomeUf() {
  const sel = document.getElementById('nome-uf-suposta');
  if (!sel) return;
  const ufs = ['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MT','MS','MG',
    'PA','PB','PR','PE','PI','RJ','RN','RO','RS','RR','SC','SE','SP','TO'];
  ufs.forEach(u => { const o = document.createElement('option'); o.value = u; o.textContent = u; sel.appendChild(o); });
})();

// ── Ranking por % de match (só quando a usuária pede — consulta Mk Buscas) ──
const RANKING_MAX_CANDIDATOS = 20;

function normTexto(s) {
  return (s || '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

// Versão só-alfanumérica pra COMPARAR termo x fonte — telefone digitado como
// "(51) 98451-5244" precisa bater com o dado guardado como "984515244" (só
// dígitos, sem parênteses/hífen/espaço); sem isso a pontuação nunca casa.
function normComparar(s) {
  return normTexto(s).replace(/[^a-z0-9]/g, '');
}

// Extrai {enderecos:[{uf,cidade,bairro,logradouro}], textoExtra} de uma resposta
// da Assertiva (mesma forma vinda de /api/assertiva/cpf), pra somar à pontuação.
// Achata qualquer objeto (raso ou 1 nível de aninhamento) em texto — pega CBO,
// profissão, classe social, ou qualquer outro campo que a Assertiva devolver,
// sem precisar saber o nome exato de cada chave de antemão.
function achatarEmTexto(obj, profundidade) {
  if (obj == null) return '';
  if (typeof obj !== 'object') return String(obj);
  if (Array.isArray(obj)) return obj.map(v => achatarEmTexto(v, (profundidade || 0) + 1)).join(' ');
  // Limite generoso (cobre objeto > array > objeto > campo, ex.: mkD.parentes[].nomeParente)
  // sem risco de loop — respostas de API são finitas e não-circulares.
  if ((profundidade || 0) >= 6) return '';
  return Object.values(obj).map(v => achatarEmTexto(v, (profundidade || 0) + 1)).join(' ');
}

function extrairAssertiva(as) {
  if (as?.status !== 'ok') return { enderecos: [], textoExtra: '', participacoes: [] };
  const resp = as.data?.resposta || {};
  const enderecos = mergeArr(resp.enderecos, resp.enderecosAdicionados).map(e => ({
    uf: e.uf, cidade: e.cidade, bairro: e.bairro, logradouro: e.logradouro,
  }));
  const participacoes = resp.participacoesEmpresas || resp.participacoesSocietarias || [];
  // Achata a resposta INTEIRA da Assertiva (dadosCadastrais, participações
  // societárias/vínculo profissional, sócios, decisores, telefones, o que vier) —
  // "vendas" ou qualquer outro termo pode estar em qualquer canto do JSON, não só
  // em dadosCadastrais.
  const textoExtra = achatarEmTexto(resp);
  return { enderecos, textoExtra, participacoes };
}

// Fontes de texto NOMEADAS (pra dizer EM QUE CAMPO um termo da descrição bateu,
// não só "bateu"). Cobre Mk Buscas inteiro (achatado, fallback) + campos
// específicos com rótulo bonito quando dá pra identificar.
function fontesTexto(mkD, extra) {
  const db = mkD.DadosBasicos || {};
  const enderecos = [...(mkD.enderecos || []), ...((extra && extra.enderecos) || [])];
  const fontes = [
    { fonte: 'Nome da mãe', texto: db.nomeMae },
    { fonte: 'Estado civil', texto: db.estadoCivil },
    { fonte: 'Profissão (Mk)', texto: (mkD.profissao || {}).cboDescricao },
    { fonte: 'Endereço', texto: enderecos.map(e => `${e.bairro || ''} ${e.logradouro || ''}`).join(' ') },
    { fonte: 'Parentes', texto: (mkD.parentes || []).map(p => p.nomeParente || '').join(' ') },
    { fonte: 'Vizinhos', texto: (mkD.vizinhos || []).map(v => v.nome || '').join(' ') },
    { fonte: 'Empresas vinculadas (Mk)', texto: (mkD.empresas || []).map(e => e.relacao || e.tipoRelacao || '').join(' ') },
    { fonte: 'Telefone', texto: (mkD.telefones || []).map(t => t.telefone || t.numero || '').join(' ') },
    { fonte: 'Vínculo profissional (Assertiva)', texto: ((extra && extra.participacoes) || []).map(p => `${p.cargo || ''} ${p.razaoSocial || ''}`).join(' ') },
    { fonte: 'Outros dados da Assertiva (ranking agressivo)', texto: (extra && extra.textoExtra) || '' },
    // Rede de segurança: qualquer outro campo do Mk (escolaridade, benefícios,
    // perfil de consumo etc.) que não tenha um rótulo específico acima.
    { fonte: 'Outros dados (Mk)', texto: achatarEmTexto(mkD) },
  ];
  return fontes.map(f => ({ fonte: f.fonte, texto: normComparar(f.texto || '') })).filter(f => f.texto);
}

function calcularScorePessoa(mk, pistas, extra) {
  const mkD = mk?.data || {};
  const enderecos = [...(mkD.enderecos || []), ...((extra && extra.enderecos) || [])];

  let pontos = 0, maxPontos = 0;
  const motivos = [];

  if (pistas.uf) {
    maxPontos += 35;
    const bate = enderecos.some(e => normTexto(e.uf) === normTexto(pistas.uf));
    if (bate) { pontos += 35; motivos.push(`✅ Estado bate (${pistas.uf.toUpperCase()})`); }
    else motivos.push(`❌ Estado não bate com nenhum endereço encontrado`);
  }
  if (pistas.cidade) {
    maxPontos += 35;
    const bate = enderecos.some(e => normTexto(e.cidade).includes(normTexto(pistas.cidade)));
    if (bate) { pontos += 35; motivos.push(`✅ Cidade bate (${pistas.cidade})`); }
    else motivos.push(`❌ Cidade "${pistas.cidade}" não bate com nenhum endereço encontrado`);
  }
  if (pistas.descricao) {
    maxPontos += 30;
    const termos = normTexto(pistas.descricao).split(/\s+/).map(t => normComparar(t)).filter(t => t.length >= 3);
    const fontes = fontesTexto(mkD, extra);
    const achados = termos.map(t => ({ termo: t, fontes: fontes.filter(f => f.texto.includes(t)).map(f => f.fonte) }));
    const bateram = achados.filter(a => a.fontes.length);
    if (termos.length) pontos += Math.round((bateram.length / termos.length) * 30);
    if (bateram.length) {
      const detalhe = bateram.map(a => `"${a.termo}" → ${a.fontes.join(' / ')}`).join('; ');
      motivos.push(`✅ Descrição (${bateram.length} de ${termos.length} termo${termos.length===1?'':'s'}): ${detalhe}`);
    } else motivos.push(`❌ Nenhum termo da descrição apareceu nos dados encontrados`);
  }
  if (!enderecos.length && (pistas.uf || pistas.cidade)) motivos.unshift('⚠️ Nenhum endereço encontrado pra essa pessoa (Mk/Assertiva sem dado)');
  // Sem nenhuma pista: não dá pra rankear além do que a busca por nome já fez.
  if (maxPontos === 0) return { score: null, motivos: [] };
  return { score: Math.round((pontos / maxPontos) * 100), motivos };
}

window.calcularRanking = async function(prefix, agressivo) {
  const btn = document.getElementById('rank-btn-' + prefix);
  const btnAgr = document.getElementById('rank-btn-agr-' + prefix);
  const note = document.getElementById('rank-note-' + prefix);
  const pistas = {
    uf: document.getElementById('nome-uf-suposta').value,
    cidade: document.getElementById('nome-cidade-suposta').value.trim(),
    descricao: document.getElementById('nome-descricao').value.trim(),
  };
  if (!pistas.uf && !pistas.cidade && !pistas.descricao) {
    note.textContent = 'Preencha ao menos uma pista (estado, cidade ou descrição) antes de calcular.';
    return;
  }
  const container = document.getElementById('rpanel-' + prefix);
  const cards = [...container.querySelectorAll('.card-person')];
  const alvo = cards.slice(0, RANKING_MAX_CANDIDATOS);
  const fonte = agressivo ? 'Mk Buscas + Assertiva (2 consultas pagas por CPF)' : 'Mk Buscas (1 consulta paga por CPF)';

  // Limpa qualquer dado de Assertiva de uma rodada ANTERIOR pra esses candidatos —
  // a Assertiva só deve aparecer se ESSE clique for "Ranking agressivo". Sem isso,
  // rodar o ranking normal depois do agressivo ainda mostrava dados velhos no card.
  alvo.forEach(card => {
    const cpf = card.dataset.cpf;
    if (window._assertivaPorCpf) delete window._assertivaPorCpf[cpf];
    const mkDiv = document.getElementById('mk-' + card.id.replace('card-', ''));
    if (mkDiv) {
      mkDiv.dataset.asLoaded = '0';
      const antigo = mkDiv.querySelector('.rank-assertiva-extra');
      if (antigo) antigo.remove();
    }
  });
  if (cards.length > RANKING_MAX_CANDIDATOS) {
    note.innerHTML = `Calculando pros ${RANKING_MAX_CANDIDATOS} primeiros de ${cards.length} — ${fonte}.`;
  }
  btn.disabled = true; if (btnAgr) btnAgr.disabled = true;
  let feitos = 0;
  const resultados = [];
  for (const card of alvo) {
    const cpf = card.dataset.cpf;
    feitos++;
    note.textContent = `Calculando ${feitos} de ${alvo.length} (${fonte})…`;
    try {
      const mk = await fetch(`${API}/api/person/${cpf}/mk`).then(r => r.json());
      let extra = null;
      if (agressivo) {
        window._assertivaPorCpf = window._assertivaPorCpf || {};
        try {
          const asResp = await fetch(`${API}/api/assertiva/cpf?cpf=${cpf}&finalidade=5`);
          const asText = await asResp.text();
          let as;
          try { as = JSON.parse(asText); }
          catch (parseErr) {
            // Resposta não é JSON (ex.: página de erro HTML) — mostra os primeiros
            // caracteres pra dar pra diagnosticar, em vez de sumir sem explicação.
            as = { status: 'error', message: `Resposta inesperada (HTTP ${asResp.status}): ${asText.slice(0, 150)}` };
          }
          extra = extrairAssertiva(as);
          // Guarda o JSON cru pra exibir por completo quando a pessoa abrir o card
          // (mesmos blocos da aba Consulta Assertiva) — não fica só influenciando a nota.
          window._assertivaPorCpf[cpf] = as;
        } catch (e) {
          // Erro de rede/fetch em si (não da resposta) — também fica visível no card.
          window._assertivaPorCpf[cpf] = { status: 'error', message: `Falha ao consultar: ${e.message}` };
        }
      }
      const { score, motivos } = calcularScorePessoa(mk, pistas, extra);
      resultados.push({ card, score, motivos });
    } catch (e) {
      resultados.push({ card, score: null, motivos: ['❌ Erro ao consultar dados desta pessoa'] });
    }
  }
  resultados.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  resultados.forEach(({ card, score, motivos }) => {
    container.appendChild(card);
    let badge = card.querySelector('.rank-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'rank-badge';
      card.querySelector('.card-person-header > div:last-child').prepend(badge);
    }
    let porque = card.querySelector('.rank-porque');
    if (!porque) {
      porque = document.createElement('div');
      porque.className = 'rank-porque';
      card.querySelector('.card-person-header > div:first-child').appendChild(porque);
    }
    if (score === null) {
      badge.textContent = ''; badge.hidden = true;
      porque.innerHTML = '';
    } else {
      badge.hidden = false;
      badge.textContent = `${score}% chance`;
      badge.className = 'rank-badge ' + (score >= 66 ? 'rank-alta' : score >= 33 ? 'rank-media' : 'rank-baixa');
      porque.innerHTML = (motivos || []).map(m => `<div>${esc(m)}</div>`).join('');
    }
  });
  note.textContent = `Ranking (${fonte}) calculado para ${alvo.length} candidato(s). Ordenado por % de chance.`;
  btn.disabled = false; if (btnAgr) btnAgr.disabled = false;
};

// ══════════════════════════════════════════════════════
//  MÓDULO PROSPECÇÃO (filtros → lista → validar → exportar)
// ══════════════════════════════════════════════════════
const prospState = {
  empresas: [],   // resultado da busca (básico)
  total: 0,
  fonte: '',      // 'local' (RFB) | 'casadosdados'
  rows: [],       // linhas montadas (1 por contato/telefone)
  building: false,
  validating: false,
};

function prospFiltros() {
  const list = v => (v || '').split(',').map(s => s.trim()).filter(Boolean);
  const escopo = [...document.querySelectorAll('.pf-esc:checked')].map(c => c.value);
  // Fallback: campo específico "Nome da empresa" (estilo Datastone) alimenta a
  // lupa geral quando ela está vazia, reaproveitando o mesmo mecanismo de busca.
  const textoGeral = document.getElementById('pf-texto').value.trim();
  const nomeEmpresaVal = document.getElementById('pf-nome-empresa').value.trim();
  const textoFinal = textoGeral || nomeEmpresaVal;
  const escopoFinal = textoGeral ? escopo : (escopo.length ? escopo : ['razao', 'fantasia']);
  return {
    cnpj: onlyDigits(document.getElementById('pf-cnpj').value),
    texto: textoFinal,
    texto_escopo: escopoFinal,
    tipo_busca: document.getElementById('pf-tipo').value,
    cnae: comboCodes('combo-cnae'),
    natureza: comboCodes('combo-natureza'),
    porte: list(document.getElementById('pf-porte').value),
    uf: getSelectedUFs(),
    municipio: comboCodes('combo-municipio'),
    situacao: list(document.getElementById('pf-situacao').value),
    capital_min: parseInt(document.getElementById('pf-cap-min').value) || 0,
    capital_max: parseInt(document.getElementById('pf-cap-max').value) || 0,
    mei_excluir: document.getElementById('pf-mei-excluir').checked,
    mei_optante: document.getElementById('pf-mei-optante').checked,
    com_telefone: document.getElementById('pf-com-tel').checked,
    somente_matriz: document.getElementById('pf-matriz').checked,
    setor: document.getElementById('pf-setor').value.trim(),
    fundada_de: document.getElementById('pf-fundada-de').value,
    fundada_ate: document.getElementById('pf-fundada-ate').value,
    nome_empresa: document.getElementById('pf-nome-empresa').value.trim(),
    tipo_empresa: document.getElementById('pf-tipo-empresa').value,
  };
}

async function prospBuscar() {
  const btn = document.getElementById('pf-buscar');
  const out = document.getElementById('prosp-results');
  const cnt = document.getElementById('pf-count');
  const cntSub = document.getElementById('pf-count-sub');
  btn.disabled = true;
  cnt.textContent = '';
  if (cntSub) cntSub.textContent = '';
  out.innerHTML = spinner();
  try {
    const res = await fetch(`${API}/api/companies/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filtros: prospFiltros(), limite: 500 }),
    }).then(r => r.json());

    if (res.status !== 'ok') {
      out.innerHTML = `<p class="msg error">${esc(res.message || 'Falha na busca.')}</p>`;
      return;
    }
    prospState.empresas = res.empresas || [];
    prospState.total = res.total || prospState.empresas.length;
    prospState.fonte = res.fonte || '';
    prospState.rows = [];
    const capMsg = prospState.total > prospState.empresas.length
      ? ` (carregadas ${prospState.empresas.length}${prospState.fonte === 'local' ? '' : ' — refine os filtros para focar'})` : '';
    const fonteTag = prospState.fonte === 'local' ? 'base local RFB' : (prospState.fonte === 'casadosdados' ? 'Casa dos Dados' : '');
    const totalStr = res.total_aprox ? `${prospState.total.toLocaleString('pt-BR')}+` : prospState.total.toLocaleString('pt-BR');
    cnt.textContent = `${totalStr} empresa${prospState.total === 1 ? '' : 's'} bate${prospState.total === 1 ? '' : 'm'} com seus filtros`;
    if (cntSub) cntSub.textContent = `${capMsg.trim() || ('Mostrando ' + prospState.empresas.length)}${fonteTag ? ' · ' + fonteTag : ''}`.replace(/^\(|\)$/g, '');
    renderProspList();
    const excluirMeetime = document.getElementById('pf-excluir-meetime');
    if (excluirMeetime && excluirMeetime.checked) prospDedupMeetime();
    const filtrosResumo = Object.entries(prospFiltros()).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(', ') || 'sem filtro';
    logBusca('Lista', filtrosResumo.slice(0, 120), `${totalStr} empresa${prospState.total === 1 ? '' : 's'}`);
  } catch (e) {
    out.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

function renderProspList() {
  const out = document.getElementById('prosp-results');
  const emp = prospState.empresas;
  if (!emp.length) {
    out.innerHTML = `<p class="msg">Nenhuma empresa encontrada com esses filtros.</p>`;
    return;
  }
  const max = emp.length;
  out.innerHTML = `
    <div class="prosp-build">
      <div class="prosp-build-overline">Passo 2 — montar a lista para ligar</div>
      <div class="prosp-build-row">
        <label>Quantas empresas
          <input id="pf-qtd" type="number" min="1" max="${max}" value="${Math.min(25, max)}" class="filter-num" />
          <span class="pf-advanced-hint" style="display:inline">de ${emp.length} carregadas${prospState.total > emp.length ? `, ${prospState.total.toLocaleString('pt-BR')} no total` : ''}</span>
        </label>
        <label>Telefones por empresa
          <input id="pf-maxtel" type="number" min="1" max="10" value="3" class="filter-num" />
        </label>
        <label>Tipo de telefone
          <select id="pf-modotel" class="filter-select">
            <option value="celular" selected>Só celular (recomendado)</option>
            <option value="celular_fixo">Celular e fixo</option>
            <option value="todos">Todos (inclui antigos)</option>
          </select>
        </label>
        <label>Fonte dos telefones
          <select id="pf-fontetel" class="filter-select">
            <option value="assertiva" selected>Assertiva (Localize)</option>
            <option value="mk">Mk (WorkAPI)</option>
          </select>
        </label>
        <label>Sócios
          <select id="pf-sociosmodo" class="filter-select" title="Todos os sócios do QSA, ou só sócio-administrador/diretor/presidente">
            <option value="todos" selected>Todos disponíveis</option>
            <option value="admin">Só sócio-administrador</option>
          </select>
        </label>
        <label>máx sócios/empresa
          <input id="pf-maxsocios" type="number" min="0" max="20" value="0" class="filter-num" title="0 = sem limite" />
        </label>
        <label>Modelo (custo Assertiva vai pra ele)
          <select id="pf-modelo" class="filter-select" title="Atribui o custo das consultas Assertiva a este modelo, visível na aba Meus Modelos">
            <option value="">— nenhum (sem rastrear) —</option>
            <option value="__cliente__">🧑‍💼 Cliente (planilha externa)</option>
          </select>
        </label>
        <label class="toggle-wrap"><input id="pf-decisores" type="checkbox" /><span>Incluir decisores (LinkedIn) <span class="pf-advanced-hint" style="display:inline">— mais lento, pode ser bloqueado</span></span></label>
        <button id="pf-dedup" class="btn-secondary" title="Remove das ${emp.length} empresas as que já estão na Meetime (CNPJ + nome)">Remover quem já está na Meetime</button>
        <button id="pf-montar" class="btn-primary">Montar lista de contatos</button>
      </div>
      <div id="pf-dedup-note" class="prosp-dedup-note"></div>
      <p class="prosp-warn">Buscar os telefones leva alguns minutos e consome consulta (${prospState.fonte === 'local' ? 'base local da Receita' : 'Casa dos Dados'}). A lista pronta pode ser exportada em planilha, no seu modelo de colunas. A validação por telefone reverso é um passo separado, sobre a lista pronta.</p>
    </div>
    <div class="prosp-table-scroll">
      <table class="prosp-table prosp-empresas-table prosp-ds-table">
        <thead><tr>
          <th></th><th>Empresa e sócio</th><th>Cidade</th><th>O que a empresa faz</th><th>Situação</th>
        </tr></thead>
        <tbody id="prosp-emp-body"></tbody>
      </table>
    </div>
    <div id="prosp-pager" class="prosp-pager"></div>
    <div id="prosp-table-wrap"></div>
  `;
  prospState.page = 0;
  renderEmpPage();
  document.getElementById('pf-montar').addEventListener('click', prospMontar);
  document.getElementById('pf-dedup').addEventListener('click', prospDedupMeetime);
  popularSelectModelo(document.getElementById('pf-modelo'));
}

// Preenche um <select> com "— nenhum —", "🧑‍💼 Cliente" + modelos salvos (usado
// na Prospecção pra atribuir custo Assertiva a um modelo).
function popularSelectModelo(sel) {
  if (!sel) return;
  fetch(`${API}/api/prospeccao/modelos`).then(r => r.json()).then(j => {
    const ms = j.modelos || [];
    const extras = ms.map(m => `<option value="${m.id}">${esc(m.nome)}</option>`).join('');
    sel.insertAdjacentHTML('beforeend', extras);
  }).catch(() => {});
}

// Remove das empresas carregadas as que já estão na Meetime (CNPJ + nome ~ LIKE %).
async function prospDedupMeetime() {
  const btn = document.getElementById('pf-dedup');
  const note = document.getElementById('pf-dedup-note');
  btn.disabled = true; note.textContent = '🔁 Consultando a Meetime…';
  try {
    const empresas = prospState.empresas.map(e => ({ cnpj: onlyDigits(e.cnpj), razao_social: e.razao_social }));
    const j = await fetch(`${API}/api/meetime/dedup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ empresas }),
    }).then(r => r.json());
    if (j.status === 'unavailable') { note.innerHTML = '⚠️ Meetime não configurada — peça ao admin para colocar o token em <strong>Configurações</strong>.'; return; }
    if (j.status && j.status !== 'ok') { note.textContent = '⚠️ ' + (j.message || 'Falha na dedup Meetime.'); return; }
    // mantém só os "novos" (não estão na Meetime), preservando os objetos originais por CNPJ
    const removidosCnpj = new Set((j.removidos || []).map(r => onlyDigits(r.cnpj)));
    const antes = prospState.empresas.length;
    prospState.empresas = prospState.empresas.filter(e => !removidosCnpj.has(onlyDigits(e.cnpj)));
    prospState.total = prospState.empresas.length;
    const porCnpj = (j.removidos || []).filter(r => r._dedup === 'cnpj').length;
    const porNome = (j.removidos || []).filter(r => r._dedup === 'nome').length;
    document.getElementById('pf-count').textContent =
      `${prospState.empresas.length} empresa${prospState.empresas.length === 1 ? '' : 's'} após dedup`;
    const sub = document.getElementById('pf-count-sub'); if (sub) sub.textContent = 'base local RFB';
    renderProspList();
    const noteEl = document.getElementById('pf-dedup-note');
    if (noteEl) noteEl.innerHTML = `✅ Removidas <strong>${antes - prospState.empresas.length}</strong> já na Meetime ` +
      `(${porCnpj} por CNPJ, ${porNome} por nome). Restam <strong>${prospState.empresas.length}</strong> para prospectar.`;
  } catch (e) {
    note.textContent = 'Erro: ' + e.message;
  } finally {
    const b = document.getElementById('pf-dedup'); if (b) b.disabled = false;
  }
}

const PROSP_PER_PAGE = 20;
function renderEmpPage() {
  const emp = prospState.empresas;
  const perPage = prospState.perPage || PROSP_PER_PAGE;
  const pages = Math.max(1, Math.ceil(emp.length / perPage));
  const page = Math.min(prospState.page || 0, pages - 1);
  prospState.page = page;
  const body = document.getElementById('prosp-emp-body');
  if (!body) return;
  body.innerHTML = emp.slice(page * perPage, page * perPage + perPage).map((e, k) => {
    const i = page * perPage + k;
    const nome = e.razao_social || e.nome_fantasia || '—';
    const porteBaixo = (e.porte || '').toLowerCase();
    const porteLabel = porteBaixo.includes('micro') ? 'micro empresa' : porteBaixo.includes('pequeno') ? 'pequeno porte' : (e.porte || '');
    return `
      <tr>
        <td><input type="checkbox" class="prosp-co-check" data-i="${i}" /></td>
        <td>
          <div class="prosp-co-name">${esc(nome)}</div>
          <div class="prosp-co-meta mono" title="${esc(fmtCnpj(e.cnpj))}">${esc(fmtCnpj(e.cnpj))}${porteLabel ? ' · ' + esc(porteLabel) : ''}</div>
          ${e.nome_fantasia && e.nome_fantasia !== e.razao_social ? `<div class="prosp-co-fantasia">${esc(e.nome_fantasia)}</div>` : ''}
        </td>
        <td>${[e.municipio, e.uf].filter(Boolean).length ? esc([e.municipio, e.uf].filter(Boolean).join(', ')) : '—'}</td>
        <td class="prosp-co-cnae" title="${esc(e.cnae || '')}">${e.cnae ? esc(e.cnae) : '—'}</td>
        <td>${badgeSit(e.situacao)}</td>
      </tr>`;
  }).join('');
  renderEmpPager(page, pages);
}

function renderEmpPager(page, pages) {
  const el = document.getElementById('prosp-pager');
  if (!el) return;
  // Janela de páginas em torno da atual (1 … 4 5 [6] 7 8 … N), estilo Datastone.
  const nums = [];
  const push = n => nums.push(n);
  const win = 2;
  for (let p = 0; p < pages; p++) {
    if (p === 0 || p === pages - 1 || (p >= page - win && p <= page + win)) push(p);
    else if (nums[nums.length - 1] !== '…') push('…');
  }
  const btn = (label, p, opts = {}) =>
    `<button class="prosp-page-btn${opts.active ? ' active' : ''}" ${opts.disabled ? 'disabled' : ''} data-p="${p}">${label}</button>`;
  el.innerHTML = `
    <select id="prosp-perpage" class="prosp-perpage">
      <option value="20"${(prospState.perPage||20)==20?' selected':''}>20</option>
      <option value="50"${(prospState.perPage||20)==50?' selected':''}>50</option>
      <option value="100"${(prospState.perPage||20)==100?' selected':''}>100</option>
    </select>
    <div class="prosp-pages">
      ${btn('«', 0, { disabled: page === 0 })}
      ${btn('‹', page - 1, { disabled: page === 0 })}
      ${nums.map(n => n === '…' ? '<span class="prosp-page-dots">…</span>' : btn(n + 1, n, { active: n === page })).join('')}
      ${btn('›', page + 1, { disabled: page >= pages - 1 })}
      ${btn('»', pages - 1, { disabled: page >= pages - 1 })}
    </div>`;
  el.querySelectorAll('.prosp-page-btn').forEach(b => b.addEventListener('click', () => {
    prospState.page = parseInt(b.dataset.p);
    renderEmpPage();
    document.getElementById('prosp-results').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }));
  el.querySelector('#prosp-perpage').addEventListener('change', e => {
    prospState.perPage = parseInt(e.target.value); prospState.page = 0; renderEmpPage();
  });
}

// Avatar circular com inicial da empresa (estilo Datastone) — cor estável por nome.
function avatarInitial(nome) {
  const clean = (nome || '').trim();
  return clean ? clean[0].toUpperCase() : '?';
}
function avatarColor(nome) {
  const palette = ['#2563eb', '#7c3aed', '#0891b2', '#059669', '#d97706', '#dc2626', '#4f46e5', '#0d9488'];
  let hash = 0;
  for (let i = 0; i < (nome || '').length; i++) hash = (hash * 31 + nome.charCodeAt(i)) >>> 0;
  return palette[hash % palette.length];
}
function fmtMoneyShort(v) {
  const n = Number(v) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.0', '') + 'B+';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.0', '') + 'M+';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K+';
  return n.toLocaleString('pt-BR');
}

async function prospMontar() {
  if (prospState.building) return;
  const qtd = parseInt(document.getElementById('pf-qtd').value) || 25;
  const decisores = document.getElementById('pf-decisores').checked;
  const modoTel = document.getElementById('pf-modotel').value;
  const maxTel = parseInt(document.getElementById('pf-maxtel').value) || 3;
  const fonteTel = document.getElementById('pf-fontetel')?.value || 'assertiva';
  const sociosModo = document.getElementById('pf-sociosmodo')?.value || 'todos';
  const maxSocios = parseInt(document.getElementById('pf-maxsocios')?.value) || 0;
  const modeloId = document.getElementById('pf-modelo')?.value || '';
  const alvo = prospState.empresas.slice(0, qtd);
  const wrap = document.getElementById('prosp-table-wrap');
  prospState.building = true;
  prospState.rows = [];

  const btn = document.getElementById('pf-montar');
  btn.disabled = true;

  // Monta em paralelo com pool de concorrência (era 1 a 1 => lento).
  // Decisores (LinkedIn) é pesado → menos concorrência para não sobrecarregar/bloquear.
  const CONC = decisores ? 2 : 6;
  const results = new Array(alvo.length);
  const leadsRaw = new Array(alvo.length);
  let completed = 0, next = 0;
  const tick = () => {
    wrap.innerHTML = `<div class="prosp-progress"><span class="spinner"></span> Montando ${completed} de ${alvo.length} empresas…</div>`;
  };
  tick();

  async function worker() {
    while (next < alvo.length) {
      const i = next++;
      try {
        const r = await fetch(`${API}/api/company/${onlyDigits(alvo[i].cnpj)}/leads?decisores=${decisores}&modo_tel=${modoTel}&max_tel=${maxTel}&fonte_tel=${fonteTel}&socios_modo=${sociosModo}&max_socios=${maxSocios}&modelo_id=${encodeURIComponent(modeloId)}`).then(x => x.json());
        if (r.status === 'ok') {
          results[i] = leadsToRows(r.empresa, r.contatos);
          leadsRaw[i] = { empresa: r.empresa, contatos: r.contatos };
        } else { results[i] = []; }
      } catch (e) { results[i] = []; }
      completed++;
      tick();
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONC, alvo.length) }, worker));

  prospState.rows = results.flat();
  prospState.leads = leadsRaw.filter(Boolean);
  prospState.building = false;
  btn.disabled = false;
  renderProspTable();
}

function catLabel(cat) {
  return { celular: 'Celular', fixo: 'Fixo', celular_antigo: 'Celular antigo' }[cat] || '';
}

// Uma linha por telefone de cada contato (contatos sem telefone geram 1 linha em branco)
function leadsToRows(empresa, contatos) {
  const base = {
    razao_social: empresa.razao_social, nome_fantasia: empresa.nome_fantasia,
    cnpj: fmtCnpj(empresa.cnpj), municipio: empresa.municipio, uf: empresa.uf,
    porte: empresa.porte, cnae: empresa.cnae, situacao: empresa.situacao,
  };
  const rows = [];
  (contatos || []).forEach(c => {
    const common = {
      ...base,
      contato_tipo: c.tipo === 'decisor' ? 'Decisor' : 'Sócio',
      contato_nome: c.nome, contato_cargo: c.cargo, contato_cpf: fmtCpf(c.cpf || ''),
      contato_cpf_raw: onlyDigits(c.cpf || ''),
    };
    const tels = (c.telefones || []).filter(t => t.raw);
    if (!tels.length) {
      rows.push({ ...common, telefone: '', telefone_raw: '', tel_categoria: '', validado: '', nome_donodozap: '' });
    } else {
      tels.forEach(t => rows.push({
        ...common,
        telefone: fmtPhone(t.raw), telefone_raw: t.raw,
        tel_categoria: catLabel(t.categoria),
        validado: '', nome_donodozap: '',
      }));
    }
  });
  return rows;
}

function renderProspTable() {
  const wrap = document.getElementById('prosp-table-wrap');
  const rows = prospState.rows;
  if (!rows.length) {
    wrap.innerHTML = `<p class="msg" style="padding:16px">Nenhum contato encontrado nas empresas selecionadas.</p>`;
    return;
  }
  const comTel = rows.filter(r => r.telefone_raw).length;
  wrap.innerHTML = `
    <div class="prosp-toolbar">
      <span class="prosp-count">${rows.length} contatos · ${comTel} com telefone</span>
      <div class="prosp-toolbar-btns">
        <button id="pf-validar" class="btn-secondary" ${comTel ? '' : 'disabled'}>✅ Validar telefones (telefone reverso)</button>
        <select id="pf-layout" class="filter-select" title="Layout da planilha">
          <option value="empresa" selected>1 empresa por linha</option>
          <option value="contato">1 contato por linha</option>
        </select>
        <button id="pf-modelo" class="btn-secondary" title="Exportar seguindo os cabeçalhos de uma planilha-modelo sua">📄 Usar meu modelo</button>
        <button id="pf-export" class="btn-primary">⬇️ Exportar planilha (XLSX)</button>
      </div>
    </div>
    <div id="pf-valprog"></div>
    <div class="prosp-table-scroll">
      <table class="prosp-table" id="pf-table">
        <thead><tr>
          <th>Razão Social</th><th>CNPJ</th><th>UF</th><th>Tipo</th><th>Contato</th>
          <th>Cargo</th><th>CPF</th><th>Telefone</th><th>Validado</th><th>Nome / Vínculo</th>
        </tr></thead>
        <tbody>${rows.map((r, i) => prospRowHtml(r, i)).join('')}</tbody>
      </table>
    </div>`;
  document.getElementById('pf-validar').addEventListener('click', prospValidar);
  document.getElementById('pf-export').addEventListener('click', prospExportar);
  document.getElementById('pf-modelo').addEventListener('click', abrirUseModelo);
}

function valBadge(v) {
  if (v === 'sim') return `<span class="val-badge val-ok">✅ sim</span>`;
  if (v === 'não') return `<span class="val-badge val-no">⚠️ não</span>`;
  if (v === 'bloq') return `<span class="val-badge val-nd" title="Chave sem acesso ao módulo de telefone reverso (intelgrax-tel)">🔒 sem acesso</span>`;
  if (v === 'sem_cpf') return `<span class="val-badge val-nd" title="Sócio sem CPF resolvido — não dá pra validar o vínculo">❓ sem CPF</span>`;
  if (v === 'n/d') return `<span class="val-badge val-nd">❓ n/d</span>`;
  return '<span class="val-badge val-pend">—</span>';
}

function prospRowHtml(r, i) {
  return `<tr id="pf-row-${i}">
    <td>${esc(r.razao_social)}</td><td class="mono">${esc(r.cnpj)}</td><td>${esc(r.uf)}</td>
    <td>${esc(r.contato_tipo)}</td><td>${esc(r.contato_nome)}</td><td>${esc(r.contato_cargo)}</td>
    <td class="mono">${esc(r.contato_cpf)}</td>
    <td class="mono">${esc(r.telefone)}${r.tel_categoria ? ` <span class="tel-cat">${esc(r.tel_categoria)}</span>` : ''}</td>
    <td id="pf-val-${i}">${valBadge(r.validado)}</td>
    <td id="pf-dz-${i}">${esc(r.nome_donodozap)}</td>
  </tr>`;
}

async function prospValidar() {
  if (prospState.validating) return;
  prospState.validating = true;
  const btn = document.getElementById('pf-validar');
  const exp = document.getElementById('pf-export');
  const prog = document.getElementById('pf-valprog');
  btn.disabled = true; exp.disabled = true;

  const idxs = prospState.rows.map((r, i) => i).filter(i => prospState.rows[i].telefone_raw);
  let done = 0, semAcesso = false;
  for (const i of idxs) {
    const r = prospState.rows[i];
    prog.innerHTML = `<div class="prosp-progress"><span class="spinner"></span> Validando ${++done} de ${idxs.length} (telefone reverso)…</div>`;
    if (!r.contato_cpf_raw) {
      r.validado = 'sem_cpf'; r.nome_donodozap = '';
    } else {
      try {
        const v = await fetch(`${API}/api/phone/${r.telefone_raw}/pertence/${r.contato_cpf_raw}`).then(x => x.json());
        if (v.status === 'no_access') { r.validado = 'bloq'; r.nome_donodozap = ''; semAcesso = true; }
        else if (v.status !== 'ok') { r.validado = 'n/d'; r.nome_donodozap = ''; }
        else if (v.atrelado) { r.validado = 'sim'; r.nome_donodozap = v.nome || ''; }
        else { r.validado = 'não'; r.nome_donodozap = v.alerta_compartilhado ? `número compartilhado (${v.total} vínculos)` : ''; }
      } catch (e) { r.validado = 'n/d'; r.nome_donodozap = ''; }
    }
    const vc = document.getElementById(`pf-val-${i}`); if (vc) vc.innerHTML = valBadge(r.validado);
    const dc = document.getElementById(`pf-dz-${i}`); if (dc) dc.textContent = r.nome_donodozap;
  }
  if (semAcesso) {
    prog.innerHTML = `<div class="prosp-progress" style="color:#b45309">🔒 A chave da WorkAPI não tem acesso ao módulo de telefone reverso (intelgrax-tel) — peça pra habilitar. Os telefones vieram da Mk Buscas (já associados ao CPF); a coluna "Validado" ficou como 🔒 sem acesso.</div>`;
  } else {
    prog.innerHTML = `<div class="prosp-progress prosp-done">✅ Validação concluída: ${prospState.rows.filter(r => r.validado === 'sim').length} telefone(s) confirmado(s).</div>`;
  }
  prospState.validating = false;
  btn.disabled = false; exp.disabled = false;
}

async function prospExportar() {
  const exp = document.getElementById('pf-export');
  exp.disabled = true;
  // Formato enriquecido (padrão Datastone): 1 linha por empresa, blocos de contato.
  const empresas = (prospState.leads || []).map(l => ({ empresa: l.empresa, contatos: l.contatos }));
  const layout = document.getElementById('pf-layout')?.value || 'empresa';
  const fonteTel = document.getElementById('pf-fontetel')?.value || 'assertiva';
  const body = empresas.length
    ? { empresas, layout, fonte_tel: fonteTel }
    : { rows: prospState.rows, fonte_tel: fonteTel };  // fallback antigo se não houver leads crus
  try {
    const resp = await fetch(`${API}/api/export/xlsx`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'capiblu-prospeccao.xlsx';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('Falha ao exportar: ' + e.message);
  } finally {
    exp.disabled = false;
  }
}

// ── Toggle de Perfil: Empresas | Clientes potenciais (sócios) ──────────
prospState.perfil = 'empresa';
function prospTrocarPerfil(perfil) {
  prospState.perfil = perfil;
  document.getElementById('pf-perfil-empresa').classList.toggle('active', perfil === 'empresa');
  document.getElementById('pf-perfil-pessoa').classList.toggle('active', perfil === 'pessoa');
  document.getElementById('pf-group-pessoa').hidden = perfil !== 'pessoa';
  document.getElementById('pf-perfil-note-pessoa').hidden = perfil !== 'pessoa';
}
document.getElementById('pf-perfil-empresa').addEventListener('click', () => prospTrocarPerfil('empresa'));
document.getElementById('pf-perfil-pessoa').addEventListener('click', () => prospTrocarPerfil('pessoa'));

// Toggle simples "deixar de fora fechadas/suspensas" — espelha no select detalhado
// de situação cadastral (que fica nos filtros avançados), sem duplicar lógica de busca.
document.getElementById('pf-somente-ativas').addEventListener('change', e => {
  document.getElementById('pf-situacao').value = e.target.checked ? 'ATIVA' : '';
});

function prospFiltrar() {
  return prospState.perfil === 'pessoa' ? prospBuscarPessoas() : prospBuscar();
}
document.getElementById('pf-buscar').addEventListener('click', prospFiltrar);
document.getElementById('pf-texto').addEventListener('keydown', e => e.key === 'Enter' && prospFiltrar());
document.getElementById('pf-cnpj').addEventListener('keydown', e => e.key === 'Enter' && prospFiltrar());
document.getElementById('pf-nome').addEventListener('keydown', e => e.key === 'Enter' && prospFiltrar());

// ── Busca de PESSOAS (sócios como proxy — ver nota no painel) ───────────
function prospFiltrosPessoa() {
  const list = v => (v || '').split(',').map(s => s.trim()).filter(Boolean);
  return {
    nome: document.getElementById('pf-nome').value.trim(),
    sobrenome: document.getElementById('pf-sobrenome').value.trim(),
    cargo: document.getElementById('pf-cargo').value.trim(),
    anos_min: parseInt(document.getElementById('pf-anos-min').value) || 0,
    anos_max: parseInt(document.getElementById('pf-anos-max').value) || 0,
    uf: getSelectedUFs(),
    municipio: comboCodes('combo-municipio'),
    setor: document.getElementById('pf-setor').value.trim(),
    cnae: comboCodes('combo-cnae'),
    natureza: comboCodes('combo-natureza'),
    porte: list(document.getElementById('pf-porte').value),
    tipo_empresa: document.getElementById('pf-tipo-empresa').value,
    nome_empresa: document.getElementById('pf-nome-empresa').value.trim(),
    fundada_de: document.getElementById('pf-fundada-de').value,
    fundada_ate: document.getElementById('pf-fundada-ate').value,
    mei_optante: document.getElementById('pf-mei-optante').checked,
    mei_excluir: document.getElementById('pf-mei-excluir').checked,
    cnpj: onlyDigits(document.getElementById('pf-cnpj').value),
  };
}

async function prospBuscarPessoas() {
  const btn = document.getElementById('pf-buscar');
  const out = document.getElementById('prosp-results');
  const cnt = document.getElementById('pf-count');
  btn.disabled = true;
  cnt.textContent = '';
  out.innerHTML = spinner();
  try {
    const res = await fetch(`${API}/api/prospeccao/pessoas`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filtros: prospFiltrosPessoa(), limite: 200 }),
    }).then(r => r.json());

    if (res.status !== 'ok') {
      out.innerHTML = `<p class="msg error">${esc(res.message || 'Falha na busca.')}</p>`;
      return;
    }
    const pessoas = res.pessoas || [];
    const totalStr = res.total_aprox ? `${(res.total || pessoas.length).toLocaleString('pt-BR')}+` : (res.total || pessoas.length).toLocaleString('pt-BR');
    cnt.textContent = `${totalStr} pessoas (sócios) · proxy — LinkedIn ainda não conectado`;
    if (!pessoas.length) {
      out.innerHTML = `<p class="msg">Nenhuma pessoa encontrada com esses filtros.</p>`;
      return;
    }
    out.innerHTML = `
      <div class="prosp-table-scroll">
        <table class="prosp-table">
          <thead><tr><th>NOME</th><th>CARGO</th><th>EMPRESA</th><th>LOCALIZAÇÃO</th><th>CNPJ</th></tr></thead>
          <tbody>${pessoas.map(p => `
            <tr>
              <td>${esc(p.nome)}</td>
              <td>${esc(p.cargo || '—')}</td>
              <td>${esc(p.empresa)}</td>
              <td>${esc([p.municipio, p.uf].filter(Boolean).join(', ')) || '—'}</td>
              <td class="mono">${esc(p.cnpj)}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (e) {
    out.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

// Sidebar de filtros retrátil (estilo Datastone)
document.getElementById('prosp-collapse-btn').addEventListener('click', () => {
  document.getElementById('prosp-sidebar').classList.add('collapsed');
  document.getElementById('prosp-expand-btn').hidden = false;
});
document.getElementById('prosp-expand-btn').addEventListener('click', () => {
  document.getElementById('prosp-sidebar').classList.remove('collapsed');
  document.getElementById('prosp-expand-btn').hidden = true;
});

// Combobox pesquisável (CNAE / Natureza) — funciona como um "select" filtrável.
// ── UF em chips (múltipla seleção) ──
const _UFS_LIST = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG',
  'PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SE','SP','TO'];
(function buildUFChips() {
  const box = document.getElementById('pf-uf');
  if (!box || box.dataset.built) return;
  box.dataset.built = '1';
  box.innerHTML = _UFS_LIST.map(u => `<button type="button" class="uf-chip" data-uf="${u}">${u}</button>`).join('');
  box.addEventListener('click', e => { const b = e.target.closest('.uf-chip'); if (b) b.classList.toggle('active'); });
})();
function getSelectedUFs() {
  return [...document.querySelectorAll('#pf-uf .uf-chip.active')].map(b => b.dataset.uf);
}
// códigos selecionados de um combo multi (cnae/natureza/municipio)
function comboCodes(id) {
  const c = document.getElementById(id);
  return (c && c._codes ? c._codes : []).map(x => x.code);
}

// Combobox com MÚLTIPLA seleção (chips). CNAE/Natureza/Município.
function setupCombo(comboId) {
  const combo = document.getElementById(comboId);
  if (!combo) return;
  const input = combo.querySelector('.combo-input');
  const listEl = combo.querySelector('.combo-list');
  const isMunicipio = combo.dataset.tipo === 'municipio';
  combo._codes = [];
  let chips = combo.querySelector('.combo-chips');
  if (!chips) { chips = document.createElement('div'); chips.className = 'combo-chips'; combo.appendChild(chips); }
  let itens = [];
  fetch(`${API}/api/cnpj/lookup?tipo=${combo.dataset.tipo}`).then(r => r.json())
    .then(j => { itens = j.itens || []; }).catch(() => { itens = []; });

  const label = it => isMunicipio && it.uf ? `${it.descricao} — ${it.uf}` : it.descricao;
  const norm = s => (s || '').toLowerCase();
  function renderChips() {
    chips.innerHTML = combo._codes.map(c =>
      `<span class="combo-chip" data-code="${esc(c.code)}"><b title="${esc(c.label)}">${esc(c.label)}</b><span class="x">✕</span></span>`).join('');
  }
  function add(code, lbl) {
    code = String(code || '').trim();
    if (!code || combo._codes.some(c => c.code === code)) return;
    combo._codes.push({ code, label: lbl || code }); renderChips();
  }
  chips.addEventListener('mousedown', e => {
    const x = e.target.closest('.x'); if (!x) return;
    const code = x.closest('.combo-chip').dataset.code;
    combo._codes = combo._codes.filter(c => c.code !== code); renderChips();
  });
  function render(q) {
    q = norm(q);
    const ufSel = getSelectedUFs();
    let pool = (isMunicipio && ufSel.length) ? itens.filter(it => ufSel.includes(it.uf)) : itens;
    const matches = (!q ? pool.slice(0, 30) : pool.filter(it => norm(it.descricao).includes(q)).slice(0, 30));
    if (!matches.length) { listEl.hidden = true; return; }
    listEl.innerHTML = matches.map(it =>
      `<div class="combo-opt" data-code="${it.codigo}" data-label="${esc(label(it))}">${esc(label(it))}</div>`).join('');
    listEl.hidden = false;
  }
  input.addEventListener('input', () => render(input.value));
  input.addEventListener('focus', () => render(input.value));
  input.addEventListener('blur', () => setTimeout(() => { listEl.hidden = true; }, 180));
  input.addEventListener('keydown', e => {   // CNAE/natureza: Enter adiciona o código cru digitado
    if (e.key === 'Enter' && !isMunicipio) {
      const raw = input.value.replace(/\D/g, '');
      if (raw) { add(raw, raw); input.value = ''; listEl.hidden = true; e.preventDefault(); }
    }
  });
  listEl.addEventListener('mousedown', e => {
    const opt = e.target.closest('.combo-opt'); if (!opt) return;
    add(opt.dataset.code, opt.dataset.label); input.value = ''; listEl.hidden = true;
  });
}
setupCombo('combo-cnae');
setupCombo('combo-natureza');
setupCombo('combo-municipio');

// ══════════════════════════════════════════════════════
//  MÓDULO TELEFONE REVERSO (WorkAPI intelgrax-tel)
// ══════════════════════════════════════════════════════
const telQ = document.getElementById('tel-q');
const telBtn = document.getElementById('tel-btn');
const telRes = document.getElementById('tel-results');

async function buscarTelefone() {
  const raw = onlyDigits(telQ.value);
  if (raw.length < 10) { telRes.innerHTML = `<p class="msg">Digite um telefone com DDD.</p>`; return; }
  telBtn.disabled = true;
  telRes.innerHTML = spinner();
  try {
    const j = await fetch(`${API}/api/phone/${raw}/reverse`).then(r => r.json());
    if (j.status === 'no_access') {
      telRes.innerHTML = `<p class="msg error">🔒 ${esc(j.message || 'Módulo intelgrax-tel não habilitado nesta chave.')}</p>`;
      return;
    }
    if (j.status !== 'ok') {
      telRes.innerHTML = `<p class="msg error">${esc(j.message || 'Falha na consulta.')}</p>`;
      return;
    }
    const regs = j.registros || [];
    const shared = (j.total || 0) >= 50;
    telRes.innerHTML = `
      <div class="tel-head">
        <strong>${(j.total || 0).toLocaleString('pt-BR')}</strong> CPF/CNPJ atrelado(s) a ${esc(fmtPhone(raw))}
        ${shared ? `<span class="tel-warn">⚠️ número compartilhado/lixo (muitos vínculos) — vínculo fraco</span>` : ''}
        ${j.remaining_daily != null ? `<span class="tel-remaining">saldo diário: ${j.remaining_daily}</span>` : ''}
      </div>
      <div class="prosp-table-scroll">
        <table class="prosp-table">
          <thead><tr><th>CPF/CNPJ</th><th>Nome</th><th>Cidade/UF</th><th>Endereço</th></tr></thead>
          <tbody>${regs.map(r => {
            const e = r.endereco || {};
            const loc = [e.cidade, e.uf].filter(Boolean).join('/');
            const end = [e.tipoLogradouro, e.logradouro, e.logradouroNumero, e.bairro].filter(Boolean).join(' ');
            return `<tr><td class="mono">${esc(r.cpf_cnpj)}</td><td>${esc(r.nome)}</td><td>${esc(loc)}</td><td>${esc(end)}</td></tr>`;
          }).join('')}</tbody>
        </table>
      </div>`;
    logBusca('Telefone', fmtPhone(raw), `${(j.total || 0).toLocaleString('pt-BR')} vínculo(s)`);
  } catch (e) {
    telRes.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    telBtn.disabled = false;
  }
}
telBtn.addEventListener('click', buscarTelefone);
telQ.addEventListener('input', e => { e.target.value = fmtPhone(e.target.value); });
telQ.addEventListener('keydown', e => e.key === 'Enter' && buscarTelefone());

// Verifica, via telefone reverso (WorkAPI), se cada telefone aponta pro CPF.
window.verificarTelefonesCpf = async function(cpf) {
  const cells = [...document.querySelectorAll('#tel-verify-table .tel-verify-cell')];
  for (const cell of cells) {
    const raw = cell.dataset.raw;
    if (!raw || raw.length < 10) { cell.textContent = '—'; continue; }
    cell.innerHTML = '<span class="spinner" style="width:12px;height:12px"></span>';
    try {
      const v = await fetch(`${API}/api/phone/${raw}/pertence/${cpf}`).then(r => r.json());
      if (v.status === 'no_access') { cell.innerHTML = `<span class="val-badge val-nd" title="${esc(v.message||'')}">🔒 sem acesso</span>`; }
      else if (v.status !== 'ok') { cell.innerHTML = `<span class="val-badge val-nd">❓ erro</span>`; }
      else if (v.atrelado) { cell.innerHTML = `<span class="val-badge val-ok">✅ sim</span>${v.alerta_compartilhado ? ' <span class="val-badge val-no" title="número com muitos vínculos">🔶 compart.</span>' : ''}`; }
      else { cell.innerHTML = `<span class="val-badge val-no">⚠️ não${v.alerta_compartilhado ? ' (compart.)' : ''}</span>`; }
    } catch (e) { cell.innerHTML = `<span class="val-badge val-nd">❓</span>`; }
  }
};

// ══════════════════════════════════════════════════════
//  MÓDULO BUSCA ASSERTIVA (API Localize V3)
// ══════════════════════════════════════════════════════
const UFS = ['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MT','MS','MG',
  'PA','PB','PR','PE','PI','RJ','RN','RO','RS','RR','SC','SE','SP','TO'];
(function initAssertiva() {
  const uf = document.getElementById('as-uf');
  if (uf) UFS.forEach(u => { const o = document.createElement('option'); o.value = u; o.textContent = u; uf.appendChild(o); });

  let modo = 'cpf';
  const btnsModo = [...document.querySelectorAll('.as-modo')];
  btnsModo.forEach(b => b.addEventListener('click', () => {
    modo = b.dataset.modo;
    btnsModo.forEach(x => x.classList.toggle('active', x === b));
    document.querySelectorAll('.as-campo').forEach(c => { c.hidden = c.dataset.campo !== modo; });
  }));

  // Avisa se as credenciais não estão no .env (não expõe nada).
  fetch(`${API}/api/assertiva/status`).then(r => r.json()).then(j => {
    const note = document.getElementById('as-config-note');
    if (note && !j.enabled) {
      note.innerHTML = `<p class="msg" style="margin-top:10px">⚙️ Integração ainda não configurada. Adicione <code>ASSERTIVA_CLIENT_ID</code> e <code>ASSERTIVA_CLIENT_SECRET</code> no <code>.env</code> e reinicie o servidor.</p>`;
    }
  }).catch(() => {});

  const val = id => (document.getElementById(id)?.value || '').trim();
  const btn = document.getElementById('as-btn');
  const out = document.getElementById('as-results');

  async function consultar() {
    const fin = val('as-finalidade');
    let req;
    if (modo === 'cpf') {
      const d = onlyDigits(val('as-cpf'));
      if (d.length < 3) return toast('Informe um CPF.');
      req = fetch(`${API}/api/assertiva/cpf?cpf=${d}&finalidade=${fin}`);
    } else if (modo === 'cnpj') {
      const d = onlyDigits(val('as-cnpj'));
      if (d.length < 8) return toast('Informe um CNPJ.');
      req = fetch(`${API}/api/assertiva/cnpj?cnpj=${d}&finalidade=${fin}`);
    } else if (modo === 'telefone') {
      const d = onlyDigits(val('as-telefone'));
      if (d.length < 10) return toast('Informe um telefone com DDD.');
      req = fetch(`${API}/api/assertiva/telefone?telefone=${d}&finalidade=${fin}`);
    } else if (modo === 'email') {
      const e = val('as-email');
      if (!e.includes('@')) return toast('Informe um e-mail válido.');
      req = fetch(`${API}/api/assertiva/email?email=${encodeURIComponent(e)}&finalidade=${fin}`);
    } else { // nome
      const filtros = {
        buscarPor: val('as-buscarpor') || 'ambas',
        nomeOuRazaoSocial: val('as-nome'),
        nomeOuRazaoSocialExata: document.getElementById('as-exata').checked,
        sexo: val('as-sexo'), dataNascimentoOuAbertura: val('as-data'),
        uf: val('as-uf'), cidade: val('as-cidade'), bairro: val('as-bairro'),
        cepOuNomeRua: val('as-cepourua'),
      };
      if (!filtros.nomeOuRazaoSocial && !filtros.cepOuNomeRua) return toast('Informe o nome ou o CEP/rua.');
      req = fetch(`${API}/api/assertiva/nome`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filtros, finalidade: parseInt(fin) }),
      });
    }
    btn.disabled = true; out.innerHTML = spinner();
    try {
      const j = await req.then(r => r.json());
      renderAssertiva(j, modo);
      logBusca('Assertiva (' + modo + ')', val('as-cpf') || val('as-cnpj') || val('as-telefone') || val('as-email') || val('as-nome') || '—', j.status === 'ok' ? 'Encontrado' : (j.message || 'Sem resultado'));
    } catch (e) {
      out.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
    } finally { btn.disabled = false; }
  }

  function toast(m) { out.innerHTML = `<p class="msg">${esc(m)}</p>`; }
  btn.addEventListener('click', consultar);
  ['as-cpf','as-cnpj','as-telefone','as-email','as-nome','as-cepourua'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => e.key === 'Enter' && consultar());
  });
  const cpfEl = document.getElementById('as-cpf');
  if (cpfEl) cpfEl.addEventListener('input', e => e.target.value = fmtCpf(e.target.value));
  const cnpjEl = document.getElementById('as-cnpj');
  if (cnpjEl) cnpjEl.addEventListener('input', e => e.target.value = fmtCnpj(e.target.value));
  const telEl = document.getElementById('as-telefone');
  if (telEl) telEl.addEventListener('input', e => e.target.value = fmtPhone(e.target.value));
})();

// Monta o HTML com TODOS os blocos da resposta da Assertiva (cadastral, contatos,
// endereços, sócios, decisores, + qualquer campo restante renderizado automaticamente,
// + JSON completo). Compartilhado entre a aba "Consulta Assertiva" e o ranking
// agressivo da Busca por Nome — nenhum dado fica de fora em nenhum dos dois lugares.
function montarHtmlAssertiva(data, modo) {
  const cab = data.cabecalho || {};
  const resp = data.resposta || {};
  let html = `<div class="as-cab">
    <span class="as-cab-prod">${esc(cab.produto || 'Localize')} · ${esc(cab.funcionalidade || modo)}</span>
    ${cab.protocolo ? `<span class="as-cab-proto">protocolo: ${esc(cab.protocolo)}</span>` : ''}
    ${data.alerta ? `<span class="tel-warn">⚠️ ${esc(data.alerta)}</span>` : ''}
  </div>`;

  // Chaves que já ganham um bloco dedicado abaixo — o resto é renderizado
  // automaticamente, pra nenhum dado do JSON ficar só no "Ver JSON completo".
  const consumidas = new Set([
    'dadosCadastrais', 'telefones', 'telefonesAdicionados', 'emails', 'emailsAdicionados',
    'enderecos', 'enderecosAdicionados', 'socios', 'possiveisDecisores', 'pessoaFisica', 'pessoaJuridica',
  ]);

  // CPF / CNPJ → ficha cadastral + contatos
  if (modo === 'cpf' || modo === 'cnpj') {
    html += asCadastralCard(resp.dadosCadastrais || {});
    html += asContatoBlock('📞 Telefones', flattenTelefones(resp.telefones, resp.telefonesAdicionados));
    html += asListBlock('✉️ E-mails', mergeArr(resp.emails, resp.emailsAdicionados).map(e => e.email || e.enderecoEmail || e.valor || asStr(e)));
    html += asEnderecoBlock(mergeArr(resp.enderecos, resp.enderecosAdicionados));
    if (resp.socios?.length) html += asPeopleTable('👥 Sócios', resp.socios);
    if (resp.possiveisDecisores?.length) html += asPeopleTable('🎯 Possíveis decisores', resp.possiveisDecisores);
  } else {
    // telefone / email / nome → listas de pessoas físicas e jurídicas
    const pf = resp.pessoaFisica || [], pj = resp.pessoaJuridica || [];
    if (pf.length) html += asPeopleTable('👤 Pessoas físicas', pf);
    if (pj.length) html += asPeopleTable('🏢 Pessoas jurídicas', pj);
    if (!pf.length && !pj.length) html += `<p class="msg">Nenhum registro vinculado encontrado.</p>`;
  }

  // Todo o resto do JSON que a Assertiva devolveu e ainda não apareceu em
  // nenhum bloco acima — renderizado automaticamente (tabela/lista/kv conforme o formato).
  Object.keys(resp).forEach(k => {
    if (consumidas.has(k)) return;
    html += asAutoRender(humanKey(k), resp[k]);
  });
  Object.keys(data).forEach(k => {
    if (k === 'cabecalho' || k === 'resposta' || k === 'alerta') return;
    html += asAutoRender(humanKey(k), data[k]);
  });

  html += `<details class="as-raw"><summary>Ver JSON completo</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;
  return html;
}

function renderAssertiva(j, modo) {
  const out = document.getElementById('as-results');
  const msgs = {
    unavailable: '⚙️ Integração não configurada (defina ASSERTIVA_CLIENT_ID/SECRET no .env).',
    auth_error: '🔒 Falha ao autenticar na Assertiva. Confira as credenciais.',
    no_access: '🚫 Sem permissão para este recurso na Assertiva (403).',
    invalid: '⚠️ Dados inválidos para a consulta.',
    error: '❌ Erro na consulta.',
  };
  if (j.status !== 'ok') {
    out.innerHTML = `<p class="msg error">${esc(msgs[j.status] || j.message || 'Falha.')}${j.message && msgs[j.status] ? ' — ' + esc(j.message) : ''}</p>`;
    return;
  }
  out.innerHTML = montarHtmlAssertiva(j.data || {}, modo);
}

// Renderiza qualquer valor "sobrando" do JSON da Assertiva sem card dedicado —
// tabela se for lista de objetos, lista simples se for lista de valores,
// pares chave/valor se for objeto, ou uma linha só se for valor simples.
function asAutoRender(titulo, valor) {
  if (valor == null || valor === '' || (Array.isArray(valor) && !valor.length)) return '';
  if (Array.isArray(valor)) {
    if (typeof valor[0] === 'object' && valor[0] !== null) {
      const cols = [...new Set(valor.flatMap(v => Object.keys(v || {})))].slice(0, 6);
      const rows = valor.map(v => `<tr>${cols.map(c => `<td>${esc(asStr(v[c]))}</td>`).join('')}</tr>`).join('');
      return `<div class="as-card"><h4>${esc(titulo)} <span class="as-count">${valor.length}</span></h4>
        <div class="prosp-table-scroll"><table class="prosp-table">
        <thead><tr>${cols.map(c => `<th>${esc(humanKey(c))}</th>`).join('')}</tr></thead>
        <tbody>${rows}</tbody></table></div></div>`;
    }
    return asListBlock(titulo, valor.map(asStr));
  }
  if (typeof valor === 'object') return asCadastralCard(valor);
  return `<div class="as-card"><h4>${esc(titulo)}</h4><div class="as-kv"><div><strong>${esc(asStr(valor))}</strong></div></div></div>`;
}

// ── helpers de render Assertiva ──
function asStr(v) { return (v == null) ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v)); }
function mergeArr(a, b) { return [...(Array.isArray(a) ? a : []), ...(Array.isArray(b) ? b : [])]; }
function humanKey(k) {
  return k.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, c => c.toUpperCase());
}
function asCadastralCard(dc) {
  const keys = Object.keys(dc || {}).filter(k => dc[k] != null && typeof dc[k] !== 'object' && dc[k] !== '');
  if (!keys.length) return '';
  return `<div class="as-card"><h4>📋 Dados cadastrais</h4><div class="as-kv">${
    keys.map(k => `<div><span>${esc(humanKey(k))}</span><strong>${esc(asStr(dc[k]))}</strong></div>`).join('')
  }</div></div>`;
}
function flattenTelefones(principais, adicionados) {
  const arr = [];
  const push = (t) => { if (t) arr.push(t); };
  const norm = (t) => {
    if (typeof t === 'string') return { numero: t };
    return {
      numero: t.numero || t.telefone || [t.ddd, t.numero].filter(Boolean).join(' ') || asStr(t),
      tipo: t.tipoTelefone || t.tipo || '', whatsApp: t.whatsApp ?? t.aplicativos?.whatsApp,
      ranking: t.ranking || t.classificacao || '',
    };
  };
  const collect = (src) => {
    if (!src) return;
    if (Array.isArray(src)) src.forEach(x => push(norm(x)));
    else if (typeof src === 'object') Object.values(src).forEach(v => Array.isArray(v) ? v.forEach(x => push(norm(x))) : (v && typeof v === 'object' && push(norm(v))));
  };
  collect(principais); collect(adicionados);
  return arr;
}
function asContatoBlock(titulo, tels) {
  if (!tels || !tels.length) return '';
  return `<div class="as-card"><h4>${esc(titulo)}</h4>
    <table class="prosp-table"><thead><tr><th>Número</th><th>Tipo</th><th>WhatsApp</th><th>Ranking</th></tr></thead>
    <tbody>${tels.map(t => `<tr>
      <td class="mono">${esc(t.numero || '')}</td><td>${esc(t.tipo || '')}</td>
      <td>${t.whatsApp === true ? '✅' : (t.whatsApp === false ? '—' : '')}</td>
      <td>${esc(t.ranking || '')}</td></tr>`).join('')}</tbody></table></div>`;
}
function asListBlock(titulo, items) {
  const list = (items || []).filter(Boolean);
  if (!list.length) return '';
  return `<div class="as-card"><h4>${esc(titulo)}</h4><ul class="as-ul">${
    list.map(i => `<li>${esc(asStr(i))}</li>`).join('')}</ul></div>`;
}
function asEnderecoBlock(ends) {
  if (!ends || !ends.length) return '';
  const fmt = e => [e.tipoLogradouro, e.logradouro, e.numero, e.complemento, e.bairro,
    [e.cidade, e.uf].filter(Boolean).join('/'), e.cep].filter(Boolean).join(', ');
  return `<div class="as-card"><h4>📍 Endereços</h4><ul class="as-ul">${
    ends.map(e => `<li>${esc(fmt(e))}</li>`).join('')}</ul></div>`;
}
function asPeopleTable(titulo, people) {
  const rows = (people || []).map(p => {
    const nome = p.nome || p.razaoSocial || p.nomeCompleto || '';
    const doc = p.cpf || p.cnpj || p.documento || '';
    const extra = p.dataNascimento || p.dataAbertura || p.idade || p.tipo || p.parentesco || p.cargo || '';
    const loc = p.uf ? [p.cidade, p.uf].filter(Boolean).join('/') : (p.endereco ? asStr(p.endereco) : '');
    return `<tr><td>${esc(nome)}</td><td class="mono">${esc(doc)}</td><td>${esc(asStr(extra))}</td><td>${esc(loc)}</td></tr>`;
  }).join('');
  return `<div class="as-card"><h4>${esc(titulo)} <span class="as-count">${people.length}</span></h4>
    <div class="prosp-table-scroll"><table class="prosp-table">
    <thead><tr><th>Nome / Razão</th><th>Documento</th><th>Info</th><th>Local</th></tr></thead>
    <tbody>${rows}</tbody></table></div></div>`;
}

// ══════════════════════════════════════════════════════
//  MÓDULO ENRIQUECER LISTA (upload XLSX → RFB + Assertiva + integralX)
// ══════════════════════════════════════════════════════
const enrichState = { upload_id: null, sheets: [], result: null };

(function initEnrich() {
  const fileEl = document.getElementById('en-file');
  const nameEl = document.getElementById('en-file-name');
  const cfg = document.getElementById('en-config');
  const sheetSel = document.getElementById('en-sheet');
  const colSel = document.getElementById('en-cnpjcol');
  const out = document.getElementById('en-results');
  if (!fileEl) return;

  // Carrega o catálogo de campos (checkboxes agrupados).
  fetch(`${API}/api/enrich/catalog`).then(r => r.json()).then(cat => {
    const box = document.getElementById('en-catalog');
    box.innerHTML = cat.grupos.map(g => `
      <div class="en-group">
        <div class="en-group-head">
          <label><input type="checkbox" class="en-group-all" data-grupo="${esc(g.grupo)}" /> <strong>${esc(g.grupo)}</strong></label>
          <span class="en-group-src">${esc(g.fonte)}</span>
        </div>
        <div class="en-group-fields">
          ${g.campos.map(c => `<label class="en-chk"><input type="checkbox" class="en-field" value="${c.key}" ${c.key.startsWith('rfb_') ? 'checked' : ''}/> ${esc(c.label)}</label>`).join('')}
        </div>
      </div>`).join('');
    const note = document.getElementById('en-src-note');
    const parts = [];
    if (!cat.assertiva_ok) parts.push('⚠️ Assertiva não configurada');
    if (!cat.integralx_ok) parts.push('⚠️ integralX sem chave');
    note.textContent = parts.join(' · ');
    box.querySelectorAll('.en-group-all').forEach(g => g.addEventListener('change', e => {
      const grp = e.target.closest('.en-group');
      grp.querySelectorAll('.en-field').forEach(f => { f.checked = e.target.checked; });
    }));
  }).catch(() => {});

  fileEl.addEventListener('change', async () => {
    const f = fileEl.files[0];
    if (!f) return;
    nameEl.textContent = f.name + ' — enviando…';
    const fd = new FormData(); fd.append('file', f);
    try {
      const j = await fetch(`${API}/api/enrich/upload`, { method: 'POST', body: fd }).then(r => r.json());
      if (j.status !== 'ok') { nameEl.textContent = j.message || 'Falha no upload.'; return; }
      enrichState.upload_id = j.upload_id;
      enrichState.sheets = j.sheets;
      sheetSel.innerHTML = j.sheets.map(s => `<option value="${esc(s.name)}">${esc(s.name)} (${s.linhas})</option>`).join('');
      syncCols();
      cfg.hidden = false;
      const tot = j.sheets.reduce((a, s) => a + s.linhas, 0);
      nameEl.textContent = `${f.name} — ${j.sheets.length} aba(s), ${tot} linhas` + (j.aviso ? ` · ⚠️ ${j.aviso}` : '');
      logBusca('Planilha', f.name, `${tot} linhas`);
    } catch (e) { nameEl.textContent = 'Erro: ' + e.message; }
  });

  function syncCols() {
    const s = enrichState.sheets.find(x => x.name === sheetSel.value) || enrichState.sheets[0];
    if (!s) return;
    colSel.innerHTML = s.columns.map(c => `<option value="${esc(c)}" ${c === s.cnpj_col ? 'selected' : ''}>${esc(c)}</option>`).join('');
  }
  sheetSel.addEventListener('change', syncCols);

  document.getElementById('en-run').addEventListener('click', async () => {
    const fields = [...document.querySelectorAll('.en-field:checked')].map(c => c.value);
    if (!fields.length) { out.innerHTML = `<p class="msg">Selecione ao menos um campo.</p>`; return; }
    const body = {
      upload_id: enrichState.upload_id, sheet: sheetSel.value,
      cnpj_col: colSel.value, fields,
      limite: parseInt(document.getElementById('en-limite').value) || 50,
    };
    document.getElementById('en-run').disabled = true;
    out.innerHTML = `<div class="prosp-progress"><span class="spinner"></span> Enriquecendo ${body.limite} linhas (RFB + Assertiva + integralX)…</div>`;
    try {
      const j = await fetch(`${API}/api/enrich/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(r => r.json());
      if (j.status !== 'ok') { out.innerHTML = `<p class="msg error">${esc(j.message)}</p>`; return; }
      enrichState.result = j;
      renderEnrich(j);
    } catch (e) { out.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; }
    finally { document.getElementById('en-run').disabled = false; }
  });

  document.getElementById('en-export').addEventListener('click', async () => {
    const j = enrichState.result;
    if (!j) return;
    const columns = [...j.base_cols.map(c => ({ key: c, label: c })), ...j.added_cols];
    const resp = await fetch(`${API}/api/enrich/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ columns, rows: j.rows }),
    });
    const blob = await resp.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'lista-enriquecida.xlsx';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });
})();

function renderEnrich(j) {
  const out = document.getElementById('en-results');
  document.getElementById('en-export').hidden = false;
  // Mostra as colunas novas (foco no enriquecimento) + CNPJ/Nome como âncora.
  const anchor = j.base_cols.filter(c => /cnpj|nome/i.test(c)).slice(0, 2);
  const cols = [...anchor, ...j.added_cols.map(c => c.key)];
  const labelOf = k => (j.added_cols.find(a => a.key === k) || {}).label || k;
  out.innerHTML = `
    <p class="msg">✅ ${j.enriquecidas} de ${j.total_aba} linhas enriquecidas. Confira abaixo e exporte (a planilha final mantém TODAS as colunas originais + as novas).</p>
    <div class="prosp-table-scroll"><table class="prosp-table">
      <thead><tr>${cols.map(c => `<th>${esc(anchor.includes(c) ? c : labelOf(c))}</th>`).join('')}</tr></thead>
      <tbody>${j.rows.slice(0, 50).map(r => `<tr>${cols.map(c => {
        const v = r[c]; return `<td>${esc(v == null ? '' : String(v))}</td>`;
      }).join('')}</tr>`).join('')}</tbody>
    </table></div>
    ${j.rows.length > 50 ? `<p class="msg">…mostrando 50 de ${j.rows.length}. O export traz todas.</p>` : ''}`;
}

// ══════════════════════════════════════════════════════
//  MÓDULO MEUS MODELOS (criar/salvar/usar modelos de planilha)
// ══════════════════════════════════════════════════════
const modelosState = { campos: [], editId: null };

function modCampoOptions(sel) {
  return ['<option value="">— não preencher —</option>'].concat(
    modelosState.campos.map(c => `<option value="${c.campo}" ${c.campo === sel ? 'selected' : ''}>${esc(c.label)} · ${esc(c.fonte)}</option>`)
  ).join('');
}
function modRowHtml(c) {
  return `<tr><td><input class="mc-header" value="${esc(c.header || '')}" style="width:100%"></td>
    <td><select class="mc-campo">${modCampoOptions(c.campo)}</select></td>
    <td><input class="mc-idx" type="number" min="1" max="4" value="${c.idx || 1}" style="width:56px"></td>
    <td><button class="danger" data-act="rm" type="button">✕</button></td></tr>`;
}
function modColetar(container) {
  return [...container.querySelectorAll('tr')].map(tr => {
    const h = tr.querySelector('.mc-header'), cp = tr.querySelector('.mc-campo'), ix = tr.querySelector('.mc-idx');
    if (!h || !cp) return null;
    return { header: h.value.trim(), campo: cp.value, idx: parseInt(ix && ix.value) || 1 };
  }).filter(c => c && c.header);
}

(function initModelos() {
  fetch(`${API}/api/prospeccao/modelo/campos`).then(r => r.json()).then(j => { modelosState.campos = j.campos || []; }).catch(() => {});
  const novo = document.getElementById('mod-novo');
  if (!novo) return;
  novo.addEventListener('click', () => modAbrirBuilder([{ header: 'CNPJ', campo: 'cnpj', idx: 1 }], null, ''));
  document.getElementById('mod-upload').addEventListener('change', modOnUpload);
  document.querySelector('[data-tab="modelos"]').addEventListener('click', () => { modCarregarLista(); modCustosCarregar(); });
  const lista = document.getElementById('mod-lista');
  lista.addEventListener('click', e => {
    const btn = e.target.closest('button'); if (!btn) return;
    const tr = btn.closest('tr'); const id = tr.dataset.id;
    const m = (lista._modelos || []).find(x => x.id === id);
    if (btn.dataset.act === 'edit') modAbrirBuilder(m.colunas, m.id, m.nome);
    else if (btn.dataset.act === 'del') { if (confirm('Excluir este modelo?')) fetch(`${API}/api/prospeccao/modelos/${id}`, { method: 'DELETE' }).then(() => modCarregarLista()); }
  });
  // Datas default: últimos 7 dias.
  const hoje = new Date();
  const seteDiasAtras = new Date(hoje.getTime() - 6 * 24 * 60 * 60 * 1000);
  const fmtISO = d => d.toISOString().slice(0, 10);
  document.getElementById('mc-desde').value = fmtISO(seteDiasAtras);
  document.getElementById('mc-ate').value = fmtISO(hoje);
  document.getElementById('mc-atualizar').addEventListener('click', modCustosCarregar);
})();

function modCustosCarregar() {
  const box = document.getElementById('mc-resultado'); if (!box) return;
  const desde = document.getElementById('mc-desde').value;
  const ate = document.getElementById('mc-ate').value;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  fetch(`${API}/api/custos/assertiva?desde=${desde}&ate=${ate}`).then(r => r.json()).then(j => {
    if (j.status !== 'ok') { box.innerHTML = `<p class="msg error">${esc(j.message || 'Falha ao carregar custos.')}</p>`; return; }
    const fmtR$ = v => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
    const linhas = (j.modelos || []).map(m => `
      <tr>
        <td>${m.tipo === 'externo' ? '🧑‍💼 Externo' : (m.tipo === 'interno' ? '🧩 Interno' : '— Sem modelo')}</td>
        <td>${esc(m.modelo_nome)}</td>
        <td>${m.n_consultas}</td>
        <td>${fmtR$(m.custo_total)}</td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="prosp-build-row" style="margin-bottom:10px">
        <span><strong>Total interno:</strong> ${fmtR$(j.custo_interno)}</span>
        <span><strong>Total externo (clientes):</strong> ${fmtR$(j.custo_externo)}</span>
        ${j.custo_sem_modelo ? `<span><strong>Sem modelo:</strong> ${fmtR$(j.custo_sem_modelo)}</span>` : ''}
        <span><strong>Total geral:</strong> ${fmtR$(j.total_geral)} (${j.total_consultas} consulta(s) · R$${j.custo_por_consulta.toFixed(3)}/consulta)</span>
      </div>
      ${j.modelos && j.modelos.length
        ? `<table class="prosp-table"><thead><tr><th>Tipo</th><th>Modelo</th><th>Consultas</th><th>Custo</th></tr></thead><tbody>${linhas}</tbody></table>`
        : '<p class="msg">Nenhuma consulta Assertiva no período selecionado.</p>'}`;
  }).catch(e => { box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; });
}

function modCarregarLista() {
  const box = document.getElementById('mod-lista'); if (!box) return;
  fetch(`${API}/api/prospeccao/modelos`).then(r => r.json()).then(j => {
    const ms = j.modelos || []; box._modelos = ms;
    box.innerHTML = ms.length
      ? `<table class="prosp-table"><thead><tr><th>Modelo</th><th>Colunas</th><th>Ações</th></tr></thead><tbody>${
        ms.map(m => `<tr data-id="${m.id}"><td><strong>${esc(m.nome)}</strong></td><td>${m.colunas.length}</td>
          <td class="user-actions"><button data-act="edit">Editar</button><button data-act="del" class="danger">Excluir</button></td></tr>`).join('')}</tbody></table>`
      : `<p class="msg">Nenhum modelo salvo. Clique "Novo modelo" ou "Detectar de uma planilha".</p>`;
  });
}
function modOnUpload(e) {
  const f = e.target.files[0]; if (!f) return;
  document.getElementById('mod-upload-name').textContent = f.name + ' — analisando…';
  const fd = new FormData(); fd.append('file', f);
  fetch(`${API}/api/prospeccao/modelo/analisar`, { method: 'POST', body: fd }).then(r => r.json()).then(j => {
    if (j.status !== 'ok') { document.getElementById('mod-upload-name').textContent = j.message || 'Falha.'; return; }
    document.getElementById('mod-upload-name').textContent = `${f.name} — ${j.colunas.filter(c => c.campo).length}/${j.colunas.length} detectados`;
    modAbrirBuilder(j.colunas.map(c => ({ header: c.header, campo: c.campo || '', idx: c.idx || 1 })), null, f.name.replace(/\.[^.]+$/, ''));
  });
}
function modAbrirBuilder(colunas, id, nome) {
  modelosState.editId = id || null;
  const box = document.getElementById('mod-builder'); box.hidden = false;
  box.innerHTML = `<div class="as-card">
    <label class="as-field as-col2"><span>Nome do modelo</span><input id="mod-nome" value="${esc(nome || '')}" placeholder="Ex.: Modelo CRM SP"></label>
    <div class="prosp-table-scroll"><table class="prosp-table"><thead><tr><th>Cabeçalho (como sai na planilha)</th><th>Campo / Fonte que preenche</th><th>Contato #</th><th></th></tr></thead>
      <tbody id="mod-cols-body">${colunas.map(modRowHtml).join('')}</tbody></table></div>
    <div class="en-step"><button id="mod-addcol" class="btn-secondary" type="button">+ coluna</button>
      <button id="mod-salvar" class="btn-primary" type="button">💾 Salvar modelo</button>
      <button id="mod-cancelar" class="btn-secondary" type="button">Cancelar</button></div></div>`;
  box.querySelector('#mod-addcol').addEventListener('click', () => box.querySelector('#mod-cols-body').insertAdjacentHTML('beforeend', modRowHtml({ header: '', campo: '', idx: 1 })));
  box.querySelector('#mod-cols-body').addEventListener('click', e => { if (e.target.closest('[data-act="rm"]')) e.target.closest('tr').remove(); });
  box.querySelector('#mod-cancelar').addEventListener('click', () => { box.hidden = true; });
  box.querySelector('#mod-salvar').addEventListener('click', () => {
    const nomeV = box.querySelector('#mod-nome').value.trim();
    if (!nomeV) { alert('Dê um nome ao modelo.'); return; }
    const colunasV = modColetar(box.querySelector('#mod-cols-body'));
    if (!colunasV.length) { alert('Adicione ao menos uma coluna com cabeçalho.'); return; }
    fetch(`${API}/api/prospeccao/modelos`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: modelosState.editId, nome: nomeV, colunas: colunasV }) })
      .then(r => r.json()).then(j => { if (j.status === 'error') { alert(j.message); return; } box.hidden = true; modCarregarLista(); alert('Modelo salvo!'); });
  });
  box.scrollIntoView();
}

// ── Usar modelo na lista montada (modal) ──
function abrirUseModelo() {
  if (!(prospState.leads || []).length) { alert('Monte a lista de contatos primeiro.'); return; }
  const modal = document.getElementById('usemodelo-modal'); modal.hidden = false;
  document.getElementById('usemodelo-map').innerHTML = '';
  document.getElementById('usemodelo-gerar').hidden = true;
  document.getElementById('usemodelo-save').hidden = true;
  document.getElementById('usemodelo-fname').textContent = '';
  const sel = document.getElementById('usemodelo-sel');
  fetch(`${API}/api/prospeccao/modelos`).then(r => r.json()).then(j => {
    sel.innerHTML = '<option value="">— escolher —</option>' + (j.modelos || []).map(m => `<option value="${m.id}">${esc(m.nome)}</option>`).join('');
    sel._modelos = j.modelos || [];
  });
}
function useRenderMap(colunas) {
  document.getElementById('usemodelo-map').innerHTML = `<div class="prosp-table-scroll"><table class="prosp-table">
    <thead><tr><th>Cabeçalho</th><th>Campo / Fonte</th><th>Contato #</th></tr></thead>
    <tbody>${colunas.map(c => `<tr><td><input class="mc-header" value="${esc(c.header || '')}" style="width:100%"></td>
      <td><select class="mc-campo">${modCampoOptions(c.campo)}</select></td>
      <td><input class="mc-idx" type="number" min="1" max="4" value="${c.idx || 1}" style="width:56px"></td></tr>`).join('')}</tbody></table></div>`;
  document.getElementById('usemodelo-gerar').hidden = false;
  document.getElementById('usemodelo-save').hidden = false;
}
(function wireUseModelo() {
  const modal = document.getElementById('usemodelo-modal'); if (!modal) return;
  document.getElementById('usemodelo-close').addEventListener('click', () => modal.hidden = true);
  document.getElementById('usemodelo-sel').addEventListener('change', e => {
    const m = (e.target._modelos || []).find(x => x.id === e.target.value);
    if (m) useRenderMap(m.colunas);
  });
  document.getElementById('usemodelo-file').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    document.getElementById('usemodelo-fname').textContent = f.name + ' — analisando…';
    const fd = new FormData(); fd.append('file', f);
    fetch(`${API}/api/prospeccao/modelo/analisar`, { method: 'POST', body: fd }).then(r => r.json()).then(j => {
      if (j.status !== 'ok') { document.getElementById('usemodelo-fname').textContent = j.message || 'Falha.'; return; }
      document.getElementById('usemodelo-fname').textContent = f.name;
      useRenderMap(j.colunas.map(c => ({ header: c.header, campo: c.campo || '', idx: c.idx || 1 })));
    });
  });
  document.getElementById('usemodelo-save').addEventListener('click', () => {
    const nome = prompt('Nome do modelo:'); if (!nome) return;
    const colunas = modColetar(document.getElementById('usemodelo-map'));
    fetch(`${API}/api/prospeccao/modelos`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome, colunas }) })
      .then(r => r.json()).then(j => alert(j.status === 'ok' ? 'Modelo salvo!' : (j.message || 'Falha.')));
  });
  document.getElementById('usemodelo-gerar').addEventListener('click', async () => {
    const colunas = modColetar(document.getElementById('usemodelo-map'));
    if (!colunas.length) { alert('Nenhuma coluna.'); return; }
    const empresas = (prospState.leads || []).map(l => ({ empresa: l.empresa, contatos: l.contatos }));
    const resp = await fetch(`${API}/api/prospeccao/modelo/exportar`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ colunas, empresas }) });
    const blob = await resp.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'capiblu-modelo.xlsx';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    modal.hidden = true;
  });
})();

// ══════════════════════════════════════════════════════
//  PAINEL ADMINISTRATIVO (histórico de navegação + custo geral)
// ══════════════════════════════════════════════════════
(function initAdmin() {
  const desdeEl = document.getElementById('adm-nav-desde');
  if (!desdeEl) return;
  const hoje = new Date();
  const trintaDiasAtras = new Date(hoje.getTime() - 29 * 24 * 60 * 60 * 1000);
  const fmtISO = d => d.toISOString().slice(0, 10);
  document.getElementById('adm-nav-desde').value = fmtISO(trintaDiasAtras);
  document.getElementById('adm-nav-ate').value = fmtISO(hoje);
  document.getElementById('adm-custo-desde').value = fmtISO(trintaDiasAtras);
  document.getElementById('adm-custo-ate').value = fmtISO(hoje);
  document.getElementById('adm-nav-atualizar').addEventListener('click', admNavCarregar);
  document.getElementById('adm-custo-atualizar').addEventListener('click', admCustoCarregar);
})();

function admCarregar() { admNavCarregar(); admCustoCarregar(); }

function admNavCarregar() {
  const box = document.getElementById('adm-nav-resultado'); if (!box) return;
  const desde = document.getElementById('adm-nav-desde').value;
  const ate = document.getElementById('adm-nav-ate').value;
  const user = document.getElementById('adm-nav-user').value;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  fetch(`${API}/api/navlog?desde=${desde}&ate=${ate}&user=${encodeURIComponent(user)}`).then(r => r.json()).then(j => {
    if (j.status !== 'ok') { box.innerHTML = `<p class="msg error">${esc(j.message || j.detail || 'Falha ao carregar.')}</p>`; return; }
    // Popula o filtro de usuário (uma vez, sem apagar a seleção atual).
    const sel = document.getElementById('adm-nav-user');
    if (sel.dataset.pop !== '1') {
      sel.insertAdjacentHTML('beforeend', (j.usuarios || []).map(u => `<option value="${esc(u)}">${esc(u)}</option>`).join(''));
      sel.dataset.pop = '1';
    }
    const fmtData = ts => new Date(ts * 1000).toLocaleString('pt-BR');
    const linhas = (j.entradas || []).slice(0, 500).map(e => `
      <tr><td class="mono">${fmtData(e.ts)}</td><td>${esc(e.user)}</td><td>${esc(e.tab)}</td></tr>`).join('');
    const porUsuario = Object.entries(j.por_usuario || {}).sort((a, b) => b[1] - a[1])
      .map(([u, n]) => `<span class="combo-chip"><b>${esc(u)}</b> · ${n}</span>`).join(' ');
    box.innerHTML = `
      <div class="prosp-build-row" style="margin-bottom:10px">
        <span><strong>Total de acessos:</strong> ${j.total}</span>
        ${j.truncado ? '<span style="color:var(--amber)">(mostrando as 500 mais recentes)</span>' : ''}
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px">${porUsuario || '<span class="msg">Nenhum acesso no período.</span>'}</div>
      ${j.entradas && j.entradas.length
        ? `<div class="prosp-table-scroll"><table class="prosp-table"><thead><tr><th>Quando</th><th>Usuário</th><th>Tela</th></tr></thead><tbody>${linhas}</tbody></table></div>`
        : ''}`;
  }).catch(e => { box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; });
}

function admCustoCarregar() {
  const box = document.getElementById('adm-custo-resultado'); if (!box) return;
  const desde = document.getElementById('adm-custo-desde').value;
  const ate = document.getElementById('adm-custo-ate').value;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  fetch(`${API}/api/custos/assertiva?desde=${desde}&ate=${ate}`).then(r => r.json()).then(j => {
    if (j.status !== 'ok') { box.innerHTML = `<p class="msg error">${esc(j.message || 'Falha ao carregar custos.')}</p>`; return; }
    const fmtR$ = v => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
    const linhas = (j.modelos || []).map(m => `
      <tr>
        <td>${m.tipo === 'externo' ? '🧑‍💼 Externo' : (m.tipo === 'interno' ? '🧩 Interno' : '— Sem modelo')}</td>
        <td>${esc(m.modelo_nome)}</td>
        <td>${m.n_consultas}</td>
        <td>${fmtR$(m.custo_total)}</td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="prosp-build-row" style="margin-bottom:10px">
        <span><strong>Total interno:</strong> ${fmtR$(j.custo_interno)}</span>
        <span><strong>Total externo (clientes):</strong> ${fmtR$(j.custo_externo)}</span>
        ${j.custo_sem_modelo ? `<span><strong>Sem modelo:</strong> ${fmtR$(j.custo_sem_modelo)}</span>` : ''}
        <span><strong>Total geral:</strong> ${fmtR$(j.total_geral)} (${j.total_consultas} consulta(s))</span>
      </div>
      ${j.modelos && j.modelos.length
        ? `<table class="prosp-table"><thead><tr><th>Tipo</th><th>Modelo</th><th>Consultas</th><th>Custo</th></tr></thead><tbody>${linhas}</tbody></table>`
        : '<p class="msg">Nenhuma consulta Assertiva no período selecionado.</p>'}`;
  }).catch(e => { box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; });
}

// ── Painel Início ────────────────────────────────────
const NOME_ABA = {
  empresa: 'Empresa', pessoa: 'Pessoa', nome: 'Pessoa (por nome)', telefone: 'Telefone',
  prospec: 'Clientes', assertiva: 'Consulta Assertiva', enrich: 'Planilha', modelos: 'Modelos', admin: 'Admin',
};

function logBusca(tipo, query, resultado) {
  fetch(`${API}/api/navlog`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tab: document.querySelector('.nav-btn.active')?.dataset.tab || '', tipo, query, resultado }),
  }).catch(() => {});
}

let _inicioDias = 7;
function inicioCarregar(dias) {
  if (dias) _inicioDias = dias;
  const chart = document.getElementById('inicio-chart');
  const ranking = document.getElementById('inicio-ranking');
  const tbody = document.querySelector('#inicio-tabela tbody');
  const link = document.getElementById('inicio-ultimos-link');
  if (!chart) return;
  if (link) link.textContent = `últimos ${_inicioDias} dias`;
  fetch(`${API}/api/navlog/mine?dias=${_inicioDias}`).then(r => r.json()).then(j => {
    if (j.status !== 'ok') return;

    document.getElementById('inicio-total').innerHTML = `${j.total_pesquisas}<span class="inicio-total-sub">no período</span>`;

    const diasChave = Object.keys(j.por_dia).slice(-7);
    const max = Math.max(1, ...diasChave.map(d => j.por_dia[d]));
    chart.innerHTML = diasChave.length
      ? diasChave.map(d => `<div class="inicio-bar-col"><div class="inicio-bar" style="height:${Math.max(4, Math.round(j.por_dia[d] / max * 100))}%"></div><div class="inicio-bar-lbl">${esc(d)}</div></div>`).join('')
      : '<p class="msg" style="padding:0">Sem uso registrado no período.</p>';

    const abas = Object.entries(j.por_aba).filter(([t]) => t !== 'inicio').sort((a, b) => b[1] - a[1]).slice(0, 4);
    const maxAba = Math.max(1, ...abas.map(a => a[1]));
    ranking.innerHTML = abas.length
      ? abas.map(([t, n], i) => `
        <div class="inicio-rank-row">
          <span class="inicio-rank-nome">${i + 1}. ${esc(NOME_ABA[t] || t)}</span>
          <span class="inicio-rank-n">${n}×</span>
          <div class="inicio-rank-bar-wrap"><div class="inicio-rank-bar" style="width:${Math.round(n / maxAba * 100)}%"></div></div>
        </div>`).join('')
      : '<p class="msg" style="padding:0">Sem uso registrado no período.</p>';

    tbody.innerHTML = j.ultimas_pesquisas.length
      ? j.ultimas_pesquisas.map(p => `
        <tr>
          <td>${esc(p.query || '—')}</td>
          <td>${esc(p.tipo || '—')}</td>
          <td>${esc(p.resultado || '—')}</td>
          <td>${new Date(p.ts * 1000).toLocaleString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</td>
        </tr>`).join('')
      : '<tr><td colspan="4" class="msg">Nenhuma pesquisa registrada ainda no período.</td></tr>';
  }).catch(() => {});
}

document.getElementById('inicio-periodo')?.addEventListener('click', e => {
  const btn = e.target.closest('.inicio-per-btn');
  if (!btn) return;
  document.querySelectorAll('.inicio-per-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  inicioCarregar(Number(btn.dataset.dias));
});

document.getElementById('inicio-precisa')?.addEventListener('click', e => {
  const item = e.target.closest('.inicio-precisa-item');
  if (!item) return;
  document.querySelector(`.nav-btn[data-tab="${item.dataset.goto}"]`)?.click();
});

// ── Dossiê PDF (Mk + Assertiva + confirmação de telefone, CPF ou CNPJ) ──
window.exportarDossie = async function(tipo, doc, btn) {
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Gerando…'; }
  try {
    const r = await fetch(`${API}/api/dossie/pdf?tipo=${tipo}&doc=${doc}`);
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      alert(j.message || 'Falha ao gerar o dossiê.');
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dossie-${tipo}-${doc}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    logBusca('Dossiê PDF', doc, `Dossiê ${tipo.toUpperCase()} gerado`);
  } catch (e) {
    alert('Erro ao gerar dossiê: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
};
