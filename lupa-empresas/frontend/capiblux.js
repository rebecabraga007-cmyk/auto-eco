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
// Motivo de um erro vindo da API. O proxy (limite diário, sessão, túnel fora)
// responde em `detail`, e as rotas de dados em `message` — olhar só um dos dois
// fazia a tela mostrar um "Erro" seco, sem dizer o que aconteceu.
function motivoErro(...respostas) {
  for (const r of respostas) {
    if (!r || typeof r !== 'object') continue;
    const txt = r.detail || r.message || r.error;
    if (!txt) continue;
    const t = String(txt);
    if (t.includes('Limite diário')) {
      return t + ' (buscar nome na base local não deveria contar — se persistir, avise.)';
    }
    if (t.includes('Não autenticado')) return 'Sua sessão expirou. Recarregue a página e entre novamente.';
    if (t.includes('Serviço de dados indisponível')) {
      return 'O serviço de dados está fora do ar (túnel ou PC desligado). Avise quem cuida da infraestrutura.';
    }
    return t;
  }
  return '';
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
    empRes.innerHTML = `<p class="msg error">${esc(motivoErro(data) || 'Erro desconhecido')}</p>`;
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
        <button class="btn-secondary btn-dossie" onclick="event.preventDefault(); event.stopPropagation(); exportarDossie('cnpj','${onlyDigits(cnpj)}', this)">📄 PDF</button>
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
      <button class="btn-secondary" onclick="buscarParentes('${onlyDigits(cpf)}', this)" title="Junta pessoas de referência e conexões da Assertiva — 2 consultas">👨‍👩‍👧 Busca Parentes (Assertiva)</button>
      <button class="btn-secondary btn-dossie" onclick="exportarDossie('cpf','${onlyDigits(cpf)}', this)">📄 Exportar PDF</button>
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
      nomeRes.innerHTML = `<p class="msg error">${esc(motivoErro(exactRes, outrosRes) || 'Não consegui buscar esse nome. Recarregue a página e tente de novo; se continuar, avise com o nome que você digitou.')}</p>`;
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
      <label class="rank-qtd" title="Quantos candidatos puxar no ranking">
        Puxar <input type="number" id="rank-qtd-${prefix}" value="20" min="1" max="5000" style="width:56px">
      </label>
      <label class="rank-qtd" title="No ranking agressivo, só chama a Assertiva (2ª consulta paga) pra quem já teve pelo menos esse % no Mk. 0 = chama pra todo mundo.">
        Agressivo a partir de <input type="number" id="rank-min-pct-${prefix}" value="1" min="0" max="100" style="width:52px">%
      </label>
      <button id="rank-btn-restantes-${prefix}" class="btn-secondary" style="display:none" onclick="calcularRankingRestantes('${prefix}')">Buscar Assertiva nos que ficaram de fora →</button>
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

// Guarda estado entre a rodada normal/agressiva e "buscar nos que ficaram de
// fora" — por prefixo ('exatos'/'outros'): resultado atual de cada CPF, quais
// ficaram pendentes (abaixo do % mínimo) e o conjunto de cards da última rodada.
window._rankResultado = window._rankResultado || {};   // { [prefix]: Map(cpf -> {score, motivos}) }
window._rankPendentes = window._rankPendentes || {};   // { [prefix]: [cpf, ...] }
window._rankAlvo = window._rankAlvo || {};             // { [prefix]: [card, ...] }

function _renderResultadosRanking(container, resultados) {
  const ordenados = [...resultados].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  ordenados.forEach(({ card, score, motivos }) => {
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
}

async function _consultarAssertivaCpf(cpf) {
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
    window._assertivaPorCpf[cpf] = as;
    return extrairAssertiva(as);
  } catch (e) {
    // Erro de rede/fetch em si (não da resposta) — também fica visível no card.
    window._assertivaPorCpf[cpf] = { status: 'error', message: `Falha ao consultar: ${e.message}` };
    return null;
  }
}

window.calcularRanking = async function(prefix, agressivo) {
  const btn = document.getElementById('rank-btn-' + prefix);
  const btnAgr = document.getElementById('rank-btn-agr-' + prefix);
  const btnRestantes = document.getElementById('rank-btn-restantes-' + prefix);
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
  const qtdInput = document.getElementById('rank-qtd-' + prefix);
  const maxCandidatos = Math.max(1, Math.min(5000, parseInt(qtdInput && qtdInput.value, 10) || RANKING_MAX_CANDIDATOS));
  const minPctInput = document.getElementById('rank-min-pct-' + prefix);
  const minPct = agressivo ? Math.max(0, Math.min(100, parseInt(minPctInput && minPctInput.value, 10) || 0)) : 0;
  const cards = [...container.querySelectorAll('.card-person')];
  const alvo = cards.slice(0, maxCandidatos);
  const fonte = agressivo
    ? (minPct > 0 ? `Mk Buscas + Assertiva só a partir de ${minPct}% no Mk` : 'Mk Buscas + Assertiva (2 consultas pagas por CPF)')
    : 'Mk Buscas (1 consulta paga por CPF)';

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
  if (btnRestantes) btnRestantes.style.display = 'none';
  window._rankPendentes[prefix] = [];
  window._rankResultado[prefix] = new Map();
  window._rankAlvo[prefix] = alvo;
  if (cards.length > maxCandidatos) {
    note.innerHTML = `Calculando pros ${maxCandidatos} primeiros de ${cards.length} — ${fonte}.`;
  }
  btn.disabled = true; if (btnAgr) btnAgr.disabled = true;
  let feitos = 0;
  let pulados = 0;
  const resultados = [];
  for (const card of alvo) {
    const cpf = card.dataset.cpf;
    feitos++;
    note.textContent = `Calculando ${feitos} de ${alvo.length} (${fonte})…`;
    try {
      const mk = await fetch(`${API}/api/person/${cpf}/mk`).then(r => r.json());
      let extra = null;
      // Score só com Mk primeiro — se o "% mínimo" do agressivo for > 0 e a
      // pessoa ficar abaixo dele, pula a consulta Assertiva e marca como
      // pendente (pode ser buscada depois, sob demanda, no botão "restantes").
      const scoreMkSomente = calcularScorePessoa(mk, pistas, null).score;
      const pulaAssertiva = agressivo && minPct > 0 && !(scoreMkSomente >= minPct);
      if (pulaAssertiva) { pulados++; window._rankPendentes[prefix].push(cpf); }
      if (agressivo && !pulaAssertiva) {
        extra = await _consultarAssertivaCpf(cpf);
      }
      const { score, motivos } = calcularScorePessoa(mk, pistas, extra);
      resultados.push({ card, score, motivos });
      window._rankResultado[prefix].set(cpf, { score, motivos });
    } catch (e) {
      resultados.push({ card, score: null, motivos: ['❌ Erro ao consultar dados desta pessoa'] });
    }
  }
  _renderResultadosRanking(container, resultados);
  if (pulados > 0 && btnRestantes) {
    btnRestantes.style.display = '';
    btnRestantes.textContent = `Buscar Assertiva nos ${pulados} que ficaram de fora (abaixo de ${minPct}%) →`;
  }
  const notaPulados = pulados ? ` ${pulados} ficaram só com o score do Mk (abaixo de ${minPct}%) — use o botão acima pra completar com Assertiva se quiser.` : '';
  note.textContent = `Ranking (${fonte}) calculado para ${alvo.length} candidato(s).${notaPulados} Ordenado por % de chance.`;
  btn.disabled = false; if (btnAgr) btnAgr.disabled = false;
};

window.calcularRankingRestantes = async function(prefix) {
  const note = document.getElementById('rank-note-' + prefix);
  const btnRestantes = document.getElementById('rank-btn-restantes-' + prefix);
  const container = document.getElementById('rpanel-' + prefix);
  const pendentes = window._rankPendentes[prefix] || [];
  const alvo = window._rankAlvo[prefix] || [];
  const resultadoMap = window._rankResultado[prefix] || new Map();
  if (!pendentes.length) {
    note.textContent = 'Nenhum candidato pendente pra buscar.';
    return;
  }
  const pistas = {
    uf: document.getElementById('nome-uf-suposta').value,
    cidade: document.getElementById('nome-cidade-suposta').value.trim(),
    descricao: document.getElementById('nome-descricao').value.trim(),
  };
  btnRestantes.disabled = true;
  let feitos = 0;
  for (const cpf of pendentes) {
    feitos++;
    note.textContent = `Buscando Assertiva ${feitos} de ${pendentes.length} pendente(s)…`;
    try {
      const mk = await fetch(`${API}/api/person/${cpf}/mk`).then(r => r.json());
      const extra = await _consultarAssertivaCpf(cpf);
      const { score, motivos } = calcularScorePessoa(mk, pistas, extra);
      resultadoMap.set(cpf, { score, motivos });
    } catch (e) {
      resultadoMap.set(cpf, { score: null, motivos: ['❌ Erro ao consultar dados desta pessoa'] });
    }
  }
  const resultadosFinal = alvo.map(card => ({ card, ...(resultadoMap.get(card.dataset.cpf) || { score: null, motivos: [] }) }));
  _renderResultadosRanking(container, resultadosFinal);
  window._rankPendentes[prefix] = [];
  btnRestantes.style.display = 'none';
  btnRestantes.disabled = false;
  note.textContent = `Assertiva buscada nos ${pendentes.length} que estavam pendentes. Ordenado por % de chance.`;
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
      out.innerHTML = `<p class="msg error">${esc(motivoErro(res) || 'Falha na busca.')}</p>`;
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
        <button id="pf-dedup" class="btn-secondary" title="Remove das ${emp.length} empresas as que já estão na Meetime (CNPJ + nome)">Remover quem já está na Meetime</button>
        <button id="pf-montar" class="btn-primary">Montar lista de contatos</button>
      </div>

      <div class="pf-decisores-box">
        <label class="toggle-wrap"><input id="pf-decisores" type="checkbox" /><span><strong>Incluir decisores</strong> — quem manda na empresa sem estar no quadro de sócios</span></label>
        <div class="prosp-build-row" id="pf-dec-opcoes" hidden>
          <label>Fonte
            <select id="pf-decfonte" class="filter-select" title="A Assertiva traz o cargo real e é rápida; o LinkedIn é lento e costuma vir vazio">
              <option value="assertiva" selected>Assertiva (cargo real)</option>
              <option value="linkedin">LinkedIn (lento)</option>
            </select>
          </label>
          <label>máx decisores/empresa
            <input id="pf-maxdec" type="number" min="1" max="20" value="3" class="filter-num" title="Cada decisor trazido ainda gasta uma consulta de telefone" />
          </label>
          <label class="toggle-wrap" style="flex-basis:100%">
            <input id="pf-pular-sem-dec" type="checkbox" />
            <span>Pular empresas que não possuem decisor na base <span class="pf-advanced-hint" style="display:inline">— a empresa sai da lista inteira, sócios inclusive</span></span>
          </label>
          <label class="toggle-wrap" style="flex-basis:100%">
            <input id="pf-fallback-dec" type="checkbox" checked />
            <span>Se não houver o cargo selecionado, trazer até
              <input id="pf-fallback-n" type="number" min="1" max="10" value="3" class="filter-num" style="width:64px" />
              de acordo com a hierarquia <span class="pf-advanced-hint" style="display:inline">— nível 1 primeiro</span></span>
          </label>
          <label class="toggle-wrap" style="flex-basis:100%">
            <input id="pf-continuar" type="checkbox" />
            <span><strong>Continuar buscando</strong> até fechar a quantidade pedida com decisor
              <span class="pf-advanced-hint" style="display:inline">— pega mais empresas na base no lugar das puladas; teto de</span>
              <input id="pf-max-tentativas" type="number" min="1" max="2000" value="150" class="filter-num" style="width:74px" />
              <span class="pf-advanced-hint" style="display:inline">tentativas</span>
            </span>
          </label>
          <label class="toggle-wrap" style="flex-basis:100%">
            <input id="pf-apenas-cargo" type="checkbox" />
            <span>Filtrar <strong>APENAS decisores nesse cargo</strong> <span class="pf-advanced-hint" style="display:inline">— lista só com quem tem o cargo marcado, sem sócios; empresa sem ninguém no cargo sai da lista</span></span>
          </label>
          <div class="filter-row" style="margin:0;flex-basis:100%">
            <button type="button" id="pf-testar-cobertura" class="btn-secondary" title="Descobre em quantas empresas existe decisor, sem puxar telefone">🔬 Testar cobertura em</button>
            <input id="pf-amostra" type="number" min="3" max="60" value="10" class="filter-num" style="width:70px" />
            <span class="pf-advanced-hint" style="display:inline">empresas da lista — 2 consultas cada, sem telefone</span>
          </div>
          <div id="pf-cobertura" class="prosp-dedup-note" hidden></div>
          <div class="filter-row" id="pf-cargos" style="margin:0">
            <span class="filter-label">Cargos:</span>
            <button type="button" class="pf-cargo active" data-c="">Todos</button>
            <button type="button" class="pf-cargo" data-c="administrador">Administrador</button>
            <button type="button" class="pf-cargo" data-c="representante">Representante legal</button>
            <button type="button" class="pf-cargo" data-c="diretor">Diretor</button>
            <button type="button" class="pf-cargo" data-c="gerente">Gerente</button>
            <button type="button" class="pf-cargo" data-c="coordenador">Coordenador</button>
          </div>
        </div>
        <p class="pf-advanced-hint" id="pf-dec-custo" hidden></p>
      </div>
      <div id="pf-dedup-note" class="prosp-dedup-note"></div>
      <p class="prosp-warn">Buscar os telefones leva alguns minutos e consome consulta (${prospState.fonte === 'local' ? 'base local da Receita' : 'Casa dos Dados'}). A lista pronta pode ser exportada em planilha, no seu modelo de colunas. A validação por telefone reverso é um passo separado, sobre a lista pronta.</p>
    </div>
    <div class="prosp-selbar">
      <span class="filter-label" id="pf-selcount">nenhuma empresa marcada</span>
      <button type="button" class="btn-secondary" id="pf-sel-todas">☑️ Selecionar todas (${emp.length})</button>
      <label class="prosp-selbar-n">selecionar as primeiras
        <input type="number" id="pf-sel-n" min="1" max="${emp.length}" value="${Math.min(25, max)}" class="filter-num" />
        <button type="button" class="btn-secondary" id="pf-sel-aplicar">Selecionar</button>
      </label>
      <button type="button" class="btn-secondary" id="pf-sel-limpar">Limpar seleção</button>
    </div>
    <div class="prosp-table-scroll">
      <table class="prosp-table prosp-empresas-table prosp-ds-table">
        <thead><tr>
          <th><input type="checkbox" id="pf-sel-cabecalho" title="Marcar/desmarcar as desta página" /></th>
          <th>Empresa e sócio</th><th>Cidade</th><th>O que a empresa faz</th><th>Situação</th>
        </tr></thead>
        <tbody id="prosp-emp-body"></tbody>
      </table>
    </div>
    <div id="prosp-pager" class="prosp-pager"></div>
    <div id="prosp-table-wrap"></div>
  `;
  prospState.page = 0;
  prospState.selecionadas = new Set();
  renderEmpPage();
  document.getElementById('pf-montar').addEventListener('click', prospMontar);
  document.getElementById('pf-dedup').addEventListener('click', prospDedupMeetime);
  popularSelectModelo(document.getElementById('pf-modelo'));
  initDecisoresBox();
  initSelecaoEmpresas();
}

// Seleção de empresas: os checkboxes existiam mas ninguém lia — a montagem
// sempre pegava as N primeiras. Agora a seleção manda, e continua valendo o
// campo "Quantas empresas" quando nada estiver marcado.
function initSelecaoEmpresas() {
  const todas = document.getElementById('pf-sel-todas');
  if (!todas) return;

  todas.addEventListener('click', () => {
    prospState.empresas.forEach((_, i) => prospState.selecionadas.add(i));
    renderEmpPage();
  });
  document.getElementById('pf-sel-limpar').addEventListener('click', () => {
    prospState.selecionadas.clear();
    renderEmpPage();
  });
  document.getElementById('pf-sel-aplicar').addEventListener('click', () => {
    const n = parseInt(document.getElementById('pf-sel-n').value) || 0;
    prospState.selecionadas.clear();
    prospState.empresas.slice(0, n).forEach((_, i) => prospState.selecionadas.add(i));
    renderEmpPage();
  });
  document.getElementById('pf-sel-cabecalho').addEventListener('change', e => {
    const perPage = prospState.perPage || PROSP_PER_PAGE;
    const inicio = (prospState.page || 0) * perPage;
    prospState.empresas.slice(inicio, inicio + perPage).forEach((_, k) => {
      if (e.target.checked) prospState.selecionadas.add(inicio + k);
      else prospState.selecionadas.delete(inicio + k);
    });
    renderEmpPage();
  });
}

function atualizarContadorSelecao() {
  const el = document.getElementById('pf-selcount');
  if (!el) return;
  const n = prospState.selecionadas ? prospState.selecionadas.size : 0;
  el.textContent = n
    ? `${n} empresa${n === 1 ? '' : 's'} marcada${n === 1 ? '' : 's'} — a montagem usa só essas`
    : 'nenhuma empresa marcada — a montagem usa as primeiras do campo "Quantas empresas"';
  const cab = document.getElementById('pf-sel-cabecalho');
  if (cab) {
    const perPage = prospState.perPage || PROSP_PER_PAGE;
    const inicio = (prospState.page || 0) * perPage;
    const daPagina = prospState.empresas.slice(inicio, inicio + perPage).map((_, k) => inicio + k);
    cab.checked = daPagina.length > 0 && daPagina.every(i => prospState.selecionadas.has(i));
  }
  // Reflete no aviso de custo dos decisores.
  const chk = document.getElementById('pf-decisores');
  if (chk && chk.checked) chk.dispatchEvent(new Event('change'));
}

// Bloco "Incluir decisores": mostra as opções só quando ligado, e avisa o custo
// antes de a usuária clicar em montar (cada decisor gasta consulta de telefone).
function initDecisoresBox() {
  const chk = document.getElementById('pf-decisores');
  const opcoes = document.getElementById('pf-dec-opcoes');
  const aviso = document.getElementById('pf-dec-custo');
  if (!chk) return;

  const atualizar = () => {
    const ligado = chk.checked;
    opcoes.hidden = !ligado;
    aviso.hidden = !ligado;
    if (!ligado) return;
    const fonte = document.getElementById('pf-decfonte').value;
    const n = parseInt(document.getElementById('pf-maxdec').value) || 0;
    const marcadas = prospState.selecionadas ? prospState.selecionadas.size : 0;
    const empresas = marcadas || parseInt(document.getElementById('pf-qtd').value) || 0;
    const pular = document.getElementById('pf-pular-sem-dec')?.checked;
    const cont = document.getElementById('pf-continuar')?.checked;
    const teto = parseInt(document.getElementById('pf-max-tentativas')?.value) || 0;
    if (cont) {
      aviso.textContent = `Com "continuar buscando", o gasto depende de quantas empresas precisam ser testadas: `
        + `cada tentativa custa 2 consultas de cadastro, mais até ${n} de telefone quando a empresa é aproveitada. `
        + `No pior caso do teto (${teto} tentativas): ~${teto * 2 + empresas * n} consultas.`;
      return;
    }
    aviso.textContent = fonte === 'assertiva'
      ? `≈ ${empresas * (2 + n)} consultas Assertiva: ${empresas} × (2 pela empresa + até ${n} telefone${n === 1 ? '' : 's'} de decisor).`
        + (pular ? ' Com "pular sem decisor", quem não tem decisor gasta só as 2 da empresa.' : '')
      : 'O LinkedIn não gasta consulta Assertiva, mas é lento e costuma voltar vazio — a Assertiva rende muito mais.';
  };

  chk.addEventListener('change', atualizar);
  const estrito = document.getElementById('pf-apenas-cargo');
  const fb = document.getElementById('pf-fallback-dec');
  const sincronizaEstrito = () => {
    // As duas opções se contradizem: "apenas nesse cargo" nunca aceita substituto.
    if (fb) { fb.disabled = estrito.checked; fb.closest('label').style.opacity = estrito.checked ? .45 : 1; }
    atualizar();
  };
  estrito?.addEventListener('change', sincronizaEstrito);
  document.getElementById('pf-testar-cobertura')?.addEventListener('click', testarCobertura);
  ['pf-decfonte', 'pf-maxdec', 'pf-qtd', 'pf-continuar', 'pf-max-tentativas', 'pf-pular-sem-dec'].forEach(id => {
    document.getElementById(id)?.addEventListener('input', atualizar);
    document.getElementById(id)?.addEventListener('change', atualizar);
  });

  // Chips de cargo: "Todos" é exclusivo; os demais somam.
  document.querySelectorAll('#pf-cargos .pf-cargo').forEach(b => b.addEventListener('click', () => {
    const todos = document.querySelector('#pf-cargos .pf-cargo[data-c=""]');
    if (!b.dataset.c) {
      document.querySelectorAll('#pf-cargos .pf-cargo').forEach(x => x.classList.remove('active'));
      todos.classList.add('active');
    } else {
      b.classList.toggle('active');
      todos.classList.toggle('active',
        !document.querySelector('#pf-cargos .pf-cargo.active[data-c]:not([data-c=""])'));
    }
  }));
  atualizar();
}

// Teste de cobertura: mede em quantas empresas a Assertiva TEM decisor antes de
// montar a lista. Custa 2 consultas por empresa e nao puxa telefone — é o passo
// barato pra decidir se vale gastar o caro.
async function testarCobertura() {
  const btn = document.getElementById('pf-testar-cobertura');
  const box = document.getElementById('pf-cobertura');
  const n = parseInt(document.getElementById('pf-amostra').value) || 10;
  const cargos = cargosSelecionados();

  // Amostra: as marcadas, se houver; senão as primeiras da lista carregada.
  const base = (prospState.selecionadas && prospState.selecionadas.size)
    ? [...prospState.selecionadas].sort((a, b) => a - b).map(i => prospState.empresas[i])
    : prospState.empresas;
  const amostra = (base || []).filter(Boolean).slice(0, n);
  if (!amostra.length) { alert('Busque empresas antes de testar a cobertura.'); return; }

  btn.disabled = true;
  box.hidden = false;
  box.innerHTML = `<span class="spinner"></span> Testando ${amostra.length} empresa(s)…`;
  try {
    const r = await fetch(`${API}/api/prospeccao/cobertura-decisores`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cnpjs: amostra.map(e => onlyDigits(e.cnpj)), cargos }),
    }).then(x => x.json());
    if (r.status !== 'ok') {
      box.innerHTML = `⚠️ ${esc(r.message || 'Falha no teste.')}`;
      return;
    }
    const alvo = parseInt(document.getElementById('pf-qtd').value) || 25;
    const taxa = cargos ? r.taxa_cargo : r.taxa;
    const precisaria = taxa > 0 ? Math.ceil(alvo / (taxa / 100)) : null;
    const dist = Object.entries(r.cargos_encontrados || {})
      .map(([c, q]) => `${esc(c)} (${q})`).join(' · ');
    box.innerHTML = `
      🔬 <strong>${r.com_decisor} de ${r.testadas}</strong> empresa(s) têm decisor na base — <strong>${r.taxa}%</strong> de cobertura.
      ${cargos ? `Com o filtro de cargo atual: <strong>${r.com_o_cargo} (${r.taxa_cargo}%)</strong>.` : ''}
      ${r.media_decisores ? `Média de ${r.media_decisores} decisor(es) por empresa que tem.` : ''}
      ${dist ? `<br>Cargos encontrados: ${dist}.` : ''}
      ${precisaria ? `<br>📐 Para fechar <strong>${alvo}</strong> empresa(s) com decisor, a projeção é testar ~<strong>${precisaria}</strong> — ajuste o teto de tentativas por aí.` : `<br>⚠️ Nenhuma empresa da amostra tem decisor: montar com "pular sem decisor" ligado devolveria lista vazia.`}
      <br><span class="pf-advanced-hint" style="display:inline">Custo deste teste: ${r.consultas_gastas} consultas de cadastro. Telefone não foi consultado.</span>`;
  } catch (e) {
    box.innerHTML = `⚠️ Erro: ${esc(e.message)}`;
  } finally {
    btn.disabled = false;
  }
}

function cargosSelecionados() {
  return [...document.querySelectorAll('#pf-cargos .pf-cargo.active')]
    .map(b => b.dataset.c).filter(Boolean).join(',');
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
        <td><input type="checkbox" class="prosp-co-check" data-i="${i}"${prospState.selecionadas && prospState.selecionadas.has(i) ? ' checked' : ''} /></td>
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
  body.querySelectorAll('.prosp-co-check').forEach(c => c.addEventListener('change', () => {
    const i = parseInt(c.dataset.i);
    if (c.checked) prospState.selecionadas.add(i);
    else prospState.selecionadas.delete(i);
    atualizarContadorSelecao();
  }));
  atualizarContadorSelecao();
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
  const decFonte = document.getElementById('pf-decfonte')?.value || 'assertiva';
  const maxDec = parseInt(document.getElementById('pf-maxdec')?.value) || 3;
  const decCargos = cargosSelecionados();
  const pularSemDec = document.getElementById('pf-pular-sem-dec')?.checked ? 'true' : 'false';
  const apenasCargo = document.getElementById('pf-apenas-cargo')?.checked ? 'true' : 'false';
  const fallbackN = document.getElementById('pf-fallback-dec')?.checked
    ? (parseInt(document.getElementById('pf-fallback-n')?.value) || 3) : 0;
  const continuar = document.getElementById('pf-continuar')?.checked;
  const tetoTentativas = parseInt(document.getElementById('pf-max-tentativas')?.value) || 0;
  // Marcou alguma? A seleção manda. Nada marcado = as N primeiras, como antes.
  const marcadas = prospState.selecionadas && prospState.selecionadas.size
    ? [...prospState.selecionadas].sort((a, b) => a - b).map(i => prospState.empresas[i]).filter(Boolean)
    : null;
  const wrap = document.getElementById('prosp-table-wrap');
  prospState.building = true;
  prospState.rows = [];

  const btn = document.getElementById('pf-montar');
  btn.disabled = true;

  // Só o LinkedIn precisa de concorrência baixa (scraping); a Assertiva aguenta.
  const CONC = (decisores && decFonte === 'linkedin') ? 2 : 6;

  // Alvo = quantas empresas APROVEITADAS a usuária quer. Sem "continuar",
  // tenta exatamente essas e aceita a lista furada (comportamento antigo).
  // Com "continuar", segue pegando candidatas — e pede páginas novas à base
  // quando as carregadas acabam — até fechar o alvo ou bater o teto.
  const alvoQtd = marcadas ? marcadas.length : qtd;
  const fila = marcadas ? marcadas.slice() : prospState.empresas.slice();
  const limite = continuar ? (tetoTentativas || alvoQtd * 6) : alvoQtd;

  const rowsAcc = [], leadsAcc = [], infoAcc = [];
  let ponteiro = 0, aceitas = 0, tentadas = 0, offsetBase = prospState.empresas.length;
  const tick = () => {
    const extra = continuar
      ? ` · ${aceitas} de ${alvoQtd} com decisor (teto de ${limite} tentativas)`
      : '';
    wrap.innerHTML = `<div class="prosp-progress"><span class="spinner"></span> Montando: ${tentadas} empresa(s) consultada(s)${extra}…</div>`;
  };
  tick();

  async function processa(emp) {
    try {
      const r = await fetch(`${API}/api/company/${onlyDigits(emp.cnpj)}/leads?decisores=${decisores}&modo_tel=${modoTel}&max_tel=${maxTel}&fonte_tel=${fonteTel}&socios_modo=${sociosModo}&max_socios=${maxSocios}&modelo_id=${encodeURIComponent(modeloId)}&decisores_fonte=${decFonte}&decisores_cargos=${encodeURIComponent(decCargos)}&max_decisores=${maxDec}&pular_sem_decisor=${pularSemDec}&fallback_hierarquia=${fallbackN}&apenas_cargo=${apenasCargo}`).then(x => x.json());
      if (r.status !== 'ok') return { aceita: false };
      if (r.decisores_info) infoAcc.push(r.decisores_info);
      if (r.decisores_info && r.decisores_info.pular) return { aceita: false };
      const linhas = leadsToRows(r.empresa, r.contatos);
      rowsAcc.push(...linhas);
      leadsAcc.push({ empresa: r.empresa, contatos: r.contatos });
      return { aceita: true };
    } catch (e) {
      return { aceita: false };
    }
  }

  // Pede mais empresas à base, continuando de onde a lista parou.
  async function carregarMais() {
    try {
      const res = await fetch(`${API}/api/companies/search`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filtros: prospFiltros(), limite: 200, offset: offsetBase }),
      }).then(r => r.json());
      const novas = (res.empresas || []).filter(e =>
        !prospState.empresas.some(x => onlyDigits(x.cnpj) === onlyDigits(e.cnpj)));
      offsetBase += (res.empresas || []).length;
      prospState.empresas.push(...novas);
      return novas;
    } catch (e) {
      return [];
    }
  }

  while (aceitas < alvoQtd && tentadas < limite) {
    // Lote do tamanho do que falta (com folga quando pode continuar).
    const faltam = alvoQtd - aceitas;
    const cabe = limite - tentadas;
    const tamanho = Math.max(1, Math.min(cabe, continuar ? faltam + CONC : faltam));
    const lote = fila.slice(ponteiro, ponteiro + tamanho);
    ponteiro += lote.length;

    if (!lote.length) {
      if (!continuar) break;
      const novas = await carregarMais();
      if (!novas.length) break;              // a base acabou
      fila.push(...novas);
      continue;
    }

    let idx = 0;
    await Promise.all(Array.from({ length: Math.min(CONC, lote.length) }, async () => {
      while (idx < lote.length && (aceitas < alvoQtd || !continuar) && tentadas < limite) {
        const emp = lote[idx++];
        tentadas++;
        const r = await processa(emp);
        if (r.aceita) aceitas++;
        tick();
      }
    }));
  }

  prospState.rows = rowsAcc;
  prospState.leads = leadsAcc;
  prospState.decisoresInfo = resumirDecisores(infoAcc);
  if (prospState.decisoresInfo) {
    prospState.decisoresInfo.aceitas = aceitas;
    prospState.decisoresInfo.alvo = alvoQtd;
    prospState.decisoresInfo.tentadas = tentadas;
    prospState.decisoresInfo.continuou = !!continuar;
    prospState.decisoresInfo.bateuTeto = continuar && aceitas < alvoQtd && tentadas >= limite;
    prospState.decisoresInfo.baseAcabou = continuar && aceitas < alvoQtd && tentadas < limite;
  }
  prospState.building = false;
  btn.disabled = false;
  renderProspTable();
}

// Explica por que vieram (ou não vieram) decisores. Sem isso, "Decisores 0" na
// tela pode ser tanto "não pedi" quanto "a Assertiva não tem" quanto "deu erro".
function resumirDecisores(infos) {
  if (!infos.length || !infos.some(i => i.pedido)) return null;
  const conta = m => infos.filter(i => i.motivo === m).length;
  const achados = infos.reduce((s, i) => s + (i.escolhidos || 0), 0);
  const semNinguem = conta('not_found');
  const filtrados = conta('filtrado');
  const erros = conta('erro') + conta('unavailable') + conta('sem_credencial');
  const puladas = infos.filter(i => i.pular).length;
  const semOCargo = infos.filter(i => i.motivo === 'sem_o_cargo').length;
  const estritoLigado = infos.some(i => i.apenas_cargo);
  const fallback = infos.filter(i => i.usou_fallback).length;
  const exemploErro = (infos.find(i => i.mensagem && i.motivo !== 'not_found') || {}).mensagem || '';
  return { empresas: infos.length, achados, semNinguem, filtrados, erros, exemploErro,
           puladas, fallback, semOCargo, estritoLigado, fonte: infos[0].fonte };
}

function notaDecisores() {
  const d = prospState.decisoresInfo;
  if (!d) return '';
  if (d.achados) {
    const extras = [
      d.semOCargo ? `<strong>${d.semOCargo} empresa${d.semOCargo === 1 ? '' : 's'}</strong> sem ninguém no cargo pedido (modo "apenas nesse cargo")` : '',
      d.puladas ? `<strong>${d.puladas} empresa${d.puladas === 1 ? '' : 's'} pulada${d.puladas === 1 ? '' : 's'}</strong> por não ter decisor na base` : '',
      d.fallback ? `${d.fallback} com decisor trazido pela hierarquia (o cargo escolhido não existia lá)` : '',
      d.semNinguem && !d.puladas ? `${d.semNinguem} empresa${d.semNinguem === 1 ? '' : 's'} sem decisor na base` : '',
      d.filtrados ? `${d.filtrados} com decisor fora dos cargos escolhidos` : '',
      d.erros ? `${d.erros} com falha na consulta` : '',
    ].filter(Boolean).join(' · ');
    const cont = d.continuou
      ? `<br>🔁 Busca continuada: <strong>${d.aceitas} de ${d.alvo}</strong> empresa(s) com decisor, testando ${d.tentadas}.`
        + (d.bateuTeto ? ` Parou no teto de tentativas — aumente o teto pra continuar.` : '')
        + (d.baseAcabou ? ` A base acabou: não há mais empresas com esses filtros.` : '')
      : '';
    return `<div class="prosp-dedup-note">🎯 ${d.achados} decisor(es) trazido(s) em ${d.empresas} empresa(s)${extras ? ' — ' + extras : ''}.${cont}</div>`;
  }
  if (d.filtrados && !d.semNinguem) {
    return `<div class="prosp-dedup-note">🎯 Nenhum decisor na lista: a Assertiva tinha gente nessas empresas, mas <strong>nenhuma bateu com os cargos escolhidos</strong>. Marque "Todos" nos cargos e monte de novo.</div>`;
  }
  if (d.erros && !d.semNinguem) {
    return `<div class="prosp-dedup-note">⚠️ A consulta de decisores falhou em ${d.erros} de ${d.empresas} empresa(s)${d.exemploErro ? ': ' + esc(d.exemploErro) : ''}.</div>`;
  }
  if (d.continuou && !d.achados) {
    return `<div class="prosp-dedup-note">🔁 Busca continuada: testei <strong>${d.tentadas} empresa(s)</strong> e nenhuma tem decisor na base`
      + (d.bateuTeto ? `, parando no teto de tentativas. ` : `. `)
      + `Nesses filtros (micro empresas), a Assertiva praticamente não tem decisor — `
      + `desmarque "pular empresas sem decisor" pra trazer os sócios, que nessas empresas são quem decide.</div>`;
  }
  if (d.puladas === d.empresas && d.puladas) {
    return `<div class="prosp-dedup-note">🎯 <strong>Todas as ${d.puladas} empresas foram puladas</strong> — nenhuma tem decisor na base da Assertiva, e a opção "pular empresas sem decisor" está ligada. Desmarque essa opção para trazer os sócios dessas empresas (em micro empresa, o sócio-administrador É o decisor).</div>`;
  }
  return `<div class="prosp-dedup-note">🎯 Nenhum decisor encontrado nas ${d.empresas} empresa${d.empresas === 1 ? '' : 's'}. A Assertiva respondeu <em>"não localizamos nenhum possível decisor"</em> — normal em micro e pequena empresa, onde quem decide é o próprio sócio, que já está na lista. A base de decisores cobre principalmente empresa média e grande.</div>`;
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
  const todas = prospState.rows;
  if (!todas.length) {
    // Lista vazia sem explicação era o pior caso: a usuária não sabe se falhou,
    // se pulou tudo ou se a base não tem ninguém. A nota conta o que houve.
    wrap.innerHTML = `<p class="msg" style="padding:16px">Nenhum contato encontrado nas empresas consultadas.</p>`
      + notaDecisores();
    return;
  }
  // Filtro por tipo de contato. Exportação e validação continuam sobre a lista
  // inteira — o filtro é só pra olhar, não recorta o que vai pra planilha.
  const tipo = prospState.tipoContato || 'todos';
  const rows = tipo === 'todos' ? todas : todas.filter(r =>
    tipo === 'decisor' ? r.contato_tipo === 'Decisor' : r.contato_tipo === 'Sócio');
  const nSocios = todas.filter(r => r.contato_tipo === 'Sócio').length;
  const nDecisores = todas.filter(r => r.contato_tipo === 'Decisor').length;
  const comTel = rows.filter(r => r.telefone_raw).length;
  wrap.innerHTML = `
    <div class="prosp-toolbar">
      <span class="prosp-count">${rows.length} contatos · ${comTel} com telefone</span>
      <div class="filter-row" id="pf-tipo" style="margin:0">
        <button type="button" class="pf-cargo${tipo === 'todos' ? ' active' : ''}" data-t="todos">Todos <span class="res-tab-count">${todas.length}</span></button>
        <button type="button" class="pf-cargo${tipo === 'socio' ? ' active' : ''}" data-t="socio">Sócios <span class="res-tab-count">${nSocios}</span></button>
        <button type="button" class="pf-cargo${tipo === 'decisor' ? ' active' : ''}" data-t="decisor">Decisores <span class="res-tab-count">${nDecisores}</span></button>
      </div>
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
    ${notaDecisores()}
    <div id="pf-valprog"></div>
    <div class="prosp-table-scroll">
      <table class="prosp-table" id="pf-table">
        <thead><tr>
          <th>Razão Social</th><th>CNPJ</th><th>UF</th><th>Tipo</th><th>Contato</th>
          <th>Cargo</th><th>CPF</th><th>Telefone</th><th>Validado</th><th>Nome / Vínculo</th>
        </tr></thead>
        <tbody>${rows.map(r => prospRowHtml(r, todas.indexOf(r))).join('')}</tbody>
      </table>
    </div>`;
  document.getElementById('pf-validar').addEventListener('click', prospValidar);
  document.getElementById('pf-export').addEventListener('click', prospExportar);
  document.getElementById('pf-modelo').addEventListener('click', abrirUseModelo);
  document.querySelectorAll('#pf-tipo .pf-cargo').forEach(b => b.addEventListener('click', () => {
    prospState.tipoContato = b.dataset.t;
    renderProspTable();
  }));
}

function valBadge(v) {
  if (v === 'sim') return `<span class="val-badge val-ok">✅ sim</span>`;
  if (v === 'não') return `<span class="val-badge val-no">⚠️ não</span>`;
  if (v === 'bloq') return `<span class="val-badge val-nd" title="Chave sem acesso ao módulo de telefone reverso (intelgrax-tel)">🔒 sem acesso</span>`;
  if (v === 'sem_cpf') return `<span class="val-badge val-nd" title="Sócio sem CPF resolvido — não dá pra validar o vínculo">❓ sem CPF</span>`;
  if (v === 'nao_testado') return `<span class="val-badge val-pend" title="Outro número da mesma pessoa já foi confirmado — este não precisou ser testado">↷ não testado</span>`;
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

  // Valida POR PESSOA, não por linha: os telefones já vêm do mais recente pro
  // mais antigo (atualidade da Assertiva), então tenta o primeiro e, se falhar,
  // desce a lista dela até um confirmar. Achou, para — os seguintes não gastam
  // consulta e ficam marcados como não testados.
  const porPessoa = new Map();
  prospState.rows.forEach((r, i) => {
    if (!r.telefone_raw) return;
    const chave = r.contato_cpf_raw || ('nome:' + r.contato_nome + '|' + r.cnpj);
    if (!porPessoa.has(chave)) porPessoa.set(chave, []);
    porPessoa.get(chave).push(i);
  });

  const pintar = i => {
    const r = prospState.rows[i];
    const vc = document.getElementById(`pf-val-${i}`); if (vc) vc.innerHTML = valBadge(r.validado);
    const dc = document.getElementById(`pf-dz-${i}`); if (dc) dc.textContent = r.nome_donodozap;
  };

  let done = 0, semAcesso = false, trocas = 0;
  const totalPessoas = porPessoa.size;
  for (const [, idxsPessoa] of porPessoa) {
    prog.innerHTML = `<div class="prosp-progress"><span class="spinner"></span> Validando pessoa ${++done} de ${totalPessoas} (telefone reverso)…</div>`;
    let confirmou = false;
    for (let ordem = 0; ordem < idxsPessoa.length; ordem++) {
      const i = idxsPessoa[ordem];
      const r = prospState.rows[i];
      if (confirmou) { r.validado = 'nao_testado'; r.nome_donodozap = ''; pintar(i); continue; }
      if (!r.contato_cpf_raw) { r.validado = 'sem_cpf'; r.nome_donodozap = ''; pintar(i); continue; }
      try {
        const v = await fetch(`${API}/api/phone/${r.telefone_raw}/pertence/${r.contato_cpf_raw}`).then(x => x.json());
        if (v.status === 'no_access') { r.validado = 'bloq'; r.nome_donodozap = ''; semAcesso = true; }
        else if (v.status !== 'ok') { r.validado = 'n/d'; r.nome_donodozap = ''; }
        else if (v.atrelado) {
          r.validado = 'sim'; r.nome_donodozap = v.nome || '';
          confirmou = true;
          if (ordem > 0) trocas++;   // precisou descer na lista até achar um bom
        } else {
          r.validado = 'não';
          r.nome_donodozap = v.alerta_compartilhado ? `número compartilhado (${v.total} vínculos)` : '';
        }
      } catch (e) { r.validado = 'n/d'; r.nome_donodozap = ''; }
      pintar(i);
    }
  }
  prospState.trocasValidacao = trocas;
  if (semAcesso) {
    prog.innerHTML = `<div class="prosp-progress" style="color:#b45309">🔒 A chave da WorkAPI não tem acesso ao módulo de telefone reverso (intelgrax-tel) — peça pra habilitar. Os telefones vieram da Mk Buscas (já associados ao CPF); a coluna "Validado" ficou como 🔒 sem acesso.</div>`;
  } else {
    const ok = prospState.rows.filter(r => r.validado === 'sim').length;
    const trocou = prospState.trocasValidacao || 0;
    prog.innerHTML = `<div class="prosp-progress prosp-done">✅ Validação concluída: ${ok} telefone(s) confirmado(s)`
      + (trocou ? ` — em ${trocou} caso(s) o primeiro número falhou e o confirmado foi o seguinte da lista da pessoa.` : '.')
      + `</div>`;
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
      out.innerHTML = `<p class="msg error">${esc(motivoErro(res) || 'Falha na busca.')}</p>`;
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

  // Busca Parentes / Conexões — opt-in, porque cada uma gasta consulta.
  const docConsultado = onlyDigits((cab.entrada || {}).cpf || (cab.entrada || {}).cnpj || '');
  if (docConsultado.length === 11) {
    html += `<div class="filter-row" style="margin-top:0">
      <button class="btn-secondary" onclick="buscarParentes('${docConsultado}', this)" title="Pessoas de referência + conexões — 2 consultas Assertiva">👨‍👩‍👧 Busca Parentes (Assertiva)</button>
    </div>`;
  } else if (docConsultado.length === 14) {
    html += `<div class="filter-row" style="margin-top:0">
      <button class="btn-secondary" onclick="buscarConexoesEmpresa('${docConsultado}', this)" title="Sócios, decisores e empresas ligadas, com telefone — 1 consulta Assertiva">🔗 Buscar conexões (Assertiva)</button>
    </div>`;
  }

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
    not_found: '🔍 Nenhum resultado encontrado.',
    error: '❌ Erro na consulta.',
  };
  if (j.status === 'not_found') {
    out.innerHTML = `<p class="msg">${esc(j.message || msgs.not_found)}</p>`;
    return;
  }
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
  document.getElementById('adm-cons-atualizar').addEventListener('click', admConsultasCarregar);
  document.getElementById('adm-cons-user').addEventListener('change', admConsultasCarregar);
  document.getElementById('adm-custou-desde').value = fmtISO(trintaDiasAtras);
  document.getElementById('adm-custou-ate').value = fmtISO(hoje);
  document.getElementById('adm-custou-atualizar').addEventListener('click', admCustoUsuarioCarregar);
  document.getElementById('adm-custou-user').addEventListener('change', admCustoUsuarioCarregar);
})();

function admCarregar() {
  admCustoTotal(30);
  admPrecosCarregar();
  admTokensCarregar();
  admConsultasCarregar(); admCustoUsuarioCarregar(); admNavCarregar(); admCustoCarregar();
}

function admCustoUsuarioCarregar() {
  const box = document.getElementById('adm-custou-resultado'); if (!box) return;
  const desde = document.getElementById('adm-custou-desde').value;
  const ate = document.getElementById('adm-custou-ate').value;
  const sel = document.getElementById('adm-custou-user');
  const user = sel.value;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  fetch(`${API}/api/custos/usuario?desde=${desde}&ate=${ate}&user=${encodeURIComponent(user)}`).then(r => r.json()).then(j => {
    if (j.status !== 'ok') { box.innerHTML = `<p class="msg error">${esc(j.message || j.detail || 'Falha ao carregar.')}</p>`; return; }
    const fmtR$ = v => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
    if (sel.dataset.pop !== '1') {
      sel.insertAdjacentHTML('beforeend', (j.usuarios || []).map(u => `<option value="${esc(u.user)}">${esc(u.user)}</option>`).join(''));
      sel.dataset.pop = '1';
      sel.value = user;
    }
    const linhas = (j.usuarios || []).map(u => `
      <tr><td class="mono">${esc(u.user)}</td><td>${u.n_consultas}</td><td>${fmtR$(u.custo_total)}</td></tr>`).join('');
    box.innerHTML = `
      <div class="prosp-build-row" style="margin-bottom:10px">
        <span><strong>Total no período:</strong> ${fmtR$(j.total_geral)} (${j.total_consultas} consulta(s))</span>
      </div>
      ${j.usuarios && j.usuarios.length
        ? `<table class="prosp-table"><thead><tr><th>Usuário</th><th>Consultas</th><th>Custo</th></tr></thead><tbody>${linhas}</tbody></table>`
        : '<p class="msg">Nenhuma consulta Assertiva no período selecionado.</p>'}`;
  }).catch(e => { box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; });
}

function admConsultasCarregar() {
  const box = document.getElementById('adm-cons-resultado'); if (!box) return;
  const sel = document.getElementById('adm-cons-user');
  const userFiltro = sel.value;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  fetch(`${API}/api/admin/consumo`).then(r => r.json()).then(async j => {
    if (!j.consumo) { box.innerHTML = `<p class="msg error">${esc(j.detail || 'Falha ao carregar.')}</p>`; return; }
    if (sel.dataset.pop !== '1') {
      sel.insertAdjacentHTML('beforeend', j.consumo.map(u => `<option value="${esc(u.email)}">${esc(u.nome || u.email)}</option>`).join(''));
      sel.dataset.pop = '1';
      sel.value = userFiltro;
    }
    const lista = userFiltro ? j.consumo.filter(u => u.email === userFiltro) : j.consumo;
    const linhasResumo = lista.map(u => {
      const pct = u.limite_diario ? Math.min(100, Math.round(100 * u.consumo_hoje / u.limite_diario)) : 0;
      const cor = pct >= 100 ? 'var(--red,#c0392b)' : (pct >= 80 ? 'var(--amber,#c98a1a)' : 'inherit');
      return `<tr>
        <td>${esc(u.nome || '')}</td><td class="mono">${esc(u.email)}</td>
        <td style="color:${cor}"><b>${u.consumo_hoje}</b> / ${u.limite_diario}${pct >= 100 ? ' ⛔' : ''}</td>
      </tr>`;
    }).join('');
    let historicoHtml = '';
    if (userFiltro) {
      const jh = await fetch(`${API}/api/navlog?user=${encodeURIComponent(userFiltro)}`).then(r => r.json()).catch(() => null);
      if (jh && jh.status === 'ok') {
        const buscas = (jh.entradas || []).filter(e => e.tipo).slice(0, 200);
        const fmtData = ts => new Date(ts * 1000).toLocaleString('pt-BR');
        historicoHtml = `
          <h4 style="margin:16px 0 8px;font-size:.92rem">O que ${esc(userFiltro)} pesquisou (últimas ${buscas.length})</h4>
          ${buscas.length
            ? `<div class="prosp-table-scroll"><table class="prosp-table"><thead><tr><th>Quando</th><th>Tipo</th><th>Pesquisou</th></tr></thead><tbody>${
                buscas.map(e => `<tr><td class="mono">${fmtData(e.ts)}</td><td>${esc(e.tipo)}</td><td>${esc(e.query || '')}</td></tr>`).join('')
              }</tbody></table></div>`
            : '<p class="msg">Nenhuma pesquisa registrada.</p>'}`;
      }
    }
    box.innerHTML = `
      ${lista.length
        ? `<table class="prosp-table"><thead><tr><th>Nome</th><th>E-mail</th><th>Consultas hoje</th></tr></thead><tbody>${linhasResumo}</tbody></table>`
        : '<p class="msg">Nenhum usuário não-admin cadastrado.</p>'}
      ${historicoHtml}`;
  }).catch(e => { box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`; });
}

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
        <tr class="inicio-pesquisa-row" title="Clique pra refazer essa busca" data-tipo="${esc(p.tipo || '')}" data-query="${esc(p.query || '')}">
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
window.exportarDossie = async function(tipo, doc, btn, insight, familia) {
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = (insight || familia) ? '⏳ Gerando (pode levar +tempo)…' : '⏳ Gerando…'; }
  try {
    const r = await fetch(`${API}/api/dossie/pdf?tipo=${tipo}&doc=${doc}${insight ? '&insight=true&web=true' : ''}${familia ? '&familia=true' : ''}`);
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      alert(j.message || 'Falha ao gerar o dossiê.');
      return false;
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
    return true;
  } catch (e) {
    alert('Erro ao gerar dossiê: ' + e.message);
    return false;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
};

