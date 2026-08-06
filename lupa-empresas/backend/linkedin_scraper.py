"""Scraper de funcionarios via LinkedIn.

Caminho principal (recomendado): Bright Data LinkedIn Scraper API.
- Lida com proxies, CAPTCHAs e parsing; retorna JSON estruturado.
- Usa o dataset "LinkedIn people search - collect by URL" para achar pessoas
  ligadas a uma empresa a partir de uma URL de busca do LinkedIn.
- Requer a variavel de ambiente BRIGHTDATA_API_KEY.

Fallback (sem chave): busca publica pelo Google (frequentemente bloqueada).

Ambos retornam de forma GRACIOSA (nunca levantam 500).
"""

import asyncio
import os
import random
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

# ---- Bright Data ----
BRIGHTDATA_API_KEY = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
BRIGHTDATA_SCRAPE_URL = "https://api.brightdata.com/datasets/v3/scrape"
# Scraper API dataset IDs (biblioteca de scrapers, tempo real / plano free).
DATASET_PEOPLE_SEARCH = "gd_m8d03he47z8nwb5xc"  # LinkedIn people search - by URL
DATASET_PEOPLE_PROFILE = "gd_l1viktl72bvl7bjuj0"  # LinkedIn people profiles - by URL
DATASET_COMPANY = "gd_l1vikfnt1wgvvqz95w"  # LinkedIn company information - by URL

# ---- Bright Data Dataset (Marketplace) — roster completo por empresa ----
# DESLIGADO por padrao no MVP (usa plano free). Ligue com BRIGHTDATA_USE_DATASET=1
# quando comprar o dataset "LinkedIn people profiles" (min. $250/pedido).
BRIGHTDATA_USE_DATASET = os.environ.get("BRIGHTDATA_USE_DATASET", "").strip().lower() in (
    "1", "true", "yes", "on"
)
# ID do dataset de Marketplace "LinkedIn people profiles" (671M perfis).
# Confirme o ID no painel: Datasets > LinkedIn people profiles > API.
BRIGHTDATA_PEOPLE_DATASET_ID = os.environ.get(
    "BRIGHTDATA_PEOPLE_DATASET_ID", "gd_l1viktl72bvl7bjuj0"
).strip()
BRIGHTDATA_FILTER_URL = "https://api.brightdata.com/datasets/v3/filter"
BRIGHTDATA_SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot"
# Teto de registros por empresa (controla custo; cada registro e cobrado).
BRIGHTDATA_DATASET_LIMIT = int(os.environ.get("BRIGHTDATA_DATASET_LIMIT", "200"))

# Cookie de sessao do LinkedIn (usado apenas pelo fallback do Google).
LINKEDIN_LI_AT = os.environ.get("LINKEDIN_LI_AT", "").strip()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}

# Bright Data pode levar dezenas de segundos por request sincrono.
_TIMEOUT = httpx.Timeout(120.0)
_GOOGLE_TIMEOUT = httpx.Timeout(25.0)

# Cache em memoria: cnpj -> resultado
_CACHE: dict[str, dict[str, Any]] = {}


def _blocked(message: str) -> dict[str, Any]:
    return {"status": "blocked", "employees": [], "message": message}


# --------------------------------------------------------------------------
# Bright Data
# --------------------------------------------------------------------------

import unicodedata


def _slugify(name: str) -> str:
    """Transforma o nome da empresa num slug de URL do LinkedIn.

    Ex.: "PETROLEO BRASILEIRO S A PETROBRAS" -> "petroleo-brasileiro-petrobras".
    """
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    # Remove sufixos societarios comuns.
    s = re.sub(
        r"\b(s\.?\s?a\.?|ltda\.?|me|epp|eireli|s/a|sa|cia|companhia)\b", " ", s
    )
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _company_url_candidates(*names: str) -> list[str]:
    """URLs candidatas da pagina da empresa no LinkedIn (mais provaveis primeiro).

    Recebe um ou mais nomes (ex.: nome fantasia e razao social). A marca costuma
    ser a PRIMEIRA palavra do nome fantasia, entao ela vem primeiro.
    """
    slugs: list[str] = []
    for name in names:
        slug = _slugify(name or "")
        if not slug:
            continue
        parts = slug.split("-")
        first = parts[0]
        if len(first) > 2:
            slugs.append(first)  # marca (primeira palavra)
        slugs.append(slug)  # slug completo
        if len(parts) >= 2 and len(parts[-1]) > 2:
            slugs.append(parts[-1])  # ultima palavra
        if len(parts) > 2:
            slugs.append("-".join(parts[:2]))  # duas primeiras
    seen: set[str] = set()
    uniq = [s for s in slugs if s and not (s in seen or seen.add(s))]
    return [f"https://www.linkedin.com/company/{s}" for s in uniq[:5]]


