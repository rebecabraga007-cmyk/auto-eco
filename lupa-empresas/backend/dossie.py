"""Dossiê em PDF: junta TUDO que Mk Buscas + Assertiva (+ confirmação de
telefone via intelgrax-tel) sabem sobre um CPF, ou Receita Federal +
Assertiva (+ mesma confirmação) sobre um CNPJ, num único documento pra
imprimir/anexar num CRM.

Confirmação de telefone usa o mesmo módulo (intelgrax-tel) que já é pago por
consulta — por isso limitamos a alguns números (os melhores, via
mkbuscas.refine_phones), não confirmamos a lista inteira.
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import assertiva
import brasilapi
import mkbuscas

_MAX_CONFIRMACOES = 5
AZUL = colors.HexColor("#0F2E4A")
TERRACOTA = colors.HexColor("#A85A2C")
TERRACOTA_SOFT = colors.HexColor("#FBEFE7")
VERDE = colors.HexColor("#2F6B4F")
VERDE_SOFT = colors.HexColor("#E9F3ED")
CINZA = colors.HexColor("#55595F")
CINZA_CLARO = colors.HexColor("#DBD4C6")
PAPEL = colors.HexColor("#F1EEE7")


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _fmt_cpf(d: str) -> str:
    d = only_digits(d).zfill(11)[:11]
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"


def _fmt_cnpj(d: str) -> str:
    d = only_digits(d).zfill(14)[:14]
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def _lista_assertiva(bloco: Any) -> list[dict[str, Any]]:
    """A Assertiva às vezes devolve telefones/enderecos/feedbackTelefones como
    lista simples, às vezes como {fixos:[...], moveis:[...]} — normaliza."""
    if isinstance(bloco, list):
        return bloco
    if isinstance(bloco, dict):
        return (bloco.get("fixos") or []) + (bloco.get("moveis") or [])
    return []


def _norm_txt(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


_PLACEHOLDERS = {"nao informado", "n?o informado", "sem informa??o", "sem informacao", "sem descri??o", "sem descricao"}


def _preenchido(v: Any) -> bool:
    """Mk usa strings tipo 'Não informado'/'Não informado' (mojibake) como
    valor — não conta como "campo preenchido" na hora de decidir qual versão
    de um telefone/endereço duplicado é a melhor."""
    if not v:
        return False
    return _norm_txt(str(v)).replace("?", "") not in {_norm_txt(p) for p in _PLACEHOLDERS}


def _dedup(itens: list[dict[str, Any]], chave) -> list[dict[str, Any]]:
    """Remove duplicatas (mesmo telefone/e-mail/endereço vindo da Mk E da
    Assertiva) mantendo a versão com MAIS campos de verdade preenchidos."""
    melhores: dict[str, dict[str, Any]] = {}
    for item in itens:
        k = chave(item)
        if not k:
            continue
        atual = melhores.get(k)
        if atual is None or sum(1 for v in item.values() if _preenchido(v)) > sum(1 for v in atual.values() if _preenchido(v)):
            melhores[k] = item
    return list(melhores.values())


def _fmt_data_iso(s: str) -> str:
    """'2019-09-24 00:00:00' ou '2019-09-24' -> '24/09/2019'. Mantém como está se não bater o padrão."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else s


_MOJIBAKE = [
    (r"\bat\?(?=\s)", "até"), (r"\bN\?O\b", "NÃO"), (r"\bn\?o\b", "não"), (r"informa\?\?o", "informação"),
    (r"descri\?\?o", "descrição"), (r"m\?vel", "móvel"), (r"m\?dio", "médio"), (r"Contato feito h\? ", "Contato feito há "),
    (r"MOBILI\?RIA", "MOBILIÁRIA"), (r"m\?dia", "média"), (r"situa\?\?o", "situação"), (r"pol\?tica", "política"),
]


def _reparar_mojibake(s: str) -> str:
    """A própria API da Mk às vezes já devolve '?' no lugar de acento (perda
    na origem, não é bug de encoding nosso) — corrige os padrões mais comuns."""
    for pat, rep in _MOJIBAKE:
        s = re.sub(pat, rep, s, flags=re.IGNORECASE)
    return s


def _texto(v: Any, vazio: str = "—") -> str:
    """Garante string simples pro PDF — nunca deixa um dict/lista bruto quebrar o Paragraph."""
    if v is None or v == "":
        return vazio
    if isinstance(v, (dict, list)):
        return vazio
    return _reparar_mojibake(str(v))


