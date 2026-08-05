"""Dossiê em PDF: junta Mk Buscas + Assertiva + confirmação de telefone (CPF)
ou Receita Federal + Assertiva + confirmação de telefone (CNPJ) num único
documento, pra imprimir/anexar num CRM.

Confirmação de telefone usa o mesmo módulo (intelgrax-tel) que já é pago por
consulta — por isso limitamos a alguns números (os melhores, via
mkbuscas.refine_phones), não confirmamos a lista inteira.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import assertiva
import brasilapi
import mkbuscas

_MAX_CONFIRMACOES = 5
AZUL = colors.HexColor("#0F2E4A")
TERRACOTA = colors.HexColor("#A85A2C")
CINZA = colors.HexColor("#55595F")


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _fmt_cpf(d: str) -> str:
    d = only_digits(d).zfill(11)[:11]
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"


def _fmt_cnpj(d: str) -> str:
    d = only_digits(d).zfill(14)[:14]
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


# ────────────────────────────────────────────────────────────────
# Coleta de dados
# ────────────────────────────────────────────────────────────────

async def montar_cpf(cpf: str) -> dict[str, Any]:
    doc = only_digits(cpf)
    mk_r = await mkbuscas.consulta_cpf(doc) if mkbuscas.enabled() else {"status": "unavailable"}
    as_r = await assertiva.consulta_cpf(doc) if assertiva.enabled() else {"status": "unavailable"}

    mk_data = mk_r.get("data") or {} if mk_r.get("status") == "ok" else {}
    as_resp = ((as_r.get("data") or {}).get("resposta") or {}) if as_r.get("status") == "ok" else {}
    db = mk_data.get("DadosBasicos") or {}
    as_cad = as_resp.get("dadosCadastrais") or {}

    telefones: list[dict[str, Any]] = list(mkbuscas._extract_phones(mk_data))
    for t in (as_resp.get("telefones") or []) + (as_resp.get("telefonesAdicionados") or []):
        num = str(t.get("telefone") or t.get("numero") or "")
        if num:
            telefones.append({"telefone": num, "ddd": str(t.get("ddd") or ""), "fonte": "Assertiva"})

    confirmacoes = await _confirmar_telefones(telefones, doc)

    enderecos = mkbuscas._extract_cities(mk_data)
    for e in (as_resp.get("enderecos") or []) + (as_resp.get("enderecosAdicionados") or []):
        if e.get("cidade"):
            enderecos.append({"cidade": e.get("cidade", ""), "uf": e.get("uf", ""), "bairro": e.get("bairro", "")})

    return {
        "tipo": "cpf",
        "doc": _fmt_cpf(doc),
        "nome": db.get("nome") or as_cad.get("nome") or "",
        "nome_mae": db.get("nomeMae") or as_cad.get("nomeMae") or "",
        "nascimento": db.get("dataNascimento") or as_cad.get("dataNascimento") or "",
        "estado_civil": db.get("estadoCivil") or as_cad.get("estadoCivil") or "",
        "sexo": db.get("sexo") or as_cad.get("sexo") or "",
        "situacao_cpf": db.get("situacaoCadastral") or "",
        "renda": db.get("faixaRenda") or db.get("renda") or "",
        "score": (db.get("scoreCredito") or {}).get("faixa") if isinstance(db.get("scoreCredito"), dict) else db.get("scoreCredito"),
        "profissao": (mk_data.get("profissao") or {}).get("cboDescricao") or "",
        "telefones": telefones,
        "confirmacoes": confirmacoes,
        "enderecos": enderecos,
        "empresas_vinculadas": mkbuscas._extract_companies(mk_data) + [
            f"{p.get('cargo', '')} — {p.get('razaoSocial', '')}".strip(" —")
            for p in (as_resp.get("participacoesEmpresas") or as_resp.get("participacoesSocietarias") or [])
        ],
        "parentes": [p.get("nomeParente") or p.get("nome") or "" for p in (mk_data.get("parentes") or [])],
        "fontes": {
            "mk": mk_r.get("status", "unavailable"),
            "assertiva": as_r.get("status", "unavailable"),
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
    for t in (as_resp.get("telefones") or []) + (as_resp.get("telefonesAdicionados") or []):
        num = str(t.get("telefone") or t.get("numero") or "")
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
        out.append({"telefone": raw, "fonte": t.get("fonte", ""), **r})
    return out


# ────────────────────────────────────────────────────────────────
# Geração do PDF
# ────────────────────────────────────────────────────────────────

def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("DTitulo", parent=ss["Title"], textColor=AZUL, fontSize=18, spaceAfter=2))
    ss.add(ParagraphStyle("DSub", parent=ss["Normal"], textColor=CINZA, fontSize=9, spaceAfter=14))
    ss.add(ParagraphStyle("DSecao", parent=ss["Heading2"], textColor=AZUL, fontSize=12,
                           spaceBefore=14, spaceAfter=6, borderColor=TERRACOTA, borderWidth=0))
    ss.add(ParagraphStyle("DCampo", parent=ss["Normal"], fontSize=9.5, leading=14))
    return ss


def _tabela(linhas: list[tuple[str, str]], col1=45 * mm) -> Table:
    rows = [[Paragraph(f"<b>{k}</b>", _styles()["DCampo"]), Paragraph(v or "—", _styles()["DCampo"])] for k, v in linhas]
    t = Table(rows, colWidths=[col1, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DBD4C6")),
    ]))
    return t


def gerar_pdf_cpf(d: dict[str, Any]) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    flow = [
        Paragraph("Dossiê — Pessoa física", styles["DTitulo"]),
        Paragraph(f"Gerado por CapiBLU em {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["DSub"]),
        Paragraph("Dados cadastrais", styles["DSecao"]),
        _tabela([
            ("CPF", d["doc"]), ("Nome", d["nome"]), ("Nome da mãe", d["nome_mae"]),
            ("Nascimento", d["nascimento"]), ("Sexo", d["sexo"]), ("Estado civil", d["estado_civil"]),
            ("Profissão", d["profissao"]), ("Situação CPF", d["situacao_cpf"]),
            ("Faixa de renda", str(d["renda"] or "")), ("Score de crédito", str(d["score"] or "")),
        ]),
    ]

    flow.append(Paragraph("Telefones encontrados", styles["DSecao"]))
    if d["telefones"]:
        rows = [["Telefone", "Fonte"]] + [[t.get("telefone", ""), t.get("fonte", "Mk Buscas")] for t in d["telefones"][:20]]
        tb = Table(rows, colWidths=[60 * mm, None])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DBD4C6")),
        ]))
        flow.append(tb)
    else:
        flow.append(Paragraph("Nenhum telefone encontrado.", styles["DCampo"]))

    if d["confirmacoes"]:
        flow.append(Paragraph("Confirmação de telefone (pertence a este CPF?)", styles["DSecao"]))
        rows = [["Telefone", "Pertence?", "Nº de vínculos"]]
        for c in d["confirmacoes"]:
            pertence = "✅ Sim" if c.get("atrelado") else ("❌ Não" if c.get("atrelado") is False else "❓ " + str(c.get("message") or "sem dados"))
            rows.append([c.get("telefone", ""), pertence, str(c.get("total", "—"))])
        tb = Table(rows, colWidths=[45 * mm, 45 * mm, None])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TERRACOTA), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tb)

    flow.append(Paragraph("Endereços", styles["DSecao"]))
    ends = d["enderecos"][:10]
    flow.append(Paragraph("<br/>".join(f"{e.get('bairro', '')}, {e.get('cidade', '')}/{e.get('uf', '')}" for e in ends) or "Nenhum endereço encontrado.", styles["DCampo"]))

    flow.append(Paragraph("Empresas / vínculo profissional", styles["DSecao"]))
    flow.append(Paragraph("<br/>".join(d["empresas_vinculadas"][:15]) or "Nenhum vínculo encontrado.", styles["DCampo"]))

    if d["parentes"]:
        flow.append(Paragraph("Parentes", styles["DSecao"]))
        flow.append(Paragraph(", ".join(p for p in d["parentes"][:15] if p), styles["DCampo"]))

    flow.append(Spacer(1, 14))
    flow.append(Paragraph(
        f"Fontes: Mk Buscas ({d['fontes']['mk']}) · Assertiva ({d['fontes']['assertiva']})",
        styles["DSub"],
    ))
    doc.build(flow)
    return buf.getvalue()


def gerar_pdf_cnpj(d: dict[str, Any]) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    flow = [
        Paragraph("Dossiê — Empresa", styles["DTitulo"]),
        Paragraph(f"Gerado por CapiBLU em {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["DSub"]),
        Paragraph("Dados cadastrais", styles["DSecao"]),
        _tabela([
            ("CNPJ", d["doc"]), ("Razão social", d["razao_social"]), ("Nome fantasia", d["nome_fantasia"]),
            ("Situação", d["situacao"]), ("Abertura", d["abertura"]), ("Atividade principal", d["atividade"]),
            ("Capital social", f"R$ {d['capital_social']}" if d["capital_social"] else ""),
            ("Endereço", d["endereco"]),
        ]),
    ]

    flow.append(Paragraph("Sócios", styles["DSecao"]))
    if d["socios"]:
        rows = [["Nome", "Qualificação"]] + [[s["nome"], s["qualificacao"]] for s in d["socios"][:15]]
        tb = Table(rows, colWidths=[100 * mm, None])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tb)
    else:
        flow.append(Paragraph("Nenhum sócio encontrado.", styles["DCampo"]))

    flow.append(Paragraph("Telefones encontrados", styles["DSecao"]))
    if d["telefones"]:
        rows = [["Telefone", "Fonte"]] + [[t.get("telefone", ""), t.get("fonte", "")] for t in d["telefones"][:20]]
        tb = Table(rows, colWidths=[60 * mm, None])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tb)
    else:
        flow.append(Paragraph("Nenhum telefone encontrado.", styles["DCampo"]))

    if d["confirmacoes"]:
        flow.append(Paragraph("Confirmação de telefone (pertence a este CNPJ?)", styles["DSecao"]))
        rows = [["Telefone", "Pertence?", "Nº de vínculos"]]
        for c in d["confirmacoes"]:
            pertence = "✅ Sim" if c.get("atrelado") else ("❌ Não" if c.get("atrelado") is False else "❓ " + str(c.get("message") or "sem dados"))
            rows.append([c.get("telefone", ""), pertence, str(c.get("total", "—"))])
        tb = Table(rows, colWidths=[45 * mm, 45 * mm, None])
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TERRACOTA), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tb)

    if d["participacoes_assertiva"]:
        flow.append(Paragraph("Outras participações societárias (Assertiva)", styles["DSecao"]))
        txt = "<br/>".join(f"{p.get('cargo', '')} — {p.get('razaoSocial', '')}" for p in d["participacoes_assertiva"][:15])
        flow.append(Paragraph(txt, styles["DCampo"]))

    flow.append(Spacer(1, 14))
    flow.append(Paragraph(
        f"Fontes: Receita Federal ({d['fontes']['receita']}) · Assertiva ({d['fontes']['assertiva']})",
        styles["DSub"],
    ))
    doc.build(flow)
    return buf.getvalue()
