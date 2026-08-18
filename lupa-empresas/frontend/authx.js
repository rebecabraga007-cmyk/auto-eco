// ══════════════════════════════════════════════════════
//  CapiBLU — autenticação (login gate + admin de usuários)
//  Carregado ANTES do capiblu.js: instala o wrapper de fetch
//  que injeta o JWT em toda chamada /api.
// ══════════════════════════════════════════════════════
(function () {
  // Sessão via COOKIE httpOnly (servidor). localStorage é só best-effort/fallback —
  // o app NÃO depende dele (navegadores com storage bloqueado funcionam mesmo assim).
  const TOKEN_KEY = 'capiblu_token';
  const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } };
  const setToken = t => { try { localStorage.setItem(TOKEN_KEY, t); } catch (e) {} };
  const clearToken = () => { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} };
  window.capibluLogout = () => {
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => {}).finally(() => { clearToken(); location.reload(); });
  };

  // Wrapper de fetch: garante cookies (same-origin já manda) e injeta Bearer se houver.
  const _fetch = window.fetch.bind(window);
  window.fetch = function (input, init = {}) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const isApi = url.includes('/api/');
    init = { ...init };
    if (isApi) {
      init.credentials = init.credentials || 'same-origin';
      const tok = getToken();
      if (tok && !url.includes('/api/auth/login')) {
        const h = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined) || {});
        if (!h.has('Authorization')) h.set('Authorization', 'Bearer ' + tok);
        init.headers = h;
      }
    }
    // NÃO recarregar em 401 de chamadas de dados: causava piscada/loop na tela de
    // login (401 corria contra o /me). A sessão é decidida só pelo /me no init().
    return _fetch(input, init);
  };

  let currentUser = null;

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    wireLogin();
    wireMenu();
    wireUsersModal();
    wirePassModal();
    wireConfigModal();
    // A sessão vem do cookie — basta perguntar quem sou eu (sem depender de token local).
    try {
      const r = await _fetch('/api/auth/me', { credentials: 'same-origin' });
      if (!r.ok) throw new Error();
      currentUser = (await r.json()).user;
      showApp();
    } catch (e) {
      showLogin();
    }
  }

  function showLogin() {
    document.getElementById('login-overlay').hidden = false;
    document.body.classList.add('locked');
  }
  function showApp() {
    document.getElementById('login-overlay').hidden = true;
    document.body.classList.remove('locked');
    document.getElementById('user-name').textContent = currentUser.nome || currentUser.email;
    const isAdmin = currentUser.role === 'admin';
    document.getElementById('menu-users').hidden = !isAdmin;
    const mc = document.getElementById('menu-config'); if (mc) mc.hidden = !isAdmin;
    const na = document.getElementById('nav-admin'); if (na) na.hidden = !isAdmin;
    const nal = document.getElementById('nav-admin-label'); if (nal) nal.hidden = !isAdmin;
    // Dossiê é só de admin: some do menu e os botões de PDF espalhados pelas
    // outras abas ficam escondidos por CSS (o backend também recusa, então
    // esconder aqui é conveniência, não a trava de verdade).
    const nd = document.querySelector('[data-tab="dossie"]'); if (nd) nd.hidden = !isAdmin;
    document.body.classList.toggle('sem-dossie', !isAdmin);
    if (!isAdmin && document.getElementById('tab-dossie')?.classList.contains('active')) {
      document.querySelector('[data-tab="inicio"]')?.click();
    }
    if (typeof inicioCarregar === 'function') inicioCarregar();
  }

  function wireLogin() {
    const form = document.getElementById('login-form');
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const err = document.getElementById('login-err');
      const btn = document.getElementById('login-btn');
      err.textContent = ''; btn.disabled = true;
      try {
        const r = await _fetch('/api/auth/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: document.getElementById('login-email').value.trim(),
            senha: document.getElementById('login-senha').value,
          }),
        });
        const j = await r.json();
        if (!r.ok) { err.textContent = j.detail || 'Falha no login.'; return; }
        setToken(j.token);
        location.reload();
      } catch (e2) { err.textContent = 'Erro de conexão.'; }
      finally { btn.disabled = false; }
    });
  }

  function wireMenu() {
    const menu = document.getElementById('user-menu');
    const dd = document.getElementById('user-dropdown');
    menu.addEventListener('click', e => {
      if (e.target.closest('.user-dropdown')) return;
      dd.hidden = !dd.hidden;
    });
    document.addEventListener('click', e => { if (!menu.contains(e.target)) dd.hidden = true; });
    document.getElementById('menu-logout').addEventListener('click', window.capibluLogout);
    document.getElementById('menu-password').addEventListener('click', () => {
      document.getElementById('pass-modal').hidden = false; dd.hidden = true;
    });
    document.getElementById('menu-users').addEventListener('click', () => {
      document.getElementById('users-modal').hidden = false; dd.hidden = true; loadUsers();
    });
    const mc = document.getElementById('menu-config');
    if (mc) mc.addEventListener('click', () => {
      document.getElementById('config-modal').hidden = false; dd.hidden = true; loadConfig();
    });
  }

  async function loadConfig() {
    const st = document.getElementById('cfg-meetime-status');
    st.textContent = 'carregando…';
    try {
      const [j, gruposRes] = await Promise.all([
        fetch('/api/config').then(r => r.json()),
        fetch('/api/admin/grupos').then(r => r.json()).catch(() => ({ grupos: [] })),
      ]);
      const m = j.meetime || {};
      const porGrupo = m.por_grupo || {};
      st.innerHTML = m.configurado ? `✅ configurado (${esc(m.token_mascarado || '')})` : '⚠️ ainda não configurado';
      document.getElementById('cfg-meetime-base').value = m.base_url || '';
      document.getElementById('cfg-meetime-path').value = m.leads_path || '';
      document.getElementById('cfg-meetime-hdr').value = m.auth_header || '';

      const box = document.getElementById('cfg-meetime-grupos');
      const grupos = gruposRes.grupos || [];
      box.innerHTML = grupos.length
        ? grupos.map(g => `
          <div class="user-create-row" data-grupo-id="${esc(g.id)}" style="margin-bottom:6px">
            <span style="min-width:120px;font-size:.85rem;font-weight:600">${esc(g.nome)}</span>
            <input type="text" class="cfg-grupo-token" placeholder="token deste grupo" autocomplete="off" />
            <span class="en-fname">${(porGrupo[g.id] || {}).configurado ? '✅ configurado' : '— sem token'}</span>
            <button type="button" class="btn-secondary cfg-grupo-salvar">Salvar</button>
          </div>`).join('')
        : '<p class="msg" style="padding:8px 0">Nenhum grupo criado ainda — crie em 👥 Usuários.</p>';
    } catch (e) { st.textContent = 'erro ao carregar (você é admin?)'; }
  }

  function wireConfigModal() {
    const modal = document.getElementById('config-modal');
    if (!modal) return;
    document.getElementById('config-close').addEventListener('click', () => modal.hidden = true);
    document.getElementById('config-form').addEventListener('submit', async e => {
      e.preventDefault();
      const err = document.getElementById('config-err'); err.textContent = '';
      const body = {
        token: document.getElementById('cfg-meetime-token').value.trim() || undefined,
        base_url: document.getElementById('cfg-meetime-base').value.trim() || undefined,
        leads_path: document.getElementById('cfg-meetime-path').value.trim() || undefined,
        auth_header: document.getElementById('cfg-meetime-hdr').value.trim() || undefined,
      };
      const r = await fetch('/api/config/meetime', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { err.textContent = j.detail || 'Falha ao salvar.'; return; }
      document.getElementById('cfg-meetime-token').value = '';
      alert('Configuração salva!'); loadConfig();
    });
    document.getElementById('cfg-meetime-grupos').addEventListener('click', async e => {
      const btn = e.target.closest('.cfg-grupo-salvar'); if (!btn) return;
      const row = btn.closest('[data-grupo-id]');
      const grupo_id = row.dataset.grupoId;
      const token = row.querySelector('.cfg-grupo-token').value.trim();
      btn.disabled = true;
      try {
        const r = await fetch('/api/config/meetime', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ grupo_id, token }),
        });
        if (!r.ok) { alert((await r.json()).detail || 'Falha ao salvar.'); return; }
        alert('Token do grupo salvo!'); loadConfig();
      } finally { btn.disabled = false; }
    });
  }

  // ---- Admin: usuários + grupos (cada grupo = 1 token/conta Meetime) ----
  let _gruposCache = [];

  async function loadGrupos() {
    try {
      const j = await fetch('/api/admin/grupos').then(r => r.json());
      _gruposCache = j.grupos || [];
    } catch (e) { _gruposCache = []; }
    const opts = g => `<option value="${esc(g.id)}">${esc(g.nome)}</option>`;
    const ucSel = document.getElementById('uc-grupo');
    if (ucSel) ucSel.innerHTML = '<option value="">Sem grupo</option>' + _gruposCache.map(opts).join('');
    const lista = document.getElementById('grupos-lista');
    if (lista) {
      lista.innerHTML = _gruposCache.length
        ? _gruposCache.map(g => `<span class="chip-ex" data-grupo-del="${esc(g.id)}" title="Clique pra excluir">${esc(g.nome)} ✕</span>`).join('')
        : '<span class="pf-advanced-hint">Nenhum grupo criado ainda.</span>';
    }
  }

  function nomeGrupo(gid) {
    const g = _gruposCache.find(x => x.id === gid);
    return g ? g.nome : '';
  }

  async function loadUsers() {
    const tb = document.querySelector('#users-table tbody');
    tb.innerHTML = '<tr><td colspan="6">Carregando…</td></tr>';
    await loadGrupos();
    try {
      const j = await fetch('/api/admin/users').then(r => r.json());
      const gruposOpts = ['<option value="">Sem grupo</option>'].concat(
        _gruposCache.map(g => `<option value="${esc(g.id)}">${esc(g.nome)}</option>`)).join('');
      tb.innerHTML = (j.users || []).map(u => `
        <tr data-id="${u.id}">
          <td>${esc(u.nome || '')}</td>
          <td class="mono">${esc(u.email)}</td>
          <td>${u.role === 'admin' ? '<b>admin</b>' : 'user'}</td>
          <td><select class="user-grupo-sel" data-cur="${esc(u.grupo_id || '')}">${gruposOpts}</select></td>
          <td>${u.ativo ? '🟢 ativo' : '⚪ inativo'}</td>
          <td>${u.role === 'admin' ? '<span class="pf-advanced-hint">—</span>' :
              `<input type="number" min="0" class="filter-num user-limite-input" style="width:64px"
                data-cur="${u.limite_diario_custom != null ? u.limite_diario_custom : ''}"
                title="Limite diário de consultas (vazio = padrão de ${esc(String(u.limite_diario))})"
                placeholder="${esc(String(u.limite_diario))}">`}</td>
          <td class="user-actions">
            <button data-act="toggle">${u.ativo ? 'Desativar' : 'Ativar'}</button>
            <button data-act="role">${u.role === 'admin' ? '→ user' : '→ admin'}</button>
            <button data-act="pass">Reset senha</button>
            <button data-act="del" class="danger">Excluir</button>
          </td>
        </tr>`).join('');
      tb.querySelectorAll('.user-grupo-sel').forEach(sel => { sel.value = sel.dataset.cur; });
      tb.querySelectorAll('.user-limite-input').forEach(inp => { inp.value = inp.dataset.cur; });
    } catch (e) { tb.innerHTML = '<tr><td colspan="7">Erro ao carregar.</td></tr>'; }
  }

  function wireUsersModal() {
    document.getElementById('users-close').addEventListener('click',
      () => document.getElementById('users-modal').hidden = true);
    document.getElementById('user-create').addEventListener('submit', async e => {
      e.preventDefault();
      const err = document.getElementById('uc-err'); err.textContent = '';
      const body = {
        nome: document.getElementById('uc-nome').value.trim(),
        email: document.getElementById('uc-email').value.trim(),
        senha: document.getElementById('uc-senha').value,
        role: document.getElementById('uc-role').value,
        grupo_id: document.getElementById('uc-grupo').value,
      };
      const r = await fetch('/api/admin/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { err.textContent = j.detail || 'Falha ao criar.'; return; }
      document.getElementById('user-create').reset();
      loadUsers();
    });
    document.getElementById('grupo-create').addEventListener('submit', async e => {
      e.preventDefault();
      const err = document.getElementById('gc-err'); err.textContent = '';
      const nome = document.getElementById('gc-nome').value.trim();
      const r = await fetch('/api/admin/grupos', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome }),
      });
      const j = await r.json();
      if (!r.ok) { err.textContent = j.detail || 'Falha ao criar grupo.'; return; }
      document.getElementById('grupo-create').reset();
      loadUsers();
    });
    document.getElementById('grupos-lista').addEventListener('click', async e => {
      const chip = e.target.closest('[data-grupo-del]'); if (!chip) return;
      const gid = chip.dataset.grupoDel;
      if (!confirm(`Excluir o grupo "${nomeGrupo(gid)}"? Usuários dele ficam sem grupo.`)) return;
      await fetch(`/api/admin/grupos/${gid}`, { method: 'DELETE' });
      loadUsers();
    });
    document.querySelector('#users-table tbody').addEventListener('click', async e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const tr = btn.closest('tr'); const id = tr.dataset.id; const act = btn.dataset.act;
      if (act === 'toggle') {
        const ativo = tr.children[4].textContent.includes('ativo') ? false : true;
        await fetch(`/api/admin/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ativo }) });
      } else if (act === 'role') {
        const role = btn.textContent.includes('admin') ? 'admin' : 'user';
        await fetch(`/api/admin/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) });
      } else if (act === 'pass') {
        const senha = prompt('Nova senha (mín. 8 caracteres):');
        if (!senha) return;
        const r = await fetch(`/api/admin/users/${id}/password`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ senha }) });
        if (!r.ok) alert((await r.json()).detail || 'Falha.'); else alert('Senha alterada.');
        return;
      } else if (act === 'del') {
        if (!confirm('Excluir este usuário?')) return;
        const r = await fetch(`/api/admin/users/${id}`, { method: 'DELETE' });
        if (!r.ok) { alert((await r.json()).detail || 'Falha.'); return; }
      }
      loadUsers();
    });
    document.querySelector('#users-table tbody').addEventListener('change', async e => {
      const sel = e.target.closest('.user-grupo-sel'); if (!sel) return;
      const id = sel.closest('tr').dataset.id;
      await fetch(`/api/admin/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ grupo_id: sel.value }) });
    });
    document.querySelector('#users-table tbody').addEventListener('blur', async e => {
      const inp = e.target.closest('.user-limite-input'); if (!inp) return;
      const id = inp.closest('tr').dataset.id;
      const v = inp.value.trim();
      if (v === (inp.dataset.cur || '')) return;
      const limite_diario = v === '' ? null : Math.max(0, parseInt(v, 10) || 0);
      const r = await fetch(`/api/admin/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limite_diario }) });
      if (!r.ok) { alert((await r.json()).detail || 'Falha ao salvar limite.'); loadUsers(); return; }
      inp.dataset.cur = v === '' ? '' : String(limite_diario);
    }, true);
  }

  function wirePassModal() {
    const modal = document.getElementById('pass-modal');
    document.getElementById('pass-close').addEventListener('click', () => modal.hidden = true);
    document.getElementById('pass-form').addEventListener('submit', async e => {
      e.preventDefault();
      const err = document.getElementById('pass-err'); err.textContent = '';
      const r = await fetch('/api/auth/change-password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          senha_atual: document.getElementById('pf-atual').value,
          nova_senha: document.getElementById('pf-nova').value,
        }),
      });
      const j = await r.json();
      if (!r.ok) { err.textContent = j.detail || 'Falha.'; return; }
      alert('Senha alterada com sucesso.'); modal.hidden = true;
      document.getElementById('pass-form').reset();
    });
  }

  // esc() pode ainda não existir (capiblu.js carrega depois) — fallback local.
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
})();
