"""
ai_header_detector.py
---------------------
Detecta dinamicamente a estrutura de qualquer planilha usando Mistral AI.
Identifica a linha de cabeçalho e mapeia as colunas para os campos necessários,
permitindo que qualquer planilha seja aceita — não apenas as do Mais Obras.
"""

import json
import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

# Palavras-chave por campo (fallback sem IA)
_KEYWORDS: dict[str, list[str]] = {
    "profissional": [
        "profissional", "arquiteto", "engenheiro", "responsavel",
        "tecnico", "projetista", "professional", "architect",
    ],
    "proprietario": [
        "proprietar", "cliente", "dono", "owner", "contratante",
        "comprador", "tomador", "solicitante",
    ],
    "cidade": ["cidade", "municipio", "city", "localidade"],
    "uf": ["uf", "estado", "state"],
    "endereco": ["endere", "logradouro", "rua", "address", "local"],
}


def _norm(texto: str) -> str:
    """Remove acentos e coloca em minúsculo para comparação."""
    if not texto:
        return ""
    txt = unicodedata.normalize("NFD", str(texto))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return txt.strip().lower()


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------

def detectar_estrutura_planilha(primeiras_linhas: list[list]) -> dict:
    """
    Analisa as primeiras linhas de uma planilha e retorna:

        {
            "header_row_index": int,      # índice base-0 da linha de cabeçalho
            "profissional": int | None,   # índice da coluna
            "proprietario": int | None,
            "cidade": int | None,
            "uf": int | None,
            "endereco": int | None,
        }

    Tenta Mistral AI primeiro; em caso de falha usa detecção por palavras-chave.
    """
    if MISTRAL_API_KEY:
        resultado = _detectar_com_mistral(primeiras_linhas)
        if resultado is not None:
            return resultado

    logger.warning(
        "Mistral indisponível ou falhou — usando detecção por palavras-chave."
    )
    return _detectar_por_palavras_chave(primeiras_linhas)


# ---------------------------------------------------------------------------
# Detecção via Mistral AI
# ---------------------------------------------------------------------------

def _detectar_com_mistral(primeiras_linhas: list[list]) -> dict | None:
    try:
        from mistralai import Mistral

        client = Mistral(api_key=MISTRAL_API_KEY)

        linhas_str = json.dumps(
            [[str(c) if c is not None else "" for c in row] for row in primeiras_linhas],
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""Você analisa planilhas de obras de construção civil.

Receba as primeiras linhas de uma planilha (índice base 0) e identifique:
1. Qual índice de linha contém os CABEÇALHOS das colunas
2. Qual índice de coluna corresponde a cada campo necessário

Dados da planilha ({len(primeiras_linhas)} primeiras linhas):
{linhas_str}

Campos necessários:
- profissional: nome do profissional / arquiteto / engenheiro / responsável técnico
- proprietario: nome do proprietário / cliente / dono / contratante
- cidade: nome da cidade / município da obra
- uf: estado / UF (sigla de 2 letras: SP, RJ, MG, etc.)
- endereco: endereço / logradouro / rua da obra (null se não existir)

Regras importantes:
- Linhas com título genérico ("Meus Favoritos", "Relatório"), datas soltas ou células em branco NÃO são cabeçalhos
- O cabeçalho real tem nomes de colunas descritivos (substantivos, labels)
- Se não encontrar um campo, use null
- Os índices são base-0 (primeira linha = 0, primeira coluna = 0)

Responda SOMENTE com JSON válido, sem markdown, sem texto extra:
{{
  "header_row_index": <número>,
  "profissional": <número ou null>,
  "proprietario": <número ou null>,
  "cidade": <número ou null>,
  "uf": <número ou null>,
  "endereco": <número ou null>
}}"""

        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )

        content = response.choices[0].message.content.strip()

        # Remove markdown code block se presente
        md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if md_match:
            content = md_match.group(1).strip()

        result = json.loads(content)

        if "header_row_index" not in result:
            raise ValueError("Resposta da IA não contém 'header_row_index'")

        # Garante que campos ausentes viram None
        for campo in ("profissional", "proprietario", "cidade", "uf", "endereco"):
            result.setdefault(campo, None)

        logger.info("Estrutura detectada pela IA Mistral: %s", result)
        return result

    except Exception as exc:
        logger.warning("Falha na detecção por Mistral: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Fallback: palavras-chave
# ---------------------------------------------------------------------------

def _detectar_por_palavras_chave(primeiras_linhas: list[list]) -> dict:
    """Detecta cabeçalho e mapeamento por correspondência de palavras-chave."""

    melhor_linha = 0
    melhor_score = -1
    melhor_mapeamento: dict[str, int | None] = {
        "profissional": None,
        "proprietario": None,
        "cidade": None,
        "uf": None,
        "endereco": None,
    }

    for row_idx, row in enumerate(primeiras_linhas[:10]):
        mapeamento: dict[str, int | None] = {
            "profissional": None,
            "proprietario": None,
            "cidade": None,
            "uf": None,
            "endereco": None,
        }
        score = 0

        for col_idx, cell in enumerate(row):
            cell_norm = _norm(str(cell or ""))
            if not cell_norm:
                continue
            for campo, keywords in _KEYWORDS.items():
                if mapeamento[campo] is None:
                    for kw in keywords:
                        if kw in cell_norm:
                            mapeamento[campo] = col_idx
                            score += 1
                            break

        if score > melhor_score:
            melhor_score = score
            melhor_linha = row_idx
            melhor_mapeamento = mapeamento

    logger.info(
        "Estrutura por palavras-chave: header_row_index=%d score=%d mapeamento=%s",
        melhor_linha,
        melhor_score,
        melhor_mapeamento,
    )
    return {"header_row_index": melhor_linha, **melhor_mapeamento}
