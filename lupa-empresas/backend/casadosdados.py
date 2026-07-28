"""Busca avançada de empresas via Casa dos Dados (estilo Datastone/Lusha).

Endpoint público (sem auth), descoberto por engenharia reversa do site:
  POST https://api.casadosdados.com.br/v5/public/cnpj/pesquisa

Aceita filtros de CNAE, natureza jurídica, situação cadastral, UF, município,
bairro, CEP, DDD, capital social, data de abertura, MEI/Simples e busca textual.
Retorna {total, cnpjs:[{cnpj, razao_social, nome_fantasia, situacao_cadastral}]}.

A lista traz só campos básicos; o enriquecimento (porte, capital, QSA, telefones)
vem depois por CNPJ via BrasilAPI + Mk + JBR.
"""

import asyncio

try:
    import cloudscraper as _cs_mod
    _scraper = _cs_mod.create_scraper()
except Exception:
    _scraper = None

PESQUISA_URL = "https://api.casadosdados.com.br/v5/public/cnpj/pesquisa"

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://casadosdados.com.br",
    "Referer": "https://casadosdados.com.br/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


def enabled() -> bool:
    return _scraper is not None


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _build_body(f: dict, limite: int) -> dict:
    """Monta o corpo do POST a partir de um dict de filtros amigável.

    Chaves aceitas em `f` (todas opcionais):
      texto, tipo_busca ('exata'|'contem'), cnae (lista/csv), natureza (lista/csv),
      situacao (lista/csv, ex. ['ATIVA']), uf (lista/csv), municipio, bairro,
      cep, ddd, incluir_atividade_secundaria (bool),
      capital_min, capital_max (int), data_abertura_de, data_abertura_ate (YYYY-MM-DD),
      mei_optante, mei_excluir, simples_optante, simples_excluir,
      somente_matriz, somente_filial, com_email, com_telefone,
      somente_fixo, somente_celular (bools).
    """
    data_abertura: dict = {}
    if f.get("data_abertura_de"):
        data_abertura["inicio"] = f["data_abertura_de"]
    if f.get("data_abertura_ate"):
        data_abertura["fim"] = f["data_abertura_ate"]

    texto = (f.get("texto") or "").strip()
    # A API só aceita dois modos de busca textual: 'exata' e 'radical' (por raiz da palavra).
    tipo = (f.get("tipo_busca") or "radical").lower()
    if tipo not in ("exata", "radical"):
        tipo = "radical"
    busca_textual = []
    if texto:
        busca_textual = [{
            "texto": [texto],
            "tipo_busca": tipo,
            "razao_social": True,
            "nome_fantasia": True,
            "nome_socio": bool(f.get("buscar_socio", True)),
        }]

    return {
        "cnpj": [],
        "cnpj_raiz": [],
        "situacao_cadastral": _as_list(f.get("situacao")),
        "codigo_atividade_principal": _as_list(f.get("cnae")),
        "codigo_natureza_juridica": _as_list(f.get("natureza")),
        "incluir_atividade_secundaria": bool(f.get("incluir_atividade_secundaria")),
        "uf": _as_list(f.get("uf")),
        "municipio": _as_list(f.get("municipio")),
        "bairro": _as_list(f.get("bairro")),
        "cep": _as_list(f.get("cep")),
        "ddd": _as_list(f.get("ddd")),
        "data_abertura": data_abertura,
        "capital_social": {
            "minimo": int(f.get("capital_min") or 0),
            "maximo": int(f.get("capital_max") or 0),
        },
        "mei": {
            "optante": bool(f.get("mei_optante")),
            "excluir_optante": bool(f.get("mei_excluir")),
        },
        "simples": {
            "optante": bool(f.get("simples_optante")),
            "excluir_optante": bool(f.get("simples_excluir")),
        },
        "mais_filtros": {
            "somente_matriz": bool(f.get("somente_matriz")),
            "somente_filial": bool(f.get("somente_filial")),
            "com_email": bool(f.get("com_email")),
            "com_telefone": bool(f.get("com_telefone")),
            "somente_fixo": bool(f.get("somente_fixo")),
            "somente_celular": bool(f.get("somente_celular")),
        },
        "limite": max(1, min(int(limite or 20), 1000)),
        "busca_textual": busca_textual,
    }


def _simplify(item: dict) -> dict:
    sit = item.get("situacao_cadastral") or {}
    sit_str = sit.get("situacao_atual") if isinstance(sit, dict) else (sit or "")
    return {
        "cnpj": str(item.get("cnpj", "")),
        "razao_social": item.get("razao_social") or "",
        "nome_fantasia": item.get("nome_fantasia") or "",
        "situacao": sit_str or "",
    }


def _sync_search(body: dict) -> dict:
    if not _scraper:
        raise RuntimeError("cloudscraper indisponível")
    resp = _scraper.post(PESQUISA_URL, json=body, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def pesquisa_avancada(filtros: dict, limite: int = 20) -> dict:
    """Executa a busca avançada e retorna {status, total, empresas}."""
    body = _build_body(filtros or {}, limite)
    loop = asyncio.get_event_loop()
    try:
        j = await loop.run_in_executor(None, _sync_search, body)
        empresas = [_simplify(x) for x in (j.get("cnpjs") or [])]
        return {"status": "ok", "total": j.get("total", len(empresas)), "empresas": empresas}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200], "total": 0, "empresas": []}
