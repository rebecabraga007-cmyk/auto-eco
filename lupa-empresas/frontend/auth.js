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
    return _fetch(input, init).then(resp => {
      if (resp.status === 401 && isApi && !url.includes('/api/auth/')) {
        // Sessão perdida numa chamada autenticada → só volta pro login se o app
        // estava VISÍVEL (evita loop na própria tela de login).
        const ov = document.getElementById('login-overlay');
        if (ov && ov.hidden) { clearToken(); location.reload(); }
      }
      return resp;
    });
  };

  let currentUser = null;

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    wireLogin();
    wireMenu();
    wireUsersModal();
    wirePassModal();
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
    document.getElementById('menu-users').hidden = currentUser.role !== 'admin';
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
  }

  // ---- Admin: usuários ----
  async function loadUsers() {
    const tb = document.querySelector('#users-table tbody');
    tb.innerHTML = '<tr><td colspan="5">Carregando…</td></tr>';
    try {
      const j = await fetch('/api/admin/users').then(r => r.json());
      tb.innerHTML = (j.users || []).map(u => `
        <tr data-id="${u.id}">
          <td>${esc(u.nome || '')}</td>
          <td class="mono">${esc(u.email)}</td>
          <td>${u.role === 'admin' ? '<b>admin</b>' : 'user'}</td>
          <td>${u.ativo ? '🟢 ativo' : '⚪ inativo'}</td>
          <td class="user-actions">
            <button data-act="toggle">${u.ativo ? 'Desativar' : 'Ativar'}</button>
            <button data-act="role">${u.role === 'admin' ? '→ user' : '→ admin'}</button>
            <button data-act="pass">Reset senha</button>
            <button data-act="del" class="danger">Excluir</button>
          </td>
        </tr>`).join('');
    } catch (e) { tb.innerHTML = '<tr><td colspan="5">Erro ao carregar.</td></tr>'; }
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
      };
      const r = await fetch('/api/admin/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { err.textContent = j.detail || 'Falha ao criar.'; return; }
      document.getElementById('user-create').reset();
      loadUsers();
    });
    document.querySelector('#users-table tbody').addEventListener('click', async e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const tr = btn.closest('tr'); const id = tr.dataset.id; const act = btn.dataset.act;
      if (act === 'toggle') {
        const ativo = tr.children[3].textContent.includes('ativo') ? false : true;
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