// ── Refazer busca a partir do histórico (Início) — usa o cache do backend,
// então clicar de novo não gera nova consulta paga (Mk/Assertiva já cacheiam
// por CPF/CNPJ no servidor; JBR e telefone reverso não têm custo por consulta
// repetida na mesma sessão do processo).
document.getElementById('inicio-tabela')?.addEventListener('click', e => {
  const row = e.target.closest('.inicio-pesquisa-row');
  if (!row) return;
  const tipo = row.dataset.tipo || '';
  const query = row.dataset.query || '';
  if (!query) return;

  const irPara = tab => document.querySelector(`.nav-btn[data-tab="${tab}"]`)?.click();

  if (tipo === 'Empresa') {
    irPara('empresa');
    setTimeout(() => { document.getElementById('emp-q').value = query; searchEmpresa(); }, 0);
  } else if (tipo === 'CPF') {
    irPara('pessoa');
    setTimeout(() => { document.getElementById('cpf-q').value = query; searchCpf(); }, 0);
  } else if (tipo === 'Nome') {
    irPara('nome');
    setTimeout(() => { document.getElementById('nome-q').value = query; searchNome(); }, 0);
  } else if (tipo === 'Telefone') {
    irPara('telefone');
    setTimeout(() => { document.getElementById('tel-q').value = query; buscarTelefone(); }, 0);
  } else if (tipo.startsWith('Assertiva')) {
    const modo = (tipo.match(/\(([^)]+)\)/) || [])[1] || 'cpf';
    irPara('assertiva');
    setTimeout(() => {
      document.querySelector(`.as-modo[data-modo="${modo}"]`)?.click();
      const campo = document.getElementById('as-' + modo);
      if (campo) campo.value = query;
      document.getElementById('as-btn')?.click();
    }, 0);
  } else {
    toast_inicio(`"${tipo}" não pode ser refeito automaticamente por aqui — abra a aba correspondente.`);
  }
});