# ────────────────────────────────────────────────────────────────
# Coleta de dados — CPF (Mk Buscas + Assertiva + intelgrax-tel)
# ────────────────────────────────────────────────────────────────

async def montar_cpf(cpf: str) -> dict[str, Any]:
    doc = only_digits(cpf)
    mk_r = await mkbuscas.consulta_cpf(doc) if mkbuscas.enabled() else {"status": "unavailable"}
    as_r = await assertiva.consulta_cpf(doc) if assertiva.enabled() else {"status": "unavailable"}

    mk_data = mk_r.get("data") or {} if mk_r.get("status") == "ok" else {}
    as_resp = ((as_r.get("data") or {}).get("resposta") or {}) if as_r.get("status") == "ok" else {}

    db = mk_data.get("DadosBasicos") or {}
    de = mk_data.get("DadosEconomicos") or {}
    prof = mk_data.get("profissao") or {}
    as_cad = as_resp.get("dadosCadastrais") or {}
    sit_cad = db.get("situacaoCadastral") if isinstance(db.get("situacaoCadastral"), dict) else {}
    obito = db.get("obito") if isinstance(db.get("obito"), dict) else {}
    poder = de.get("poderAquisitivo") if isinstance(de.get("poderAquisitivo"), dict) else {}
    score = de.get("score") if isinstance(de.get("score"), dict) else {}
    mosaic = de.get("serasaMosaic") if isinstance(de.get("serasaMosaic"), dict) else {}
    flags = mk_data.get("flags") if isinstance(mk_data.get("flags"), dict) else {}

    telefones: list[dict[str, Any]] = list(mkbuscas._extract_phones(mk_data))
    for t in _lista_assertiva(as_resp.get("telefones")) + _lista_assertiva(as_resp.get("telefonesAdicionados")):
        num = str(t.get("numero") or t.get("telefone") or "")
        if num:
            telefones.append({
                "telefone": num, "ddd": str(t.get("ddd") or ""), "fonte": "Assertiva",
                "operadora": t.get("operadora", ""), "ultimo_contato": t.get("ultimoContato", ""),
                "whatsapp": (t.get("aplicativos") or {}).get("whatsApp") if isinstance(t.get("aplicativos"), dict) else None,
            })

    def _tel_digits(t: dict[str, Any]) -> str:
        raw = only_digits((t.get("ddd", "") or "") + (t.get("telefone", "") or t.get("number", "") or ""))
        return raw[-11:] if len(raw) >= 10 else ""

    telefones = _dedup(telefones, _tel_digits)

    confirmacoes = await _confirmar_telefones(telefones, doc)
    for t in telefones:
        td = _tel_digits(t)
        t["_pertence"] = next((c for c in confirmacoes if td and (td.endswith(c["telefone"]) or c["telefone"].endswith(td))), None)

    enderecos = mkbuscas._extract_cities(mk_data)
    enderecos_brutos = [dict(e) for e in (mk_data.get("enderecos") or []) if isinstance(e, dict)]
    for e in _lista_assertiva(as_resp.get("enderecos")) + _lista_assertiva(as_resp.get("enderecosAdicionados")):
        if isinstance(e, dict) and e.get("cidade"):
            enderecos_brutos.append(e)
    enderecos_completos = _dedup(
        enderecos_brutos,
        lambda e: only_digits(str(e.get("cep", ""))) or _norm_txt(f"{e.get('logradouro', '')}{e.get('logradouroNumero', '')}{e.get('cidade', '')}"),
    )

    parentes = [
        {"nome": p.get("nomeParente", ""), "grau": p.get("grauParentesco", ""), "cpf": p.get("cpfParente", "")}
        for p in (mk_data.get("parentes") or []) if isinstance(p, dict) and p.get("nomeParente")
    ]
    vizinhos = [
        {"nome": v.get("nome", ""), "idade": v.get("idade", ""), "nome_mae": v.get("nomeMae", "")}
        for v in (mk_data.get("vizinhos") or []) if isinstance(v, dict) and v.get("nome")
    ]
    beneficios = [
        b for b in (mk_data.get("beneficios") or [])
        if isinstance(b, dict) and (b.get("totalParcelasRecebidas") or 0) > 0
    ]
    emails = _dedup(
        [e for e in (mk_data.get("emails") or []) + (as_resp.get("emails") or []) if isinstance(e, dict) and e.get("email")],
        lambda e: (e.get("email") or "").lower(),
    )
    redes_sociais = [r for r in (as_resp.get("redesSociais") or []) if isinstance(r, dict)]
    empregos = [e for e in (mk_data.get("empregos") or []) if isinstance(e, dict)]
    empresas_vinc = mkbuscas._extract_companies(mk_data)
    participacoes = as_resp.get("participacoesEmpresas") or as_resp.get("participacoesSocietarias") or []
    hist_seg = as_resp.get("historicoConsultasPorSegmento") or {}
    historico_profissional = [h for h in (as_resp.get("possivelHistoricoProfissional") or []) if isinstance(h, dict)]
    registros_profissionais = [r for r in (as_resp.get("registrosProfissionais") or []) if isinstance(r, dict)]
    comentarios = [c for c in (as_resp.get("comentarios") or []) if c]
    imposto = [i for i in (mk_data.get("DadosImposto") or []) if i]
    siape = mk_data.get("servidor_siape") or {}
    eh_servidor = bool(siape.get("ID_Servidor")) or bool(flags.get("__servidor_publico_siape__"))

    return {
        "tipo": "cpf",
        "doc": _fmt_cpf(doc),
        "protocolo": uuid.uuid4().hex[:8],
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "nome": db.get("nome") or as_cad.get("nome") or "",
        "idade": as_cad.get("idade"),
        "nome_mae": db.get("nomeMae") or as_cad.get("maeNome") or "",
        "nome_pai": db.get("nomePai") or "",
        "nascimento": db.get("dataNascimento") or as_cad.get("dataNascimento") or "",
        "municipio_nascimento": db.get("municipioNascimento") or "",
        "estado_civil": db.get("estadoCivil") or "",
        "nacionalidade": db.get("nacionalidade") or "",
        "sexo": (db.get("sexo") or as_cad.get("sexo") or "").replace(" - ", "/"),
        "escolaridade": db.get("escolaridade") or "",
        "situacao_cpf": sit_cad.get("descricaoSituacaoCadastral", ""),
        "situacao_cpf_data": _fmt_data_iso(sit_cad.get("dataSituacaoCadastral", "") or as_cad.get("dataSituacaoCadastral", "")),
        "obito": (obito.get("obito") or "").upper(),
        "pep": bool(as_cad.get("ppe")) or bool(flags.get("__pessoa_exposta_politicamente__")),
        "renda": de.get("renda") or "",
        "faixa_renda": poder.get("faixaPoderAquisitivo") or "",
        "score": score.get("scoreCSBA") or "",
        "score_faixa": score.get("scoreCSBAFaixaRisco") or "",
        "mosaic": mosaic.get("descricaoMosaicNovo") or mosaic.get("descricaoMosaic") or "",
        "mosaic_classe": mosaic.get("classeMosaicNovo") or "",
        "profissao": prof.get("cboDescricao") if prof.get("cboDescricao") and "sem descri" not in (prof.get("cboDescricao") or "").lower() else "",
        "cbo": prof.get("cbo") or "",
        "pis": prof.get("pis") or "",
        "eh_servidor_publico": eh_servidor,
        "empregos": empregos,
        "empresas_vinculadas": empresas_vinc,
        "participacoes": participacoes,
        "historico_profissional": historico_profissional,
        "registros_profissionais": registros_profissionais,
        "telefones": telefones,
        "confirmacoes": confirmacoes,
        "enderecos": enderecos_completos,
        "parentes": parentes,
        "vizinhos": vizinhos,
        "beneficios": beneficios,
        "emails": emails,
        "redes_sociais": redes_sociais,
        "historico_consultas": hist_seg,
        "comentarios": comentarios,
        "declaracao_imposto": imposto,
        "fontes": {
            "mk": mk_r.get("status", "unavailable"),
            "assertiva": as_r.get("status", "unavailable"),
            "telefone": "ok" if confirmacoes else ("unavailable" if not mkbuscas.TEL_AUTH_VALUE else "sem números pra confirmar"),
        },
    }


