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
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import httpx

API_URL = "https://api.mistral.ai/v1/chat/completions"
CONVERSATIONS_URL = "https://api.mistral.ai/v1/conversations"
API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest").strip()
WEB_SEARCH_TOOL = os.environ.get("MISTRAL_WEB_SEARCH_TOOL", "web_search").strip() or "web_search"
WEB_SEARCH_ENABLED = os.environ.get("MISTRAL_WEB_SEARCH_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
_TIMEOUT = httpx.Timeout(30.0)
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parents[1]
AGENTE_MD_PATH = Path(os.environ.get("MISTRAL_AGENT_MD", str(_REPO_ROOT / "agente.md")))


def enabled() -> bool:
    return bool(API_KEY)


def web_search_enabled() -> bool:
    return enabled() and WEB_SEARCH_ENABLED


def _fmt_historico(itens: list[dict[str, Any]]) -> str:
    linhas = []
    for h in itens or []:
        cargo = h.get("cboDescricao", "")
        empresa = h.get("razaoSocial", "")
        data = h.get("dataRegistro", "")
        linhas.append(f"{cargo} em {empresa} ({data})")
    return "; ".join(linhas)


def _load_agente_md() -> str:
    """Carrega as instruções locais do agente para pesquisa web do dossiê."""
    try:
        return AGENTE_MD_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _resumo_web_para_prompt(d: dict[str, Any]) -> str:
    """Extrai achados web/processuais quando algum coletor os anexar ao dossiê."""
    chaves = (
        "web_search",
        "pesquisa_web",
        "achados_web",
        "processos_web",
        "processos_judiciais",
        "registros_publicos_web",
    )
    achados: dict[str, Any] = {}
    for chave in chaves:
        valor = d.get(chave)
        if valor:
            achados[chave] = valor
    if not achados:
        return ""
    return json.dumps(achados, ensure_ascii=False, indent=2, default=str)[:7000]


def _nomes_parentes(d: dict[str, Any], limit: int = 8) -> list[str]:
    nomes = []
    for p in d.get("parentes", []) or []:
        nome = (p.get("nome") or "").strip()
        if nome and nome not in nomes:
            nomes.append(nome)
        if len(nomes) >= limit:
            break
    return nomes


def _web_search_prompt(d: dict[str, Any]) -> str:
    agente = _load_agente_md()
    contexto = _resumo_dados_para_prompt(d)
    parentes = "\n".join(f"- {n}" for n in _nomes_parentes(d)) or "- nenhum familiar listado"
    cidades = ", ".join(sorted(set(e.get("cidade", "") for e in d.get("enderecos", []) if e.get("cidade")))) or "não informado"
    return f"""Você deve fazer web search pública para complementar um dossiê de pessoa física no Brasil.

INSTRUÇÕES DO AGENTE:
{agente}

DADOS DA PESSOA PRINCIPAL:
{contexto}

Cidades/endereço de contexto: {cidades}

FAMILIARES A PESQUISAR COMO CONTEXTO INDIRETO:
{parentes}

Tarefas:
1. Pesquise o nome completo da pessoa principal com termos como processos, eproc, TJ, TRF, TRT, diário oficial, Jusbrasil e Escavador.
2. Pesquise familiares listados apenas como contexto indireto.
3. Separe achados judiciais/processuais de registros não judiciais.
4. Cite fontes/URLs retornadas pelo web_search.
5. Se nada relevante for encontrado sobre a pessoa principal, declare isso com cautela.
6. Não inclua JSON bruto de ferramenta, snippets longos, metadados, favicons, thumbnails, base64, listas não analisadas nem resultados de homônimos.
7. Limite a resposta final a no máximo 6 achados classificados e 8 fontes citadas.

Responda somente em JSON válido, sem markdown, neste formato:
{{
  "status": "ok",
  "resumo": "",
  "conclusao_operacional": "",
  "principal": {{
    "nome": "{d.get('nome', '')}",
    "processos_encontrados": false,
    "achados": [
      {{"tipo": "", "descricao": "", "fonte": "", "url": "", "confianca": "forte|provavel|incerto"}}
    ]
  }},
  "familiares": [
    {{
      "nome": "",
      "parentesco": "",
      "processos_encontrados": false,
      "achados": [
        {{"tipo": "", "descricao": "", "fonte": "", "url": "", "confianca": "forte|provavel|incerto"}}
      ]
    }}
  ],
  "fontes": [
    {{"titulo": "", "url": "", "fonte": "", "observacao": ""}}
  ],
  "limitacoes": ["Ausência de achados em web aberta não equivale a certidão negativa judicial."],
  "insight_complementar": ""
}}"""


def _clip_text(texto: str, max_chars: int = 2400) -> str:
    texto = (texto or "").strip()
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars].rsplit(" ", 1)[0] + "..."