function toast_inicio(msg) {
  const link = document.getElementById('inicio-ultimos-link');
  if (link) { const old = link.textContent; link.textContent = msg; setTimeout(() => { link.textContent = old; }, 3000); }
}

// ── Aba Dossiê (CPF ou CNPJ) ──────────────────────────
(function initDossieTab() {
  const btns = [...document.querySelectorAll('.doss-modo')];
  const input = document.getElementById('doss-q');
  const btn = document.getElementById('doss-btn');
  const status = document.getElementById('doss-status');
  const insightRow = document.getElementById('doss-insight-row');
  const insightChk = document.getElementById('doss-insight');
  const familiaRow = document.getElementById('doss-familia-row');
  const familiaChk = document.getElementById('doss-familia');
  if (!input || !btn) return;
  let modo = 'cpf';
  if (insightRow) insightRow.hidden = false;
  if (familiaRow) familiaRow.hidden = false;

  btns.forEach(b => b.addEventListener('click', () => {
    modo = b.dataset.modo;
    btns.forEach(x => x.classList.toggle('active', x === b));
    input.placeholder = modo === 'cpf' ? '000.000.000-00' : '00.000.000/0000-00';
    input.value = '';
    if (insightRow) insightRow.hidden = modo !== 'cpf';
    if (familiaRow) familiaRow.hidden = modo !== 'cpf';
  }));

  input.addEventListener('input', () => {
    input.value = modo === 'cpf' ? fmtCpf(input.value) : fmtCnpj(input.value);
  });

  btn.addEventListener('click', async () => {
    const doc = onlyDigits(input.value);
    if (modo === 'cpf' && doc.length !== 11) { status.textContent = 'CPF inválido — precisa ter 11 dígitos.'; return; }
    if (modo === 'cnpj' && doc.length !== 14) { status.textContent = 'CNPJ inválido — precisa ter 14 dígitos.'; return; }
    status.textContent = '';
    const comInsight = modo === 'cpf' && insightChk && insightChk.checked;
    const comFamilia = modo === 'cpf' && familiaChk && familiaChk.checked;
    const ok = await exportarDossie(modo, doc, btn, comInsight, comFamilia);
    status.textContent = ok ? '✅ Dossiê gerado e baixado.' : '';
  });
})();