async def montar_cnpj(cnpj: str) -> dict[str, Any]:
    doc = only_digits(cnpj)
    try:
        company = await brasilapi.fetch_company(doc)
        empresa_status = "ok"
    except Exception as exc:
        company, empresa_status = {}, f"error: {exc}"
    as_r = await assertiva.consulta_cnpj(doc) if assertiva.enabled() else {"status": "unavailable"}
    as_resp = ((as_r.get("data") or {}).get("resposta") or {}) if as_r.get("status") == "ok" else {}
    as_cad = as_resp.get("dadosCadastrais") or {}

    telefones: list[dict[str, Any]] = []
    for i in (1, 2):
        ddd = company.get(f"ddd_telefone_{i}")
        if ddd:
            telefones.append({"telefone": only_digits(ddd), "fonte": "Receita Federal"})
    for t in _lista_assertiva(as_resp.get("telefones")) + _lista_assertiva(as_resp.get("telefonesAdicionados")):
        num = str(t.get("numero") or t.get("telefone") or "")
        if num:
            telefones.append({"telefone": num, "ddd": str(t.get("ddd") or ""), "fonte": "Assertiva"})

    confirmacoes = await _confirmar_telefones(telefones, doc)

    socios = [
        {"nome": s.get("nome_socio", ""), "qualificacao": s.get("qualificacao_socio", "")}
        for s in (company.get("qsa") or [])
    ]

    endereco_rfb = ", ".join(filter(None, [
        company.get("logradouro"), company.get("numero"), company.get("bairro"),
        company.get("municipio"), company.get("uf"),
    ]))

    return {
        "tipo": "cnpj",
        "doc": _fmt_cnpj(doc),
        "protocolo": uuid.uuid4().hex[:8],
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "razao_social": company.get("razao_social") or as_cad.get("razaoSocial") or "",
        "nome_fantasia": company.get("nome_fantasia") or "",
        "situacao": company.get("descricao_situacao_cadastral") or "",
        "abertura": company.get("data_inicio_atividade") or "",
        "atividade": company.get("cnae_fiscal_descricao") or "",
        "capital_social": company.get("capital_social"),
        "endereco": endereco_rfb,
        "socios": socios,
        "telefones": telefones,
        "confirmacoes": confirmacoes,
        "participacoes_assertiva": as_resp.get("participacoesEmpresas") or [],
        "fontes": {
            "receita": empresa_status,
            "assertiva": as_r.get("status", "unavailable"),
        },
    }


