"""BrasilAPI wrapper — free, no API key required."""
import httpx
import asyncio
from typing import Optional

BASE_URL = "https://brasilapi.com.br/api"
TIMEOUT = 15


async def fetch_cnpj(cnpj: str) -> dict:
    """Fetch company data from BrasilAPI CNPJ endpoint."""
    cnpj_clean = "".join(filter(str.isdigit, cnpj))
    url = f"{BASE_URL}/cnpj/v1/{cnpj_clean}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return {"sucesso": True, "source": "brasilapi", "data": data}
            else:
                return {"sucesso": False, "source": "brasilapi", "error": f"HTTP {resp.status_code}", "data": {}}
    except Exception as e:
        return {"sucesso": False, "source": "blocked", "error": str(e), "data": {}}


async def fetch_cep(cep: str) -> dict:
    """Fetch address from BrasilAPI CEP endpoint."""
    cep_clean = "".join(filter(str.isdigit, cep))
    url = f"{BASE_URL}/cep/v1/{cep_clean}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"sucesso": True, "source": "brasilapi", "data": resp.json()}
            return {"sucesso": False, "source": "brasilapi", "error": f"HTTP {resp.status_code}", "data": {}}
    except Exception as e:
        return {"sucesso": False, "source": "blocked", "error": str(e), "data": {}}


async def fetch_municipios(uf: str) -> dict:
    """Fetch municipalities by state from BrasilAPI."""
    url = f"{BASE_URL}/ibge/municipios/v1/{uf.upper()}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"sucesso": True, "source": "brasilapi", "data": resp.json()}
            return {"sucesso": False, "source": "brasilapi", "error": f"HTTP {resp.status_code}", "data": []}
    except Exception as e:
        return {"sucesso": False, "source": "blocked", "error": str(e), "data": []}


def parse_brasilapi_cnpj(data: dict) -> dict:
    """Normalize BrasilAPI CNPJ response to our CompanyRecord format."""
    d = data.get("data", {})
    if not d:
        return {}

    partners = []
    for qsa in d.get("qsa", []):
        partners.append({
            "name": qsa.get("nome_socio", ""),
            "role": qsa.get("qualificacao_socio", ""),
            "cpf_cnpj": qsa.get("cnpj_cpf_do_socio", ""),
        })

    atividade_principal = d.get("cnae_fiscal_descricao", "") or (
        d.get("atividade_principal", [{}])[0].get("text", "") if d.get("atividade_principal") else ""
    )
    cnae_code = str(d.get("cnae_fiscal", "")) or (
        d.get("atividade_principal", [{}])[0].get("code", "") if d.get("atividade_principal") else ""
    )

    municipio = d.get("municipio", "")
    uf = d.get("uf", "")
    location = f"{municipio}, {uf}" if municipio and uf else municipio or uf

    return {
        "cnpj": d.get("cnpj", ""),
        "name": d.get("razao_social", ""),
        "trade_name": d.get("nome_fantasia", ""),
        "sector": atividade_principal,
        "cnae_code": cnae_code,
        "cnae_desc": atividade_principal,
        "location": location,
        "state": uf,
        "zip_code": d.get("cep", ""),
        "phone": d.get("ddd_telefone_1", ""),
        "email": d.get("email", ""),
        "founded_at": d.get("data_inicio_atividade", ""),
        "legal_nature": d.get("natureza_juridica", ""),
        "simples_nacional": None,
        "mei": None,
        "partners": partners,
        "source": "brasilapi",
    }