// ══════════════════════════════════════════════════════
//  MÓDULO VÍNCULOS EMPREGATÍCIOS (RAIS)
//  Quem trabalha (ou trabalhou) num CNPJ — nome, CPF, admissão.
// ══════════════════════════════════════════════════════
const vinQ   = document.getElementById('vin-q');
const vinBtn = document.getElementById('vin-btn');
const vinRes = document.getElementById('vin-results');

const VIN_PER_PAGE = 25;
const vinState = { cnpj: '', dados: null, filtro: 'todos', nivel: 'todos', busca: '', page: 0 };

// Hierarquia: a RAIS não traz cargo. O nível vem do QSA da Receita (grátis,
// cruzado por CPF) e, se a usuária pedir, do LinkedIn (lento e pago).
const VIN_NIVEIS = {
  1: { rotulo: 'Decide sozinho', curto: 'Nível 1', cor: 'var(--terracota)', fundo: 'var(--terracota-soft)' },
  2: { rotulo: 'Decide na área', curto: 'Nível 2', cor: 'var(--blue-mid)', fundo: 'var(--blue-soft)' },
  3: { rotulo: 'Influencia e veta', curto: 'Nível 3', cor: 'var(--green)', fundo: 'var(--green-soft)' },
};

if (vinQ) vinQ.addEventListener('input', e => {
  e.target.value = vinState.modo === 'cpf' ? fmtCpf(e.target.value) : fmtCnpj(e.target.value);
});

async function vinBuscar() {
  const cnpj = onlyDigits(vinQ.value);
  if (cnpj.length !== 14) {
    vinRes.innerHTML = `<p class="msg error">CNPJ inválido — precisa ter 14 dígitos.</p>`;
    return;
  }
  vinBtn.disabled = true;
  vinRes.innerHTML = spinner();
  Object.assign(vinState, { cnpj, dados: null, filtro: 'todos', nivel: 'todos', busca: '', page: 0 });
  try {
    const r = await fetch(`${API}/api/company/${cnpj}/vinculos`);
    const data = await r.json();
    vinState.dados = data;
    vinRender();
    logBusca('Vínculos', fmtCnpj(cnpj), `${data.total || 0} pessoa(s)`);
  } catch (e) {
    vinRes.innerHTML = `<p class="msg error">Erro ao consultar: ${esc(e.message)}</p>`;
  } finally {
    vinBtn.disabled = false;
  }
}

function vinFiltrados() {
  const d = vinState.dados;
  if (!d || !Array.isArray(d.vinculos)) return [];
  const termo = normTexto(vinState.busca || '');
  const termoDigitos = onlyDigits(vinState.busca || '');
  return d.vinculos.filter(v => {
    if (vinState.filtro === 'ativos' && !v.ativo) return false;
    if (vinState.filtro === 'desligados' && v.ativo) return false;
    const n = v.nivel || 0;
    if (vinState.nivel === 'decisores' && n === 0) return false;
    if (vinState.nivel === 'sem' && n !== 0) return false;
    if (['1', '2', '3'].includes(vinState.nivel) && String(n) !== vinState.nivel) return false;
    if (!termo) return true;
    const achouNome = normTexto(v.nome || '').includes(termo);
    const achouCpf = termoDigitos && (v.cpf || '').includes(termoDigitos);
    return achouNome || achouCpf;
  });
}