async def _confirmar_telefones(telefones: list[dict[str, Any]], doc: str) -> list[dict[str, Any]]:
    """Confirma se os melhores telefones (até _MAX_CONFIRMACOES) pertencem ao doc."""
    if not mkbuscas.TEL_AUTH_VALUE:
        return []
    melhores = mkbuscas.refine_phones(telefones, modo="celular_fixo", max_n=_MAX_CONFIRMACOES)
    out = []
    for t in melhores:
        raw = t.get("digits") or only_digits(t.get("telefone") or "")
        if len(raw) < 10:
            continue
        r = await mkbuscas.telefone_pertence(raw, doc)
        out.append({"telefone": raw, "fonte": t.get("fonte", "Mk Buscas"), **r})
    return out


# ────────────────────────────────────────────────────────────────
# Geração do PDF — estilo "CapiBLU Design System" (papel, azul-noite,
# terracota, IBM Plex, cards + tabelas com fio embaixo, sem sombra).
# ────────────────────────────────────────────────────────────────

def _styles():
    ss = getSampleStyleSheet()
    if "DTopo" not in ss:
        ss.add(ParagraphStyle("DTopo", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5,
                               textColor=CINZA, spaceAfter=0))
        ss.add(ParagraphStyle("DTopoDireita", parent=ss["DTopo"], alignment=2))
        ss.add(ParagraphStyle("DNome", parent=ss["Title"], textColor=colors.HexColor("#1A1D21"),
                               fontSize=22, leading=26, spaceBefore=10, spaceAfter=4, alignment=0))
        ss.add(ParagraphStyle("DSub", parent=ss["Normal"], textColor=CINZA, fontSize=10, spaceAfter=10))
        ss.add(ParagraphStyle("DSecao", parent=ss["Heading2"], textColor=AZUL, fontSize=13,
                               spaceBefore=16, spaceAfter=8))
        ss.add(ParagraphStyle("DSubsecao", parent=ss["Heading3"], textColor=colors.HexColor("#1A1D21"),
                               fontSize=11, spaceBefore=12, spaceAfter=6))
        ss.add(ParagraphStyle("DCampo", parent=ss["Normal"], fontSize=9.5, leading=14))
        ss.add(ParagraphStyle("DCampoLabel", parent=ss["DCampo"], fontName="Helvetica-Bold", textColor=CINZA, fontSize=8))
        ss.add(ParagraphStyle("DNota", parent=ss["Normal"], fontSize=8.5, textColor=CINZA, leading=12))
        ss.add(ParagraphStyle("DCardLabel", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=7.5,
                               textColor=CINZA, spaceAfter=3))
        ss.add(ParagraphStyle("DCardValor", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=14,
                               leading=17, textColor=colors.HexColor("#1A1D21"), spaceAfter=3))
        ss.add(ParagraphStyle("DCardSub", parent=ss["Normal"], fontSize=8, textColor=CINZA, leading=11))
        ss.add(ParagraphStyle("DPill", parent=ss["Normal"], fontSize=8.5, textColor=AZUL, alignment=1))
    return ss


