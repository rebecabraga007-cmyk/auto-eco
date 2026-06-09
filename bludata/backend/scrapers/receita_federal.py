"""
Receita Federal / ReceitaWS / CNPJ.ws scrapers.
Falls back gracefully if blocked.
"""
import httpx
import asyncio
from typing import Optional

RECEITAWS_URL = "https://www.receitaws.com.br/v1/cnpj/{cnpj}"
CNPJWS_URL = "https://publica.cnpj.ws/cnpj/{cnpj}"
TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def fetch_receitaws(cnpj: str) -> dict:
    """Fetch CNPJ data from ReceitaWS (free, no key)."""
    cnpj_clean = "".join(filter(str.isdigit, cnpj))
    url = RECEITAWS_URL.format(cnpj=cnpj_clean)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ERROR":
                    return {"sucesso": False, "source": "receitaws", "error": data.get("message", "Not found"), "data": {}}
                return {"sucesso": True, "source": "receitaws", "data": data}
            elif resp.status_code == 429:
                return {"sucesso": False, "source": "blocked", "error": "Rate limited", "data": {}}
            else:
                return {"sucesso": False, "source": "receitaws", "error": f"HTTP {resp.status_code}", "data": {}}
    except Exception as e:
        return {"sucesso": False, "source": "blocked", "error": str(e), "data": {}}


async def fetch_cnpjws(cnpj: str) -> dict:
    """Fetch CNPJ data from CNPJ.ws (free, includes QSA and secondary activities)."""
    cnpj_clean = "".join(filter(str.isdigit, cnpj))
    url = CNPJWS_URL.format(cnpj=cnpj_clean)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"sucesso": True, "source": "cnpjws", "data": resp.json()}
            elif resp.status_code == 404:
                return {"sucesso": False, "source": "cnpjws", "error": "CNPJ not found", "data": {}}
            elif resp.status_code == 429:
                return {"sucesso": False, "source": "blocked", "error": "Rate limited", "data": {}}
            else:
                return {"sucesso": False, "source": "cnpjws", "error": f"HTTP {resp.status_code}", "data": {}}
    except Exception as e:
        return {"sucesso": False, "source": "blocked", "error": str(e), "data": {}}


def parse_receitaws(data: dict) -> dict:
    """Normalize ReceitaWS response to our format."""
    d = data.get("data", {})
    if not d:
        return {}

    partners = []
    for q in d.get("qsa", []):
        partners.append({
            "name": q.get("nome", ""),
            "role": q.get("qual", ""),
        })

    municipio = d.get("municipio", "")
    uf = d.get("uf", "")
    location = f"{municipio}, {uf}" if municipio and uf else municipio or uf

    atividades = d.get("atividade_principal", [{}])
    cnae_desc = atividades[0].get("text", "") if atividades else ""
    cnae_code = atividades[0].get("code", "") if atividades else ""

    return {
        "cnpj": d.get("cnpj", ""),
        "name": d.get("nome", ""),
        "trade_name": d.get("fantasia", ""),
        "sector": cnae_desc,
        "cnae_code": cnae_code,
        "cnae_desc": cnae_desc,
        "location": location,
        "state": uf,
        "zip_code": d.get("cep", ""),
        "phone": d.get("telefone", ""),
        "email": d.get("email", ""),
        "founded_at": d.get("abertura", ""),
        "legal_nature": d.get("natureza_juridica", ""),
        "employee_range": d.get("porte", ""),
        "simples_nacional": d.get("simples", {}).get("optante", None) if isinstance(d.get("simples"), dict) else None,
        "mei": d.get("mei", {}).get("optante", None) if isinstance(d.get("mei"), dict) else None,
        "partners": partners,
        "source": "receitaws",
    }


async def fetch_cpf_situacao(cpf: str) -> dict:
    """
    CPF situation from Receita Federal.
    NOTE: The official endpoint requires CAPTCHA. We return a graceful placeholder.
    """
    # The Receita Federal CPF endpoint uses CAPTCHA that cannot be bypassed automatically.
    # A real implementation would need a CAPTCHA-solving service.
    return {
        "sucesso": False,
        "source": "blocked",
        "error": "CPF lookup requires CAPTCHA resolution. Integration with anti-CAPTCHA service needed.",
        "data": {
            "cpf": cpf,
            "nome": None,
            "situacao": "Não disponível (CAPTCHA)",
            "nota": "Consulta CPF na Receita Federal requer resolução de CAPTCHA. Plugue um serviço anti-CAPTCHA para habilitar.",
        }
    }
