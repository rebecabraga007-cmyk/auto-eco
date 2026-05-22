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
from dataclasses import dataclass

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


# ---------------------------------------------------------------------------
# Scraper principal (httpx async)
# ---------------------------------------------------------------------------

class MaisObrasScraper:
    """
    Scraper baseado em httpx (sem browser).
    Mantém uma sessão autenticada e chama diretamente
    o endpoint /pesquisa_perfil para cada obra.
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False

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

    async def stop(self):
        if self._client:
            await self._client.aclose()
        self._authenticated = False
        logger.info("Cliente httpx encerrado.")

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
                        return True

                # Se status 200 mas sem redirecionamento, pode ser que
                # o endpoint retornou JSON de sucesso
                    if r.status_code == 200:
                        try:
                            data = r.json()
                            if data.get("success") or data.get("status") == "ok":
                                self._authenticated = True
                                logger.info(f"Login OK via {endpoint} (JSON).")
                                return True
                        except Exception:
                            pass

            logger.error("Login falhou em todos os endpoints testados.")
            return False

        except Exception as e:
            logger.error(f"Erro durante login: {e}")
            return False

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

    async def _buscar_ver_mais(
        self,
        nome: str,
        cpf_cnpj: str = "",
        uf: str = "",
        ccp: str = "0",
        sequence_id: str = "",
    ) -> dict:
        """
        Replica o botao "Ver Mais": POST /api/pesquisa_contatos_api
        com o campo form-data `contato` contendo o dataset em JSON.
        """
        payload = {
            "nome": nome or "",
            "cpfcnpj": cpf_cnpj or "",
            "uf": uf or "",
            "ccp": ccp or "0",
        }
        if sequence_id:
            payload["sequence_id"] = sequence_id

        try:
            r = await self._client.post(
                BASE_URL + "/api/pesquisa_contatos_api",
                data={"contato": json.dumps(payload, ensure_ascii=False)},
            )
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                if data.get("is_array") is True and isinstance(data.get("result"), list):
                    escolhido = self._escolher_resultado_ver_mais(nome, uf, data["result"])
                    if escolhido and escolhido.get("SequentialId") and not sequence_id:
                        return await self._buscar_ver_mais(
                            nome=escolhido.get("Name") or nome,
                            cpf_cnpj=cpf_cnpj,
                            uf=uf,
                            ccp=ccp,
                            sequence_id=str(escolhido.get("SequentialId")),
                        )
                return data
        except Exception as e:
            logger.debug(f"Erro em /api/pesquisa_contatos_api ({nome}): {e}")
        return {}

    def _escolher_resultado_ver_mais(
        self, nome: str, uf: str, resultados: list[dict]
    ) -> dict | None:
        """
        Escolhe o candidato mais provável na lista do Ver Mais.

        IMPORTANTE: retorna None se nenhum candidato tiver qualquer correspondência
        de nome com o buscado — evita pegar telefones de uma pessoa aleatória.
        """
        nome_norm = _normalizar(nome)
        uf_norm = _normalizar(uf)

        def score(item: dict) -> int:
            item_nome = _normalizar(item.get("Name", ""))
            location = _normalizar(item.get("Location", ""))
            pontos = 0
            if item_nome == nome_norm:
                pontos += 4
            elif nome_norm and (nome_norm in item_nome or item_nome in nome_norm):
                pontos += 2
            if uf_norm and uf_norm in location:
                pontos += 1
            return pontos

        candidatos = [r for r in resultados if isinstance(r, dict)]
        if not candidatos:
            return None

        melhor = max(candidatos, key=score)
        pontuacao = score(melhor)

        # Sem nenhuma correspondência de nome → recusar para não retornar
        # telefones de uma pessoa completamente diferente.
        if pontuacao == 0:
            logger.warning(
                "Ver Mais: nenhum candidato com nome compativel para '%s' "
                "(%d resultados) — descartando para evitar numero errado",
                nome[:40], len(candidatos),
            )
            return None

        if pontuacao < 2:
            logger.warning(
                "Ver Mais: correspondencia fraca (score=%d) para '%s' "
                "→ selecionado '%s'",
                pontuacao, nome[:30], melhor.get("Name", "?")[:30],
            )
        else:
            logger.debug(
                "Ver Mais: '%s' selecionado (score=%d) para '%s'",
                melhor.get("Name", "?")[:30], pontuacao, nome[:30],
            )

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

        for phone in dados.get("Phones") or []:
            if phone.get("Status") != 0 and phone.get("FormattedNumber"):
                telefones.append(phone["FormattedNumber"])

        for mail in dados.get("Emails") or []:
            if mail.get("Status") != 0 and mail.get("Email"):
                emails.append(mail["Email"])

        return _unicos(telefones), _unicos(emails)

    async def _coletar_contato_pessoa(
        self, nome: str, tipo: str, uf: str
    ) -> tuple[list[str], list[str]]:
        resp = await self._buscar_perfil(nome=nome, tipo=tipo, uf=uf)
        telefones, emails = self._extrair_contato(resp)

        perfil = resp.get("perfil")
        cpf_cnpj = ""
        uf_ver_mais = uf
        if perfil and isinstance(perfil, list) and len(perfil) > 0:
            principal = next((p for p in perfil if p.get("cpfcnpj")), perfil[0])
            cpf_cnpj = principal.get("cpfcnpj") or ""
            uf_ver_mais = principal.get("uf") or uf

        resp_api = await self._buscar_ver_mais(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            uf=uf_ver_mais,
        )
        telefones_api, emails_api = self._extrair_contato_ver_mais(resp_api)

        return _unicos(telefones + telefones_api), _unicos(emails + emails_api)

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

        # --- Arquiteto / Profissional ---
        resultado.nome_arquiteto = obra.nome_profissional
        if obra.nome_profissional:
            if _eh_empresa(obra.nome_profissional):
                # Apenas loga — empresa não é buscada no Mais Obras.
                # Não seta resultado.erro: isso bloquearia o proprietário também.
                logger.warning(
                    "[%s] Empresa detectada no campo profissional — busca ignorada",
                    obra.nome_profissional[:40],
                )
            else:
                try:
                    tels, emails = await self._coletar_contato_pessoa(
                        nome=obra.nome_profissional,
                        tipo="Profissional",
                        uf=obra.uf,
                    )
                    if len(tels) > 0:
                        resultado.tel_arq_1 = tels[0]
                    if len(tels) > 1:
                        resultado.tel_arq_2 = tels[1]
                    if emails:
                        resultado.email_arq = emails[0]
                except Exception as e:
                    logger.warning(f"[{obra.nome_profissional[:20]}] Erro arquiteto: {e}")

        # --- Proprietário ---
        resultado.nome_proprietario = obra.nome_proprietario
        if obra.nome_proprietario:
            if _eh_empresa(obra.nome_proprietario):
                # Mesmo critério: apenas loga, não bloqueia o registro.
                logger.warning(
                    "[%s] Empresa detectada no campo proprietário — busca ignorada",
                    obra.nome_proprietario[:40],
                )
            else:
                try:
                    tels, emails = await self._coletar_contato_pessoa(
                        nome=obra.nome_proprietario,
                        tipo="Proprietário",
                        uf=obra.uf,
                    )
                    if len(tels) > 0:
                        resultado.tel_prop_1 = tels[0]
                    if len(tels) > 1:
                        resultado.tel_prop_2 = tels[1]
                    if emails:
                        resultado.email_prop = emails[0]
                except Exception as e:
                    logger.warning(f"[{obra.nome_proprietario[:20]}] Erro proprietário: {e}")

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
