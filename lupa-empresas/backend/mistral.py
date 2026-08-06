"""Insight gerado por IA (Mistral) sobre uma pessoa, pro fim do dossiê.

Gera dois textos a partir do JSON consolidado do dossiê (mesmo dict que vira
o PDF): um resumo objetivo da vida da pessoa e um perfil psicológico inferido
do padrão de consumo/emprego/estilo de vida.

IMPORTANTE: perfil psicológico gerado por IA a partir de dado de consumo é
INFERÊNCIA ESTATÍSTICA FRÁGIL, não avaliação clínica — o PDF deixa isso
explícito (aviso). Decisão do usuário, ciente do risco (LGPD / perfilamento
automatizado), manter esse disclaimer sempre visível.
"""
import os
from typing import Any

import httpx

API_URL = "https://api.mistral.ai/v1/chat/completions"
API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest").strip()
_TIMEOUT = httpx.Timeout(30.0)


def enabled() -> bool:
    return bool(API_KEY)


def _fmt_historico(itens: list[dict[str, Any]]) -> str:
    linhas = []
    for h in itens or []:
        cargo = h.get("cboDescricao", "")
        empresa = h.get("razaoSocial", "")
        data = h.get("dataRegistro", "")
        linhas.append(f"{cargo} em {empresa} ({data})")
    return "; ".join(linhas)


def _fmt_familia(parentes: list[dict[str, Any]]) -> str:
    """Resumo por parente, incluindo o enriquecimento da Mk quando a busca de
    família (opt-in) rodou — sem isso, o insight só sabia "tem N parentes",
    nunca dizia nada real sobre eles."""
    linhas = []
    for p in parentes or []:
        nome, grau = p.get("nome", ""), (p.get("grau") or "").split("(")[0].strip()
        r = p.get("resumo")
        if r:
            detalhe = ", ".join(x for x in [
                f"situação {r['situacao_cpf'].lower()}" if r.get("situacao_cpf") else "",
                f"renda R$ {r['renda']}" if r.get("renda") else "",
                f"risco {r['score_faixa'].lower()}" if r.get("score_faixa") else "",
                f"profissão {r['profissao']}" if r.get("profissao") else "",
                f"vínculo com {', '.join(r['empresas_vinculadas'])}" if r.get("empresas_vinculadas") else "",
            ] if x)
            linhas.append(f"{nome} ({grau}): {detalhe or 'sem dados adicionais'}")
        else:
            linhas.append(f"{nome} ({grau})")
    return "; ".join(linhas)


def _resumo_dados_para_prompt(d: dict[str, Any]) -> str:
    """Reduz o dict do dossiê a um texto compacto pro prompt (sem mandar o
    JSON inteiro — só o que é relevante pro insight)."""
    partes = [
        f"Nome: {d.get('nome', '')}",
        f"Idade: {d.get('idade', '')}",
        f"Escolaridade: {d.get('escolaridade', '')}",
        f"Estado civil: {d.get('estado_civil', '')}",
        f"Renda estimada: R$ {d.get('renda', '')} (faixa: {d.get('faixa_renda', '')})",
        f"Score de crédito: {d.get('score', '')} ({d.get('score_faixa', '')})",
        f"Perfil de consumo (Mosaic): {d.get('mosaic', '')} — {d.get('mosaic_classe', '')}",
        f"Profissão / CBO: {d.get('profissao', '')}",
        f"Emprego atual na base: {', '.join(e.get('razaoSocial') or e.get('nome', '') for e in d.get('empregos', [])) or 'nenhum'}",
        f"Participação em empresas: {', '.join(d.get('empresas_vinculadas', [])) or 'nenhuma'}",
        f"Histórico profissional (Assertiva): {_fmt_historico(d.get('historico_profissional', []))}",
        f"Benefícios sociais recebidos: {'; '.join(b.get('beneficio', '') for b in d.get('beneficios', [])) or 'nenhum'}",
        f"Nº de endereços já registrados: {len(d.get('enderecos', []))}",
        f"Cidades: {', '.join(sorted(set(e.get('cidade', '') for e in d.get('enderecos', []) if e.get('cidade'))))}",
        f"É PPE (politicamente exposta): {'sim' if d.get('pep') else 'não'}",
        f"Família (nome, parentesco, e dados dela quando disponíveis): {_fmt_familia(d.get('parentes', []))}",
    ]
    return "\n".join(p for p in partes if p.split(": ", 1)[-1] not in ("", "nenhum", "nenhuma", "não"))


