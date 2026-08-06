"""Integração com donodozap.com — identifica o titular de um número WhatsApp.

Fluxo (Next.js Server Action):
  1. POST /telefone/{phone} com header next-action fixo → retorna RSC stream com UUID
  2. GET /resultado?id={uuid} com Accept:text/x-component → RSC stream com names/maskedCpfs

Retorna {status, phone, names, masked_cpfs, match} onde match é True se o nome
passado aparece na lista de titulares.
"""

import asyncio
import json
import re
import unicodedata
from urllib.parse import quote

try:
    import cloudscraper as _cs_mod
    _scraper = _cs_mod.create_scraper()
except Exception:
    _scraper = None

BASE = "https://donodozap.com"
# Next.js server action hash — pode mudar em novos deploys
NEXT_ACTION = "60c2a30d14d4f57be1320216de6021b3a8b48f0b0e"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_cache: dict[str, dict] = {}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _format_phone(raw: str) -> str:
    """Normaliza para 10 ou 11 dígitos (DDD + número, sem +55)."""
    d = _only_digits(raw)
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    return d


def _router_tree(phone: str) -> str:
    tree = json.dumps(
        ["", {"children": ["telefone", {"children": [[
            "numero", phone, "d"],
            {"children": ["__PAGE__", {}, None, None]},
            None, None
        ]}, None, None]}, None, None, True]
    )
    return quote(tree)


def _extract_uuid(rsc_text: str) -> str | None:
    m = re.search(r'"id"\s*:\s*"([0-9a-f\-]{36})"', rsc_text)
    return m.group(1) if m else None


def _extract_results(rsc_text: str) -> dict:
    """Extrai names e maskedCpfs do RSC stream do resultado."""
    # O payload está em "names":[...], "maskedCpfs":[...]
    names_m = re.search(r'"names"\s*:\s*(\[[^\]]+\])', rsc_text)
    cpfs_m = re.search(r'"maskedCpfs"\s*:\s*(\[[^\]]+\])', rsc_text)
    phone_m = re.search(r'"phone"\s*:\s*"([^"]+)"', rsc_text)

    names, cpfs = [], []
    try:
        if names_m:
            names = json.loads(names_m.group(1))
        if cpfs_m:
            cpfs = json.loads(cpfs_m.group(1))
    except Exception:
        pass

    return {
        "names": names,
        "masked_cpfs": cpfs,
        "phone_display": phone_m.group(1) if phone_m else "",
    }


def _match_name(query_name: str, candidates: list[str]) -> str | None:
    """Retorna o candidato que melhor bate com query_name (palavras em comum ≥ 2)."""
    qn = set(_norm(query_name).split())
    if not qn:
        return None
    best, best_score = None, 0
    for c in candidates:
        cn = set(_norm(c).split())
        shared = len(qn & cn)
        if shared >= 2 and shared > best_score:
            best, best_score = c, shared
    return best


def _sync_post(phone: str) -> str:
    """POST /telefone/{phone} via cloudscraper. Retorna RSC text."""
    if not _scraper:
        raise RuntimeError("cloudscraper indisponível")
    url = f"{BASE}/telefone/{phone}"
    headers = {
        "Accept": "text/x-component",
        "next-action": NEXT_ACTION,
        "next-router-state-tree": _router_tree(phone),
        "User-Agent": _UA,
        "Referer": f"{BASE}/telefone/{phone}",
        "Origin": BASE,
    }
    # FormData vazia (Next.js aceita sem campos extras para este action)
    resp = _scraper.post(url, headers=headers, data={}, timeout=25)
    resp.raise_for_status()
    return resp.text


def _sync_get_resultado(uuid: str) -> str:
    """GET /resultado?id={uuid} com headers RSC."""
    if not _scraper:
        raise RuntimeError("cloudscraper indisponível")
    url = f"{BASE}/resultado?id={uuid}"
    tree = quote(json.dumps(["", {"children": ["resultado", {"children": ["__PAGE__", {}]}]}]))
    headers = {
        "Accept": "text/x-component",
        "RSC": "1",
        "next-router-state-tree": tree,
        "User-Agent": _UA,
        "Referer": url,
    }
    resp = _scraper.get(url, headers=headers, timeout=25)
    resp.raise_for_status()
    return resp.text


async def consultar(phone_raw: str, nome_esperado: str = "") -> dict:
    """Consulta o donodozap para um número e valida contra nome_esperado.

    Retorna:
    {
      status: "ok" | "not_found" | "error",
      phone: "...",         # normalizado
      names: [...],         # todos os titulares encontrados
      masked_cpfs: [...],   # CPFs mascarados correspondentes
      match: str | None,    # nome que bateu (ou None)
      confidence: "high" | "low" | None
    }
    """
    phone = _format_phone(phone_raw)
    if not phone or len(phone) < 10:
        return {"status": "error", "message": "Telefone inválido", "phone": phone_raw}

    if phone in _cache:
        cached = _cache[phone].copy()
        cached["_from_cache"] = True
        if nome_esperado:
            cached["match"] = _match_name(nome_esperado, cached.get("names", []))
            cached["confidence"] = "high" if cached["match"] else "low"
        return cached

    loop = asyncio.get_event_loop()
    try:
        # 1. POST → UUID
        try:
            rsc_post = await loop.run_in_executor(None, _sync_post, phone)
        except Exception as post_exc:
            # O Server Action exige um token Cloudflare Turnstile (cf-turnstile-response)
            # gerado por um navegador real. Sem ele o servidor responde 500 — não dá
            # para validar server-side sem resolver o CAPTCHA (o que não fazemos).
            return {
                "status": "blocked",
                "message": ("DonoDoZap protegido por Cloudflare Turnstile (CAPTCHA); "
                            "validação automática indisponível."),
                "detail": str(post_exc)[:150],
                "phone": phone, "names": [], "masked_cpfs": [],
                "match": None, "confidence": None,
            }
        uuid = _extract_uuid(rsc_post)
        if not uuid:
            return {"status": "blocked",
                    "message": ("DonoDoZap não retornou resultado (provável Cloudflare "
                                "Turnstile/CAPTCHA); validação automática indisponível."),
                    "phone": phone, "names": [], "masked_cpfs": [],
                    "match": None, "confidence": None}

        # 2. GET resultado → dados
        rsc_resultado = await loop.run_in_executor(None, _sync_get_resultado, uuid)
        data = _extract_results(rsc_resultado)

        result = {
            "status": "ok" if data["names"] else "not_found",
            "phone": phone,
            "phone_display": data["phone_display"],
            "names": data["names"],
            "masked_cpfs": data["masked_cpfs"],
            "match": None,
            "confidence": None,
        }

        if nome_esperado and data["names"]:
            m = _match_name(nome_esperado, data["names"])
            result["match"] = m
            result["confidence"] = "high" if m else "low"

        _cache[phone] = result.copy()
        return result

    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200], "phone": phone, "names": [], "masked_cpfs": [], "match": None, "confidence": None}
