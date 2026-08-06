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
AMBAR = colors.HexColor("#8C6A16")


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
    # A Mk também manda alguns valores sem acento nenhum (não é "?", é ausência mesmo) —
    # cobre só o vocabulário fixo (enums) que aparece com frequência no dossiê.
    (r"\botimo\b", "Ótimo"), (r"\bmedia\b", "média"), (r"\bmedio\b", "médio"),
    (r"\bflorianopolis\b", "Florianópolis"), (r"\bmaceio\b", "Maceió"), (r"\bgoncalves\b", "Gonçalves"),
    (r"\bmae\b", "Mãe"), (r"\birma\b", "Irmã"),
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


def _fmt_inteiro(s: Any) -> str:
    """'1630' -> '1.630' (separador de milhar, pt-BR)."""
    d = only_digits(str(s or ""))
    return f"{int(d):,}".replace(",", ".") if d else ""


def _fmt_moeda(s: Any) -> str:
    """'1714,12' -> '1.714,12'."""
    s = str(s or "").strip()
    if not s:
        return ""
    inteiro, _, dec = s.replace(".", "").partition(",")
    return _fmt_inteiro(inteiro) + (f",{dec}" if dec else "")


def _fmt_preco(s: Any) -> str:
    """'31.85' (a Mk manda com ponto decimal) -> '31,85'."""
    s = str(s or "").strip()
    if "." in s and "," not in s:
        inteiro, dec = s.rsplit(".", 1)
        return f"{inteiro},{dec}"
    return s


def _fmt_faixa(s: str) -> str:
    """'De R$ 1630 at? R$ 4082' -> 'R$ 1.630–4.082'."""
    m = re.search(r"R\$\s*([\d.,]+).*?R\$\s*([\d.,]+)", s or "")
    if not m:
        return _reparar_mojibake(s or "")
    return f"R$ {_fmt_inteiro(m.group(1))}–{_fmt_inteiro(m.group(2))}"


_TIPO_LOGRADOURO = {
    "R": "R.", "AV": "Av.", "TRAV": "Trav.", "AL": "Al.", "ALA": "Al.", "PC": "Pç.",
    "CJ": "Cj.", "ESTR": "Estr.", "ROD": "Rod.", "VL": "Vl.", "QD": "Qd.", "LT": "Lt.",
}


def _titlecase(s: str) -> str:
    """ALL CAPS -> Title Case, mantendo conectores (de/da/do/dos/das/e) minúsculos
    e algarismos romanos (I, II, III) maiúsculos."""
    conectores = {"de", "da", "do", "dos", "das", "e"}
    palavras = (s or "").strip().lower().split()
    out = []
    for i, p in enumerate(palavras):
        if p in conectores and i > 0:
            out.append(p)
        elif re.fullmatch(r"[ivx]+", p):
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return " ".join(out)


def _tel_tipo(raw_tipo: str) -> str:
    t = (raw_tipo or "").upper()
    if "MOVEL" in t or "M" + chr(0xd3) + "VEL" in t or "CELULAR" in t:
        return "Celular"
    if "RESIDENCIAL" in t or "FIXO" in t:
        return "Fixo"
    if "COMERCIAL" in t:
        return "Comercial"
    return ""


# ────────────────────────────────────────────────────────────────
# Coleta de dados — CPF (Mk Buscas + Assertiva + intelgrax-tel)
# ────────────────────────────────────────────────────────────────

def _telefones_assertiva_com_tipo(as_resp: dict[str, Any]):
    """Telefones/telefonesAdicionados da Assertiva, com TIPO (Celular/Fixo)
    conhecido quando o bloco vem separado em {fixos, moveis} — a Assertiva
    às vezes já classifica, e isso é melhor que adivinhar pelo formato do número."""
    for chave in ("telefones", "telefonesAdicionados"):
        bloco = as_resp.get(chave)
        if isinstance(bloco, dict):
            for tipo, lista in (("Celular", bloco.get("moveis") or []), ("Fixo", bloco.get("fixos") or [])):
                for t in lista:
                    num = str(t.get("numero") or t.get("telefone") or "")
                    if num:
                        yield num, str(t.get("ddd") or ""), tipo, t
        elif isinstance(bloco, list):
            for t in bloco:
                num = str(t.get("numero") or t.get("telefone") or "")
                if num:
                    yield num, str(t.get("ddd") or ""), "", t


