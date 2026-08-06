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
        f"Nº de parentes na base: {len(d.get('parentes', []))}",
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


def _fmt_pessoa_para_comparar(nome: str, idade, renda, score_faixa, profissao, cidades,
                               estado_civil="", escolaridade="", mosaic="", beneficios=None, compras=None) -> str:
    """Mesmo formato pra pessoa principal E pra cada parente — sem isso os dois
    lados não ficam comparáveis (a pessoa principal só entrava como um nome
    solto, sem nenhum dado dela, e o modelo não conseguia comparar nada)."""
    campos = [
        f"idade {idade}" if idade is not None else "idade desconhecida",
        f"renda R$ {renda}" if renda else "renda desconhecida",
        f"risco de crédito {score_faixa.lower()}" if score_faixa else "",
        f"profissão {profissao}" if profissao else "",
        f"estado civil {estado_civil.lower()}" if estado_civil else "",
        f"escolaridade {escolaridade.lower()}" if escolaridade else "",
        f"perfil de consumo {mosaic}" if mosaic else "",
        f"cidades: {', '.join(cidades)}" if cidades else "",
        f"benefícios sociais: {', '.join(beneficios)}" if beneficios else "",
        f"compras recentes: {', '.join(compras[:3])}" if compras else "",
    ]
    return f"{nome}: " + ", ".join(c for c in campos if c)


def _fmt_familia_grounded(d: dict[str, Any]) -> str:
    """Monta o contexto pra hipoteses de dinamica familiar - só os campos REAIS
    coletados (idade veio de dataNascimento real, não estimada), E com os
    dados da PRÓPRIA pessoa principal no mesmo formato dos parentes — sem
    isso o modelo não tinha nada dela pra comparar."""
    linhas = [
        "Pessoa principal — " + _fmt_pessoa_para_comparar(
            d.get("nome", ""), d.get("idade"), d.get("renda"), d.get("score_faixa"),
            d.get("profissao"), sorted(set(e.get("cidade", "") for e in d.get("enderecos", []) if e.get("cidade"))),
            d.get("estado_civil", ""), d.get("escolaridade", ""), d.get("mosaic", ""),
        )
    ]
    for p in d.get("parentes", []) or []:
        r = p.get("resumo")
        if not r:
            continue
        grau = (p.get("grau") or "").split("(")[0].strip().lower()
        linha = _fmt_pessoa_para_comparar(
            p.get("nome", ""), r.get("idade"), r.get("renda"), r.get("score_faixa"), r.get("profissao"),
            r.get("cidades"), r.get("estado_civil", ""), r.get("escolaridade", ""), r.get("mosaic", ""),
            r.get("beneficios"), r.get("compras"),
        )
        linhas.append(f"{grau.capitalize()} — {linha}")
    return "\n".join(linhas)


async def gerar_hipoteses_familia(d: dict[str, Any]) -> dict[str, str]:
    """Hipóteses sobre a dinâmica familiar, SÓ com dado real coletado (idade,
    renda, score, profissão de cada parente) — proibido inventar qualquer
    número/fato que não esteja listado no contexto."""
    if not enabled():
        return {"erro": "MISTRAL_API_KEY não configurada."}

    contexto = _fmt_familia_grounded(d)
    if contexto.count("\n") < 1:
        return {"erro": "Sem parentes com dados suficientes pra gerar hipótese."}

    prompt = f"""Você tem os dados REAIS abaixo sobre uma pessoa (marcada "Pessoa principal") e seus parentes, pra um dossiê de prospecção comercial no Brasil.

REGRAS MAIS IMPORTANTES:
1. Use SÓ os números/fatos que estão escritos abaixo. Se um campo diz "idade desconhecida" ou "renda desconhecida", NÃO invente um valor pra ele — trabalhe só com o que tem. Nunca cite uma idade, renda ou dado que não esteja explicitamente no texto abaixo.
2. Cada parente vem com o GRAU DE PARENTESCO escrito antes do nome (ex.: "Filha — NOME", "Irmã — NOME"). Respeite esse grau à risca — NUNCA chame uma filha de irmã, ou vice-versa, mesmo que a idade pareça sugerir outra coisa.

DADOS:
{contexto}

Escreva 4-6 frases em português do Brasil com hipóteses sobre a DINÂMICA FAMILIAR. Faça SEMPRE a comparação de mão dupla — não fale só dos parentes entre si, compare cada parente COM a pessoa principal (diferença de idade, quem tem renda/risco melhor ou pior que ela, se a escolaridade/profissão é parecida ou destoa) — e também entre os parentes, quando fizer sentido. Cubra: o que a diferença de idade sugere sobre gerações/quando teve os filhos; quem tem melhor situação financeira (pessoa principal ou parente) e o que isso pode indicar sobre dependência ou autonomia; se moram perto (rede de apoio) ou longe; qualquer padrão de consumo ou benefício social que se destaque. Tom hipotético o tempo todo ("pode sugerir", "é compatível com"), nunca certeza, sem termos diagnósticos, e não exagere a intensidade de um dado (ex.: não transforme "alto risco" em "altíssimo risco"). Se faltar dado pra alguma hipótese, simplesmente não a faça — não compense inventando.

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
