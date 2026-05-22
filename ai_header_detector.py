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
# ATENÇÃO: evitar substrings que colidam com outros campos
# Ex: "socia" colide com "razão SOCIAl" → usar "socio" (não bate em "social")
_KEYWORDS: dict[str, list[str]] = {
    "profissional": [
        # Pessoa física / profissional liberal
        "profissional", "arquiteto", "engenheiro",
        "tecnico", "projetista", "professional", "architect",
        # Fallback — nome de empresa como identificador
        "razao social", "nome fantasia", "empresa",
    ],
    "proprietario": [
        # Pessoa física — dono ou cliente
        "proprietar", "cliente", "dono", "owner", "contratante",
        "comprador", "tomador", "solicitante", "responsavel",
        # Sócios de empresas (CNPJ / Receita Federal)
        # NÃO use "socia" — conflito com "razão SOCIAl", "capital SOCIAl"
        "socio",   # bate em "socios", "sócio", "sócios"
        "partner",
    ],
    "cidade": ["cidade", "municipio", "city", "localidade"],
    "uf": ["uf", "estado", "state", "sigla", "sg_uf"],
    "endereco": ["endere", "logradouro", "rua", "address", "local"],
}

# Siglas de estados brasileiros — para extração do endereço quando não há coluna UF
_UF_BR = {
    "AC","AL","AM","AP","BA","CE","DF","ES","GO",
    "MA","MG","MS","MT","PA","PB","PE","PI","PR",
    "RJ","RN","RO","RR","RS","SC","SE","SP","TO",
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

        prompt = f"""Você analisa planilhas relacionadas a construção civil e empresas do setor.

Receba as primeiras linhas de uma planilha (índice base 0) e identifique:
1. Qual índice de linha contém os CABEÇALHOS das colunas
2. Qual índice de coluna corresponde a cada campo necessário

Dados da planilha ({len(primeiras_linhas)} primeiras linhas):
{linhas_str}

Campos necessários (mapeie o MELHOR candidato para cada um):
- profissional: nome da pessoa física responsável / arquiteto / engenheiro / profissional
  → Se não houver pessoa física, use coluna de nome da empresa / razão social / nome fantasia
- proprietario: nome do proprietário / cliente / sócio / responsável legal / dono
  → Coluna "Sócios" ou "Sócio" se presente
- cidade: nome da cidade / município
  → null se não houver coluna dedicada (mesmo que o endereço contenha a cidade)
- uf: estado / UF / sigla do estado (SP, RJ, MG...)
  → null se não houver coluna dedicada
- endereco: endereço completo / logradouro / rua
  → null se não existir

Regras:
- Linhas com título genérico, datas soltas ou em branco NÃO são cabeçalho
- Índices são base-0 (linha 0 = primeira linha, coluna 0 = primeira coluna)
- Prefira mapear algo a deixar null — use o melhor candidato disponível
- "Sócios", "Sócio", "Responsável" → proprietario
- "Razão Social", "Nome Fantasia", "Empresa" → profissional (se não houver pessoa física)

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
        colunas_usadas: set[int] = set()  # evita dois campos na mesma coluna

        for col_idx, cell in enumerate(row):
            cell_norm = _norm(str(cell or ""))
            if not cell_norm:
                continue
            for campo, keywords in _KEYWORDS.items():
                if mapeamento[campo] is None and col_idx not in colunas_usadas:
                    for kw in keywords:
                        if kw in cell_norm:
                            mapeamento[campo] = col_idx
                            colunas_usadas.add(col_idx)
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


# ---------------------------------------------------------------------------
# Extração de UF a partir de valores de endereço
# ---------------------------------------------------------------------------

_RE_UF = re.compile(r"\b(" + "|".join(sorted(_UF_BR, reverse=True)) + r")\b")


def extrair_uf_de_texto(texto: str) -> str:
    """
    Tenta encontrar uma sigla de estado brasileiro em um texto livre.
    Exemplo: 'RUA FOO, 10 - JUNDIAI - SP' → 'SP'
    Retorna '' se não encontrar.
    """
    if not texto:
        return ""
    m = _RE_UF.search(str(texto).upper())
    return m.group(1) if m else ""