def _tokens(name: str) -> set[str]:
    slug = _slugify(name)
    return {t for t in slug.split("-") if len(t) >= 4}


def _name_matches(query: str, returned: str) -> bool:
    """Confere se a empresa retornada tem relacao com o nome buscado."""
    if not returned:
        return False
    qt, rt = _tokens(query), _tokens(returned)
    if not qt or not rt:
        return False
    return bool(qt & rt)


def _first(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


async def _brightdata_call(dataset_id: str, urls: list[str]) -> tuple[int, Any]:
    """POST sincrono para /scrape. Retorna (status_code, payload|texto)."""
    api_url = f"{BRIGHTDATA_SCRAPE_URL}?dataset_id={dataset_id}&format=json"
    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_API_KEY}",
        "Content-Type": "application/json",
    }
    body = [{"url": u} for u in urls]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(api_url, headers=headers, json=body)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def _is_anon(name: str, link: str) -> bool:
    n = (name or "").strip().lower()
    return (not link) or n in ("", "linkedin member", "membro do linkedin")


def _clean_headline_name(title: str) -> str:
    """O campo 'title' da lista de funcionarios as vezes duplica o nome.

    Ex.: "Reid Hoffman Reid Hoffman is an Influencer" -> "Reid Hoffman".
    """
    t = re.sub(r"\s+is an influencer.*$", "", title or "", flags=re.IGNORECASE).strip()
    words = t.split()
    half = len(words) // 2
    if half and words[:half] == words[half:half * 2]:
        t = " ".join(words[:half])
    return t.strip()


