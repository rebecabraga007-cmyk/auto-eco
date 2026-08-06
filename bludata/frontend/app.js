/* bludata frontend — B2B Prospecting Platform */

const API_BASE = "http://localhost:8001";

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  personsPage: 1,
  personsTotal: 0,
  personsCacheKey: null,
  personsData: [],
  selectedPersons: new Set(),

  companiesPage: 1,
  companiesTotal: 0,
  companiesCacheKey: null,

  currentJobId: null,
  jobPollInterval: null,
};

// ── Navigation ────────────────────────────────────────────────────────────────

function showPage(page) {
  document.querySelectorAll("[id^='page-']").forEach(el => el.style.display = "none");
  document.querySelectorAll(".sidebar-nav a").forEach(el => el.classList.remove("active"));

  document.getElementById(`page-${page}`).style.display = "block";
  const nav = document.getElementById(`nav-${page}`);
  if (nav) nav.classList.add("active");
}

// ── Persons Search ────────────────────────────────────────────────────────────

async function searchPersons(page = 1) {
  // If new search (page 1), clear cache key
  if (page === 1) state.personsCacheKey = null;

  const body = {
    page,
    per_page: 20,
    cache_key: state.personsCacheKey,
    person_filters: {
      name: textToArray("pf-name"),
      surname: textToArray("pf-surname"),
      roles: textToArray("pf-role"),
      departments: selectToArray("pf-department"),
      seniority_levels: selectToArray("pf-seniority"),
      skills: [],
      locations: [],
      states: selectToArray("pf-state"),
      has_email: boolSelect("pf-has-email"),
      has_phone: boolSelect("pf-has-phone"),
      has_linkedin: boolSelect("pf-has-linkedin"),
      contact_lists: [],
      list_exclusion_filter: false,
    },
    company_filters: {
      company_name: textToArray("pf-company-name"),
      states: selectToArray("pf-company-state"),
      locations: [], sectors: [], cnae_activities: [],
      company_sizes: [], legal_natures: [],
    },
  };

  showLoading("persons-loading");
  document.getElementById("persons-results-card").style.display = "none";
  document.getElementById("persons-empty").style.display = "none";

  try {
    const resp = await fetch(`${API_BASE}/v1/b2b/persons/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();

    if (!data.sucesso) {
      alert("Erro na busca: " + (data.detail || JSON.stringify(data)));
      return;
    }

    state.personsCacheKey = data.chave_cache;
    state.personsPage = page;
    state.personsTotal = data.total;
    state.personsData = data.dados;

    renderPersonsTable(data.dados, data.total, page, data.credits_used);
  } catch (err) {
    alert("Erro de conexão: " + err.message + "\n\nVerifique se o backend está rodando em http://localhost:8001");
  } finally {
    hideLoading("persons-loading");
  }
}

function renderPersonsTable(dados, total, page, creditsUsed) {
  const tbody = document.getElementById("persons-tbody");
  tbody.innerHTML = "";

  if (!dados.length) {
    document.getElementById("persons-empty").style.display = "block";
    return;
  }

  document.getElementById("persons-results-card").style.display = "block";
  document.getElementById("persons-count").textContent = `${total} resultado${total !== 1 ? "s" : ""}`;

  dados.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="person-check" value="${p.person_id}" /></td>
      <td><strong>${esc(p.name)}</strong></td>
      <td>${esc(p.role || "—")}</td>
      <td>${esc(p.company_name || "—")}</td>
      <td>${p.state ? `<span class="chip chip-gray">${p.state}</span>` : "—"}</td>
      <td>${badge(p.has_email)}</td>
      <td>${badge(p.has_phone)}</td>
      <td>${p.has_linkedin ? `<a href="${p.linkedin_url || "#"}" target="_blank" title="LinkedIn">🔗</a>` : badge(false)}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="openPersonModal(${JSON.stringify(p).replace(/"/g, "&quot;")})">Ver</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  renderPagination("persons-pagination", page, Math.ceil(total / 20), (p) => searchPersons(p));

  if (creditsUsed > 0) {
    showToast(`1 crédito consumido. Cache key gerada — páginas seguintes são gratuitas.`, "info");
  }
}

// ── Companies Search ──────────────────────────────────────────────────────────

async function searchCompanies(page = 1) {
  if (page === 1) state.companiesCacheKey = null;

  const body = {
    page,
    per_page: 20,
    cache_key: state.companiesCacheKey,
    company_name: textToArray("cf-name"),
    sectors: selectToArray("cf-sector"),
    states: selectToArray("cf-state"),
    company_sizes: selectToArray("cf-size"),
    legal_natures: textToArray("cf-legal-nature"),
    cnae_activities: textToArray("cf-cnae"),
    include_mei: boolSelect("cf-mei"),
    locations: [],
    foundation_date: null,
    revenue_range: null,
    has_cnpj: null,
  };

  showLoading("companies-loading");
  document.getElementById("companies-results-card").style.display = "none";

  try {
    const resp = await fetch(`${API_BASE}/v1/b2b/companies/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();

    if (!data.sucesso) {
      alert("Erro na busca: " + (data.detail || JSON.stringify(data)));
      return;
    }

    state.companiesCacheKey = data.chave_cache;
    state.companiesPage = page;
    state.companiesTotal = data.total;

    renderCompaniesTable(data.dados, data.total, page);
  } catch (err) {
    alert("Erro de conexão: " + err.message);
  } finally {
    hideLoading("companies-loading");
  }
}

function renderCompaniesTable(dados, total, page) {
  const tbody = document.getElementById("companies-tbody");
  tbody.innerHTML = "";

  if (!dados.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text-muted)">Nenhuma empresa encontrada.</td></tr>`;
    document.getElementById("companies-results-card").style.display = "block";
    return;
  }

  document.getElementById("companies-results-card").style.display = "block";
  document.getElementById("companies-count").textContent = `${total} empresa${total !== 1 ? "s" : ""}`;

  dados.forEach((c, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${(page - 1) * 20 + i + 1}</td>
      <td>
        <strong>${esc(c.trade_name || c.name)}</strong>
        ${c.trade_name ? `<br><small style="color:var(--text-muted)">${esc(c.name)}</small>` : ""}
      </td>
      <td><code style="font-size:11px">${formatCNPJ(c.cnpj) || "—"}</code></td>
      <td>${esc(c.sector || "—")}</td>
      <td>${c.state ? `<span class="chip chip-gray">${c.state}</span>` : "—"}</td>
      <td>${esc(c.employee_range || "—")}</td>
      <td>${c.founded_at ? c.founded_at.split("T")[0] : "—"}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="openCompanyModal(${JSON.stringify(c).replace(/"/g, "&quot;")})">Ver</button>
        <button class="btn btn-secondary btn-sm" onclick="lookupCNPJDirect('${c.cnpj}')">CNPJ</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  renderPagination("companies-pagination", page, Math.ceil(total / 20), (p) => searchCompanies(p));
}

// ── Person Modal ──────────────────────────────────────────────────────────────

function openPersonModal(person) {
  document.getElementById("modal-person-name").textContent = person.name;

  const grid = document.getElementById("person-detail-grid");
  grid.innerHTML = detailItem("Cargo", person.role) +
    detailItem("Empresa", person.company_name) +
    detailItem("Departamento", person.department) +
    detailItem("Senioridade", person.seniority) +
    detailItem("Localização", person.location) +
    detailItem("Estado", person.state) +
    detailItem("Tem Email", person.has_email ? "✅ Sim" : "❌ Não") +
    detailItem("Tem Telefone", person.has_phone ? "✅ Sim" : "❌ Não") +
    detailItem("LinkedIn", person.linkedin_url ? `<a href="${esc(person.linkedin_url)}" target="_blank">Ver perfil 🔗</a>` : "Não") +
    detailItem("Fonte", person.source) +
    detailItem("Cadastrado em", person.created_at ? person.created_at.split("T")[0] : "—");

  // Reset contacts tab
  document.getElementById("person-contacts-section").innerHTML = `<div class="loading"><div class="spinner"></div> Carregando contatos...</div>`;

  // Pre-load contacts
  loadPersonContacts(person.person_id);

  openModal("person-modal");
}

async function loadPersonContacts(personId) {
  try {
    const resp = await fetch(`${API_BASE}/v1/person/contact/info/?person_id=${personId}`);
    const data = await resp.json();

    const section = document.getElementById("person-contacts-section");
    let html = "";

    html += renderContactGroup("📧 E-mails", data.emails);
    html += renderContactGroup("📱 Celulares", data.mobile_phones);
    html += renderContactGroup("📞 Fixos", data.landlines);
    html += renderContactGroup("🏢 Fixos Corporativos", data.corporate_landlines);

    section.innerHTML = html || "<p style='color:var(--text-muted)'>Nenhum contato cadastrado.</p>";
  } catch (err) {
    document.getElementById("person-contacts-section").innerHTML =
      `<p style="color:var(--danger)">Erro ao carregar contatos: ${err.message}</p>`;
  }
}

function renderContactGroup(title, items) {
  if (!items || !items.length) return "";
  let html = `<div class="contact-section"><h4>${title}</h4>`;
  for (const c of items) {
    const statusClass = c.source === "placeholder" ? "status-placeholder" :
      (c.status === "valid" ? "status-valid" : c.status === "invalid" ? "status-invalid" : "status-unknown");
    html += `
      <div class="contact-item">
        <div class="contact-type-icon">${title[0]}</div>
        <span class="contact-value">${esc(c.value)}</span>
        <span class="contact-status ${statusClass}">${c.status || "desconhecido"}</span>
        ${c.whatsapp === true ? '<span class="chip chip-green" style="font-size:10px">WhatsApp ✓</span>' : ""}
      </div>`;
  }
  html += "</div>";
  return html;
}

// ── Company Modal ─────────────────────────────────────────────────────────────

function openCompanyModal(company) {
  document.getElementById("modal-company-name").textContent = company.trade_name || company.name;

  const grid = document.getElementById("company-detail-grid");
  grid.innerHTML =
    detailItem("Razão Social", company.name) +
    detailItem("CNPJ", formatCNPJ(company.cnpj)) +
    detailItem("Setor", company.sector) +
    detailItem("CNAE", company.cnae_code ? `${company.cnae_code} — ${company.cnae_desc || ""}` : null) +
    detailItem("Localização", company.location) +
    detailItem("Estado", company.state) +
    detailItem("CEP", company.zip_code) +
    detailItem("Porte", company.employee_range) +
    detailItem("Faturamento", company.revenue_range) +
    detailItem("Fundação", company.founded_at) +
    detailItem("Natureza Jurídica", company.legal_nature) +
    detailItem("Simples Nacional", company.simples_nacional === true ? "Sim" : company.simples_nacional === false ? "Não" : "—") +
    detailItem("MEI", company.mei === true ? "Sim" : company.mei === false ? "Não" : "—") +
    detailItem("Telefone", company.phone) +
    detailItem("Email", company.email) +
    detailItem("Website", company.website ? `<a href="${esc(company.website)}" target="_blank">${esc(company.website)}</a>` : null);

  const partnersSection = document.getElementById("company-partners-section");
  if (company.partners && company.partners.length) {
    let ph = `<h4 style="font-weight:700;margin-bottom:10px">Quadro Societário (QSA)</h4>`;
    company.partners.forEach(p => {
      ph += `<div class="contact-item">
        <div class="contact-type-icon">👤</div>
        <div>
          <div class="contact-value">${esc(p.name || "")}</div>
          <div style="font-size:11px;color:var(--text-muted)">${esc(p.role || "")} ${p.cpf_cnpj ? "— " + p.cpf_cnpj : ""}</div>
        </div>
      </div>`;
    });
    partnersSection.innerHTML = ph;
  } else {
    partnersSection.innerHTML = "";
  }

  openModal("company-modal");
}

// ── CNPJ Lookup ───────────────────────────────────────────────────────────────

async function lookupCNPJ() {
  const cnpj = document.getElementById("cnpj-input").value;
  const resultDiv = document.getElementById("cnpj-result");
  resultDiv.innerHTML = `<div class="loading"><div class="spinner"></div> Consultando...</div>`;

  try {
    const cnpjClean = cnpj.replace(/\D/g, "");
    const resp = await fetch(`${API_BASE}/v1/company/info/?cnpj=${cnpjClean}`);
    const data = await resp.json();

    if (!data.sucesso) {
      resultDiv.innerHTML = `<div class="alert alert-warning">⚠️ ${data.error || "CNPJ não encontrado."}</div>`;
      return;
    }

    const c = data.data;
    resultDiv.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h3>${esc(c.trade_name || c.name)}</h3>
          <span class="chip chip-green">✓ Encontrado via ${esc(data.source)}</span>
        </div>
        <div class="card-body">
          <div class="detail-grid">
            ${detailItem("Razão Social", c.name)}
            ${detailItem("CNPJ", formatCNPJ(c.cnpj))}
            ${detailItem("Setor / CNAE", c.cnae_desc)}
            ${detailItem("Localização", c.location)}
            ${detailItem("Fundação", c.founded_at)}
            ${detailItem("Natureza Jurídica", c.legal_nature)}
            ${detailItem("Telefone", c.phone)}
            ${detailItem("Email", c.email)}
          </div>
          ${c.partners && c.partners.length ? `
            <h4 style="margin-top:16px;font-weight:700">Quadro Societário</h4>
            ${c.partners.map(p => `<div class="contact-item"><div class="contact-type-icon">👤</div><div><div>${esc(p.name)}</div><div style="font-size:11px;color:var(--text-muted)">${esc(p.role || "")}</div></div></div>`).join("")}
          ` : ""}
        </div>
      </div>`;
  } catch (err) {
    resultDiv.innerHTML = `<div class="alert alert-warning">Erro: ${err.message}</div>`;
  }
}

async function lookupCNPJDirect(cnpj) {
  if (!cnpj) return;
  showPage("cnpj-lookup");
  document.getElementById("cnpj-input").value = formatCNPJ(cnpj) || cnpj;
  await lookupCNPJ();
}

async function lookupCPF() {
  const cpf = document.getElementById("cpf-input").value.replace(/\D/g, "");
  const resultDiv = document.getElementById("cpf-result");
  resultDiv.innerHTML = `<div class="loading"><div class="spinner"></div> Consultando...</div>`;

  try {
    const resp = await fetch(`${API_BASE}/v1/person/info/?cpf=${cpf}`);
    const data = await resp.json();

    if (!data.sucesso) {
      // Show Receita Federal scraper response (which explains CAPTCHA limitation)
      resultDiv.innerHTML = `<div class="alert alert-warning">
        <strong>Consulta CPF bloqueada:</strong><br>
        A Receita Federal exige CAPTCHA para consulta de CPF. Para uso em produção, integre um serviço anti-CAPTCHA.
      </div>`;
      return;
    }

    const p = data.data;
    resultDiv.innerHTML = `<div class="card"><div class="card-body"><div class="detail-grid">
      ${detailItem("Nome", p.name)}
      ${detailItem("Cargo", p.role)}
      ${detailItem("Empresa", p.company_name)}
      ${detailItem("Localização", p.location)}
    </div></div></div>`;
  } catch (err) {
    resultDiv.innerHTML = `<div class="alert alert-warning">Erro: ${err.message}</div>`;
  }
}

// ── Enrich ────────────────────────────────────────────────────────────────────

function openEnrichModal() {
  const selected = [...document.querySelectorAll(".person-check:checked")].map(el => ({
    id_pessoa: el.value,
  }));
  document.getElementById("enrich-modal-count").textContent = `${selected.length} pessoa(s) selecionada(s)`;
  openModal("enrich-modal");
}

async function submitEnrichFromModal() {
  const selected = [...document.querySelectorAll(".person-check:checked")].map(el => ({
    id_pessoa: el.value,
  }));
  const webhook = document.getElementById("enrich-modal-webhook").value;
  closeModal("enrich-modal");
  showPage("enrich");

  document.getElementById("enrich-payload").value = JSON.stringify(selected, null, 2);
  document.getElementById("enrich-webhook").value = webhook;
  await startEnrich();
}

async function startEnrich() {
  let pessoas;
  try {
    pessoas = JSON.parse(document.getElementById("enrich-payload").value || "[]");
  } catch {
    alert("JSON inválido no payload.");
    return;
  }

  const webhook = document.getElementById("enrich-webhook").value;

  try {
    const resp = await fetch(`${API_BASE}/v1/b2b/persons/enrich/bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pessoas, url_webhook: webhook || null }),
    });
    const data = await resp.json();

    state.currentJobId = data.job_id;
    document.getElementById("enrich-job-card").style.display = "block";
    renderJobStatus(data);

    // Auto-poll every 3 seconds
    if (state.jobPollInterval) clearInterval(state.jobPollInterval);
    state.jobPollInterval = setInterval(pollJobStatus, 3000);
  } catch (err) {
    alert("Erro: " + err.message);
  }
}