async def gerar_insight_pessoa(d: dict[str, Any]) -> dict[str, str]:
    """Retorna {resumo_vida, perfil_psicologico} ou {erro: msg}."""
    if not enabled():
        return {"erro": "MISTRAL_API_KEY não configurada."}

    contexto = _resumo_dados_para_prompt(d)
    prompt = f"""Você está analisando dados públicos/de data broker (Mk Buscas + Assertiva) sobre uma pessoa, pra um dossiê de prospecção comercial no Brasil. Use SÓ os dados abaixo — não invente fato novo.

DADOS:
{contexto}

Gere DUAS seções em português do Brasil. Cada frase deve trazer uma ideia NOVA — nunca repita a mesma ressalva ("é inferência", "pode sugerir", "não é confirmado") mais de uma vez por seção; diga a ressalva geral só uma vez, no início ou no fim, e no resto do texto vá direto ao ponto.

1) RESUMO (3-5 frases): resumo objetivo e neutro do que se sabe sobre a vida dessa pessoa (trabalho, renda, situação familiar, estabilidade) — só fatos, sem opinião. SE houver dados de família na lista acima (nome + situação/renda/score de parentes), use-os aqui: diga quem são e o que se sabe sobre eles, não só "tem N parentes".

2) PERFIL (5-8 frases): leitura interpretativa do padrão de consumo/trabalho/estilo de vida — cada frase abordando um ângulo DIFERENTE (não repita a mesma observação reformulada). Cubra, sem repetir a ressalva em cada uma:
   - se a idade é compatível com o padrão de comportamento observado (ex.: histórico de empregos concentrado num período e nada depois — o que isso sugere sobre a trajetória?);
   - UMA hipótese sobre temperamento/tolerância a risco/propensão a mudança, como hipótese fraca, sem repetir a hipótese de outro ângulo;
   - contradições nos dados (ex.: score baixo mas mosaic de alto consumo) que valham destacar;
   - SE houver dados de família enriquecidos: o que o contexto socioeconômico da família (renda/risco dos parentes) acrescenta ou contradiz sobre o perfil dela — isso é um ângulo obrigatório quando o dado existir, não pode ficar de fora.
   Não use termos diagnósticos (transtorno, patologia, distúrbio) e não afirme nada como certeza.

Responda EXATAMENTE neste formato, sem markdown:
RESUMO: <texto>
PERFIL: <texto>"""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 800,
                },
            )
    except Exception as exc:
        return {"erro": f"Falha ao chamar Mistral: {str(exc)[:150]}"}

    if resp.status_code >= 400:
        return {"erro": f"Mistral {resp.status_code}: {resp.text[:200]}"}

    try:
        texto = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return {"erro": "Resposta inesperada da Mistral."}

    resumo, perfil = "", ""
    for linha in texto.split("\n"):
        if linha.upper().startswith("RESUMO:"):
            resumo = linha.split(":", 1)[1].strip()
        elif linha.upper().startswith("PERFIL:"):
            perfil = linha.split(":", 1)[1].strip()
    if not resumo and not perfil:
        # Modelo não seguiu o formato — devolve tudo em "resumo" pra não perder o conteúdo.
        resumo = texto
    return {"resumo_vida": resumo, "perfil_psicologico": perfil}