def _collect_company_employees(rec: dict[str, Any]) -> list[dict[str, str]]:
    """Extrai funcionarios em destaque + alumni da resposta do dataset de company."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in ("employees", "alumni"):
        for e in rec.get(key) or []:
            if not isinstance(e, dict):
                continue
            link = (e.get("link") or e.get("url") or "").split("?")[0]
            name = _clean_headline_name(e.get("title") or e.get("name") or "")
            if _is_anon(name, link) or link in seen:
                continue
            seen.add(link)
            out.append({"name": name, "title": "", "url": link})
    return out


def _profile_key(url: str) -> str:
    """Chave estavel de um perfil: o slug apos /in/ (ignora dominio/idioma)."""
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).lower() if m else (url or "").split("?")[0].lower()


def _profile_city(rec: dict[str, Any]) -> str:
    """Cidade da PESSOA (nao da empresa). Prefere 'city'; senao deriva de 'location'."""
    city = _first(rec, "city")
    if city:
        return city
    # location costuma vir "Cidade, Estado, Pais" -> pega a 1a parte.
    loc = _first(rec, "location")
    if loc:
        return loc.split(",")[0].strip()
    return ""


def _profile_role(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    """De um registro de perfil, extrai (url, nome, cargo, cidade_da_pessoa)."""
    url = _first(rec, "url", "input_url", "profile_url").split("?")[0]
    name = _first(rec, "name", "full_name")
    title = _first(rec, "position", "headline")
    if not title:
        cc = rec.get("current_company")
        if isinstance(cc, dict):
            # Apenas o cargo/titulo — nunca o "name" (que e a empresa).
            title = _first(cc, "title", "position")
    city = _profile_city(rec)
    return url, name, title, city


# --------------------------------------------------------------------------
# Bright Data DATASET (Marketplace) — roster completo por empresa
# Fluxo: POST /filter (dispara snapshot) -> GET /snapshot/{id} (poll+download).
# So e usado quando BRIGHTDATA_USE_DATASET esta ligado.
# --------------------------------------------------------------------------

async def _dataset_employees_by_company(company_id: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_API_KEY}",
        "Content-Type": "application/json",
    }
    # Filtra o dataset de perfis por empresa atual (id do LinkedIn).
    filter_body = {
        "dataset_id": BRIGHTDATA_PEOPLE_DATASET_ID,
        "records_limit": BRIGHTDATA_DATASET_LIMIT,
        "filter": {
            "name": "current_company_company_id",
            "operator": "=",
            "value": company_id,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIGHTDATA_FILTER_URL}?format=json", headers=headers, json=filter_body
            )
            if resp.status_code >= 400:
                return _blocked(
                    f"Dataset filter retornou {resp.status_code}: {resp.text[:150]}"
                )
            data = resp.json()
            snapshot_id = (
                data.get("snapshot_id") or data.get("id") or data.get("snapshotId")
            )
            if not snapshot_id:
                return _blocked("Dataset nao retornou snapshot_id.")

            # Poll do snapshot ate ficar pronto (202 = building, 200 = pronto).
            for _ in range(40):  # ~40 x 3s = 2 min
                snap = await client.get(
                    f"{BRIGHTDATA_SNAPSHOT_URL}/{snapshot_id}?format=json",
                    headers=headers,
                )
                if snap.status_code == 202:
                    await asyncio.sleep(3)
                    continue
                if snap.status_code >= 400:
                    return _blocked(
                        f"Snapshot retornou {snap.status_code}: {snap.text[:150]}"
                    )
                payload = snap.json()
                people = _extract_dataset_people(payload)
                return {
                    "status": "ok",
                    "source": "brightdata-dataset",
                    "employees": people,
                    "message": "" if people else "Nenhum perfil no dataset para essa empresa.",
                }
            return _blocked("Snapshot do dataset demorou demais (timeout).")
    except Exception as exc:
        return _blocked(f"Erro no dataset do Bright Data: {str(exc)[:120]}")


def _extract_dataset_people(payload: Any) -> list[dict[str, str]]:
    """Converte registros do dataset de perfis em nome/cargo/url."""
    records = payload if isinstance(payload, list) else payload.get("data", [])
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        url = _first(rec, "url", "input_url").split("?")[0]
        name = _first(rec, "name", "first_name")
        title = _first(rec, "position", "headline")
        if not title:
            cc = rec.get("current_company")
            if isinstance(cc, dict):
                title = _first(cc, "title", "position")
        key = _profile_key(url) or name
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name or "(sem nome)",
            "title": title,
            "city": _profile_city(rec),  # cidade DA PESSOA
            "url": url,
        })
    return out


async def _brightdata_employees(company_name: str, company_legal: str = "") -> dict[str, Any]:
    # 1) Resolve a pagina da empresa e coleta funcionarios em destaque.
    company_rec: dict[str, Any] | None = None
    best_unmatched: dict[str, Any] | None = None
    match_ref = f"{company_legal} {company_name}".strip()
    for url in _company_url_candidates(company_name, company_legal):
        status, payload = await _brightdata_call(DATASET_COMPANY, [url])
        if status == 401:
            return _blocked("BRIGHTDATA_API_KEY invalida ou conta inativa.")
        if status == 402:
            return _blocked("Sem creditos no Bright Data.")
        if status >= 400:
            return _blocked(f"Bright Data retornou {status}: {str(payload)[:150]}")
        rec = payload[0] if isinstance(payload, list) and payload else payload
        if not (isinstance(rec, dict) and rec.get("name")):
            continue
        # Valida que a empresa retornada bate com o nome buscado (evita
        # match fuzzy errado do LinkedIn para slugs inexistentes).
        if _name_matches(match_ref, rec.get("name", "")):
            company_rec = rec
            break
        best_unmatched = best_unmatched or rec

    if not company_rec:
        hint = ""
        if best_unmatched:
            hint = (
                f" (o LinkedIn sugeriu '{best_unmatched.get('name')}', "
                "que nao parece ser a mesma empresa)"
            )
        return _blocked(
            "Nao encontrei a pagina da empresa no LinkedIn a partir do nome"
            + hint
            + ". A empresa pode nao ter LinkedIn ou usar outro nome la."
        )

    company_id = company_rec.get("company_id") or ""
    company_info = {
        "name": company_rec.get("name"),
        "company_id": company_id,
        "linkedin_url": (company_rec.get("url") or "").split("?")[0],
        "employees_in_linkedin": company_rec.get("employees_in_linkedin"),
        "industries": company_rec.get("industries"),
        "headquarters": company_rec.get("headquarters"),
        "website": company_rec.get("website") or company_rec.get("website_simplified"),
    }

    # 1b) Se o dataset estiver LIGADO, busca o roster COMPLETO por empresa.
    # No dataset de perfis, current_company_company_id costuma ser o SLUG
    # (ex.: "microsoft"), entao preferimos o slug da URL ao id numerico.
    if BRIGHTDATA_USE_DATASET:
        url_slug = ""
        m = re.search(r"/company/([^/?#]+)", company_info["linkedin_url"] or "")
        if m:
            url_slug = m.group(1).lower()
        filter_value = url_slug or company_id
        if filter_value:
            ds = await _dataset_employees_by_company(filter_value)
            if ds.get("status") == "ok":
                ds["company"] = company_info
                return ds
            # Se o dataset falhar, cai no caminho free (funcionarios em destaque).

    featured = _collect_company_employees(company_rec)
    if not featured:
        return {
            "status": "ok",
            "source": "brightdata",
            "employees": [],
            "company": company_info,
            "message": (
                "A empresa foi encontrada, mas o LinkedIn nao expos funcionarios "
                "publicos em destaque (muitos aparecem como 'LinkedIn Member')."
            ),
        }

    # 2) Enriquece cargo via dataset de perfis (batch, ate 20 URLs).
    profile_urls = [e["url"] for e in featured][:20]
    status, payload = await _brightdata_call(DATASET_PEOPLE_PROFILE, profile_urls)
    roles: dict[str, str] = {}
    names: dict[str, str] = {}
    cities: dict[str, str] = {}
    if status < 400 and isinstance(payload, list):
        for rec in payload:
            if not isinstance(rec, dict):
                continue
            url, name, title, city = _profile_role(rec)
            key = _profile_key(url) or _profile_key(rec.get("input_url", ""))
            if key:
                if title:
                    roles[key] = title
                if name:
                    names[key] = name
                if city:
                    cities[key] = city

    employees = []
    for e in featured:
        k = _profile_key(e["url"])
        employees.append({
            "name": names.get(k, e["name"]) or e["name"],
            "title": roles.get(k, ""),
            "city": cities.get(k, ""),  # cidade DA PESSOA (do perfil LinkedIn)
            "url": e["url"],
        })

    return {
        "status": "ok",
        "source": "brightdata",
        "employees": employees,
        "company": company_info,
        "message": "",
    }


# --------------------------------------------------------------------------
# Fallback: Google
# --------------------------------------------------------------------------

def _split_name_title(text: str) -> tuple[str, str]:
    text = re.sub(r"\s*\|\s*LinkedIn.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*-\s*LinkedIn.*$", "", text, flags=re.IGNORECASE).strip()
    parts = re.split(r"\s+[-–—]\s+", text)
    name = parts[0].strip() if parts else text
    title = " - ".join(p.strip() for p in parts[1:]) if len(parts) > 1 else ""
    return name, title


def _clean_google_url(href: str) -> str:
    if href.startswith("/url?q="):
        href = href[len("/url?q="):]
        href = href.split("&")[0]
    return href


def _is_linkedin_profile(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    return "linkedin.com" in p.netloc and "/in/" in p.path


async def _google_search(company_name: str) -> dict[str, Any]:
    query = f'site:linkedin.com/in "{company_name}"'
    url = f"https://www.google.com/search?q={quote_plus(query)}&num=20&hl=pt-BR"

    headers = dict(BROWSER_HEADERS)
    if LINKEDIN_LI_AT:
        headers["Cookie"] = f"li_at={LINKEDIN_LI_AT}"

    try:
        async with httpx.AsyncClient(
            timeout=_GOOGLE_TIMEOUT, headers=headers, follow_redirects=True
        ) as client:
            resp = await client.get(url)
    except Exception:
        return _blocked(
            "Nao foi possivel conectar ao Google/LinkedIn. "
            "Configure BRIGHTDATA_API_KEY para scraping confiavel."
        )

    if resp.status_code in (429, 999) or resp.status_code >= 400:
        return _blocked(
            "Google/LinkedIn bloqueou a requisicao. "
            "Configure BRIGHTDATA_API_KEY para scraping confiavel."
        )

    html = resp.text
    if "captcha" in html.lower() or "unusual traffic" in html.lower():
        return _blocked(
            "Google exigiu captcha. Configure BRIGHTDATA_API_KEY para scraping confiavel."
        )

    soup = BeautifulSoup(html, "lxml")
    employees: list[dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = _clean_google_url(a["href"])
        if not _is_linkedin_profile(href) or href in seen:
            continue

        h3 = a.find("h3")
        text = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
        if not text:
            continue

        name, title = _split_name_title(text)
        if not name:
            continue

        seen.add(href)
        employees.append({"name": name, "title": title, "url": href.split("?")[0]})

    if not employees:
        return _blocked(
            "Nenhum resultado publico encontrado. "
            "Configure BRIGHTDATA_API_KEY para scraping confiavel."
        )

    return {"status": "ok", "source": "google", "employees": employees, "message": ""}


# --------------------------------------------------------------------------
# Entrada publica
# --------------------------------------------------------------------------

async def scrape_employees(
    cnpj: str, company_name: str, company_legal: str = ""
) -> dict[str, Any]:
    """Faz scraping dos funcionarios e cacheia por CNPJ.

    Usa Bright Data quando BRIGHTDATA_API_KEY estiver definida; senao, cai no
    fallback do Google.
    """
    if cnpj in _CACHE:
        return _CACHE[cnpj]

    if not company_name and not company_legal:
        return _blocked("Nome da empresa indisponivel para a busca no LinkedIn.")

    if BRIGHTDATA_API_KEY:
        result = await _brightdata_employees(company_name or company_legal, company_legal)
    else:
        await asyncio.sleep(random.uniform(0.4, 1.1))
        result = await _google_search(company_name)

    if result.get("status") == "ok":
        _CACHE[cnpj] = result
    return result