async function pollJobStatus() {
  if (!state.currentJobId) return;

  try {
    const resp = await fetch(`${API_BASE}/v1/b2b/waterfall/job/?validationJobId=${state.currentJobId}`);
    const data = await resp.json();
    renderJobStatus(data);

    if (data.status === "completed" || data.status === "failed") {
      clearInterval(state.jobPollInterval);
    }
  } catch (err) {
    console.error("Poll error:", err);
  }
}

function renderJobStatus(job) {
  const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;
  const statusChip = job.status === "completed" ? "chip-green" :
    job.status === "failed" ? "chip-orange" : "chip-blue";

  document.getElementById("enrich-job-body").innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;gap:12px;align-items:center">
        <span class="chip ${statusChip}">${job.status}</span>
        <span style="color:var(--text-muted);font-size:13px">Job: <code>${job.job_id}</code></span>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;margin-bottom:6px">
          <span style="font-size:13px">Progresso</span>
          <span style="font-size:13px;font-weight:600">${job.processed || 0} / ${job.total || 0}</span>
        </div>
        <div style="background:var(--border);border-radius:4px;height:8px;overflow:hidden">
          <div style="background:var(--primary);height:100%;width:${pct}%;transition:width .3s"></div>
        </div>
      </div>
      ${job.created_at ? `<div style="font-size:12px;color:var(--text-muted)">Iniciado: ${job.created_at.replace("T", " ").split(".")[0]}</div>` : ""}
      ${job.completed_at ? `<div style="font-size:12px;color:var(--text-muted)">Concluído: ${job.completed_at.replace("T", " ").split(".")[0]}</div>` : ""}
      ${job.result ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-size:13px;font-weight:600">Ver resultado completo</summary>
          <pre style="background:var(--bg);padding:12px;border-radius:var(--radius);font-size:11px;overflow:auto;margin-top:8px;max-height:300px">${esc(JSON.stringify(job.result, null, 2))}</pre>
        </details>` : ""}
    </div>`;
}

// ── Pagination ────────────────────────────────────────────────────────────────

function renderPagination(containerId, currentPage, totalPages, onPageClick) {
  const container = document.getElementById(containerId);
  if (!container) return;

  let html = `<button class="page-btn" onclick="(${onPageClick})(${currentPage - 1})" ${currentPage === 1 ? "disabled" : ""}>← Anterior</button>`;

  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, currentPage + 2);

  if (start > 1) html += `<button class="page-btn" onclick="(${onPageClick})(1)">1</button>${start > 2 ? "<span>…</span>" : ""}`;

  for (let i = start; i <= end; i++) {
    html += `<button class="page-btn ${i === currentPage ? "active" : ""}" onclick="(${onPageClick})(${i})">${i}</button>`;
  }

  if (end < totalPages) html += `${end < totalPages - 1 ? "<span>…</span>" : ""}<button class="page-btn" onclick="(${onPageClick})(${totalPages})">${totalPages}</button>`;

  html += `<button class="page-btn" onclick="(${onPageClick})(${currentPage + 1})" ${currentPage >= totalPages ? "disabled" : ""}>Próxima →</button>`;
  html += `<span class="page-info">Página ${currentPage} de ${totalPages}</span>`;

  container.innerHTML = html;
}