function vinRender() {
  const d = vinState.dados;
  if (!d) return;
  if (d.status === 'unavailable') {
    vinRes.innerHTML = `<p class="msg">ℹ️ ${esc(d.message || 'Consulta de vínculos não configurada.')}</p>`;
    return;
  }
  if (d.status === 'not_found') {
    vinRes.innerHTML = `<p class="msg">Nenhum vínculo declarado na RAIS para o CNPJ ${esc(fmtCnpj(vinState.cnpj))}.
      <br><span style="font-size:.85rem;color:var(--gray-500)">A base cobre o último ano entregue — empresa nova, MEI sem empregado ou quadro só de sócios não aparece aqui.</span></p>`;
    return;
  }
  if (d.status !== 'ok') {
    vinRes.innerHTML = `<p class="msg error">${esc(d.message || 'Falha ao consultar os vínculos.')}</p>`;
    return;
  }

  const lista = vinFiltrados();
  const h = d.hierarquia || {};
  vinRes.innerHTML = `
    <div class="results-head">
      <h2>${esc(d.razao_social || fmtCnpj(d.cnpj))}</h2>
      <span class="results-head-note">Fontes: RAIS (entregue em ${esc(d.referencia_br || '—')}) + quadro de sócios da Receita</span>
    </div>
    <div class="metric-grid" style="margin-bottom:16px">
      <div class="metric-cell">
        <div class="metric-label">Pessoas declaradas</div>
        <div class="metric-value">${d.total}</div>
        <div class="metric-sub">na última RAIS entregue</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Ainda na empresa</div>
        <div class="metric-value" style="color:var(--green)">${d.ativos}</div>
        <div class="metric-sub">sem desligamento até ${esc(d.referencia_br || '—')}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Já saíram</div>
        <div class="metric-value" style="color:var(--gray-500)">${d.desligados}</div>
        <div class="metric-sub">com desligamento declarado</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Quem decide</div>
        <div class="metric-value" style="color:var(--terracota)">${h.decisores || 0}</div>
        <div class="metric-sub">${d.socios_fora_da_folha ? esc(String(d.socios_fora_da_folha)) + ' fora da folha' : 'com cargo identificado'}</div>
      </div>
    </div>

    <div class="res-tabs" id="vin-tabs">
      <button class="res-tab${vinState.filtro === 'todos' ? ' active' : ''}" data-f="todos">Todos <span class="res-tab-count">${d.total}</span></button>
      <button class="res-tab${vinState.filtro === 'ativos' ? ' active' : ''}" data-f="ativos">Ainda lá <span class="res-tab-count">${d.ativos}</span></button>
      <button class="res-tab${vinState.filtro === 'desligados' ? ' active' : ''}" data-f="desligados">Já saíram <span class="res-tab-count">${d.desligados}</span></button>
    </div>

    <div class="search-panel" style="margin-bottom:14px">
      <div class="filter-row" id="vin-niveis" style="margin-bottom:10px">
        <span class="filter-label">Hierarquia:</span>
        <button class="vin-nivel${vinState.nivel === 'todos' ? ' active' : ''}" data-n="todos">Todo mundo</button>
        <button class="vin-nivel vin-nivel-dec${vinState.nivel === 'decisores' ? ' active' : ''}" data-n="decisores">👑 Só quem decide <span class="res-tab-count">${h.decisores || 0}</span></button>
        <button class="vin-nivel${vinState.nivel === '1' ? ' active' : ''}" data-n="1">1 · dono e presidência <span class="res-tab-count">${h.nivel_1 || 0}</span></button>
        <button class="vin-nivel${vinState.nivel === '2' ? ' active' : ''}" data-n="2">2 · diretoria <span class="res-tab-count">${h.nivel_2 || 0}</span></button>
        <button class="vin-nivel${vinState.nivel === '3' ? ' active' : ''}" data-n="3">3 · gerência <span class="res-tab-count">${h.nivel_3 || 0}</span></button>
        <button class="vin-nivel${vinState.nivel === 'sem' ? ' active' : ''}" data-n="sem">sem cargo conhecido <span class="res-tab-count">${h.sem_cargo || 0}</span></button>
      </div>
      <div class="search-row">
        <div class="input-wrap">
          <span class="input-icon">🔎</span>
          <input id="vin-filtro-nome" type="text" placeholder="Filtrar por nome ou CPF…" value="${esc(vinState.busca)}" autocomplete="off" />
        </div>
        <button id="vin-assertiva" class="btn-secondary" title="Puxa os possíveis decisores da Assertiva e cruza por CPF — 2 consultas Assertiva">🎯 Busca Assertiva</button>
        <button id="vin-cargos" class="btn-secondary" title="Consulta o LinkedIn da empresa e cruza por nome — lento e pago">🔗 Buscar cargos no LinkedIn</button>
        <button id="vin-export" class="btn-secondary">📊 Exportar XLSX</button>
      </div>
      <div id="vin-cargos-status" class="prosp-dedup-note" hidden></div>
    </div>

    <div id="vin-lista-head" class="results-head" style="margin-bottom:8px">
      <h2 style="font-size:1rem">${lista.length} pessoa${lista.length === 1 ? '' : 's'} nesta lista</h2>
      <span class="results-head-note">clique em alguém para puxar telefone e endereço</span>
    </div>
    <div id="vin-lista"></div>
    <div id="vin-pager" class="prosp-pager"></div>

    <div class="dica">
      <div class="dica-title">O que essa lista é (e o que ela não é)</div>
      <div class="dica-body">É a RAIS: a declaração anual que a empresa entrega ao Ministério do Trabalho, com quem estava na folha. A última aqui foi entregue em ${esc(d.referencia_br || '—')} — quem entrou depois disso não aparece, e "ainda na empresa" quer dizer "estava lá naquela data". De quem já saiu, a base informa só o dia e o mês do desligamento, sem o ano.</div>
    </div>
    <div class="dica">
      <div class="dica-title">De onde vem a hierarquia</div>
      <div class="dica-body">A RAIS <strong>não traz cargo de ninguém</strong>. O nível de decisão vem do quadro de sócios da Receita Federal, cruzado por CPF — por isso só sócio e administrador aparecem classificados de cara${d.socios_fora_da_folha ? `, incluindo ${esc(String(d.socios_fora_da_folha))} que não está${d.socios_fora_da_folha === 1 ? '' : 'ão'} na folha mas mand${d.socios_fora_da_folha === 1 ? 'a' : 'am'} na empresa` : ''}. Para descobrir o cargo de funcionário que não é sócio, use "Buscar cargos no LinkedIn" — aí é consulta paga e o cruzamento é por nome, então confira antes de ligar.</div>
    </div>`;

  document.querySelectorAll('#vin-tabs .res-tab').forEach(b => b.addEventListener('click', () => {
    vinState.filtro = b.dataset.f;
    vinState.page = 0;
    vinRender();
  }));

  document.querySelectorAll('#vin-niveis .vin-nivel').forEach(b => b.addEventListener('click', () => {
    vinState.nivel = b.dataset.n;
    vinState.page = 0;
    vinRender();
  }));

  document.getElementById('vin-assertiva').addEventListener('click', vinBuscarAssertiva);
  document.getElementById('vin-cargos').addEventListener('click', vinBuscarCargos);

  document.getElementById('vin-filtro-nome').addEventListener('input', e => {
    vinState.busca = e.target.value;
    vinState.page = 0;
    vinRenderPagina();
    const n = vinFiltrados().length;
    document.querySelector('#vin-lista-head h2').textContent = `${n} pessoa${n === 1 ? '' : 's'} nesta lista`;
  });

  document.getElementById('vin-export').addEventListener('click', vinExportar);
  vinRenderPagina();
}


function vinRenderPagina() {
  const lista = vinFiltrados();
  const pages = Math.max(1, Math.ceil(lista.length / VIN_PER_PAGE));
  const page = Math.min(vinState.page || 0, pages - 1);
  vinState.page = page;
  const el = document.getElementById('vin-lista');
  if (!el) return;

  if (!lista.length) {
    el.innerHTML = `<p class="msg" style="padding:24px 0">Ninguém bate com esse filtro.</p>`;
    document.getElementById('vin-pager').innerHTML = '';
    return;
  }

  el.innerHTML = lista.slice(page * VIN_PER_PAGE, page * VIN_PER_PAGE + VIN_PER_PAGE).map((v, k) => {
    const id = 'vin-' + (page * VIN_PER_PAGE + k);
    const badge = v.ativo
      ? `<span class="badge badge-ativa">Ainda lá</span>`
      : `<span class="badge badge-neutra">Saiu em ${esc(v.desligamento_br || '—')}</span>`;
    const nv = VIN_NIVEIS[v.nivel];
    const badgeNivel = nv
      ? `<span class="vin-badge-nivel" style="background:${nv.fundo};color:${nv.cor}" title="${esc(nv.rotulo)} · fonte: ${esc(v.fonte_cargo || '')}">${esc(nv.curto)} · ${esc(v.cargo || '')}${v.area ? ' · ' + esc(v.area) : ''}</span>`
      : '';
    const desde = vinDataBr(v.desde);
    const meta = [
      v.na_rais === false
        ? `📋 sócio fora da folha${desde ? ' · desde ' + esc(desde) : ''}`
        : `📅 admitido em ${esc(v.admissao_br || '—')}`,
      v.tempo_casa ? `⏳ ${esc(v.tempo_casa)} de casa` : '',
    ].filter(Boolean).join(' · ');
    // Sócio cujo CPF a base JBR não resolveu: não dá pra abrir a ficha da pessoa.
    const semCpf = !v.cpf;
    return `
    <div class="card-person" data-cpf="${esc(v.cpf)}">
      <div class="card-person-header"${semCpf ? ' style="cursor:default"' : ` onclick="togglePerson('${id}', '${v.cpf}')"`}>
        <div>
          <div class="person-name">${esc(v.nome || '—')} ${badgeNivel}</div>
          <div class="person-meta">${meta}</div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          ${badge}
          <span class="person-cpf">${semCpf ? 'CPF não resolvido' : esc(fmtCpf(v.cpf))}</span>
          ${semCpf ? '' : `<span class="person-chevron" id="chev-np-${id}">▼</span>`}
        </div>
      </div>
      <div class="card-person-body" id="body-${id}">
        <div id="mk-${id}" style="padding-top:12px"><p class="msg" style="padding:12px">Carregando dados Mk Buscas…</p></div>
      </div>
    </div>`;
  }).join('');

  vinRenderPager(page, pages);
}

function vinRenderPager(page, pages) {
  const el = document.getElementById('vin-pager');
  if (!el) return;
  if (pages <= 1) { el.innerHTML = ''; return; }
  const nums = [];
  const win = 2;
  for (let p = 0; p < pages; p++) {
    if (p === 0 || p === pages - 1 || (p >= page - win && p <= page + win)) nums.push(p);
    else if (nums[nums.length - 1] !== '…') nums.push('…');
  }
  const btn = (label, p, opts = {}) =>
    `<button class="prosp-page-btn${opts.active ? ' active' : ''}" ${opts.disabled ? 'disabled' : ''} data-p="${p}">${label}</button>`;
  el.innerHTML = `<div class="prosp-pages">
      ${btn('«', 0, { disabled: page === 0 })}
      ${btn('‹', page - 1, { disabled: page === 0 })}
      ${nums.map(n => n === '…' ? '<span class="prosp-page-dots">…</span>' : btn(n + 1, n, { active: n === page })).join('')}
      ${btn('›', page + 1, { disabled: page >= pages - 1 })}
      ${btn('»', pages - 1, { disabled: page >= pages - 1 })}
    </div>`;
  el.querySelectorAll('.prosp-page-btn').forEach(b => b.addEventListener('click', () => {
    vinState.page = parseInt(b.dataset.p);
    vinRenderPagina();
    document.getElementById('vin-lista-head').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }));
}

