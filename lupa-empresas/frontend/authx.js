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
    vigiarSessao();
    wireLogin();
    wireMenu();
    wireUsersModal();
    wireUmt();
    wireAdmEmail();
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

  function showLogin(motivo) {
    document.getElementById('login-overlay').hidden = false;
    document.body.classList.add('locked');
    // Login mudo parece queda de sistema. Se a sessão venceu, diga isso.
    const err = document.getElementById('login-err');
    if (err && motivo) err.textContent = motivo;
  }

  // Qualquer 401 com o app já carregado = sessão vencida. Mostra o login com
  // explicação em vez de deixar a tela travada sem dizer nada.
  function vigiarSessao() {
    const original = window.fetch;
    window.fetch = async function(...args) {
      const resp = await original.apply(this, args);
      try {
        const url = String(args[0] || '');
        if (resp.status === 401 && url.includes('/api/') && !url.includes('/api/auth/login')) {
          if (document.getElementById('login-overlay')?.hidden) {
            showLogin('Sua sessão expirou. Entre novamente para continuar.');
          }
        }
        const manut = resp.headers.get('X-Manutencao');
        if (manut !== null) avisoManutencao(JSON.parse(decodeURIComponent(manut)));
      } catch (e) { /* nunca atrapalhar a chamada original */ }
      return resp;
    };
  }
  /* ── AVISO DE "MANUTENÇÃO!" ─────────────────────────────────────────
     O serviço de dados marca com `X-Manutencao` a resposta das funções cujo
     fornecedor está fora do ar no radar do vigia de APIs e SEM substituta
     (backend/vigia_apis.py). Sem este aviso, a tela mostrava "nada
     encontrado" -- e "não achei" e "o fornecedor caiu" são coisas muito
     diferentes para quem está prospectando. Lista vazia = a função está no
     ar de novo: o aviso some. */
  function avisoManutencao(itens) {
    const aba = document.querySelector('.tab-section.active');
    if (!aba) return;
    let box = aba.querySelector('.aviso-manutencao');
    if (!itens || !itens.length) { if (box) box.remove(); return; }
    if (!box) {
      box = document.createElement('div');
      box.className = 'aviso-manutencao';
      box.setAttribute('role', 'status');
      box.style.cssText = 'border:1px solid #D9A441;background:#FBF3E0;color:#5C4210;'
        + 'border-radius:10px;padding:12px 16px;margin:0 0 14px;font-size:.92rem;line-height:1.45';
      const alvo = aba.querySelector('[id$="-results"],[id$="-resultado"]');
      if (alvo) alvo.parentNode.insertBefore(box, alvo);
      else (aba.querySelector('.module-header') || aba.firstElementChild).insertAdjacentElement('afterend', box);
    }
    const hora = ts => ts ? new Date(ts * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
    box.innerHTML = '<strong style="font-size:1rem">🛠️ Manutenção!</strong> '
      + itens.map(i => `<b>${esc(i.funcao)}</b> está temporariamente fora do ar — ${esc(i.api)} não responde`
        + (i.desde ? ` desde ${esc(hora(i.desde))}` : '')).join('; ')
      + '. Não há substituto disponível agora, então o resultado pode vir vazio ou incompleto.'
      + ' A equipe já foi avisada; tente de novo mais tarde.';
  }

  function showApp() {
    document.getElementById('login-overlay').hidden = true;
    document.body.classList.remove('locked');
    document.getElementById('user-name').textContent = currentUser.nome || currentUser.email;
    /* O e-mail de cadastro, escrito por extenso onde ele importa. A planilha
       enriquecida so vai para ele -- e "vai para o seu e-mail" sem dizer QUAL
       faz a pessoa ficar esperando numa caixa que nao e a que recebeu. */
    const quem = document.getElementById('en-email-quem');
    if (quem && currentUser.email) quem.textContent = currentUser.email;
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
          <!-- NOME EDITAVEL. Ele so podia ser definido na criacao, e quem
               e criado sem nome (importado, ou cadastrado as pressas) ficava
               com a celula em branco para sempre -- quatro linhas vazias no
               topo da lista parecem quatro linhas quebradas. -->
          <td><input type="text" class="user-nome-input" style="width:130px"
                     data-cur="${esc(u.nome || '')}" placeholder="(sem nome)"
                     title="Clique para dar um nome a este usuário"></td>
          <td class="mono">${esc(u.email)}</td>
          <td>${u.role === 'admin' ? '<b>admin</b>' : 'user'}</td>
          <td><select class="user-grupo-sel" data-cur="${esc(u.grupo_id || '')}">${gruposOpts}</select></td>
          <td>${u.ativo ? '🟢 ativo' : '⚪ inativo'}</td>
          <td>${u.role === 'admin' ? '<span class="pf-advanced-hint">—</span>' :
              `<input type="number" min="0" class="filter-num user-limite-input" style="width:64px"
                data-cur="${u.limite_diario_custom != null ? u.limite_diario_custom : ''}"
                title="Limite diário de consultas (vazio = padrão de ${esc(String(u.limite_diario ?? 100))})"
                placeholder="${esc(String(u.limite_diario ?? 100))}">`}</td>
          <td class="user-actions">
            <button data-act="toggle">${u.ativo ? 'Desativar' : 'Ativar'}</button>
            <button data-act="role">${u.role === 'admin' ? '→ user' : '→ admin'}</button>
            <button data-act="meetime" title="Cadastrar o token da Meetime na conta desta pessoa">🔗 Meetime</button>
            <button data-act="pass">Reset senha</button>
            <button data-act="del" class="danger">Excluir</button>
          </td>
        </tr>`).join('');
      tb.querySelectorAll('.user-grupo-sel').forEach(sel => { sel.value = sel.dataset.cur; });
      tb.querySelectorAll('.user-limite-input').forEach(inp => { inp.value = inp.dataset.cur; });
      tb.querySelectorAll('.user-nome-input').forEach(inp => { inp.value = inp.dataset.cur; });
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
      } else if (act === 'meetime') {
        umtAbrir(tr.children[1].textContent.trim());
        return;
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
      const nomeInp = e.target.closest('.user-nome-input');
      if (nomeInp) {
        const idn = nomeInp.closest('tr').dataset.id;
        const nv = nomeInp.value.trim();
        if (nv === (nomeInp.dataset.cur || '')) return;
        const rn = await fetch(`/api/admin/users/${idn}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nome: nv }) });
        if (!rn.ok) { alert((await rn.json()).detail || 'Falha ao salvar o nome.'); loadUsers(); return; }
        nomeInp.dataset.cur = nv;
        return;
      }
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

  /* ── CONTAS MEETIME DE UM USUARIO (visao do admin) ─────────────────
     A mesma rota que a pessoa usa para si (`/api/meetime/contas`), com
     `usuario` apontando para ela. O backend so aceita isso de admin -- e
     recusa em voz alta quem nao for, em vez de agir na propria conta em
     silencio. */
  let umtAlvo = '';

  async function umtChamar(acao, extra) {
    const r = await fetch('/api/meetime/contas', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao, usuario: umtAlvo, ...(extra || {}) }),
    }).then(x => x.json());
    umtPinta(r);
    return r;
  }

  function umtPinta(d) {
    const box = document.getElementById('umt-contas');
    const contas = (d && d.contas) || [];
    if (!contas.length) {
      box.innerHTML = '<span class="pf-advanced-hint">Esta pessoa não tem '
        + 'conta própria' + (d && d.tem_grupo ? ' — hoje ela usa a conta do grupo dela.' : '.')
        + '</span>';
      return;
    }
    box.innerHTML = contas.map(c => `
      <span class="chip-ex" style="${c.ativo ? 'background:var(--blue-700);color:#fff' : ''}">
        <button type="button" class="umt-usar" data-id="${esc(c.id)}"
                title="Deixar esta como a que vale" style="all:unset;cursor:pointer">
          ${c.ativo ? '● ' : '○ '}${esc(c.nome)} <small>••${esc(c.final)}</small></button>
        ${c.ativo ? '' : `<button type="button" class="umt-remover" data-id="${esc(c.id)}"
                title="Tirar">✕</button>`}
      </span>`).join(' ');
    box.querySelectorAll('.umt-usar').forEach(b => b.addEventListener('click',
      () => umtChamar('usar', { id: b.dataset.id })));
    box.querySelectorAll('.umt-remover').forEach(b => b.addEventListener('click', () => {
      if (confirm('Tirar esta conta da pessoa?')) umtChamar('remover', { id: b.dataset.id });
    }));
  }

  async function umtAbrir(email) {
    umtAlvo = email;
    document.getElementById('umt-quem').textContent = email;
    document.getElementById('umt-nota').textContent = '';
    document.getElementById('umt-token').value = '';
    document.getElementById('umt-nome').value = '';
    document.getElementById('umt-wrap').hidden = false;
    document.getElementById('umt-wrap').scrollIntoView({ behavior: 'smooth', block: 'center' });
    await umtChamar('listar');
  }

  function wireUmt() {
    document.getElementById('umt-fechar')?.addEventListener('click',
      () => { document.getElementById('umt-wrap').hidden = true; });
    document.getElementById('umt-add')?.addEventListener('click', async () => {
      const nota = document.getElementById('umt-nota');
      const tok = document.getElementById('umt-token');
      const nome = document.getElementById('umt-nome');
      if (!tok.value.trim()) { nota.textContent = 'Cole o token da Meetime.'; return; }
      nota.textContent = 'cadastrando…';
      const d = await umtChamar('add', { nome: nome.value.trim(), token: tok.value.trim() });
      if (d.status !== 'ok') { nota.textContent = d.message || 'Não deu certo.'; return; }
      /* TESTA O TOKEN NA HORA. Cadastrar na conta de outra pessoa e errar uma
         letra é pior que errar na própria: quem descobre é ela, dias depois,
         com a dedup silenciosamente desligada. */
      try {
        const t = await fetch('/api/meetime/testar', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: tok.value.trim() }),
        }).then(x => x.json());
        nota.textContent = t.status === 'ok'
          ? `Cadastrada para ${umtAlvo} · ${(t.leads_na_conta || 0).toLocaleString('pt-BR')} leads nesta conta.`
          : `Cadastrada, MAS o token não respondeu: ${t.message || 'erro'}.`;
      } catch (e) { nota.textContent = 'Cadastrada. Não consegui testar agora.'; }
      tok.value = ''; nome.value = '';
    });
  }


  /* ── TESTE DE ENVIO DE E-MAIL ──────────────────────────────────────
     Configurar SMTP é quatro variáveis de ambiente e três registros de DNS.
     Sem um teste, o único jeito de saber se funcionou seria gastar um
     enriquecimento inteiro para ver se o anexo chega -- e, quando não
     chegasse, não daria para saber se o problema é a senha, o DNS ou o
     serviço que não foi reiniciado.

     Por isso a tela mostra também O QUE O PROCESSO LEU (host, porta,
     usuário, se tem senha). O erro mais comum não é senha errada: é a
     variável posta no lugar errado e o serviço nunca reiniciado, e isso é
     invisível até alguém mostrar o que o processo enxerga. */
  function admEmailPinta(d) {
    const box = document.getElementById('adm-email-estado');
    if (!box) return;
    const c = (d && d.config) || {};
    const onde = `<code>${esc(c.usuario || '(sem usuário)')}</code> via `
      + `<code>${esc(c.host || '?')}:${esc(String(c.porta || '?'))}</code>`
      + (c.de && c.de !== c.usuario ? ` · remetente <code>${esc(c.de)}</code>` : '');
    box.innerHTML = d && d.configurado
      ? `✅ Envio ligado — ${onde}`
      : `⚠️ Envio desligado — ${esc((d && d.motivo) || 'sem configuração')}`
        + `<br><span class="pf-advanced-hint">O processo está lendo: ${onde}`
        + ` · senha: ${c.tem_senha ? 'definida' : 'AUSENTE'}</span>`;
  }

  async function admEmailStatus() {
    if (!document.getElementById('adm-email-estado')) return;
    try {
      admEmailPinta(await fetch('/api/admin/email/status').then(r => r.json()));
    } catch (e) { /* painel some sozinho se a rota não existir */ }
  }

  function wireAdmEmail() {
    const btn = document.getElementById('adm-email-testar');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const res = document.getElementById('adm-email-resultado');
      const para = (document.getElementById('adm-email-para').value || '').trim();
      btn.disabled = true;
      res.textContent = 'enviando…';
      try {
        const d = await fetch('/api/admin/email/testar', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: para }),
        }).then(r => r.json());
        res.innerHTML = d.status === 'ok'
          ? `✅ ${esc(d.message || 'Enviado.')} Confira a caixa (e o spam).`
          : `❌ ${esc(d.message || 'Não saiu.')}`;
        admEmailPinta({ configurado: d.status === 'ok', motivo: d.message, config: d.config });
      } catch (e) {
        res.textContent = 'Erro: ' + e.message;
      } finally { btn.disabled = false; }
    });
    admEmailStatus();
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