// ── Selection ────────────────────────────────────────────────────────────────

function toggleSelectAll(entity) {
  const all = document.getElementById(`select-all-${entity}`).checked;
  document.querySelectorAll(`.${entity.slice(0, -1)}-check`).forEach(cb => { cb.checked = all; });
}

// ── Modal helpers ─────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.add("open");
  document.body.style.overflow = "hidden";
}

function closeModal(id) {
  document.getElementById(id).classList.remove("open");
  document.body.style.overflow = "";
}

function switchModalTab(btn, tabId) {
  btn.closest(".modal-body").querySelectorAll("[id^='tab-']").forEach(t => t.style.display = "none");
  btn.closest(".modal-tabs").querySelectorAll(".modal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(tabId).style.display = "block";
  btn.classList.add("active");
}

// Close modal on overlay click
document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", e => {
    if (e.target === overlay) closeModal(overlay.id);
  });
});

// ── Utilities ─────────────────────────────────────────────────────────────────

function esc(str) {
  if (str == null) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function badge(val) {
  return val
    ? `<span class="has-badge badge-yes" title="Sim">✓</span>`
    : `<span class="has-badge badge-no" title="Não">—</span>`;
}

function detailItem(label, value) {
  const v = value == null || value === "" ? "—" : value;
  return `<div class="detail-item"><span class="label">${esc(label)}</span><span class="value">${v}</span></div>`;
}

function textToArray(id) {
  const val = document.getElementById(id)?.value?.trim();
  return val ? [val] : [];
}

function selectToArray(id) {
  const val = document.getElementById(id)?.value;
  return val ? [val] : [];
}

function boolSelect(id) {
  const val = document.getElementById(id)?.value;
  if (val === "true") return true;
  if (val === "false") return false;
  return null;
}

function formatCNPJ(cnpj) {
  if (!cnpj) return null;
  const d = cnpj.replace(/\D/g, "");
  if (d.length !== 14) return cnpj;
  return `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12)}`;
}

function maskCNPJ(input) {
  let v = input.value.replace(/\D/g, "").slice(0, 14);
  if (v.length > 12) v = v.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{0,2})$/, "$1.$2.$3/$4-$5");
  else if (v.length > 8) v = v.replace(/^(\d{2})(\d{3})(\d{3})(\d{0,4})$/, "$1.$2.$3/$4");
  else if (v.length > 5) v = v.replace(/^(\d{2})(\d{3})(\d{0,3})$/, "$1.$2.$3");
  else if (v.length > 2) v = v.replace(/^(\d{2})(\d{0,3})$/, "$1.$2");
  input.value = v;
}