// Cruza os possíveis decisores da Assertiva (gerente/diretor/administrador, com
// CPF) na lista da RAIS. Cruzamento por CPF exato — quem não está na folha entra
// como linha nova, porque costuma ser gente contratada depois da última RAIS.
async function vinBuscarAssertiva() {
  const btn = document.getElementById('vin-assertiva');
  const status = document.getElementById('vin-cargos-status');
  const d = vinState.dados;
  if (!d) return;
  btn.disabled = true;
  status.hidden = false;
  status.textContent = 'Consultando a Assertiva (cadastro + possíveis decisores)…';
  try {
    const r = await fetch(`${API}/api/company/${d.cnpj}/vinculos/assertiva`).then(x => x.json());
    if (r.status !== 'ok') {
      status.textContent = '⚠️ ' + (r.message || 'Não foi possível consultar a Assertiva.');
      return;
    }
    const porCpf = {};
    d.vinculos.forEach(v => { if (v.cpf) porCpf[v.cpf] = v; });
    let marcados = 0, adicionados = 0;
    (r.decisores || []).forEach(p => {
      const alvo = porCpf[p.cpf];
      if (alvo) {
        // Cargo da Receita é registro oficial — não sobrescreve.
        if (alvo.fonte_cargo === 'Receita Federal (QSA)') return;
        Object.assign(alvo, { cargo: p.cargo, fonte_cargo: 'Assertiva', nivel: p.nivel, rotulo: p.rotulo, area: p.area });
        marcados++;
      } else if (p.cpf) {
        d.vinculos.push({
          cpf: p.cpf, nome: p.nome, cargo: p.cargo, fonte_cargo: 'Assertiva',
          nivel: p.nivel, rotulo: p.rotulo, area: p.area, nascimento: p.nascimento,
          admissao: '', admissao_br: '', desligamento: null, desligamento_br: '',
          ativo: true, tempo_casa: '', socio: false, na_rais: false,
        });
        adicionados++;
      }
    });
    d.total = d.vinculos.length;
    d.ativos = d.vinculos.filter(v => v.ativo).length;
    d.desligados = d.total - d.ativos;
    d.hierarquia = vinRecontarHierarquia(d.vinculos);
    vinState.page = 0;
    vinRender();
    const st = document.getElementById('vin-cargos-status');
    st.hidden = false;
    st.textContent = `✅ Assertiva: ${r.total} possível(is) decisor(es) — ${marcados} cruzado(s) por CPF com a folha da RAIS e ${adicionados} adicionado(s) (não estavam na última RAIS entregue).`;
  } catch (e) {
    status.textContent = '⚠️ Erro na consulta Assertiva: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function vinBuscarCargos() {
  const btn = document.getElementById('vin-cargos');
  const status = document.getElementById('vin-cargos-status');
  const d = vinState.dados;
  if (!d) return;
  btn.disabled = true;
  status.hidden = false;
  status.textContent = 'Procurando os perfis da empresa no LinkedIn… isso leva um tempo.';
  try {
    const r = await fetch(`${API}/api/company/${d.cnpj}/vinculos/cargos`);
    const res = await r.json();
    if (res.status !== 'ok') {
      status.textContent = '⚠️ ' + (res.message || 'Não foi possível buscar cargos no LinkedIn.');
      return;
    }
    // Aplica na lista que já está na tela, sem refazer a consulta da RAIS.
    const porCpf = {};
    (res.cargos || []).forEach(c => { if (c.cpf) porCpf[c.cpf] = c; });
    let aplicados = 0;
    d.vinculos.forEach(v => {
      const c = porCpf[v.cpf];
      if (!c || v.fonte_cargo === 'Receita Federal (QSA)') return;
      Object.assign(v, { cargo: c.cargo, fonte_cargo: c.fonte_cargo, nivel: c.nivel, rotulo: c.rotulo, area: c.area });
      aplicados++;
    });
    d.hierarquia = vinRecontarHierarquia(d.vinculos);
    vinRender();
    const st = document.getElementById('vin-cargos-status');
    st.hidden = false;
    st.textContent = aplicados
      ? `✅ ${aplicados} cargo(s) do LinkedIn cruzado(s) por nome, de ${res.perfis_linkedin || 0} perfil(is) encontrado(s). Confira antes de usar — nome igual não é sempre a mesma pessoa.`
      : `Nenhum dos ${res.perfis_linkedin || 0} perfil(is) do LinkedIn bateu com um nome da RAIS.${res.message ? ' ' + res.message : ''}`;
  } catch (e) {
    status.textContent = '⚠️ Erro ao buscar cargos: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// data_entrada_sociedade vem da Receita em ISO (2020-01-16) — na tela é BR.
function vinDataBr(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso || '');
}

function vinRecontarHierarquia(vinculos) {
  const c = { nivel_1: 0, nivel_2: 0, nivel_3: 0, sem_cargo: 0, socios: 0, decisores: 0 };
  vinculos.forEach(v => {
    const n = v.nivel || 0;
    c[n === 1 ? 'nivel_1' : n === 2 ? 'nivel_2' : n === 3 ? 'nivel_3' : 'sem_cargo']++;
    if (v.socio) c.socios++;
  });
  c.decisores = c.nivel_1 + c.nivel_2 + c.nivel_3;
  return c;
}

async function vinExportar() {
  const btn = document.getElementById('vin-export');
  const d = vinState.dados;
  if (!d) return;
  btn.disabled = true;
  try {
    const resp = await fetch(`${API}/api/vinculos/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cnpj: d.cnpj,
        razao_social: d.razao_social,
        referencia_br: d.referencia_br,
        vinculos: vinFiltrados(),
      }),
    });
    if (!resp.ok) throw new Error('servidor respondeu ' + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vinculos-${d.cnpj}.xlsx`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('Falha ao exportar: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

function vinBuscarConformeModo() {
  return vinState.modo === 'cpf' ? vinBuscarCpf() : vinBuscar();
}

if (vinBtn) {
  vinBtn.addEventListener('click', vinBuscarConformeModo);
  vinQ.addEventListener('keydown', e => e.key === 'Enter' && vinBuscarConformeModo());
  document.querySelectorAll('.chip-vin').forEach(c => c.addEventListener('click', () => {
    vinQ.value = fmtCnpj(c.dataset.val);
    vinBuscar();
  }));
}

// ══════════════════════════════════════════════════════
//  MÓDULO EMPRESA ASSERTIVA
//  Cadastro da empresa (Receita/BrasilAPI) + possíveis decisores (Assertiva).
//  Os decisores são GESTORES (gerente, diretor, administrador), não sócios.
// ══════════════════════════════════════════════════════
const eaQ   = document.getElementById('ea-q');
const eaBtn = document.getElementById('ea-btn');
const eaRes = document.getElementById('ea-results');

const EA_PER_PAGE = 25;
const eaState = { cnpj: '', empresa: null, dados: null, nivel: 'todos', busca: '', page: 0 };

if (eaQ) eaQ.addEventListener('input', e => { e.target.value = fmtCnpj(e.target.value); });

async function eaBuscar() {
  const cnpj = onlyDigits(eaQ.value);
  if (cnpj.length !== 14) {
    eaRes.innerHTML = `<p class="msg error">CNPJ inválido — precisa ter 14 dígitos.</p>`;
    return;
  }
  const comConexoes = document.getElementById('ea-conexoes')?.checked;
  eaBtn.disabled = true;
  eaRes.innerHTML = spinner();
  Object.assign(eaState, { cnpj, empresa: null, dados: null, nivel: 'todos', busca: '', page: 0 });
  try {
    const [emp, dec] = await Promise.all([
      fetch(`${API}/api/company/${cnpj}`).then(r => r.json()).catch(() => null),
      fetch(`${API}/api/company/${cnpj}/decisores${comConexoes ? '?conexoes=true' : ''}`).then(r => r.json()),
    ]);
    eaState.empresa = (emp && emp.company) || null;
    eaState.dados = dec;
    eaRender();
    logBusca('Empresa Assertiva', fmtCnpj(cnpj), `${dec.total || 0} decisor(es)`);
  } catch (e) {
    eaRes.innerHTML = `<p class="msg error">Erro ao consultar: ${esc(e.message)}</p>`;
  } finally {
    eaBtn.disabled = false;
  }
}

function eaFiltrados() {
  const lista = (eaState.dados && eaState.dados.decisores) || [];
  const termo = normTexto(eaState.busca || '');
  const digitos = onlyDigits(eaState.busca || '');
  return lista.filter(p => {
    if (['1', '2', '3'].includes(eaState.nivel) && String(p.nivel || 0) !== eaState.nivel) return false;
    if (!termo) return true;
    return normTexto(p.nome || '').includes(termo) || (digitos && (p.cpf || '').includes(digitos));
  });
}

function eaRender() {
  const d = eaState.dados;
  if (!d) return;
  if (d.status === 'unavailable' || d.status === 'no_access') {
    eaRes.innerHTML = `<p class="msg">ℹ️ ${esc(d.message || 'Assertiva indisponível.')}</p>`;
    return;
  }
  if (d.status !== 'ok') {
    eaRes.innerHTML = `<p class="msg error">${esc(d.message || 'Falha na consulta Assertiva.')}</p>`;
    return;
  }

  const emp = eaState.empresa || {};
  const cad = d.cadastro_assertiva || {};
  const n = d.por_nivel || {};
  const lista = eaFiltrados();
  const socios = d.socios_assertiva || [];
  const conexoes = d.conexoes || [];

  const razao = emp.razao_social || cad.razao_social || fmtCnpj(d.cnpj);
  const cidade = [emp.municipio, emp.uf].filter(Boolean).join('/');

  eaRes.innerHTML = `
    <div class="results-head">
      <h2>${esc(razao)}</h2>
      <span class="results-head-note">Cadastro: Receita Federal · Decisores: Assertiva</span>
    </div>

    <div class="metric-grid" style="margin-bottom:16px">
      <div class="metric-cell">
        <div class="metric-label">Situação na Receita</div>
        <div class="metric-value" style="font-size:1.05rem">${badgeSit(emp.descricao_situacao_cadastral || cad.situacao || '')}</div>
        <div class="metric-sub">${esc(fmtCnpj(d.cnpj))}${cidade ? ' · ' + esc(cidade) : ''}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Funcionários declarados</div>
        <div class="metric-value">${cad.quantidade_funcionarios != null ? cad.quantidade_funcionarios : '—'}</div>
        <div class="metric-sub">${esc(cad.porte || emp.porte || '')}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Possíveis decisores</div>
        <div class="metric-value" style="color:var(--terracota)">${d.total}</div>
        <div class="metric-sub">gestores, não sócios</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Idade da empresa</div>
        <div class="metric-value">${cad.idade_empresa != null ? cad.idade_empresa + ' anos' : '—'}</div>
        <div class="metric-sub">${emp.data_inicio_atividade ? 'desde ' + esc(emp.data_inicio_atividade) : ''}</div>
      </div>
    </div>

    ${eaBlocoEmpresa(emp)}
    ${eaBlocoSocios(socios)}
    ${conexoes.length ? eaBlocoConexoes(conexoes) : ''}
    ${d.conexoes_erro ? `<p class="msg" style="font-size:.85rem">Conexões indisponíveis: ${esc(d.conexoes_erro)}</p>` : ''}

    <div class="search-panel" style="margin:18px 0 14px">
      <div class="filter-row" id="ea-niveis" style="margin-bottom:10px">
        <span class="filter-label">Hierarquia:</span>
        <button class="vin-nivel${eaState.nivel === 'todos' ? ' active' : ''}" data-n="todos">Todos <span class="res-tab-count">${d.total}</span></button>
        <button class="vin-nivel${eaState.nivel === '1' ? ' active' : ''}" data-n="1">1 · decide sozinho <span class="res-tab-count">${n.nivel_1 || 0}</span></button>
        <button class="vin-nivel${eaState.nivel === '2' ? ' active' : ''}" data-n="2">2 · diretoria <span class="res-tab-count">${n.nivel_2 || 0}</span></button>
        <button class="vin-nivel${eaState.nivel === '3' ? ' active' : ''}" data-n="3">3 · gerência <span class="res-tab-count">${n.nivel_3 || 0}</span></button>
      </div>
      <div class="search-row">
        <div class="input-wrap">
          <span class="input-icon">🔎</span>
          <input id="ea-filtro-nome" type="text" placeholder="Filtrar por nome ou CPF…" value="${esc(eaState.busca)}" autocomplete="off" />
        </div>
        <button id="ea-export" class="btn-secondary">📊 Exportar XLSX</button>
      </div>
    </div>

    <div id="ea-lista-head" class="results-head" style="margin-bottom:8px">
      <h2 style="font-size:1rem">${lista.length} pessoa${lista.length === 1 ? '' : 's'} nesta lista</h2>
      <span class="results-head-note">clique em alguém para puxar telefone e endereço</span>
    </div>
    <div id="ea-lista"></div>
    <div id="ea-pager" class="prosp-pager"></div>

    <div class="dica">
      <div class="dica-title">"Possível decisor" quer dizer o quê</div>
      <div class="dica-body">É gente com cargo de gestão que a Assertiva liga a este CNPJ — gerente, diretor, coordenador, administrador. <strong>Não são os sócios</strong>: no CNPJ da Google Brasil vieram 602 nomes e nenhum deles está no quadro societário da Receita. A Assertiva não diz de onde tira o cargo, então trate como pista forte de prospecção, não como prova de que a pessoa assina contrato.</div>
    </div>`;

  document.querySelectorAll('#ea-niveis .vin-nivel').forEach(b => b.addEventListener('click', () => {
    eaState.nivel = b.dataset.n; eaState.page = 0; eaRender();
  }));
  document.getElementById('ea-filtro-nome').addEventListener('input', e => {
    eaState.busca = e.target.value; eaState.page = 0;
    eaRenderPagina();
    const q = eaFiltrados().length;
    document.querySelector('#ea-lista-head h2').textContent = `${q} pessoa${q === 1 ? '' : 's'} nesta lista`;
  });
  document.getElementById('ea-export').addEventListener('click', eaExportar);
  eaRenderPagina();
}

function eaBlocoEmpresa(emp) {
  if (!emp || !emp.cnpj) return '';
  const linhas = [
    ['Nome fantasia', emp.nome_fantasia],
    ['Atividade principal', emp.cnae_fiscal_descricao],
    ['Natureza jurídica', emp.natureza_juridica],
    ['Capital social', emp.capital_social ? 'R$ ' + Number(emp.capital_social).toLocaleString('pt-BR') : ''],
    ['Endereço', [emp.logradouro, emp.numero, emp.bairro, emp.municipio, emp.uf, emp.cep].filter(Boolean).join(', ')],
    ['Telefone', emp.ddd_telefone_1 ? fmtPhone(emp.ddd_telefone_1) : ''],
    ['E-mail', emp.email],
  ].filter(([, v]) => v);
  if (!linhas.length) return '';
  return makeAccordion('🏢', 'Cadastro na Receita Federal', linhas.length,
    `<div class="as-kv">${linhas.map(([k, v]) => `<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div>`);
}

function eaBlocoSocios(socios) {
  if (!socios.length) return '';
  const itens = socios.map(s => `<li>${esc(s.nomeOuRazaoSocial || '')} — <span class="mono">${esc(s.documento || '')}</span>${s.dataEntrada ? ' · desde ' + esc(s.dataEntrada) : ''}</li>`).join('');
  return makeAccordion('👤', 'Sócios (quadro societário)', socios.length, `<ul class="as-ul">${itens}</ul>`);
}

function eaBlocoConexoes(conexoes) {
  const itens = conexoes.map(c => {
    const tel = c.telefone ? `${esc(c.telefone)}${c.whatsapp ? ' 💬' : ''}${c.naoPerturbe ? ' 🚫 não perturbe' : ''}` : '—';
    return `<tr><td>${esc(c.nomeOuRazaoSocial || '')}</td><td>${esc(c.relacao || '')}</td>
            <td class="mono">${esc(c.documento || '')}</td><td>${tel}</td></tr>`;
  }).join('');
  return makeAccordion('🔗', 'Conexões com telefone (Assertiva)', conexoes.length,
    `<table class="data-table"><thead><tr><th>Nome</th><th>Relação</th><th>Documento</th><th>Telefone</th></tr></thead><tbody>${itens}</tbody></table>`);
}

function eaRenderPagina() {
  const lista = eaFiltrados();
  const pages = Math.max(1, Math.ceil(lista.length / EA_PER_PAGE));
  const page = Math.min(eaState.page || 0, pages - 1);
  eaState.page = page;
  const el = document.getElementById('ea-lista');
  if (!el) return;

  if (!lista.length) {
    el.innerHTML = `<p class="msg" style="padding:24px 0">Ninguém bate com esse filtro.</p>`;
    document.getElementById('ea-pager').innerHTML = '';
    return;
  }

  el.innerHTML = lista.slice(page * EA_PER_PAGE, page * EA_PER_PAGE + EA_PER_PAGE).map((p, k) => {
    const id = 'ea-' + (page * EA_PER_PAGE + k);
    const nv = VIN_NIVEIS[p.nivel];
    const badgeNivel = nv
      ? `<span class="vin-badge-nivel" style="background:${nv.fundo};color:${nv.cor}" title="${esc(nv.rotulo)}">${esc(nv.curto)} · ${esc(p.cargo || '')}${p.area ? ' · ' + esc(p.area) : ''}</span>`
      : `<span class="vin-badge-nivel" style="background:var(--gray-100);color:var(--gray-700)">${esc(p.cargo || 'sem cargo')}</span>`;
    const semCpf = !p.cpf;
    return `
    <div class="card-person" data-cpf="${esc(p.cpf)}">
      <div class="card-person-header"${semCpf ? ' style="cursor:default"' : ` onclick="togglePerson('${id}', '${p.cpf}')"`}>
        <div>
          <div class="person-name">${esc(p.nome || '—')} ${badgeNivel}</div>
          <div class="person-meta">${p.nascimento ? '🎂 ' + esc(p.nascimento) : ''}</div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="person-cpf">${semCpf ? 'sem CPF' : esc(fmtCpf(p.cpf))}</span>
          ${semCpf ? '' : `<span class="person-chevron" id="chev-np-${id}">▼</span>`}
        </div>
      </div>
      <div class="card-person-body" id="body-${id}">
        <div id="mk-${id}" style="padding-top:12px"><p class="msg" style="padding:12px">Carregando dados Mk Buscas…</p></div>
      </div>
    </div>`;
  }).join('');

  eaRenderPager(page, pages);
}

function eaRenderPager(page, pages) {
  const el = document.getElementById('ea-pager');
  if (!el) return;
  if (pages <= 1) { el.innerHTML = ''; return; }
  const nums = [];
  for (let p = 0; p < pages; p++) {
    if (p === 0 || p === pages - 1 || (p >= page - 2 && p <= page + 2)) nums.push(p);
    else if (nums[nums.length - 1] !== '…') nums.push('…');
  }
  const btn = (label, p, opts = {}) =>
    `<button class="prosp-page-btn${opts.active ? ' active' : ''}" ${opts.disabled ? 'disabled' : ''} data-p="${p}">${label}</button>`;
  el.innerHTML = `<div class="prosp-pages">
      ${btn('«', 0, { disabled: page === 0 })}
      ${btn('‹', page - 1, { disabled: page === 0 })}
      ${nums.map(n => n === '…' ? '<span class="prosp-page-dots">…</span>' : btn(n + 1, n, { active: n === page })).join('')}
      ${btn('›', page + 1, { disabled: page >= pages - 1 })}
      ${btn('»', pages - 1, { disabled: page >= pages - 1 })}
    </div>`;
  el.querySelectorAll('.prosp-page-btn').forEach(b => b.addEventListener('click', () => {
    eaState.page = parseInt(b.dataset.p);
    eaRenderPagina();
    document.getElementById('ea-lista-head').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }));
}

async function eaExportar() {
  const btn = document.getElementById('ea-export');
  const d = eaState.dados;
  if (!d) return;
  btn.disabled = true;
  try {
    // Mesmo XLSX da aba de vínculos — as colunas de cargo/nível já existem lá.
    const linhas = eaFiltrados().map(p => ({ ...p, ativo: true, tempo_casa: '', admissao_br: '', desligamento_br: '' }));
    const resp = await fetch(`${API}/api/vinculos/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cnpj: d.cnpj,
        razao_social: (eaState.empresa && eaState.empresa.razao_social) || (d.cadastro_assertiva || {}).razao_social || '',
        referencia_br: 'consulta Assertiva',
        vinculos: linhas,
      }),
    });
    if (!resp.ok) throw new Error('servidor respondeu ' + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `decisores-${d.cnpj}.xlsx`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('Falha ao exportar: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

if (eaBtn) {
  eaBtn.addEventListener('click', eaBuscar);
  eaQ.addEventListener('keydown', e => e.key === 'Enter' && eaBuscar());
  document.querySelectorAll('.chip-ea').forEach(c => c.addEventListener('click', () => {
    eaQ.value = fmtCnpj(c.dataset.val);
    eaBuscar();
  }));
}

// ── Aba Vínculo empregatício: modo por CPF (o inverso do CNPJ) ────────
// Por empresa a pergunta é "quem trabalha aqui"; por pessoa é "onde essa
// pessoa trabalhou". Mesma base RAIS, mesmo endpoint invertido.
vinState.modo = 'cnpj';

function vinTrocarModo(modo) {
  vinState.modo = modo;
  vinState.dados = null;
  vinState.dadosCpf = null;
  document.querySelectorAll('#vin-modos .as-modo').forEach(b =>
    b.classList.toggle('active', b.dataset.m === modo));
  const porCnpj = modo === 'cnpj';
  document.getElementById('vin-titulo').textContent =
    porCnpj ? 'Quem trabalha nessa empresa?' : 'Onde essa pessoa trabalhou?';
  document.getElementById('vin-sub').textContent = porCnpj
    ? 'Cole o CNPJ e eu trago o quadro de funcionários que a empresa declarou na RAIS — nome, CPF e data de admissão de cada um. Clique em qualquer pessoa para puxar telefone e endereço dela.'
    : 'Cole o CPF e eu trago as empresas que declararam essa pessoa na RAIS, com data de admissão e tempo de casa em cada uma.';
  document.getElementById('vin-icone').textContent = porCnpj ? '🏢' : '🪪';
  const campo = document.getElementById('vin-q');
  campo.value = '';
  campo.placeholder = porCnpj ? 'CNPJ (00.000.000/0001-00)' : 'CPF (000.000.000-00)';
  campo.maxLength = porCnpj ? 18 : 14;
  document.getElementById('vin-btn').textContent = porCnpj ? 'Ver funcionários' : 'Ver vínculos';
  document.getElementById('vin-results').innerHTML = '';
  document.querySelectorAll('.chip-vin').forEach(c => { c.hidden = !porCnpj; });
}

async function vinBuscarCpf() {
  const cpf = onlyDigits(vinQ.value);
  if (cpf.length !== 11) {
    vinRes.innerHTML = `<p class="msg error">CPF inválido — precisa ter 11 dígitos.</p>`;
    return;
  }
  vinBtn.disabled = true;
  vinRes.innerHTML = spinner();
  try {
    const d = await fetch(`${API}/api/person/${cpf}/vinculos`).then(r => r.json());
    vinState.dadosCpf = d;
    vinRenderCpf();
    logBusca('Vínculos por CPF', fmtCpf(cpf), `${d.total || 0} vínculo(s)`);
  } catch (e) {
    vinRes.innerHTML = `<p class="msg error">Erro ao consultar: ${esc(e.message)}</p>`;
  } finally {
    vinBtn.disabled = false;
  }
}

function vinRenderCpf() {
  const d = vinState.dadosCpf;
  if (!d) return;
  if (d.status === 'unavailable') {
    vinRes.innerHTML = `<p class="msg">ℹ️ ${esc(d.message || 'Consulta por CPF não configurada.')}</p>`;
    return;
  }
  if (d.status === 'not_found') {
    vinRes.innerHTML = `<p class="msg">Nenhum vínculo declarado na RAIS para esse CPF.
      <br><span style="font-size:.85rem;color:var(--gray-500)">Autônomo, sócio sem carteira assinada ou quem nunca teve emprego formal não aparece na RAIS.</span></p>`;
    return;
  }
  if (d.status !== 'ok') {
    vinRes.innerHTML = `<p class="msg error">${esc(d.message || 'Falha ao consultar os vínculos.')}</p>`;
    return;
  }

  const linhas = d.vinculos.map(v => `
    <tr>
      <td>
        <div class="prosp-co-name">${esc(v.razao_social || '—')}</div>
        <div class="prosp-co-meta mono">${esc(fmtCnpj(v.cnpj))}</div>
      </td>
      <td>${esc(v.admissao_br || '—')}</td>
      <td>${v.ativo
        ? '<span class="badge badge-ativa">Ainda lá</span>'
        : `<span class="badge badge-neutra">Saiu em ${esc(v.desligamento_br || '—')}</span>`}</td>
      <td>${esc(v.tempo_casa || '—')}</td>
      <td><button class="btn-secondary" onclick="vinVerEmpresa('${esc(v.cnpj)}')">Quem mais trabalha lá →</button></td>
    </tr>`).join('');

  vinRes.innerHTML = `
    <div class="results-head">
      <h2>${esc(d.nome || fmtCpf(d.cpf))}</h2>
      <span class="results-head-note">Fonte: RAIS · entregue em ${esc(d.referencia_br || '—')}</span>
    </div>
    <div class="metric-grid" style="margin-bottom:16px">
      <div class="metric-cell">
        <div class="metric-label">Vínculos declarados</div>
        <div class="metric-value">${d.total}</div>
        <div class="metric-sub">empresas que declararam essa pessoa</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Ainda na empresa</div>
        <div class="metric-value" style="color:var(--green)">${d.ativos}</div>
        <div class="metric-sub">sem desligamento até ${esc(d.referencia_br || '—')}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Já saiu</div>
        <div class="metric-value" style="color:var(--gray-500)">${d.desligados}</div>
        <div class="metric-sub">com desligamento declarado</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">CPF</div>
        <div class="metric-value mono" style="font-size:1.05rem">${esc(fmtCpf(d.cpf))}</div>
        <div class="metric-sub">${esc(d.nome || '')}</div>
      </div>
    </div>
    <table class="data-table">
      <thead><tr><th>Empresa</th><th>Admissão</th><th>Situação</th><th>Tempo de casa</th><th></th></tr></thead>
      <tbody>${linhas}</tbody>
    </table>
    <div class="dica">
      <div class="dica-title">O que essa lista mostra</div>
      <div class="dica-body">Só emprego formal declarado na RAIS até ${esc(d.referencia_br || '—')}. Sócio que não é empregado da própria empresa, autônomo e PJ não aparecem aqui — para esses, a aba <strong>Empresa Assertiva</strong> e o quadro de sócios da Receita contam mais.</div>
    </div>`;
}

window.vinVerEmpresa = function(cnpj) {
  vinTrocarModo('cnpj');
  document.getElementById('vin-q').value = fmtCnpj(cnpj);
  vinBuscar();
};

(function initVinModos() {
  const modos = document.getElementById('vin-modos');
  if (!modos) return;
  modos.querySelectorAll('.as-modo').forEach(b =>
    b.addEventListener('click', () => vinTrocarModo(b.dataset.m)));
})();

// ══════════════════════════════════════════════════════
//  BUSCA PARENTES (ASSERTIVA)
//  Junta /localize/v3/pessoas-de-referencia (parentesco de mais gente) com
//  /localize-api/v1/base-cadastral/conexoes (telefone + flag de WhatsApp).
//  As duas se sobrepõem; o backend cruza por documento e funde.
// ══════════════════════════════════════════════════════
window.buscarParentes = async function(cpf, btn) {
  const doc = onlyDigits(cpf);
  const rotulo = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Buscando parentes…';

  // A caixa nasce logo depois do bloco de resultado onde o botão está.
  const raiz = btn.closest('.results-area, #as-results, .person-header')?.parentElement
            || btn.closest('.results-area') || document.body;
  let caixa = document.getElementById('parentes-' + doc);
  if (!caixa) {
    caixa = document.createElement('div');
    caixa.id = 'parentes-' + doc;
    caixa.style.marginTop = '14px';
    raiz.appendChild(caixa);
  }
  caixa.innerHTML = spinner();

  try {
    const d = await fetch(`${API}/api/person/${doc}/parentes`).then(r => r.json());
    caixa.innerHTML = htmlParentes(d);
    logBusca('Busca Parentes', fmtCpf(doc), `${d.total || 0} conexão(ões)`);
  } catch (e) {
    caixa.innerHTML = `<p class="msg error">Erro ao buscar parentes: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = rotulo;
  }
  caixa.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
};

function htmlParentes(d) {
  if (d.status === 'unavailable') return `<p class="msg">ℹ️ ${esc(d.message || 'Assertiva não configurada.')}</p>`;
  if (d.status === 'not_found' || !d.total) {
    return `<p class="msg">Nenhum parente ou conexão encontrada para esse CPF na Assertiva.
      ${(d.avisos || []).length ? `<br><span style="font-size:.85rem;color:var(--gray-500)">${esc(d.avisos.join(' · '))}</span>` : ''}</p>`;
  }
  if (d.status !== 'ok') return `<p class="msg error">${esc(d.message || 'Falha na busca de parentes.')}</p>`;

  const chips = Object.entries(d.por_relacao || {})
    .sort((a, b) => b[1] - a[1])
    .map(([rel, n]) => `<span class="source-pill" style="background:var(--terracota-soft);color:var(--terracota)">${esc(rel)}: ${n}</span>`)
    .join(' ');

  const linhas = (d.parentes || []).map(p => {
    const doc = onlyDigits(p.documento || '');
    const docFmt = doc.length === 11 ? fmtCpf(doc) : doc.length === 14 ? fmtCnpj(doc) : (p.documento || '');
    const zap = p.whatsapp ? ' 💬' : '';
    const np = p.nao_perturbe ? ' <span class="tel-warn" title="Cadastrado no Não Perturbe">🚫</span>' : '';
    const acao = doc.length === 11
      ? `<button class="btn-secondary" onclick="verPessoaPorCpf('${doc}')">Ver pessoa →</button>`
      : (doc.length === 14 ? `<a class="btn-secondary" href="company.html?cnpj=${doc}" target="_blank">Ver empresa →</a>` : '');
    return `<tr>
      <td>${esc(p.relacao || p.tipo_relacao || '—')}</td>
      <td>${esc(p.nome || '—')}</td>
      <td class="mono">${esc(docFmt)}</td>
      <td>${esc(p.nascimento || '')}</td>
      <td class="mono">${p.telefone ? esc(p.telefone) + zap + np : '—'}</td>
      <td style="font-size:.78rem;color:var(--gray-500)">${esc(p.fonte || '')}</td>
      <td>${acao}</td>
    </tr>`;
  }).join('');

  return `
    <div class="results-head" style="margin-bottom:8px">
      <h2 style="font-size:1rem">👨‍👩‍👧 ${d.total} parente(s) e conexão(ões) — ${d.com_telefone} com telefone</h2>
      <span class="results-head-note">Assertiva · pessoas de referência + conexões</span>
    </div>
    <div class="filter-row" style="margin-top:0">${chips}</div>
    <table class="data-table">
      <thead><tr><th>Relação</th><th>Nome</th><th>Documento</th><th>Nascimento</th><th>Telefone</th><th>Fonte</th><th></th></tr></thead>
      <tbody>${linhas}</tbody>
    </table>
    ${(d.avisos || []).length ? `<p class="msg" style="font-size:.82rem">⚠️ ${esc(d.avisos.join(' · '))}</p>` : ''}
    <div class="dica">
      <div class="dica-title">De onde vem cada linha</div>
      <div class="dica-body"><strong>Pessoas de referência</strong> traz o parentesco (mãe, pai, filho, irmão, cônjuge) e sócios. <strong>Conexões</strong> traz menos gente, mas com telefone, tipo de linha e as flags de WhatsApp e "não perturbe". Quem aparece nas duas vem fundido numa linha só.</div>
    </div>`;
}

// Abre o CPF na aba "Uma pessoa" (reaproveita a busca que já existe).
window.verPessoaPorCpf = function(cpf) {
  document.querySelector('[data-tab="pessoa"]')?.click();
  const campo = document.getElementById('cpf-q');
  if (!campo) return;
  campo.value = fmtCpf(cpf);
  if (typeof searchCpf === 'function') searchCpf();
};

// ── Conexões de um CNPJ (mesmo endpoint, lado empresa) ──────────────
window.buscarConexoesEmpresa = async function(cnpj, btn) {
  const doc = onlyDigits(cnpj);
  const rotulo = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Buscando conexões…';
  let caixa = document.getElementById('conexoes-' + doc);
  if (!caixa) {
    caixa = document.createElement('div');
    caixa.id = 'conexoes-' + doc;
    caixa.style.marginTop = '14px';
    (btn.closest('.results-area, #as-results') || btn.parentElement).appendChild(caixa);
  }
  caixa.innerHTML = spinner();
  try {
    const d = await fetch(`${API}/api/company/${doc}/conexoes`).then(r => r.json());
    caixa.innerHTML = htmlConexoesEmpresa(d);
    logBusca('Conexões CNPJ', fmtCnpj(doc), `${d.total || 0} conexão(ões)`);
  } catch (e) {
    caixa.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = rotulo;
  }
};

function htmlConexoesEmpresa(d) {
  if (d.status === 'unavailable') return `<p class="msg">ℹ️ ${esc(d.message || 'Assertiva não configurada.')}</p>`;
  if (d.status === 'not_found' || !d.total) return `<p class="msg">Nenhuma conexão encontrada para esse CNPJ na Assertiva.</p>`;
  if (d.status !== 'ok') return `<p class="msg error">${esc(d.message || 'Falha ao consultar conexões.')}</p>`;

  const linhas = (d.conexoes || []).map(c => {
    const doc = onlyDigits(c.documento || '');
    const docFmt = doc.length === 11 ? fmtCpf(doc) : doc.length === 14 ? fmtCnpj(doc) : (c.documento || '');
    const zap = c.whatsapp ? ' 💬' : '';
    const np = c.naoPerturbe ? ' 🚫' : '';
    return `<tr>
      <td>${esc(c.relacao || c.tipoRelacao || '—')}</td>
      <td>${esc(c.nomeOuRazaoSocial || '—')}</td>
      <td class="mono">${esc(docFmt)}</td>
      <td>${esc(c.cargo || '')}</td>
      <td class="mono">${c.telefone ? esc(c.telefone) + zap + np : '—'}</td>
    </tr>`;
  }).join('');

  const chips = Object.entries(d.por_tipo || {})
    .map(([t, n]) => `<span class="source-pill" style="background:var(--blue-soft);color:var(--blue-dark)">${esc(t)}: ${n}</span>`).join(' ');

  return `
    <div class="results-head" style="margin-bottom:8px">
      <h2 style="font-size:1rem">🔗 ${d.total} conexão(ões) — ${d.com_telefone} com telefone</h2>
      <span class="results-head-note">Assertiva · sócios, decisores e empresas ligadas</span>
    </div>
    <div class="filter-row" style="margin-top:0">${chips}</div>
    <table class="data-table">
      <thead><tr><th>Relação</th><th>Nome</th><th>Documento</th><th>Cargo</th><th>Telefone</th></tr></thead>
      <tbody>${linhas}</tbody>
    </table>`;
}

// ══════════════════════════════════════════════════════
//  ADMIN · Relatório de uso TOTAL (Assertiva)
//  Confronta o que a Assertiva registrou (o que vira fatura) com o que o
//  CapiBLU logou. Os dois não batem por bons motivos — o widget explica.
// ══════════════════════════════════════════════════════
async function admCustoTotal(dias) {
  const box = document.getElementById('adm-total-resultado');
  if (!box) return;
  const desde = document.getElementById('adm-total-desde').value;
  const ate = document.getElementById('adm-total-ate').value;
  const q = dias && !desde && !ate ? `dias=${dias}` :
    `desde=${encodeURIComponent(desde || '')}&ate=${encodeURIComponent(ate || '')}`;
  box.innerHTML = spinner();
  try {
    const d = await fetch(`${API}/api/custos/total?${q}`).then(r => r.json());
    if (d.status !== 'ok') {
      box.innerHTML = `<p class="msg error">${esc(d.detail || d.message || 'Falha ao carregar.')}</p>`;
      return;
    }
    box.innerHTML = admTotalHtml(d);
  } catch (e) {
    box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  }
}

function admTotalHtml(d) {
  const a = d.assertiva || {};
  const i = d.interno || {};
  const brl = v => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const funcs = Object.entries(a.por_funcionalidade || {}).sort((x, y) => y[1] - x[1]);
  const users = Object.entries(a.por_usuario || {}).sort((x, y) => y[1] - x[1]);
  const totalUsers = users.reduce((s, [, n]) => s + n, 0) || 1;

  // Fora do CapiBLU = o que a Assertiva registrou menos o que saiu daqui.
  // Nunca negativo: cache nosso pode fazer o log local passar do oficial.
  const fora = Math.max(0, (a.total_registros || 0) - (i.chamadas || 0));
  const foraCusto = fora * (d.custo_por_consulta || 0);
  const pctCapi = a.total_registros ? Math.round(((i.chamadas || 0) / a.total_registros) * 100) : 0;

  return `
    <div class="metric-grid" style="margin:12px 0 16px">
      <div class="metric-cell">
        <div class="metric-label">Consultas na Assertiva</div>
        <div class="metric-value" style="color:var(--terracota)">${a.total_registros || 0}</div>
        <div class="metric-sub">${a.consultas || 0} consultas + ${a.subitens || 0} complementos</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Custo no período</div>
        <div class="metric-value">${brl(a.custo_estimado)}</div>
        <div class="metric-sub">${d.preco_medio && Math.abs(d.preco_medio - d.custo_por_consulta) > 0.0001
          ? 'média de ' + brl(d.preco_medio) + ' por consulta (tabela de preços)'
          : 'a ' + brl(d.custo_por_consulta) + ' por consulta — <b>tabela de preços não preenchida</b>'}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Gasto pelo CapiBLU</div>
        <div class="metric-value" style="color:var(--green)">${brl(i.custo_estimado)}</div>
        <div class="metric-sub">${i.chamadas || 0} chamadas — ${pctCapi}% do total</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Gasto FORA do CapiBLU</div>
        <div class="metric-value" style="color:var(--red)">${brl(foraCusto)}</div>
        <div class="metric-sub">${fora} consulta(s) — ${100 - pctCapi}% · portal da Assertiva ou outra integração</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Período</div>
        <div class="metric-value" style="font-size:1.1rem">${esc(d.periodo.dias)} dias</div>
        <div class="metric-sub">${esc(d.periodo.desde)} → ${esc(d.periodo.ate)}</div>
      </div>
    </div>

    ${a.truncado ? `<p class="msg" style="font-size:.85rem">⚠️ O período tem mais registros do que uma leitura só alcança — os números acima são um piso, o real é maior.</p>` : ''}
    ${!a.disponivel ? `<p class="msg error">Relatório da Assertiva indisponível: ${esc(a.mensagem || '')}</p>` : ''}

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px">
      <div>
        <h4 style="font-size:.9rem;margin:0 0 8px">Por tipo de consulta (Assertiva)</h4>
        <table class="data-table">
          <thead><tr><th>Funcionalidade</th><th>Consultas</th><th>Custo</th><th>Preço</th></tr></thead>
          <tbody>${funcs.map(([f, n]) => `<tr><td>${esc(f)}</td><td>${n}</td><td class="mono">${brl((a.custo_por_funcionalidade || {})[f])}</td><td class="mono" style="font-size:.75rem;color:var(--gray-500)">R$ ${Number((d.precos || {})[f] ?? d.custo_por_consulta).toLocaleString('pt-BR', {minimumFractionDigits: 3, maximumFractionDigits: 4})}/un</td></tr>`).join('') || '<tr><td colspan="4" class="msg">Sem registros.</td></tr>'}</tbody>
        </table>
      </div>
      <div>
        <h4 style="font-size:.9rem;margin:0 0 8px">Quem consumiu (conta Assertiva)</h4>
        <table class="data-table">
          <thead><tr><th>Usuário na Assertiva</th><th>Consultas</th><th>%</th><th>Custo</th></tr></thead>
          <tbody>${users.map(([u, n]) => `<tr><td>${esc(u)}</td><td>${n}</td><td>${Math.round((n / totalUsers) * 100)}%</td><td class="mono">${brl(n * d.custo_por_consulta)}</td></tr>`).join('') || '<tr><td colspan="4" class="msg">Sem registros.</td></tr>'}</tbody>
        </table>
        <p class="pf-advanced-hint" style="display:block;margin-top:6px">Este é o nome de usuário <strong>no portal da Assertiva</strong>, não o e-mail do CapiBLU. Quem aparece aqui com número alto e não aparece na tabela de baixo está consultando por fora.</p>
      </div>
    </div>

    <h4 style="font-size:.9rem;margin:18px 0 8px">Quem consumiu (pelo CapiBLU)</h4>
    <table class="data-table">
      <thead><tr><th>Usuário do CapiBLU</th><th>Chamadas</th><th>Custo estimado</th></tr></thead>
      <tbody>${(i.por_usuario || []).map(u => `<tr><td>${esc(u.user)}</td><td>${u.n_consultas}</td><td class="mono">${brl(u.custo_total)}</td></tr>`).join('') || '<tr><td colspan="3" class="msg">Sem registros.</td></tr>'}</tbody>
    </table>

    <div class="dica">
      <div class="dica-title">Por que os dois números não batem</div>
      <div class="dica-body">
        A coluna da <strong>Assertiva</strong> é a contagem oficial dela — a que vira fatura. A do <strong>CapiBLU</strong> conta só o que sai desta plataforma.
        A diferença de ${Math.abs(d.diferenca.chamadas)} consulta(s) (${brl(Math.abs(d.diferenca.custo))}) é consumo da conta Assertiva
        <strong>fora do CapiBLU</strong> — portal web, planilha, outra integração — mais o efeito do cache
        (quando repetimos um documento já consultado, não gastamos de novo e a Assertiva também não cobra).
        Se um nome aparece na tabela da Assertiva e não na do CapiBLU, essa pessoa está consultando por fora.
      </div>
    </div>`;
}

(function initAdmTotal() {
  const btn = document.getElementById('adm-total-atualizar');
  if (!btn) return;
  let diasAtual = 30;
  btn.addEventListener('click', () => admCustoTotal(diasAtual));
  document.querySelectorAll('.adm-per').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.adm-per').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    diasAtual = parseInt(b.dataset.dias) || 30;
    // Botão de período manda: limpa as datas manuais.
    document.getElementById('adm-total-desde').value = '';
    document.getElementById('adm-total-ate').value = '';
    admCustoTotal(diasAtual);
  }));
})();

// ── ADMIN · tabela de preço por tipo de consulta ────────────────────
// A Assertiva não devolve preço em lugar nenhum da API; só o contrato diz.
// Enquanto não preenchido, tudo é calculado pelo padrão (0,119) e o total do
// relatório é estimativa.
async function admPrecosCarregar() {
  const box = document.getElementById('adm-precos-form');
  if (!box) return;
  box.innerHTML = '<p class="msg">Carregando…</p>';
  try {
    const d = await fetch(`${API}/api/custos/precos`).then(r => r.json());
    if (d.status !== 'ok') {
      box.innerHTML = `<p class="msg error">${esc(d.detail || d.message || 'Falha ao carregar.')}</p>`;
      return;
    }
    const definidos = new Set(d.definidos || []);
    box.innerHTML = `<div class="prosp-build-row">` + (d.funcionalidades || []).map(f => `
      <label>${esc(f)}
        <input type="number" step="0.001" min="0" class="filter-num adm-preco"
               data-f="${esc(f)}" value="${d.precos[f] != null ? d.precos[f] : ''}"
               placeholder="${d.padrao}" title="${definidos.has(f) ? 'preço definido por você' : 'usando o padrão'}" />
        ${definidos.has(f) ? '' : `<span class="pf-advanced-hint" style="display:inline">padrão</span>`}
      </label>`).join('') + `</div>`;
  } catch (e) {
    box.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  }
}

async function admPrecosSalvar() {
  const status = document.getElementById('adm-precos-status');
  const precos = {};
  document.querySelectorAll('.adm-preco').forEach(i => { precos[i.dataset.f] = i.value; });
  status.textContent = 'Salvando…';
  try {
    const r = await fetch(`${API}/api/custos/precos`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ precos }),
    }).then(x => x.json());
    if (r.status !== 'ok') { status.textContent = '⚠️ ' + (r.detail || r.message || 'falhou'); return; }
    status.textContent = '✅ salvo — o relatório acima já usa esses valores';
    admPrecosCarregar();
    admCustoTotal(30);
  } catch (e) {
    status.textContent = '⚠️ ' + e.message;
  }
}

document.getElementById('adm-precos-salvar')?.addEventListener('click', admPrecosSalvar);

// ══════════════════════════════════════════════════════
//  ADMIN · Tokens de API
//  Só admin chega aqui: a aba fica escondida pra quem não é, e as rotas
//  /api/admin/tokens recusam sessão sem role admin.
// ══════════════════════════════════════════════════════
async function admTokensCarregar() {
  const lista = document.getElementById('tok-lista');
  if (!lista) return;
  lista.innerHTML = '<p class="msg">Carregando…</p>';
  try {
    const d = await fetch(`${API}/api/admin/tokens`).then(r => r.json());
    if (d.status !== 'ok') {
      lista.innerHTML = `<p class="msg error">${esc(d.detail || d.message || 'Falha ao carregar tokens.')}</p>`;
      return;
    }
    // dono do token: preenche o select uma vez
    const sel = document.getElementById('tok-user');
    if (sel && !sel.options.length) {
      sel.innerHTML = (d.usuarios || []).map(u =>
        `<option value="${u.id}">${esc(u.email)}${u.role === 'admin' ? ' (admin)' : ''}</option>`).join('');
    }
    const emailPorId = {};
    (d.usuarios || []).forEach(u => { emailPorId[u.id] = u.email; });

    const tokens = d.tokens || [];
    if (!tokens.length) {
      lista.innerHTML = `<p class="msg">Nenhum token criado ainda. Use o formulário acima para gerar o primeiro.</p>`;
      return;
    }
    lista.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>Nome</th><th>Token</th><th>Dono</th><th>Escopo</th>
          <th>Criado</th><th>Último uso</th><th>Chamadas</th><th></th>
        </tr></thead>
        <tbody>${tokens.map(t => `
          <tr${t.ativo ? '' : ' style="opacity:.45"'}>
            <td>${esc(t.nome)}${t.ativo ? '' : ' <span class="badge badge-inativa">revogado</span>'}</td>
            <td class="mono" style="font-size:.78rem">${esc(t.token)}</td>
            <td>${esc(emailPorId[t.user_id] || ('usuário ' + t.user_id))}</td>
            <td>${t.escopo === 'consulta'
              ? '<span class="badge badge-amber">consulta — gasta</span>'
              : '<span class="badge badge-neutra">leitura</span>'}</td>
            <td>${esc(tokData(t.criado_em))}</td>
            <td>${esc(tokData(t.ultimo_uso) || 'nunca usado')}</td>
            <td>${t.chamadas || 0}</td>
            <td>${t.ativo ? `<button class="btn-secondary tok-revogar" data-id="${t.id}" data-nome="${esc(t.nome)}">Revogar</button>` : ''}</td>
          </tr>`).join('')}</tbody>
      </table>`;

    lista.querySelectorAll('.tok-revogar').forEach(b => b.addEventListener('click', async () => {
      if (!confirm(`Revogar o token "${b.dataset.nome}"? Quem estiver usando perde o acesso na hora.`)) return;
      b.disabled = true;
      const r = await fetch(`${API}/api/admin/tokens/${b.dataset.id}`, { method: 'DELETE' }).then(x => x.json());
      if (r.status !== 'ok') { alert(r.detail || 'Falha ao revogar.'); b.disabled = false; return; }
      admTokensCarregar();
    }));
  } catch (e) {
    lista.innerHTML = `<p class="msg error">Erro: ${esc(e.message)}</p>`;
  }
}

function tokData(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

async function admTokenCriar() {
  const btn = document.getElementById('tok-criar');
  const caixa = document.getElementById('tok-novo');
  const nome = document.getElementById('tok-nome').value.trim();
  const escopo = document.getElementById('tok-escopo').value;
  const userId = document.getElementById('tok-user').value;
  if (!nome) { alert('Dê um nome ao token — é o que permite revogar o certo depois.'); return; }

  btn.disabled = true;
  try {
    const r = await fetch(`${API}/api/admin/tokens`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome, escopo, user_id: userId ? parseInt(userId) : undefined }),
    }).then(x => x.json());
    if (r.status !== 'ok') { alert(r.detail || 'Falha ao criar token.'); return; }

    const t = r.token.token;
    caixa.hidden = false;
    // O token só existe em claro AGORA — o servidor guarda apenas o hash.
    caixa.innerHTML = `
      <div class="dica" style="border-color:var(--terracota)">
        <div class="dica-title">🔑 Token criado — copie agora</div>
        <div class="dica-body">
          <div class="mono" id="tok-valor" style="background:var(--gray-100);padding:10px 12px;word-break:break-all;font-size:.85rem;border:1px solid var(--gray-200)">${esc(t)}</div>
          <div class="filter-row">
            <button class="btn-primary" id="tok-copiar">📋 Copiar token</button>
            <button class="btn-secondary" id="tok-fechar">Já guardei, fechar</button>
          </div>
          <strong>Esta é a única vez que ele aparece.</strong> O CapiBLU guarda só o hash — se perder, revogue e gere outro.
          Use no header: <code>Authorization: Bearer ${esc(t.slice(0, 18))}…</code>
          ${escopo === 'consulta'
            ? '<br>⚠️ Escopo <strong>consulta</strong>: este token pode gastar consulta paga, respeitando o limite diário de ' + esc(document.getElementById('tok-user').selectedOptions[0]?.textContent || 'quem é dono') + '.'
            : '<br>Escopo <strong>leitura</strong>: só base local, não gera custo.'}
        </div>
      </div>`;
    document.getElementById('tok-copiar').addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(t);
        document.getElementById('tok-copiar').textContent = '✅ Copiado';
      } catch (e) {
        // Sem permissão de clipboard: seleciona pra copiar na mão.
        const el = document.getElementById('tok-valor');
        const sel = window.getSelection(); const range = document.createRange();
        range.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(range);
        document.getElementById('tok-copiar').textContent = 'Selecionado — use Ctrl+C';
      }
    });
    document.getElementById('tok-fechar').addEventListener('click', () => {
      caixa.hidden = true; caixa.innerHTML = '';
    });
    document.getElementById('tok-nome').value = '';
    admTokensCarregar();
  } catch (e) {
    alert('Erro ao criar token: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('tok-criar')?.addEventListener('click', admTokenCriar);
