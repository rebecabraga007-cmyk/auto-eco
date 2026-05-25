"""
scraper.py  —  Mais Obras Enricher  (httpx, sem Playwright)
------------------------------------------------------------

Fluxo descoberto via análise do código-fonte da plataforma:

  LOGIN
    GET  /                            → obtém cookie de sessão e CSRF token (se houver)
    POST /verificar_login             → { email, senha }  → redireciona para área logada

  COLETA DE CONTATOS (por obra)
    POST /pesquisa_perfil             → { contato, tipo, cpf_cnpj, uf }
    Resposta JSON:
      {
        "perfil": [{ "telefones": "11 99999, 11 88888", "cidade": "...", "uf": "...", "cbo": "...", "cpfcnpj": "..." }],
        "emails": [{ "email": "..." }],
        "api_json": null
      }

  Sem ID no Excel → identifica cada obra pelo nome (profissional + proprietário + UF).
  Faz 2 chamadas por obra (1 para arquiteto, 1 para proprietário).
"""

import asyncio
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("MAISOBRAS_BASE_URL", "https://www.maisobras.online").rstrip("/")
TIMEOUT = httpx.Timeout(
    connect=15.0,
    read=float(os.getenv("PLAYWRIGHT_TIMEOUT", "30000")) / 1000,
    write=15.0,
    pool=5.0,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/pesquisa_obras",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    if not texto:
        return ""
    txt = unicodedata.normalize("NFD", str(texto))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return txt.strip().upper()


def _chave(profissional: str, proprietario: str, cidade: str) -> str:
    return f"{_normalizar(profissional)}|{_normalizar(proprietario)}|{_normalizar(cidade)}"


def _parse_telefones(tels_str: str) -> list[str]:
    """Converte '11 99999-9999, 11 88888-8888' em lista limpa."""
    if not tels_str:
        return []
    return [t.strip() for t in tels_str.split(",") if t.strip()]


def _unicos(valores: list[str]) -> list[str]:
    vistos = set()
    saida = []
    for valor in valores:
        valor = str(valor or "").strip()
        chave = re.sub(r"\D+", "", valor).lower() or valor.lower()
        if valor and chave not in vistos:
            vistos.add(chave)
            saida.append(valor)
    return saida


# Indicadores de pessoa jurídica — sufixos legais claros + termos inequívocos de empresa.
# ATENÇÃO: evitar ambíguos como "me", "sc", "studio" que batem em nomes de pessoas.
_EMPRESA_RE = re.compile(
    r"\b(ltda|eireli|epp\b|"
    r"construtora|incorporadora|empreendimentos|"
    r"construcoes|construcao|construção|"
    r"associacao|associação|condominio|condomínio|holding)\b",
    re.IGNORECASE,
)


def _eh_empresa(nome: str) -> bool:
    """Retorna True se o nome parece ser pessoa jurídica (empresa/CNPJ)."""
    if not nome:
        return False
    return bool(_EMPRESA_RE.search(_normalizar(nome)))


# ---------------------------------------------------------------------------
# Dataclass de resultado
# ---------------------------------------------------------------------------

@dataclass
class ContatoObra:
    chave: str
    row_index: int = 0
    nome_arquiteto: str = ""
    tel_arq_1: str = ""
    tel_arq_2: str = ""
    email_arq: str = ""
    nome_proprietario: str = ""
    tel_prop_1: str = ""
    tel_prop_2: str = ""
    email_prop: str = ""
    erro: str = ""
    log_messages: list = field(default_factory=list)  # logs detalhados para o terminal da UI


# ---------------------------------------------------------------------------
# Scraper principal (httpx async)
# ---------------------------------------------------------------------------

class MaisObrasScraper:
    """
    Scraper com httpx para /pesquisa_perfil e Playwright para /api/pesquisa_contatos_api.
    O Ver Mais exige sessão real de browser — httpx sozinho não consegue autenticar
    nesse endpoint. O Playwright compartilha os cookies do login httpx.
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        # Playwright (Ver Mais)
        self._pw = None
        self._pw_browser = None
        self._pw_context = None
        self._pw_page = None
        self._pw_lock = asyncio.Lock()   # serializa chamadas ao browser

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self):
        self._client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        logger.info("Cliente httpx iniciado.")

        # Inicia Playwright para o Ver Mais
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._pw_browser = await self._pw.chromium.launch(headless=True)
            self._pw_context = await self._pw_browser.new_context(
                user_agent=HEADERS["User-Agent"],
                extra_http_headers={
                    "Accept-Language": "pt-BR,pt;q=0.9",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            self._pw_page = await self._pw_context.new_page()
            logger.info("Playwright iniciado (Ver Mais ativo).")
        except ImportError:
            logger.warning("playwright não instalado — Ver Mais usará httpx (pode não funcionar).")
        except Exception as e:
            logger.warning("Playwright falhou ao iniciar: %s — Ver Mais usará httpx.", e)

    async def stop(self):
        if self._client:
            await self._client.aclose()
        self._authenticated = False
        for obj, method in [
            (self._pw_page, "close"),
            (self._pw_context, "close"),
            (self._pw_browser, "close"),
        ]:
            if obj:
                try:
                    await getattr(obj, method)()
                except Exception:
                    pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        logger.info("httpx e Playwright encerrados.")

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> bool:
        """
        Autentica no Mais Obras.
        Estratégia:
          1. GET / para obter o cookie de sessão inicial
          2. Extrai CSRF token do HTML (se existir — CodeIgniter pode usar ci_csrf_token)
          3. POST /verificar_login com email + senha
          4. Verifica se chegamos na área logada
        """
        try:
            # 1. Acessa a página inicial para estabelecer sessão
            logger.info("Obtendo página inicial para cookie de sessão...")
            r = await self._client.get(BASE_URL + "/login")
            r.raise_for_status()

            # 2. Extrai CSRF token do HTML (se presente)
            csrf_name = None
            csrf_value = None

            # Padrão CodeIgniter: <input type="hidden" name="ci_csrf_token" value="...">
            # ou meta tag: <meta name="csrf-token" content="...">
            match_input = re.search(
                r'<input[^>]+name=["\']([^"\']*csrf[^"\']*)["\'][^>]+value=["\']([^"\']+)["\']',
                r.text, re.IGNORECASE,
            )
            match_meta = re.search(
                r'<meta[^>]+name=["\']csrf[^"\']*["\'][^>]+content=["\']([^"\']+)["\']',
                r.text, re.IGNORECASE,
            )

            if match_input:
                csrf_name = match_input.group(1)
                csrf_value = match_input.group(2)
                logger.debug(f"CSRF encontrado (input): {csrf_name}={csrf_value[:8]}...")
            elif match_meta:
                csrf_name = "csrf_token"
                csrf_value = match_meta.group(1)
                logger.debug(f"CSRF encontrado (meta): {csrf_value[:8]}...")

            # 3. Monta payload de login
            # CodeIgniter geralmente usa /login ou /verificar_login
            payloads = [
                {"identity": email, "password": password},
                {"email": email, "senha": password},
            ]
            if csrf_name and csrf_value:
                for payload in payloads:
                    payload[csrf_name] = csrf_value

            login_headers = {
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": BASE_URL + "/login",
            }

            # 4. Tenta os endpoints de login conhecidos
            login_endpoints = ["/auth/login", "/login", "/verificar_login"]

            for endpoint in login_endpoints:
                for payload in payloads:
                    logger.info(f"Tentando login em: {endpoint}")
                    r = await self._client.post(
                        BASE_URL + endpoint,
                        data=payload,
                        headers=login_headers,
                    )
                    refresh = r.headers.get("refresh", "")
                    if refresh:
                        match_refresh = re.search(r"url=([^;]+)", refresh, re.IGNORECASE)
                        if match_refresh:
                            next_url = match_refresh.group(1).strip()
                            logger.info(f"Seguindo Refresh de login para: {next_url}")
                            r = await self._client.get(next_url)

                # Verifica se autenticou (redireciona para área interna
                # ou a resposta contém elementos da área logada)
                    is_logado = (
                        "pesquisa_obras" in str(r.url)
                        or "pesquisa_obras" in r.text
                        or "navbar-brand" in r.text
                        or "logo_topo" in r.text
                        or "Pesquisar Obras" in r.text
                        or "Meus Favoritos" in r.text
                    )

                    if is_logado:
                        self._authenticated = True
                        logger.info(f"Login OK via {endpoint}. URL final: {r.url}")
                        # Login real no Playwright (browser completo, sessão legítima)
                        await self._sincronizar_sessao_playwright(email, password)
                        return True

                # Se status 200 mas sem redirecionamento, pode ser que
                # o endpoint retornou JSON de sucesso
                    if r.status_code == 200:
                        try:
                            data = r.json()
                            if data.get("success") or data.get("status") == "ok":
                                self._authenticated = True
                                logger.info(f"Login OK via {endpoint} (JSON).")
                                await self._sincronizar_sessao_playwright(email, password)
                                return True
                        except Exception:
                            pass

            logger.error("Login falhou em todos os endpoints testados.")
            return False

        except Exception as e:
            logger.error(f"Erro durante login: {e}")
            return False

    async def _sincronizar_sessao_playwright(self, email: str = "", password: str = ""):
        """
        Faz login real via Playwright (preenche o formulário no browser).
        Mais confiável que compartilhar cookies do httpx — garante sessão legítima
        para o endpoint /api/pesquisa_contatos_api.
        """
        if not self._pw_page:
            return
        try:
            page = self._pw_page

            # Navega para o login
            await page.goto(BASE_URL + "/login", wait_until="domcontentloaded", timeout=25000)
            logger.info("Playwright: página de login carregada. URL=%s", page.url)

            # Preenche email — tenta os campos mais comuns do CodeIgniter
            for selector in ['input[name="identity"]', 'input[name="email"]', 'input[type="email"]']:
                try:
                    await page.fill(selector, email, timeout=3000)
                    logger.info("Playwright: email preenchido em '%s'", selector)
                    break
                except Exception:
                    continue

            # Preenche senha
            for selector in ['input[name="password"]', 'input[name="senha"]', 'input[type="password"]']:
                try:
                    await page.fill(selector, password, timeout=3000)
                    logger.info("Playwright: senha preenchida em '%s'", selector)
                    break
                except Exception:
                    continue

            # Submete o formulário
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
            logger.info("Playwright: após submit. URL=%s", page.url)

            # Verifica se está logado
            is_logado = (
                "pesquisa_obras" in page.url
                or "Pesquisar Obras" in await page.content()
                or "Meus Favoritos" in await page.content()
            )

            if is_logado:
                logger.info("Playwright: login OK. URL=%s", page.url)
                # Garante que está na página de obras para o fetch funcionar
                if "pesquisa_obras" not in page.url:
                    await page.goto(BASE_URL + "/pesquisa_obras", wait_until="domcontentloaded", timeout=15000)
            else:
                logger.warning("Playwright: login pode ter falhado. URL=%s", page.url)

        except Exception as e:
            logger.warning("Playwright login falhou: %s", e)

    # ------------------------------------------------------------------
    # Coleta de contatos via /pesquisa_perfil
    # ------------------------------------------------------------------

    async def _buscar_perfil(
        self, nome: str, tipo: str, uf: str, cpf_cnpj: str = ""
    ) -> dict:
        """
        POST /pesquisa_perfil com os dados do contato.
        Retorna o dict com 'perfil' e 'emails', ou {} em caso de erro.
        """
        payload = {
            "contato": nome,
            "tipo": tipo,        # "Profissional" ou "Proprietário"
            "cpf_cnpj": cpf_cnpj,
            "uf": uf,
        }
        try:
            r = await self._client.post(
                BASE_URL + "/pesquisa_perfil",
                data=payload,
            )
            if r.status_code == 200 and r.text.strip():
                return json.loads(r.text)
        except Exception as e:
            logger.debug(f"Erro em /pesquisa_perfil ({nome}): {e}")
        return {}

    async def _chamar_api_ver_mais(
        self, payload: dict, nome_log: str, log_cb=None
    ) -> tuple[int, dict, str]:
        """
        Faz UMA chamada HTTP ao /api/pesquisa_contatos_api.
        Usa Playwright (browser com sessão real) se disponível; httpx como fallback.
        Retorna (status_http, dict_resposta, body_raw).

        Usa jQuery.ajax() se disponível na página (mesmo método que o site usa),
        com fallback para URLSearchParams e depois FormData.
        """
        contato_json = json.dumps(payload, ensure_ascii=False)

        # ── Playwright (preferencial) ───────────────────────────────────────
        if self._pw_page:
            async with self._pw_lock:
                try:
                    result = await self._pw_page.evaluate(
                        """async ([url, contato]) => {
                            const isLoggedIn = (
                                document.body.innerHTML.includes('pesquisa_obras') ||
                                document.body.innerHTML.includes('Meus Favoritos') ||
                                document.body.innerHTML.includes('logout') ||
                                document.cookie.includes('ci_session')
                            );

                            // Tenta jQuery primeiro — mesmo método que o site usa (CodeIgniter)
                            const jq = (typeof jQuery !== 'undefined') ? jQuery
                                      : (typeof $ !== 'undefined' ? $ : null);
                            if (jq) {
                                return new Promise((resolve) => {
                                    jq.ajax({
                                        url: url,
                                        type: 'POST',
                                        data: {contato: contato},
                                        dataType: 'json',
                                        headers: {'X-Requested-With': 'XMLHttpRequest'},
                                    })
                                    .done(data => resolve({
                                        ok: true, status: 200,
                                        body: (typeof data === 'string') ? data : JSON.stringify(data),
                                        method: 'jquery', pageUrl: location.href, loggedIn: isLoggedIn
                                    }))
                                    .fail(xhr => resolve({
                                        ok: false, status: xhr.status,
                                        body: xhr.responseText || '',
                                        method: 'jquery-err', pageUrl: location.href, loggedIn: isLoggedIn
                                    }));
                                });
                            }

                            // Fallback 1: URLSearchParams (application/x-www-form-urlencoded)
                            try {
                                const params = new URLSearchParams();
                                params.append('contato', contato);
                                const r = await fetch(url, {
                                    method: 'POST', body: params,
                                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                                });
                                return {ok: true, status: r.status, body: await r.text(),
                                        method: 'urlencoded', pageUrl: location.href, loggedIn: isLoggedIn};
                            } catch(e1) {}

                            // Fallback 2: FormData (multipart)
                            try {
                                const fd = new FormData();
                                fd.append('contato', contato);
                                const r = await fetch(url, {
                                    method: 'POST', body: fd,
                                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                                });
                                return {ok: true, status: r.status, body: await r.text(),
                                        method: 'formdata', pageUrl: location.href, loggedIn: isLoggedIn};
                            } catch(e2) {
                                return {ok: false, status: 0, body: '', error: String(e2),
                                        method: 'err', pageUrl: location.href, loggedIn: isLoggedIn};
                            }
                        }""",
                        [BASE_URL + "/api/pesquisa_contatos_api", contato_json],
                    )
                    status = result.get("status", 0)
                    body = result.get("body", "")
                    method = result.get("method", "?")
                    page_url = result.get("pageUrl", "?")
                    logged_in = result.get("loggedIn", None)
                    logger.info(
                        "[%s] Ver Mais PW HTTP %d | method=%s | loggedIn=%s | pageUrl=%s | seq=%s | body[:200]=%s",
                        nome_log[:25], status, method, logged_in, page_url[:60],
                        payload.get("sequence_id", "(lista)"), body[:200]
                    )
                    if log_cb:
                        seq_tag = f"seq={payload['sequence_id']}" if payload.get("sequence_id") else "lista"
                        auth_tag = "" if logged_in is None else (" loggedIn=SIM" if logged_in else " loggedIn=NAO!")
                        log_cb(f"    [DBG] ver_mais {seq_tag} {method} HTTP {status}{auth_tag} → {body[:100] or '(vazio)'}")
                    if status == 200 and body.strip():
                        return status, json.loads(body), body
                    if not result.get("ok"):
                        logger.warning("[%s] Ver Mais PW error: %s", nome_log[:25], result.get("error"))
                    return status, {}, body
                except Exception as e:
                    logger.warning("[%s] Ver Mais PW exception: %s", nome_log[:25], e)
                    if log_cb:
                        log_cb(f"    [DBG] ver_mais PW exception: {e}")
                    return 0, {}, ""

        # ── Fallback: httpx ─────────────────────────────────────────────────
        try:
            r = await self._client.post(
                BASE_URL + "/api/pesquisa_contatos_api",
                data={"contato": contato_json},
            )
            body = r.text
            logger.info("[%s] Ver Mais httpx HTTP %d | seq=%s | body[:200]=%s",
                nome_log[:25], r.status_code, payload.get("sequence_id", "(lista)"), body[:200])
            if log_cb:
                seq_tag = f"seq={payload['sequence_id']}" if payload.get("sequence_id") else "lista"
                log_cb(f"    [DBG] ver_mais {seq_tag} httpx HTTP {r.status_code} → {body[:100] or '(vazio)'}")
            if r.status_code == 200 and body.strip():
                return r.status_code, json.loads(body), body
        except Exception as e:
            logger.warning("[%s] Ver Mais httpx exception: %s", nome_log[:25], e)
        return 0, {}, ""

    async def _buscar_ver_mais(
        self,
        nome: str,
        cpf_cnpj: str = "",
        uf: str = "",
        cidade: str = "",
        sequence_id: str = "",
        nome_mae: str = "",
        log_cb=None,
    ) -> dict:
        """
        Fluxo Ver Mais em dois passos — payload exato conforme funcoes_contatos.js:
          1. LISTA  → {nome, cpfcnpj, uf, ccp:"1"}
          2. DETALHE → {nome, cidade, uf, nome_mae, cpfcnpj:"", sequence_id}
        """
        if not sequence_id:
            # Chamada de LISTA — busca candidatos pelo nome
            payload: dict = {
                "nome": nome or "",
                "cpfcnpj": cpf_cnpj or "",
                "uf": uf or "",
                "ccp": "1",           # obrigatório — ausência causava [] para todos
            }
        else:
            # Chamada de DETALHE — busca telefone pelo SequentialId
            payload: dict = {
                "nome": nome or "",
                "cidade": cidade or "",
                "uf": uf or "",
                "nome_mae": nome_mae or "",   # MotherNameFmt da resposta de lista
                "cpfcnpj": "",                # sempre vazio na chamada de detalhe
                "sequence_id": sequence_id,
            }

        if log_cb and not sequence_id:
            log_cb(f"    [DBG] payload → nome='{nome[:30]}' cpf={'sim' if cpf_cnpj else 'NÃO'} uf='{uf}' ccp=1")

        _status, data, _body = await self._chamar_api_ver_mais(payload, nome, log_cb=log_cb)

        # A API pode retornar [] (lista vazia) quando não encontra nada —
        # não é um dict, então não podemos chamar .get(). Retorna sentinel
        # para que o caller possa logar a mensagem correta (sem duplicar).
        if not isinstance(data, dict):
            logger.info("[%s] Ver Mais retornou %s — tratando como vazio.", nome[:25], type(data).__name__)
            return {"_empty_result": True}

        if log_cb and not data:
            log_cb(f"    ver_mais: sem resposta (HTTP {_status})")

        # Resposta de LISTA — escolhe candidato e faz chamada de detalhe
        if data.get("is_array") is True and isinstance(data.get("result"), list):
            candidatos = data["result"]
            logger.info("[%s] Ver Mais lista: %d candidato(s) — %s",
                nome[:30], len(candidatos),
                [(c.get("Name", "?")[:25], c.get("Location", "")) for c in candidatos[:4]])
            if log_cb:
                resumo = " | ".join(
                    f"'{c.get('Name','?')[:20]}' {c.get('Location','')}" for c in candidatos[:4]
                )
                log_cb(f"    ver_mais: {len(candidatos)} candidato(s) → {resumo}")

            escolhido = self._escolher_resultado_ver_mais(nome, uf, candidatos, cidade=cidade, log_cb=log_cb)
            if escolhido and escolhido.get("SequentialId") and not sequence_id:
                loc_raw = escolhido.get("Location") or ""
                loc_parts = loc_raw.split("-")
                cidade_candidato = loc_parts[0].strip() if loc_parts else cidade
                uf_candidato = loc_parts[1].strip() if len(loc_parts) > 1 else uf
                logger.info("[%s] Ver Mais selecionado: '%s' loc='%s' (seq=%s)",
                    nome[:30], escolhido.get("Name", "?")[:30], loc_raw, escolhido.get("SequentialId"))
                # Chamada de detalhe (sem lock aninhado pois _chamar_api_ver_mais gerencia o lock)
                return await self._buscar_ver_mais(
                    nome=escolhido.get("Name") or nome,
                    cpf_cnpj=cpf_cnpj,
                    uf=uf_candidato or uf,
                    cidade=cidade_candidato or cidade,
                    sequence_id=str(escolhido.get("SequentialId")),
                    nome_mae=escolhido.get("MotherNameFmt") or "",
                    log_cb=log_cb,
                )

        return data

    def _ia_localizar_candidato(
        self, nome: str, cidade: str, uf: str, candidatos: list[dict], log_cb=None
    ) -> dict | None:
        """
        Usa Mistral AI para interpretar qual candidato corresponde à localização esperada.
        Lida com cidades abreviadas ou mal formatadas (ex: 'S.CARLOS' = 'São Carlos').
        Chamado somente quando há ambiguidade (múltiplos candidatos ou localização suspeita).
        """
        try:
            from mistralai import Mistral

            api_key = os.getenv("MISTRAL_API_KEY", "")
            if not api_key:
                return None

            client = Mistral(api_key=api_key)

            lista = "\n".join(
                f"[{i}] nome='{c.get('Name', '')}' local='{c.get('Location', '')}'"
                for i, c in enumerate(candidatos)
            )

            prompt = f"""Você está identificando a pessoa certa em uma lista de candidatos de um banco de dados brasileiro.

Pessoa buscada:
- Nome: {nome}
- Cidade esperada: {cidade or "(nao informada)"}
- UF esperada: {uf or "(nao informada)"}

Candidatos retornados pela API:
{lista}

Regras:
- A cidade pode estar abreviada ou com formatacao diferente. Ex: "S.CARLOS" = "Sao Carlos", "RIB.PRETO" = "Ribeirao Preto", "S.J.RIO PRETO" = "Sao Jose do Rio Preto".
- Considere o estado (UF) como critério secundário.
- Se nenhum candidato bate com a cidade/UF esperada, responda null.

Responda SOMENTE com o numero do indice entre colchetes (ex: 0) ou null. Sem explicacao."""

            response = client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5,
            )

            content = response.choices[0].message.content.strip()
            if content.lower() in ("null", "none", ""):
                msg = f"    IA: nenhum candidato bate com {cidade or uf} — descartando"
                logger.info("IA Ver Mais: nenhum candidato bate com localização de '%s' (%s/%s)", nome[:30], cidade, uf)
                if log_cb: log_cb(msg)
                return None

            m = re.search(r"\d+", content)
            if not m:
                return None
            idx = int(m.group())
            if 0 <= idx < len(candidatos):
                c = candidatos[idx]
                msg = f"    IA: '{c.get('Name','?')[:30]}' loc='{c.get('Location','')}' ✓"
                logger.info("IA Ver Mais: [%d] '%s' loc='%s' escolhido para '%s'", idx, c.get("Name","?")[:30], c.get("Location",""), nome[:30])
                if log_cb: log_cb(msg)
                return c

        except Exception as e:
            logger.warning("Mistral falhou na seleção de candidato Ver Mais: %s", e)
            if log_cb: log_cb(f"    IA: falhou ({e}), usando score simples")
        return None

    def _escolher_resultado_ver_mais(
        self, nome: str, uf: str, resultados: list[dict], cidade: str = "", log_cb=None
    ) -> dict | None:
        """
        Escolhe o candidato certo na lista do Ver Mais em dois estágios:

        1. Filtro por nome — descarta candidatos sem nenhuma correspondência de nome.
           Se zero candidatos passam, retorna None (não arriscamos número errado).

        2. Desempate por localização — usa IA (Mistral) para interpretar cidade/UF
           mesmo quando vierem abreviados ou mal formatados.
           Fallback para score simples se Mistral falhar.
        """
        nome_norm = _normalizar(nome)

        def nome_score(item: dict) -> int:
            item_nome = _normalizar(item.get("Name", ""))
            if item_nome == nome_norm:
                return 4
            if nome_norm and (nome_norm in item_nome or item_nome in nome_norm):
                return 2
            return 0

        candidatos = [r for r in resultados if isinstance(r, dict)]
        if not candidatos:
            return None

        max_nome = max(nome_score(c) for c in candidatos)
        if max_nome == 0:
            msg = f"    ver_mais: nenhum candidato com nome compativel ({len(candidatos)} resultados) — descartando"
            logger.warning("Ver Mais: nenhum candidato com nome compativel para '%s' (%d resultados) — descartando", nome[:40], len(candidatos))
            if log_cb: log_cb(msg)
            return None

        # Apenas candidatos com melhor score de nome
        melhores = [c for c in candidatos if nome_score(c) == max_nome]

        uf_norm = _normalizar(uf)
        cidade_norm = _normalizar(cidade)

        def loc_score(item: dict) -> int:
            location = _normalizar(item.get("Location", ""))
            s = 0
            if cidade_norm and cidade_norm in location:
                s += 2
            if uf_norm and uf_norm in location:
                s += 1
            return s

        # Candidato único — verificar localização; usar IA se não bater
        if len(melhores) == 1:
            c = melhores[0]
            if (cidade or uf) and loc_score(c) == 0:
                if log_cb: log_cb(f"    ver_mais: 1 candidato '{c.get('Name','?')[:25]}' loc='{c.get('Location','')}' — sem match de localização, consultando IA")
                ia = self._ia_localizar_candidato(nome, cidade, uf, melhores, log_cb=log_cb)
                if ia is None:
                    return None
            else:
                if log_cb: log_cb(f"    ver_mais: candidato único '{c.get('Name','?')[:25]}' loc='{c.get('Location','')}' ✓")
            return c

        # Múltiplos candidatos com mesmo nome — IA desempata pela localização
        nomes_lista = ", ".join(f"'{c.get('Name','?')[:20]}' ({c.get('Location','')})" for c in melhores[:3])
        if log_cb: log_cb(f"    ver_mais: {len(melhores)} candidatos com mesmo nome → IA desempata: {nomes_lista}")
        ia = self._ia_localizar_candidato(nome, cidade, uf, melhores, log_cb=log_cb)
        if ia:
            return ia

        # Fallback: score de localização simples
        melhor = max(melhores, key=loc_score)
        if loc_score(melhor) == 0:
            if log_cb: log_cb(f"    ver_mais: fallback — sem match de localização, usando '{melhor.get('Name','?')[:25]}'")
        return melhor

    def _extrair_contato(self, resposta: dict) -> tuple[list[str], list[str]]:
        """
        Extrai listas de telefones e e-mails da resposta de /pesquisa_perfil.
        Retorna (telefones, emails).

        USA APENAS O PRIMEIRO item do perfil — evitar misturar telefones de pessoas
        diferentes quando a API retorna múltiplos perfis para nomes ambíguos.
        """
        telefones: list[str] = []
        emails: list[str] = []

        perfil = resposta.get("perfil")
        if perfil and isinstance(perfil, list) and len(perfil) > 0:
            if len(perfil) > 1:
                logger.debug(
                    "pesquisa_perfil retornou %d perfis — usando apenas o primeiro "
                    "para evitar mistura de telefones de pessoas diferentes",
                    len(perfil),
                )
            # Apenas o primeiro perfil (o mais relevante retornado pela API)
            item = perfil[0]
            tels_str = item.get("telefones") or ""
            telefones.extend(_parse_telefones(tels_str))

        array_emails = resposta.get("emails")
        if array_emails and isinstance(array_emails, list):
            emails = [e.get("email", "") for e in array_emails if e.get("email")]

        return _unicos(telefones), _unicos(emails)

    def _extrair_contato_ver_mais(self, resposta: dict) -> tuple[list[str], list[str]]:
        retorno = resposta.get("result")
        if not isinstance(retorno, dict) or retorno.get("Status") != "200":
            return [], []

        dados = retorno.get("Data") or {}
        telefones = []
        emails = []

        # Incluir TODOS os telefones com FormattedNumber — não filtrar por Status
        # porque não temos documentação do significado dos valores de Status da API.
        # Filtrar por Status != 0 excluía potencialmente os números ativos (Status=0).
        for phone in dados.get("Phones") or []:
            num = phone.get("FormattedNumber") or ""
            if num:
                telefones.append(num)

        for mail in dados.get("Emails") or []:
            addr = mail.get("Email") or ""
            if addr:
                emails.append(addr)

        logger.info(
            "Ver Mais extração: %d telefone(s) %d email(s) — raw phones: %s",
            len(telefones), len(emails),
            [p.get("FormattedNumber") for p in (dados.get("Phones") or [])],
        )
        return _unicos(telefones), _unicos(emails)

    async def _coletar_contato_pessoa(
        self, nome: str, tipo: str, uf: str, cidade: str = "", log_cb=None
    ) -> tuple[list[str], list[str]]:
        # --- Etapa 1: /pesquisa_perfil ---
        resp = await self._buscar_perfil(nome=nome, tipo=tipo, uf=uf)
        telefones_perfil, emails_perfil = self._extrair_contato(resp)
        logger.info("[%s] pesquisa_perfil: %d tel, %d email — %s", nome[:30], len(telefones_perfil), len(emails_perfil), telefones_perfil[:2])
        if log_cb:
            if telefones_perfil:
                log_cb(f"    perfil: {len(telefones_perfil)} tel → {', '.join(telefones_perfil[:2])}")
            else:
                log_cb(f"    perfil: sem telefone")

        perfil = resp.get("perfil")
        cpf_cnpj = ""
        uf_ver_mais = uf
        if perfil and isinstance(perfil, list) and len(perfil) > 0:
            principal = next((p for p in perfil if p.get("cpfcnpj")), perfil[0])
            cpf_cnpj = principal.get("cpfcnpj") or ""
            uf_ver_mais = principal.get("uf") or uf
            logger.info("[%s] cpfcnpj para Ver Mais: %s | uf: %s", nome[:30], cpf_cnpj[:8] + "***" if cpf_cnpj else "(vazio)", uf_ver_mais)

        # --- Etapa 2: Ver Mais (/api/pesquisa_contatos_api) ---
        resp_api = await self._buscar_ver_mais(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            uf=uf_ver_mais,
            cidade=cidade,
            log_cb=log_cb,
        )
        telefones_vm, emails_vm = self._extrair_contato_ver_mais(resp_api)
        logger.info("[%s] ver_mais: %d tel — %s", nome[:30], len(telefones_vm), telefones_vm[:2])

        # Ver Mais tem precedência: seus dados passaram por validação de nome.
        # Só usa pesquisa_perfil como fallback quando Ver Mais não retornou nada.
        if telefones_vm:
            if log_cb: log_cb(f"    ver_mais tel: {', '.join(telefones_vm[:2])}")
            return _unicos(telefones_vm), _unicos(emails_vm or emails_perfil)

        # Inspeciona o tipo de retorno para log único e preciso
        if resp_api.get("_empty_result"):
            if log_cb: log_cb(f"    ver_mais: sem resultados — usando fallback perfil")
        elif not resp_api or resp_api == {}:
            if log_cb: log_cb(f"    ver_mais: sem resposta da API — usando fallback perfil")
        elif resp_api.get("is_array") and not resp_api.get("result"):
            if log_cb: log_cb(f"    ver_mais: API não retornou candidatos — usando fallback perfil")
        else:
            if log_cb: log_cb(f"    ver_mais: candidato encontrado mas sem telefone — usando fallback perfil")
        logger.info("[%s] Ver Mais vazio — usando fallback pesquisa_perfil", nome[:30])
        return _unicos(telefones_perfil), _unicos(emails_perfil)

    # ------------------------------------------------------------------
    # Processamento de uma obra
    # ------------------------------------------------------------------

    async def coletar_contatos_obra(self, obra) -> ContatoObra:
        """
        Coleta telefones e e-mails de uma obra fazendo 2 chamadas:
          1. /pesquisa_perfil para o profissional/arquiteto
          2. /pesquisa_perfil para o proprietário
        """
        resultado = ContatoObra(chave=obra.chave, row_index=obra.row_index)

        if not self._authenticated:
            resultado.erro = "Scraper não autenticado"
            return resultado

        log = resultado.log_messages.append  # atalho para logar na UI

        # --- Arquiteto / Profissional ---
        resultado.nome_arquiteto = obra.nome_profissional
        if obra.nome_profissional:
            if _eh_empresa(obra.nome_profissional):
                logger.warning("[%s] Empresa detectada no campo profissional — busca ignorada", obra.nome_profissional[:40])
                log(f"  ARQ: '{obra.nome_profissional[:45]}' → empresa, sem busca")
            else:
                log(f"  ARQ: buscando '{obra.nome_profissional[:45]}'…")
                try:
                    tels, emails = await self._coletar_contato_pessoa(
                        nome=obra.nome_profissional,
                        tipo="Profissional",
                        uf=obra.uf,
                        cidade=obra.cidade,
                        log_cb=log,
                    )
                    if len(tels) > 0:
                        resultado.tel_arq_1 = tels[0]
                    if len(tels) > 1:
                        resultado.tel_arq_2 = tels[1]
                    if emails:
                        resultado.email_arq = emails[0]
                    if tels:
                        log(f"  ARQ ✓ tel: {tels[0]}" + (f", {tels[1]}" if len(tels) > 1 else ""))
                    else:
                        log(f"  ARQ: sem telefone")
                except Exception as e:
                    logger.warning(f"[{obra.nome_profissional[:20]}] Erro arquiteto: {e}")
                    log(f"  ARQ: erro — {e}")

        # --- Proprietário ---
        resultado.nome_proprietario = obra.nome_proprietario
        if obra.nome_proprietario:
            if _eh_empresa(obra.nome_proprietario):
                logger.warning("[%s] Empresa detectada no campo proprietário — busca ignorada", obra.nome_proprietario[:40])
                log(f"  PROP: '{obra.nome_proprietario[:45]}' → empresa, sem busca")
            else:
                log(f"  PROP: buscando '{obra.nome_proprietario[:45]}'…")
                try:
                    tels, emails = await self._coletar_contato_pessoa(
                        nome=obra.nome_proprietario,
                        tipo="Proprietário",
                        uf=obra.uf,
                        cidade=obra.cidade,
                        log_cb=log,
                    )
                    if len(tels) > 0:
                        resultado.tel_prop_1 = tels[0]
                    if len(tels) > 1:
                        resultado.tel_prop_2 = tels[1]
                    if emails:
                        resultado.email_prop = emails[0]
                    if tels:
                        log(f"  PROP ✓ tel: {tels[0]}" + (f", {tels[1]}" if len(tels) > 1 else ""))
                    else:
                        log(f"  PROP: sem telefone")
                except Exception as e:
                    logger.warning(f"[{obra.nome_proprietario[:20]}] Erro proprietário: {e}")
                    log(f"  PROP: erro — {e}")

        logger.info(
            f"[{obra.nome_profissional[:18]:18}] "
            f"Arq: {resultado.tel_arq_1 or '—':15} | "
            f"Prop: {resultado.tel_prop_1 or '—'}"
        )
        return resultado

    # ------------------------------------------------------------------
    # Processamento em lote
    # ------------------------------------------------------------------

    async def processar_lote(
        self, obras: list, concorrencia: int = 5, progress_callback=None
    ) -> list[ContatoObra]:
        """
        Processa obras em paralelo com semáforo de concorrência.
        httpx é muito mais leve que Playwright — podemos usar concorrência maior.
        """
        semaforo = asyncio.Semaphore(concorrencia)

        async def processar_com_limite(obra):
            async with semaforo:
                # Pequeno delay para não sobrecarregar
                await asyncio.sleep(0.1)
                resultado = await self.coletar_contatos_obra(obra)
                if progress_callback:
                    progress_callback(obra, resultado)
                return resultado

        resultados = await asyncio.gather(
            *[processar_com_limite(o) for o in obras],
            return_exceptions=False,
        )

        erros = sum(1 for r in resultados if r.erro)
        sucesso = sum(1 for r in resultados if r.tel_arq_1 or r.tel_prop_1)
        logger.info(
            f"Lote concluído: {len(resultados)} obras processadas | "
            f"{sucesso} com telefone | {erros} com erro"
        )
        return resultados
