"""Substituição de variáveis nos modelos de mensagem.

Deliberadamente burro: `{{chave}}` troca por texto, sem expressão, sem laço e
sem execução. Modelo de mensagem é conteúdo editável por usuário — um motor de
template de verdade (Jinja) daria a quem escreve o texto o poder de ler o
processo inteiro.
"""
import re

_VAR = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.IGNORECASE)


def lead_vars(lead, user=None) -> dict[str, str]:
    """As variáveis que um modelo pode usar, todas já em texto."""
    first = (lead.first_name or (lead.name or "").split(" ")[0] or "").strip()
    return {
        "nome": lead.name or "",
        "primeiro_nome": first,
        "empresa": lead.company or "",
        "razao_social": lead.razao_social or "",
        "cargo": lead.position or "",
        "email": lead.email or "",
        "telefone": lead.phone or "",
        "cidade": lead.city or "",
        "estado": lead.state or "",
        "cnpj": lead.cnpj or "",
        "remetente": (getattr(user, "name", "") or ""),
        "remetente_email": (getattr(user, "email", "") or ""),
    }


def render(text: str, values: dict[str, str]) -> str:
    return _VAR.sub(lambda m: values.get(m.group(1).lower(), m.group(0)), text or "")


def missing(text: str, values: dict[str, str]) -> list[str]:
    """Variáveis usadas no texto que ficariam vazias — o aviso do editor.

    Uma variável que não resolve é pior que erro de digitação: o e-mail sai com
    "Olá {{primeiro_nome}}" para um lead de verdade.
    """
    used = {m.group(1).lower() for m in _VAR.finditer(text or "")}
    return sorted(v for v in used if not (values.get(v) or "").strip())