def _pill(texto: str, cor_fundo=colors.HexColor("#E8EDF1"), cor_texto=AZUL) -> Table:
    styles = _styles()
    st = ParagraphStyle("pill_" + str(id(cor_texto)), parent=styles["DPill"], textColor=cor_texto)
    t = Table([[Paragraph(texto, st)]], colWidths=None)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), cor_fundo),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _linha_pills(pills: list[Table]) -> Table:
    if not pills:
        return Spacer(1, 0)
    t = Table([pills], colWidths=None)
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (1, 0), (-1, -1), 6)]))
    return t


def _cabecalho(tipo_doc: str, d: dict[str, Any]) -> Table:
    styles = _styles()
    esquerda = Paragraph(f"CAPIBLU · DOSSIÊ DE {tipo_doc}", styles["DTopo"])
    direita = Paragraph(f"{d['gerado_em']} · protocolo {d['protocolo']}", styles["DTopoDireita"])
    t = Table([[esquerda, direita]], colWidths=[None, None])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.75, AZUL),
    ]))
    return t


def _tabela_kv(linhas: list[tuple[str, str]], col1=48 * mm) -> Table:
    styles = _styles()
    rows = [[Paragraph(f"<b>{k}</b>", styles["DCampo"]), Paragraph(_texto(v), styles["DCampo"])] for k, v in linhas]
    t = Table(rows, colWidths=[col1, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CINZA_CLARO),
    ]))
    return t


def _tabela_dados(cabecalho: list[str], linhas: list[list[str]], col_widths=None) -> Table:
    styles = _styles()
    header = [Paragraph(f"<b>{h.upper()}</b>", ParagraphStyle("th", parent=styles["DCampo"], fontSize=7.5, textColor=CINZA)) for h in cabecalho]
    body = [[Paragraph(_texto(c), styles["DCampo"]) for c in row] for row in linhas]
    t = Table([header] + body, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0ECE3")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CINZA_CLARO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _cards(cards: list[tuple[str, str, str]]) -> Table:
    """cards: [(label, valor, sub), ...] — 2 ou 3 colunas."""
    styles = _styles()
    cel = []
    for label, valor, sub in cards:
        conteudo = [Paragraph(label.upper(), styles["DCardLabel"]), Paragraph(_texto(valor), styles["DCardValor"])]
        if sub:
            conteudo.append(Paragraph(sub, styles["DCardSub"]))
        cel.append(conteudo)
    t = Table([cel], colWidths=[None] * len(cards))
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, CINZA_CLARO),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, CINZA_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _endereco_txt(e: dict[str, Any]) -> str:
    partes = [e.get("tipoLogradouro", ""), e.get("logradouro", "")]
    linha1 = " ".join(p for p in partes if p).strip()
    if e.get("logradouroNumero"):
        linha1 += f", {e['logradouroNumero']}"
    if e.get("complemento"):
        linha1 += f" · {e['complemento']}"
    if e.get("bairro"):
        linha1 += f" — {e['bairro']}"
    linha2 = ", ".join(p for p in [e.get("cidade", ""), e.get("uf", "")] if p)
    if e.get("cep"):
        cep = only_digits(str(e["cep"])).zfill(8)
        linha2 += f" · CEP {cep[:5]}-{cep[5:]}"
    return "<br/>".join(p for p in [linha1, linha2] if p) or "—"


