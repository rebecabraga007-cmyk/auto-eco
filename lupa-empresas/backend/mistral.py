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


def _fmt_participacoes_mk(itens: list[dict[str, Any]]) -> str:
    linhas = [f"{p['relacao']} em {p['cnpj']} ({p['desde']}–{p['ate']})" for p in (itens or [])]
    return "; ".join(linhas) or "nenhuma"


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
        f"Perfil de consumo (Mosaic, classificação principal): {d.get('mosaic', '')} — {d.get('mosaic_classe', '')}",
        f"Perfil de consumo (Mosaic novo, foco em trajetória/geração): {d.get('mosaic_novo', '')} — {d.get('mosaic_novo_classe', '')}",
        f"Profissão / CBO: {d.get('profissao', '')}",
        f"Emprego atual na base: {', '.join(e.get('razaoSocial') or e.get('nome', '') for e in d.get('empregos', [])) or 'nenhum'}",
        f"Participação em empresas: {', '.join(d.get('empresas_vinculadas', [])) or 'nenhuma'}",
        f"Participação societária (Mk, CNPJ/relação/período): {_fmt_participacoes_mk(d.get('participacoes_mk', []))}",
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

Gere DUAS seções, cada uma com 2-4 frases, em português do Brasil:

1) RESUMO: um resumo objetivo e neutro do que se sabe sobre a vida dessa pessoa (trabalho, renda, situação familiar, estabilidade) — só fatos, sem opinião.

2) PERFIL: uma leitura interpretativa do padrão de consumo/trabalho/estilo de vida (o que o Mosaic, a renda, o histórico profissional e os hábitos sugerem sobre comportamento/perfil dela). Deixe claro que é uma INFERÊNCIA a partir de dados estatísticos de consumo, não uma avaliação psicológica clínica.

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
                    "max_tokens": 500,
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


def _fmt_familia_grounded(pessoa_nome: str, parentes: list[dict[str, Any]]) -> str:
    """Monta o contexto pra hipoteses de dinamica familiar - só os campos REAIS
    coletados (idade veio de dataNascimento real, não estimada). Sem isso no
    contexto, o modelo inventa idade/renda que não existem (já aconteceu)."""
    linhas = [f"Pessoa principal: {pessoa_nome}"]
    for p in parentes or []:
        r = p.get("resumo")
        if not r:
            continue
        grau = (p.get("grau") or "").split("(")[0].strip().lower()
        campos = [
            f"idade {r['idade']}" if r.get("idade") is not None else "idade desconhecida",
            f"situação CPF {r['situacao_cpf'].lower()}" if r.get("situacao_cpf") else "",
            f"renda R$ {r['renda']}" if r.get("renda") else "renda desconhecida",
            f"risco de crédito {r['score_faixa'].lower()}" if r.get("score_faixa") else "",
            f"profissão {r['profissao']}" if r.get("profissao") else "",
            f"cidades: {', '.join(r['cidades'])}" if r.get("cidades") else "",
        ]
        linhas.append(f"- {p.get('nome', '')} ({grau}): " + ", ".join(c for c in campos if c))
    return "\n".join(linhas)


async def gerar_hipoteses_familia(d: dict[str, Any]) -> dict[str, str]:
    """Hipóteses sobre a dinâmica familiar, SÓ com dado real coletado (idade,
    renda, score, profissão de cada parente) — proibido inventar qualquer
    número/fato que não esteja listado no contexto."""
    if not enabled():
        return {"erro": "MISTRAL_API_KEY não configurada."}

    contexto = _fmt_familia_grounded(d.get("nome", ""), d.get("parentes", []))
    if contexto.count("\n") < 1:
        return {"erro": "Sem parentes com dados suficientes pra gerar hipótese."}

    prompt = f"""Você tem os dados REAIS abaixo sobre uma pessoa e seus parentes (Mk Buscas), pra um dossiê de prospecção comercial no Brasil.

REGRA MAIS IMPORTANTE: use SÓ os números/fatos que estão escritos abaixo. Se um campo diz "idade desconhecida" ou "renda desconhecida", NÃO invente um valor pra ele — trabalhe só com o que tem. Nunca cite uma idade, renda ou dado que não esteja explicitamente no texto abaixo.

DADOS:
{contexto}

Escreva 3-5 frases em português do Brasil com hipóteses sobre a DINÂMICA FAMILIAR — o que a diferença de idade, renda e situação financeira entre os parentes pode sugerir (ex.: dependência financeira, autonomia, rede de apoio, proximidade geográfica). Tom hipotético o tempo todo ("pode sugerir", "é compatível com"), nunca certeza, sem termos diagnósticos. Se faltar dado pra alguma hipótese, simplesmente não a faça — não compense inventando.

Responda só com o texto das hipóteses, sem título, sem markdown."""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 400,
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

    return {"texto": texto}