def _conversation_text_and_refs(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    textos: list[str] = []
    refs: list[dict[str, str]] = []

    def collect_content(obj: Any) -> None:
        if isinstance(obj, dict):
            typ = obj.get("type")
            if typ == "text" and obj.get("text"):
                textos.append(str(obj["text"]))
            elif typ == "tool_reference":
                refs.append({
                    "titulo": str(obj.get("title") or ""),
                    "url": str(obj.get("url") or ""),
                    "fonte": str(obj.get("source") or obj.get("tool") or ""),
                })
            elif isinstance(obj.get("content"), str):
                textos.append(obj["content"])
            elif "content" in obj:
                collect_content(obj["content"])
        elif isinstance(obj, list):
            for item in obj:
                collect_content(item)
        elif isinstance(obj, str):
            textos.append(obj)

    for entry in payload.get("outputs") or payload.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        entry_type = str(entry.get("type") or "")
        role = str(entry.get("role") or entry.get("agent") or "")
        if "tool" in entry_type and entry_type != "tool_reference":
            continue
        if entry_type in {"message.output", "message", "assistant_message"} or role == "assistant":
            collect_content(entry.get("content", entry))
        elif entry_type == "tool_reference":
            collect_content(entry)
    if not textos:
        fallback = payload.get("output_text") or payload.get("text") or payload.get("content") or ""
        if isinstance(fallback, str):
            textos.append(fallback)

    texto = "\n".join(dict.fromkeys(_clip_text(t.strip(), 3000) for t in textos if t.strip()))
    fontes = []
    seen = set()
    for ref in refs:
        key = (ref.get("url"), ref.get("titulo"))
        if key in seen:
            continue
        seen.add(key)
        fontes.append(ref)
    return texto, fontes


def _parse_json_object(texto: str) -> dict[str, Any]:
    try:
        return json.loads(texto)
    except Exception:
        pass
    ini = texto.find("{")
    fim = texto.rfind("}")
    if ini >= 0 and fim > ini:
        try:
            return json.loads(texto[ini:fim + 1])
        except Exception:
            pass
    return {}


async def web_search_dossie(d: dict[str, Any]) -> dict[str, Any]:
    """Executa web_search da Mistral via Conversations API e devolve achados estruturados."""
    if not web_search_enabled():
        return {"status": "unavailable", "message": "Mistral web_search não configurado."}

    prompt = _web_search_prompt(d)
    payload = {
        "model": MODEL,
        "inputs": [{"role": "user", "content": prompt}],
        "tools": [{"type": WEB_SEARCH_TOOL}],
        "store": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                CONVERSATIONS_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as exc:
        return {"status": "error", "message": f"Falha ao chamar Mistral web_search: {str(exc)[:150]}"}

    if resp.status_code >= 400:
        return {"status": "error", "message": f"Mistral web_search {resp.status_code}: {resp.text[:300]}"}

    raw = resp.json()
    texto, refs = _conversation_text_and_refs(raw)
    data = _parse_json_object(texto)
    if not data:
        data = {"status": "ok", "resumo": _clip_text(texto, 1200), "fontes": []}
    if "principal" not in data and isinstance(data.get("pessoa_principal"), dict):
        data["principal"] = data.pop("pessoa_principal")
    data.setdefault("status", "ok")
    if data.get("resumo"):
        data["resumo"] = _clip_text(str(data["resumo"]), 1200)
    if data.get("conclusao_operacional"):
        data["conclusao_operacional"] = _clip_text(str(data["conclusao_operacional"]), 900)
    data.setdefault("fontes", [])
    if isinstance(data.get("fontes"), list):
        for fonte in data["fontes"]:
            if isinstance(fonte, dict) and "titulo" not in fonte and fonte.get("nome"):
                fonte["titulo"] = fonte.get("nome")
        data["fontes"] = [f for f in data["fontes"] if isinstance(f, dict)][:8]
    if isinstance(data.get("principal"), dict) and isinstance(data["principal"].get("achados"), list):
        data["principal"]["achados"] = [a for a in data["principal"]["achados"] if isinstance(a, dict)][:6]
    if isinstance(data.get("familiares"), list):
        for fam in data["familiares"]:
            if isinstance(fam, dict) and isinstance(fam.get("achados"), list):
                fam["achados"] = [a for a in fam["achados"] if isinstance(a, dict)][:6]
    if refs:
        existentes = {(f.get("url"), f.get("titulo")) for f in data.get("fontes", []) if isinstance(f, dict)}
        for ref in refs:
            if (ref.get("url"), ref.get("titulo")) not in existentes:
                data["fontes"].append(ref)
    if isinstance(data.get("fontes"), list):
        data["fontes"] = data["fontes"][:8]
    data["ferramenta"] = WEB_SEARCH_TOOL
    data["modelo"] = MODEL
    data["consultado_em"] = datetime.now(timezone.utc).isoformat()
    return data


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
    agente = _load_agente_md()
    achados_web = _resumo_web_para_prompt(d)
    bloco_agente = f"\n\nINSTRUÇÕES DO AGENTE PARA WEB SEARCH:\n{agente}" if agente else ""
    bloco_web = (
        f"\n\nACHADOS WEB / PROCESSUAIS JÁ COLETADOS:\n{achados_web}"
        if achados_web
        else "\n\nACHADOS WEB / PROCESSUAIS JÁ COLETADOS: nenhum achado foi anexado ao JSON."
    )
    prompt = f"""Você está analisando dados públicos/de data broker (Mk Buscas + Assertiva) sobre uma pessoa, pra um dossiê de prospecção comercial no Brasil. Use SÓ os dados abaixo — não invente fato novo.

Quando houver achados web/processuais no JSON, aplique as instruções do agente. Preserve o insight da pessoa principal: achados sobre familiares servem apenas como contexto complementar, nunca como conclusão direta sobre a pessoa consultada. Se não houver achados web, diga somente o que os dados internos sustentam.{bloco_agente}

DADOS:
{contexto}
{bloco_web}

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
                    "max_tokens": 900,
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