def gerar_pdf_cpf(d: dict[str, Any]) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    flow = [_cabecalho("PESSOA", d)]

    idade_txt = f"{d['idade']} anos" if d.get("idade") else ""
    nasc_txt = f"nascida em {d['nascimento']}" if d.get("nascimento") else ""
    nasc_local = f" em {d['municipio_nascimento']}" if d.get("municipio_nascimento") else ""
    subtitulo = " · ".join(p for p in [d["doc"], idade_txt, (nasc_txt + nasc_local).strip(), d.get("sexo", "")] if p)
    flow.append(Paragraph(d["nome"] or "Nome não encontrado", styles["DNome"]))
    flow.append(Paragraph(subtitulo, styles["DSub"]))

    pills = []
    if d.get("situacao_cpf"):
        boa = "regular" in d["situacao_cpf"].lower()
        pills.append(_pill(f"CPF {d['situacao_cpf'].lower()} na Receita", VERDE_SOFT if boa else TERRACOTA_SOFT, VERDE if boa else TERRACOTA))
    if d.get("obito"):
        sem_obito = d["obito"] not in ("SIM",)
        pills.append(_pill("Sem indício de óbito" if sem_obito else "Óbito registrado", VERDE_SOFT if sem_obito else TERRACOTA_SOFT, VERDE if sem_obito else TERRACOTA))
    pills.append(_pill("É PPE (pessoa politicamente exposta)" if d.get("pep") else "Não é PPE", TERRACOTA_SOFT if d.get("pep") else colors.HexColor("#E8EDF1"), TERRACOTA if d.get("pep") else AZUL))
    flow.append(_linha_pills(pills))
    flow.append(Spacer(1, 10))

    cards = []
    if d.get("renda"):
        cards.append(("Renda estimada", f"R$ {d['renda']}", f"Faixa {d['faixa_renda']}." if d.get("faixa_renda") else ""))
    if d.get("score"):
        cards.append(("Score de crédito", f"{d['score']}  {d.get('score_faixa', '').lower()}", ""))
    if d.get("mosaic"):
        cards.append(("Perfil de consumo", d["mosaic"], d.get("mosaic_classe", "")))
    if cards:
        flow.append(_cards(cards))
        flow.append(Spacer(1, 12))

    kv = [
        ("Nome da mãe / do pai", " / ".join(p for p in [d.get("nome_mae", ""), d.get("nome_pai", "")] if p)),
        ("Estado civil / nacionalidade", " · ".join(p for p in [d.get("estado_civil", ""), d.get("nacionalidade", "")] if p)),
        ("Escolaridade", d.get("escolaridade", "")),
        ("Situação cadastral", (f"{d['situacao_cpf']}" + (f" — confirmada em {d['situacao_cpf_data']}" if d.get("situacao_cpf_data") else "")) if d.get("situacao_cpf") else ""),
        ("Benefícios sociais", "; ".join(f"{b.get('beneficio', '')} ({b.get('totalRecebido', '')})" for b in d.get("beneficios", [])) or "Nenhum registrado."),
    ]
    flow.append(_tabela_kv([(k, v) for k, v in kv if v]))

    flow.append(PageBreak())
    flow.append(Paragraph("Trabalho, família e contato", styles["DSecao"]))

    flow.append(Paragraph("Trabalho e renda formal", styles["DSubsecao"]))
    kv_trab = [
        ("Profissão", f"{d['profissao']} (CBO {d['cbo']})" if d.get("profissao") else ""),
        ("Emprego atual", ", ".join(e.get("razaoSocial") or e.get("nomeEmpresa") or e.get("nome", "") for e in d.get("empregos", [])) or ""),
        ("PIS/PASEP", str(d["pis"]) if d.get("pis") else ""),
        ("Participação em empresas", "; ".join(d.get("empresas_vinculadas", [])) or ("Nenhuma. " + ("É servidora pública (SIAPE)." if d.get("eh_servidor_publico") else "Não é servidora pública."))),
    ]
    flow.append(_tabela_kv([(k, v) for k, v in kv_trab if v]))

    if d.get("registros_profissionais"):
        flow.append(Paragraph("Registros profissionais (conselhos de classe)", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Profissão", "Registro", "UF"],
                                   [[r.get("profissao", ""), f"{r.get('sigla', '')} {r.get('numeroInscricao', '')}".strip(), r.get("uf", "") or ""] for r in d["registros_profissionais"][:10]]))

    if d.get("historico_profissional"):
        flow.append(Paragraph("Histórico de vínculos profissionais (Assertiva)", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Cargo", "Empresa", "Setor", "Desde"],
                                   [[h.get("cboDescricao", ""), h.get("razaoSocial", ""), h.get("setor", ""), h.get("dataRegistro", "")] for h in d["historico_profissional"][:10]],
                                   col_widths=[35 * mm, None, 40 * mm, 22 * mm]))

    if d.get("parentes"):
        flow.append(Paragraph("Família e vínculos", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Nome", "Parentesco", "CPF"],
                                   [[p["nome"], p.get("grau", ""), _fmt_cpf(p["cpf"]) if p.get("cpf") else ""] for p in d["parentes"][:12]],
                                   col_widths=[None, 45 * mm, 35 * mm]))

    if d.get("redes_sociais"):
        flow.append(Paragraph("Redes sociais associadas ao CPF", styles["DSubsecao"]))
        rs_pills = [_pill(f"{r.get('rede', r.get('tipo', ''))} · {r.get('usuario', r.get('perfil', ''))}") for r in d["redes_sociais"][:8]]
        flow.append(_linha_pills(rs_pills))

    if d.get("emails"):
        flow.append(Paragraph(f"E-mails encontrados — {len(d['emails'])}", styles["DSubsecao"]))
        flow.append(_tabela_dados(["E-mail", "Qualidade", "Prioridade"],
                                   [[e.get("email", ""), e.get("qualidade", ""), e.get("prioridade", "")] for e in d["emails"][:10]]))

    if d.get("telefones"):
        flow.append(Paragraph(f"Telefones — {len(d['telefones'])} encontrado{'s' if len(d['telefones']) != 1 else ''}", styles["DSubsecao"]))
        linhas_tel = []
        for t in d["telefones"][:15]:
            pert = t.get("_pertence")
            if pert and pert.get("atrelado") is True:
                confirmado = "✅ Confirmado"
            elif pert and pert.get("atrelado") is False:
                confirmado = "❌ Não confirmado"
            else:
                confirmado = "—"
            ult = t.get("ultimo_contato", "")
            linhas_tel.append([_fmt_tel(t), t.get("operadora", "") or t.get("fonte", ""), ult, confirmado])
        flow.append(_tabela_dados(["Telefone", "Operadora", "Último contato", "É dela mesmo?"], linhas_tel,
                                   col_widths=[35 * mm, 30 * mm, None, 35 * mm]))

    flow.append(PageBreak())
    flow.append(Paragraph("Renda formal e histórico", styles["DSecao"]))

    if d.get("declaracao_imposto"):
        flow.append(Paragraph("Declaração de imposto de renda", styles["DSubsecao"]))
        flow.append(Paragraph(f"{len(d['declaracao_imposto'])} declaração(ões) encontrada(s) na base.", styles["DCampo"]))

    if d.get("enderecos"):
        flow.append(Paragraph(f"Onde já morou — {len(d['enderecos'])} endereço{'s' if len(d['enderecos']) != 1 else ''}", styles["DSubsecao"]))
        for i, e in enumerate(d["enderecos"][:10]):
            linha = Table([[Paragraph(_endereco_txt(e), styles["DCampo"]),
                             Paragraph("mais recente" if i == 0 else "", ParagraphStyle("tag", parent=styles["DCampo"], textColor=VERDE, fontName="Helvetica-Bold", alignment=2))]],
                          colWidths=[None, 30 * mm])
            linha.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8),
                                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CINZA_CLARO), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow.append(linha)

    hist = d.get("historico_consultas") or {}
    if hist.get("quantidadeTotal"):
        segs = ", ".join(s.get("segmento", "") for s in hist.get("segmentos", []) if isinstance(s, dict)) or "não detalhados"
        flow.append(Paragraph("Histórico de consultas por outros clientes", styles["DSubsecao"]))
        flow.append(Paragraph(f"{hist['quantidadeTotal']} consulta(s) recente(s), nos segmentos {segs}.", styles["DCampo"]))

    if d.get("vizinhos"):
        flow.append(Paragraph(f"Pessoas que moram perto dela — {len(d['vizinhos'])} encontrada(s)", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Nome", "Idade", "Nome da mãe"],
                                   [[v["nome"], str(v.get("idade", "")), v.get("nome_mae", "")] for v in d["vizinhos"][:10]],
                                   col_widths=[None, 20 * mm, None]))

    if d.get("comentarios"):
        flow.append(Paragraph("Anotações", styles["DSubsecao"]))
        for c in d["comentarios"][:5]:
            flow.append(Paragraph(f"“{_texto(c)}”", styles["DNota"]))

    insight = d.get("insight_ia")
    if insight and not insight.get("erro"):
        flow.append(PageBreak())
        flow.append(Paragraph("Insight gerado por IA", styles["DSecao"]))
        flow.append(Paragraph(
            "Texto gerado automaticamente (Mistral AI) a partir dos dados deste dossiê. O \"perfil\" abaixo é uma "
            "INFERÊNCIA ESTATÍSTICA a partir de padrão de consumo/renda/emprego — não é uma avaliação psicológica "
            "clínica, pode conter erro, e não deve ser a única base de nenhuma decisão sobre esta pessoa.",
            ParagraphStyle("DAviso", parent=styles["DNota"], textColor=TERRACOTA, spaceAfter=10),
        ))
        if insight.get("resumo_vida"):
            flow.append(Paragraph("Resumo da vida da pessoa", styles["DSubsecao"]))
            flow.append(Paragraph(_texto(insight["resumo_vida"]), styles["DCampo"]))
        if insight.get("perfil_psicologico"):
            flow.append(Paragraph("Perfil psicológico inferido", styles["DSubsecao"]))
            flow.append(Paragraph(_texto(insight["perfil_psicologico"]), styles["DCampo"]))

    flow.append(Spacer(1, 16))
    flow.append(Paragraph(
        f"Fontes: Mk Buscas ({d['fontes']['mk']}) · Assertiva ({d['fontes']['assertiva']}) · "
        f"confirmação de telefone / intelgrax-tel ({d['fontes']['telefone']})",
        styles["DNota"],
    ))
    doc.build(flow)
    return buf.getvalue()