_MAX_PARENTES_ENRIQUECIDOS = 4


async def _enriquecer_familia(parentes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consulta Mk Buscas pra cada parente com CPF conhecido (até
    _MAX_PARENTES_ENRIQUECIDOS, pra não estourar custo) e anexa um resumo
    básico — usado só quando o usuário liga "Incluir família" (opt-in, cada
    parente é 1+ consulta paga extra)."""
    out = []
    consultados = 0
    for p in parentes:
        p = dict(p)
        cpf_p = only_digits(p.get("cpf", ""))
        if cpf_p and len(cpf_p) == 11 and consultados < _MAX_PARENTES_ENRIQUECIDOS and mkbuscas.enabled():
            consultados += 1
            r = await mkbuscas.consulta_cpf(cpf_p)
            if r.get("status") == "ok":
                d = r["data"]
                db_p = d.get("DadosBasicos") or {}
                de_p = d.get("DadosEconomicos") or {}
                sit_p = db_p.get("situacaoCadastral") if isinstance(db_p.get("situacaoCadastral"), dict) else {}
                p["resumo"] = {
                    "situacao_cpf": sit_p.get("descricaoSituacaoCadastral", ""),
                    "renda": (de_p.get("renda") or ""),
                    "score_faixa": ((de_p.get("score") or {}).get("scoreCSBAFaixaRisco") or ""),
                    "profissao": ((d.get("profissao") or {}).get("cboDescricao") or ""),
                    "empresas_vinculadas": mkbuscas._extract_companies(d),
                }
        out.append(p)
    return out


async def montar_cpf(cpf: str, incluir_familia: bool = False) -> dict[str, Any]:
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

    telefones: list[dict[str, Any]] = [
        {**t, "tipo": _tel_tipo(t.get("tipo", ""))} for t in mkbuscas._extract_phones(mk_data)
    ]
    for num, ddd, tipo, resto in _telefones_assertiva_com_tipo(as_resp):
        telefones.append({
            "telefone": num, "ddd": ddd, "fonte": "Assertiva", "tipo": tipo,
            "operadora": resto.get("operadora", ""), "ultimo_contato": resto.get("ultimoContato", ""),
            "whatsapp": (resto.get("aplicativos") or {}).get("whatsApp") if isinstance(resto.get("aplicativos"), dict) else None,
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
    if incluir_familia:
        parentes = await _enriquecer_familia(parentes)
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
    compras = [c for c in (mk_data.get("comprasId") or []) if isinstance(c, dict) and c.get("produto")]
    perfil_consumo = mk_data.get("perfilConsumo") if isinstance(mk_data.get("perfilConsumo"), dict) else {}
    tem_vacinacao = bool(mk_data.get("imunoBiologicos"))
    lista_docs = mk_data.get("listaDocumentos") if isinstance(mk_data.get("listaDocumentos"), dict) else {}
    cns_lista = lista_docs.get("CNS") or []

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
        "poder_aquisitivo": poder.get("poderAquisitivoDescricao") or "",
        "score": score.get("scoreCSBA") or "",
        "score_faixa": score.get("scoreCSBAFaixaRisco") or "",
        "score_csb_ausente": not score.get("scoreCSB"),
        "mosaic": mosaic.get("descricaoMosaicSecundario") or mosaic.get("descricaoMosaicNovo") or mosaic.get("descricaoMosaic") or "",
        "mosaic_classe": mosaic.get("classeMosaicSecundario") or mosaic.get("classeMosaicNovo") or "",
        "mosaic_grupo_principal": mosaic.get("descricaoMosaic") or "",
        "mosaic_novo": mosaic.get("descricaoMosaicNovo") or "",
        "mosaic_novo_classe": mosaic.get("classeMosaicNovo") or "",
        "profissao": prof.get("cboDescricao") if prof.get("cboDescricao") and "sem descri" not in (prof.get("cboDescricao") or "").lower() else "",
        "cbo": prof.get("cbo") or "",
        "pis": prof.get("pis") or "",
        "rg": db.get("registroGeral") if isinstance(db.get("registroGeral"), str) else (mk_data.get("registroGeral") or ""),
        "cns": (cns_lista[0] if cns_lista else "") or db.get("cns") or "",
        "compras": compras,
        "perfil_consumo": perfil_consumo,
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
        "tem_vacinacao": tem_vacinacao,
        "incluiu_familia": incluir_familia,
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
            conteudo.append(Paragraph(_texto(sub), styles["DCardSub"]))
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
    tipo = _TIPO_LOGRADOURO.get((e.get("tipoLogradouro") or "").upper(), (e.get("tipoLogradouro") or "").title())
    partes = [tipo, _titlecase(e.get("logradouro", ""))]
    linha1 = " ".join(p for p in partes if p).strip()
    if e.get("logradouroNumero"):
        linha1 += f", {e['logradouroNumero']}"
    if e.get("complemento"):
        linha1 += f" · {_titlecase(e['complemento'])}"
    if e.get("bairro"):
        linha1 += f" — {_titlecase(e['bairro'])}"
    linha2 = ", ".join(p for p in [_titlecase(e.get("cidade", "")), e.get("uf", "")] if p)
    if e.get("cep"):
        cep = only_digits(str(e["cep"])).zfill(8)
        linha2 += f" · CEP {cep[:5]}-{cep[5:]}"
    return _reparar_mojibake("<br/>".join(p for p in [linha1, linha2] if p) or "—")


def _callout(titulo: str, texto: str) -> Table:
    styles = _styles()
    t = Table([[Paragraph(f"<b>{titulo}</b><br/>{texto}", styles["DCampo"])]], colWidths=[None])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, 0), 2.5, TERRACOTA),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _header_pagina(titulo: str, numero: int, total: int = 4) -> Table:
    styles = _styles()
    st_titulo = ParagraphStyle("hpTitulo", parent=styles["DTopo"], fontName="Helvetica-Bold", fontSize=9)
    esquerda = Paragraph(titulo.upper(), st_titulo)
    direita = Paragraph(f"página {numero} de {total}", styles["DTopoDireita"])
    t = Table([[esquerda, direita]], colWidths=[None, None])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CINZA_CLARO),
    ]))
    return t


def _barra(pct: float, largura: float = 32 * mm, altura: float = 3.2):
    from reportlab.graphics.shapes import Drawing, Rect
    dw = Drawing(largura, altura)
    dw.add(Rect(0, 0, largura, altura, fillColor=CINZA_CLARO, strokeColor=None))
    dw.add(Rect(0, 0, largura * max(0, min(pct, 100)) / 100.0, altura, fillColor=AZUL, strokeColor=None))
    return dw


_LABELS_PCT = {
    "financiamento_veiculo": "Financiamento de veículo", "compra_internet": "Compra pela internet",
    "credito_pessoal": "Crédito pessoal", "casa_propria": "Casa própria", "investimentos": "Investimentos",
    "turismo": "Turismo", "multiplos_cartoes": "Múltiplos cartões", "cartao_prime": "Cartão prime",
    "tv_cabo": "TV por assinatura", "banda_larga": "Banda larga", "seguro_automotivo": "Seguro automotivo",
    "seguro_saude": "Seguro saúde", "seguro_vida": "Seguro vida", "seguro_residencial": "Seguro residencial",
    "consignado": "Crédito consignado", "previdencia_privada": "Previdência privada",
    "resgate_milhas": "Resgate de milhas", "cacador_descontos": "Caçador de descontos", "fitness": "Fitness",
    "cinefilo": "Cinéfilo", "transporte_publico": "Transporte público", "jogos_online": "Jogos online",
    "video_game": "Videogame", "early_adopters": "Early adopter", "credito_mobiliario": "Crédito imobiliário",
    "celular_pre_pago": "Celular pré-pago", "celular_pos_pago": "Celular pós-pago", "luxo": "Produtos de luxo",
}
_LABELS_BOOL = {
    "credito_pessoal_pre_aprovado": "Crédito pessoal pré-aprovado",
    "credito_imobiliario_pre_aprovado": "Crédito imobiliário pré-aprovado",
    "financiamento_de_veiculo_pre_aprovado": "Financiamento de veículo pré-aprovado",
    "classe_media": "Classe média", "debito_autmatico": "Débito automático", "possui_luxo": "Produtos de luxo",
    "possui_investimentos": "Investimentos", "possui_cartao_de_credito": "Cartão de crédito",
    "possui_multiplos_cartoes": "Múltiplos cartões", "possui_conta_alto_padrao": "Conta de alto padrão",
    "possui_cartao_black": "Cartão black", "possui_cartao_prime": "Cartão prime",
    "possui_celular_pre_pago": "Celular pré-pago", "possui_celular_pos_pago": "Celular pós-pago",
    "possui_milhas_acumuladas": "Milhas acumuladas", "possui_casa_propria": "Casa própria",
    "possui_descontos": "Caçador de descontos", "possui_contas_correntes": "Contas correntes",
    "possui_seguro_automotivo": "Seguro automotivo", "possui_previdencia_privada": "Previdência privada",
    "possui_internet_banking": "Internet banking", "possui_token_instalado": "Token de segurança instalado",
    "realizou_viagens": "Já viajou",
}


def _parece_comercial(email: str) -> bool:
    local, _, dominio = (email or "").partition("@")
    dominio_nome = dominio.split(".")[0].lower()
    return bool(local) and bool(dominio_nome) and (local.lower() == dominio_nome or local.lower() in dominio_nome)


def gerar_pdf_cpf(d: dict[str, Any]) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)

    # ── Página 1 — identificação ──────────────────────────────────
    esquerda = Paragraph("CAPIBLU · DOSSIÊ DE PESSOA", styles["DTopo"])
    direita = Paragraph("consulta de CPF", styles["DTopoDireita"])
    cab = Table([[esquerda, direita]], colWidths=[None, None])
    cab.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), 0.75, AZUL),
    ]))
    flow = [cab]

    idade_txt = f"{d['idade']} anos" if d.get("idade") else ""
    nasc_txt = f"nascida em {d['nascimento']}" if d.get("nascimento") else ""
    nasc_local = f" em {_titlecase(d['municipio_nascimento'])}" if d.get("municipio_nascimento") else ""
    subtitulo = " · ".join(p for p in [d["doc"], idade_txt, (nasc_txt + nasc_local).strip(), (d.get("sexo") or "").lower()] if p)
    flow.append(Paragraph(_titlecase(d["nome"]) or "Nome não encontrado", styles["DNome"]))
    flow.append(Paragraph(subtitulo, styles["DSub"]))

    pills = []
    if d.get("situacao_cpf"):
        boa = "regular" in d["situacao_cpf"].lower()
        pills.append(_pill(f"CPF {d['situacao_cpf'].lower()} na Receita", VERDE_SOFT if boa else TERRACOTA_SOFT, VERDE if boa else TERRACOTA))
    if d.get("obito"):
        sem_obito = d["obito"] not in ("SIM",)
        pills.append(_pill("Sem indício de óbito" if sem_obito else "Óbito registrado", VERDE_SOFT if sem_obito else TERRACOTA_SOFT, VERDE if sem_obito else TERRACOTA))
    pills.append(_pill("É PPE" if d.get("pep") else "Não é PPE", TERRACOTA_SOFT if d.get("pep") else colors.HexColor("#E8EDF1"), TERRACOTA if d.get("pep") else AZUL))
    flow.append(_linha_pills(pills))
    flow.append(Spacer(1, 10))

    cards = []
    if d.get("renda"):
        sub_renda = ""
        if d.get("faixa_renda"):
            sub_renda = f"Faixa {_fmt_faixa(d['faixa_renda'])}"
            if d.get("poder_aquisitivo"):
                sub_renda += f", poder aquisitivo {d['poder_aquisitivo'].lower()}"
            sub_renda += ". Estimativa, não é salário confirmado."
        cards.append(("Renda estimada", f"R$ {_fmt_moeda(d['renda'])}", sub_renda))
    if d.get("score"):
        risco = {"medio": "médio"}.get((d.get("score_faixa") or "").lower(), (d.get("score_faixa") or "").lower())
        cor_risco = VERDE if "baixo" in risco else (TERRACOTA if "alto" in risco else AMBAR)
        cor_hex = "#" + cor_risco.hexval()[2:]
        valor_html = f"{d['score']}  <font size='8.5' color='{cor_hex}'>risco {risco}</font>" if risco else str(d["score"])
        sub_score = "Uma segunda base não devolveu score para este CPF." if d.get("score_csb_ausente") else ""
        cards.append(("Score de crédito", valor_html, sub_score))
    if d.get("mosaic"):
        sub_mosaic = f'Grupo principal "{d["mosaic_grupo_principal"]}"; classificação de mercado, não é renda confirmada.' if d.get("mosaic_grupo_principal") else "Classificação de mercado, não é renda confirmada."
        cards.append(("Perfil de consumo", d["mosaic"], sub_mosaic))
    if cards:
        flow.append(_cards(cards))
        flow.append(Spacer(1, 12))

    kv = [
        ("Nome da mãe", _titlecase(d.get("nome_mae", ""))),
        ("Situação cadastral", (f"{d['situacao_cpf'].capitalize()}" + (f" — confirmada em {d['situacao_cpf_data']}" if d.get("situacao_cpf_data") else "")) if d.get("situacao_cpf") else ""),
        ("Escolaridade", _texto(d.get("escolaridade", "")).capitalize() if d.get("escolaridade") else ""),
        ("Benefícios sociais", "; ".join(f"{b.get('beneficio', '')} ({b.get('totalRecebido', '')})" for b in d.get("beneficios", [])) or "Nenhum registrado (auxílio emergencial, Bolsa Família, BPC, INSS)."),
    ]
    flow.append(_tabela_kv([(k, v) for k, v in kv if v]))
    flow.append(Spacer(1, 14))
    flow.append(_callout(
        "Como ler este documento",
        "Reúne dados públicos e de mercado sobre a pessoa acima, para fins de prospecção comercial "
        "(legítimo interesse, LGPD). Estimativas de renda e consumo são probabilísticas — não confirme "
        "decisões só com elas.",
    ))

    # ── Página 2 — como falar com ela ─────────────────────────────
    flow.append(PageBreak())
    flow.append(_header_pagina("Como falar com ela", 2))

    if d.get("telefones"):
        n = len(d["telefones"])
        flow.append(Paragraph(f"Telefones — {n} encontrado{'s' if n != 1 else ''}", styles["DSubsecao"]))
        melhor = next((c for c in d.get("confirmacoes", []) if c.get("atrelado") and (c.get("total") or 99) <= 2), None)
        if melhor:
            flow.append(Paragraph(f"O celular abaixo aparece só ligado a ela em busca reversa.", styles["DCampo"]))
        linhas_tel = []
        for t in d["telefones"][:15]:
            pert = t.get("_pertence")
            if pert and pert.get("atrelado") is True:
                total_p = pert.get("total") or 1
                confirmado = "Confirmado — só ela aparece" if total_p <= 1 else f"Confirmado (aparece {total_p}x)"
            elif pert and pert.get("atrelado") is False:
                confirmado = "não é dela"
            else:
                confirmado = "não conferido"
            linhas_tel.append([_fmt_tel(t), t.get("tipo") or "—", confirmado])
        flow.append(_tabela_dados(["Telefone", "Tipo", "É dela mesmo?"], linhas_tel, col_widths=[35 * mm, 30 * mm, None]))

    if d.get("emails"):
        n = len(d["emails"])
        flow.append(Paragraph(f"E-mails — {n} encontrado{'s' if n != 1 else ''}", styles["DSubsecao"]))
        comercial = next((e for e in d["emails"] if _parece_comercial(e.get("email", ""))), None)
        if comercial:
            local_com = comercial["email"].split("@")[0]
            flow.append(Paragraph(f'Um deles ("{local_com}") sugere um negócio próprio ou envolvimento comercial.', styles["DCampo"]))
        linhas_email = []
        for e in d["emails"][:10]:
            pessoal = (e.get("emailPessoal") or "").upper()
            if pessoal == "SIM":
                eh_pessoal = "Sim"
            elif _parece_comercial(e.get("email", "")):
                eh_pessoal = "Não — parece comercial"
            else:
                eh_pessoal = "Não" if pessoal == "NAO" or pessoal == "N" + chr(0xd3) else "—"
            qualidade = " · ".join(p for p in [_texto(e.get("qualidade", ""), "").capitalize(), (e.get("prioridade") or "").lower()] if p and p != "—")
            linhas_email.append([e.get("email", ""), qualidade, eh_pessoal])
        flow.append(_tabela_dados(["E-mail", "Qualidade", "É pessoal?"], linhas_email))

    if d.get("enderecos"):
        n = len(d["enderecos"])
        flow.append(Paragraph(f"Onde ela já morou — {n} endereço{'s' if n != 1 else ''}", styles["DSubsecao"]))
        flow.append(Paragraph("Do mais recente para o mais antigo.", styles["DCampo"]))
        for i, e in enumerate(d["enderecos"][:10]):
            linha = Table([[Paragraph(_endereco_txt(e), styles["DCampo"]),
                             Paragraph("mais recente" if i == 0 else "", ParagraphStyle("tag", parent=styles["DCampo"], textColor=VERDE, fontName="Helvetica-Bold", alignment=2))]],
                          colWidths=[None, 30 * mm])
            linha.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8),
                                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CINZA_CLARO), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow.append(linha)

    # ── Página 3 — perfil de consumo ──────────────────────────────
    flow.append(PageBreak())
    flow.append(_header_pagina("Perfil de consumo", 3))

    pc = d.get("perfil_consumo") or {}
    tem = [_LABELS_BOOL[k] for k, v in pc.items() if k in _LABELS_BOOL and v is True]
    nao_tem = [_LABELS_BOOL[k] for k, v in pc.items() if k in _LABELS_BOOL and v is False]
    if tem or nao_tem:
        flow.append(Paragraph("O que ela provavelmente tem e usa", styles["DSubsecao"]))
        flow.append(Paragraph("Sinalizadores de mercado, não confirmação bancária.", styles["DCampo"]))
        col_tem = [Paragraph("<b>PROVAVELMENTE TEM</b>", styles["DCardLabel"]), Paragraph(" · ".join(tem) or "—", styles["DCampo"])]
        col_nao = [Paragraph("<b>PROVAVELMENTE NÃO TEM</b>", styles["DCardLabel"]), Paragraph(" · ".join(nao_tem) or "—", styles["DCampo"])]
        tb = Table([[col_tem, col_nao]], colWidths=[None, None])
        tb.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, CINZA_CLARO), ("INNERGRID", (0, 0), (-1, -1), 0.6, CINZA_CLARO),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        flow.append(tb)
        flow.append(Spacer(1, 12))

    pcts = []
    for k, v in pc.items():
        if isinstance(v, str):
            m = re.search(r"(\d+)%", v)
            if m:
                pcts.append((_LABELS_PCT.get(k, k.replace("_", " ").capitalize()), int(m.group(1))))
    pcts.sort(key=lambda x: -x[1])
    if pcts:
        pct_style = ParagraphStyle("pct", parent=styles["DCampo"], fontSize=9, wordWrap=None)
        flow.append(Paragraph(f"Chance de interesse em cada oferta (top {min(len(pcts), 8)} de {len(pcts)})", styles["DSubsecao"]))
        linhas_bar = []
        top = pcts[:8]
        pares = list(zip(top[0::2], top[1::2] + [None]))
        for (lbl1, pct1), par2 in pares:
            row = [Paragraph(lbl1, styles["DCampo"]), _barra(pct1), Paragraph(f"{pct1}%", pct_style)]
            if par2:
                lbl2, pct2 = par2
                row += [Paragraph(lbl2, styles["DCampo"]), _barra(pct2), Paragraph(f"{pct2}%", pct_style)]
            else:
                row += ["", "", ""]
            linhas_bar.append(row)
        tb = Table(linhas_bar, colWidths=[40 * mm, 30 * mm, 13 * mm, 40 * mm, 30 * mm, 13 * mm])
        tb.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        flow.append(tb)

    if d.get("compras"):
        flow.append(Paragraph("Compras recentes identificadas", styles["DSubsecao"]))
        flow.append(Paragraph("Sinalizador de mercado, a partir de bases de e-commerce/varejo.", styles["DCampo"]))
        linhas_compra = [[_texto(c.get("produto", "")), c.get("quantidade", ""), f"R$ {_fmt_preco(c.get('preco', ''))}"] for c in d["compras"][:8]]
        flow.append(_tabela_dados(["Produto", "Qtd.", "Preço"], linhas_compra, col_widths=[None, 20 * mm, 25 * mm]))

    # ── Página 4 — família, vizinhos e metodologia ────────────────
    flow.append(PageBreak())
    flow.append(_header_pagina("Família, vizinhos e metodologia", 4))

    if d.get("parentes"):
        flow.append(Paragraph("Família próxima", styles["DSubsecao"]))
        linhas_fam = [[_titlecase(p["nome"]), re.sub(r"\(\w+\)$", "", p.get("grau", "")).strip().capitalize() or "—", _fmt_cpf(p["cpf"]) if p.get("cpf") else "não informado"] for p in d["parentes"][:12]]
        flow.append(_tabela_dados(["Nome", "Parentesco", "CPF"], linhas_fam, col_widths=[None, 40 * mm, 35 * mm]))
        if d.get("incluiu_familia") and any(p.get("resumo") for p in d["parentes"]):
            flow.append(Spacer(1, 6))
            for p in d["parentes"][:_MAX_PARENTES_ENRIQUECIDOS]:
                r = p.get("resumo")
                if not r:
                    continue
                partes = [
                    f"situação {r['situacao_cpf'].lower()}" if r.get("situacao_cpf") else "",
                    f"renda R$ {_fmt_moeda(r['renda'])}" if r.get("renda") else "",
                    f"risco {r['score_faixa'].lower()}" if r.get("score_faixa") else "",
                    f"profissão: {r['profissao']}" if r.get("profissao") else "",
                ]
                resumo_txt = ", ".join(x for x in partes if x)
                if resumo_txt:
                    grau_limpo = re.sub(r"\(\w+\)$", "", p.get("grau", "")).strip().lower()
                    flow.append(Paragraph(f"<b>{_titlecase(p['nome'])} ({grau_limpo}):</b> {resumo_txt}.", styles["DCampo"]))

    if d.get("vizinhos"):
        total_viz = len(d["vizinhos"])
        mostrar = d["vizinhos"][:4]
        flow.append(Paragraph("Pessoas que moram perto dela", styles["DSubsecao"]))
        flow.append(Paragraph(f"Mostrando {len(mostrar)} de {total_viz} encontrados.", styles["DCampo"]))
        flow.append(_tabela_dados(["Nome", "Idade", "Nome da mãe"],
                                   [[_titlecase(v["nome"]), str(v.get("idade", "")), _titlecase(v.get("nome_mae", ""))] for v in mostrar],
                                   col_widths=[None, 20 * mm, None]))

    if d.get("comentarios"):
        flow.append(Paragraph("Anotações", styles["DSubsecao"]))
        for c in d["comentarios"][:5]:
            flow.append(Paragraph(f"“{_texto(c)}”", styles["DNota"]))

    metodologia = [("Consulta", "CPF · finalidade legítimo interesse (prospecção comercial, LGPD)")]

    imposto = d.get("declaracao_imposto") or []
    sem_decl = [i.get("ano", "") for i in imposto if "NAO CONSTA" in (i.get("status", "") or "").upper()]
    if sem_decl and len(sem_decl) == len(imposto):
        metodologia.append(("Declaração de IR", f"Sem declaração na Receita para {' e '.join(sorted(set(sem_decl)))}."))
    elif imposto:
        metodologia.append(("Declaração de IR", f"{len(imposto)} registro(s) de declaração encontrado(s) na base."))

    melhor_conf = next((c for c in d.get("confirmacoes", []) if c.get("status") == "ok"), None)
    if melhor_conf:
        if melhor_conf.get("atrelado"):
            total_c = melhor_conf.get("total") or 1
            nome_bate = melhor_conf.get("nome") or d.get("nome", "")
            txt = f"{_fmt_tel({'telefone': melhor_conf['telefone']})} aparece {total_c}x, sempre para {_titlecase(nome_bate)}" + (" — sem duplicidade com outra pessoa." if total_c <= 2 else ".")
        else:
            txt = f"{_fmt_tel({'telefone': melhor_conf['telefone']})} não aparece atrelado a este CPF na base de telefone reverso."
        metodologia.append(("Telefone reverso", txt))

    flow.append(Paragraph("De onde vêm esses dados", styles["DSubsecao"]))
    flow.append(_tabela_kv(metodologia))

    faltantes = []
    if not d.get("rg"):
        faltantes.append("RG")
    if not d.get("cns"):
        faltantes.append("CNS")
    if not d.get("estado_civil"):
        faltantes.append("estado civil")
    if not d.get("profissao"):
        faltantes.append("profissão")
    if not d.get("empregos"):
        faltantes.append("emprego")
    if not d.get("tem_vacinacao"):
        faltantes.append("vacinação")
    aviso_faltantes = f" Sem {', '.join(faltantes[:-1])}{' e ' if len(faltantes) > 1 else ''}{faltantes[-1] if faltantes else ''} registrados nas bases consultadas." if faltantes else ""
    flow.append(Spacer(1, 10))
    flow.append(_callout(
        "Antes de usar este documento",
        "Dados de renda, score e consumo são estimativas de mercado, não confirmação bancária." + aviso_faltantes,
    ))

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