function maskCPF(input) {
  let v = input.value.replace(/\D/g, "").slice(0, 11);
  if (v.length > 9) v = v.replace(/^(\d{3})(\d{3})(\d{3})(\d{0,2})$/, "$1.$2.$3-$4");
  else if (v.length > 6) v = v.replace(/^(\d{3})(\d{3})(\d{0,3})$/, "$1.$2.$3");
  else if (v.length > 3) v = v.replace(/^(\d{3})(\d{0,3})$/, "$1.$2");
  input.value = v;
}

function clearPersonFilters() {
  ["pf-name", "pf-surname", "pf-role", "pf-company-name"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  ["pf-department", "pf-seniority", "pf-state", "pf-company-state",
   "pf-has-email", "pf-has-phone", "pf-has-linkedin"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

function clearCompanyFilters() {
  ["cf-name", "cf-legal-nature", "cf-cnae"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  ["cf-sector", "cf-state", "cf-size", "cf-mei"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

function showLoading(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "flex";
}

function hideLoading(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function showToast(msg, type = "info") {
  const toast = document.createElement("div");
  toast.className = `alert alert-${type}`;
  toast.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:9999;max-width:400px;box-shadow:var(--shadow-md)";
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Trigger initial persons search with no filters to show sample data
  searchPersons(1);
});