def _fmt_tel(t: dict[str, Any]) -> str:
    raw = only_digits(t.get("telefone") or t.get("number") or "")
    ddd = only_digits(t.get("ddd") or "")
    if ddd and raw.startswith(ddd):
        raw = raw[len(ddd):]
    elif ddd and not raw.startswith(ddd):
        pass
    else:
        ddd, raw = raw[:2], raw[2:]
    if len(raw) == 9:
        return f"({ddd}) {raw[:5]}-{raw[5:]}"
    if len(raw) == 8:
        return f"({ddd}) {raw[:4]}-{raw[4:]}"
    return t.get("telefone") or "—"


def gerar_pdf_cnpj(d: dict[str, Any]) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    flow = [
        _cabecalho("EMPRESA", d),
        Paragraph(d["razao_social"] or "Empresa não encontrada", styles["DNome"]),
        Paragraph(" · ".join(p for p in [d["doc"], d.get("nome_fantasia", "")] if p), styles["DSub"]),
    ]

    if d.get("situacao"):
        boa = "ativa" in d["situacao"].lower()
        flow.append(_linha_pills([_pill(d["situacao"], VERDE_SOFT if boa else TERRACOTA_SOFT, VERDE if boa else TERRACOTA)]))
        flow.append(Spacer(1, 10))

    kv = [
        ("Abertura", d.get("abertura", "")), ("Atividade principal", d.get("atividade", "")),
        ("Capital social", f"R$ {d['capital_social']}" if d.get("capital_social") else ""),
        ("Endereço", d.get("endereco", "")),
    ]
    flow.append(_tabela_kv([(k, v) for k, v in kv if v]))

    if d.get("socios"):
        flow.append(Paragraph("Sócios", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Nome", "Qualificação"], [[s["nome"], s["qualificacao"]] for s in d["socios"][:15]]))

    if d.get("telefones"):
        flow.append(Paragraph(f"Telefones — {len(d['telefones'])} encontrado(s)", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Telefone", "Fonte"], [[t.get("telefone", ""), t.get("fonte", "")] for t in d["telefones"][:15]]))

    if d.get("confirmacoes"):
        flow.append(Paragraph("Confirmação de telefone (pertence a este CNPJ?)", styles["DSubsecao"]))
        linhas = []
        for c in d["confirmacoes"]:
            pertence = "✅ Sim" if c.get("atrelado") else ("❌ Não" if c.get("atrelado") is False else "❓ sem dados")
            linhas.append([c.get("telefone", ""), pertence, str(c.get("total", "—"))])
        flow.append(_tabela_dados(["Telefone", "Pertence?", "Nº de vínculos"], linhas))

    if d.get("participacoes_assertiva"):
        flow.append(Paragraph("Outras participações societárias (Assertiva)", styles["DSubsecao"]))
        flow.append(_tabela_dados(["Cargo", "Razão social"],
                                   [[p.get("cargo", ""), p.get("razaoSocial", "")] for p in d["participacoes_assertiva"][:15]]))

    flow.append(Spacer(1, 16))
    flow.append(Paragraph(
        f"Fontes: Receita Federal ({d['fontes']['receita']}) · Assertiva ({d['fontes']['assertiva']})",
        styles["DNota"],
    ))
    doc.build(flow)
    return buf.getvalue()
