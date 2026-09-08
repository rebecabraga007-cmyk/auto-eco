# -*- coding: utf-8 -*-
"""Diretório de municípios: entende a cidade do LinkedIn mesmo escrita errado.

POR QUE EXISTE. Medido no cache: de 9.016 perfis brasileiros com cidade
preenchida, 806 (8,9%) não casavam com município nenhum — em 37 grafias
distintas. Sem casar, não há DDD, não há filtro por cidade e não há repescagem
por UF: o perfil ia direto para a consulta paga e voltava vazio.

AS SEIS FAMÍLIAS DE ERRO, todas tiradas do cache real:

  1. só o estado        "Santa Catarina, Brazil", "Brazil"     ~740 perfis
     Não é cidade. Devolve a UF e cidade vazia, em vez de inventar um
     município chamado "Santa Catarina" — que existe, no RN, e mandaria a
     busca para o estado errado com ar de acerto.

  2. região administrativa do DF   Ceilândia, Gama, Samambaia, Lago Norte…
     O DF tem UM município: Brasília. As RAs são bairros grandes, e nenhuma
     está na base da Receita.

  3. nome em inglês     "New Fribourg" = Nova Friburgo/RJ

  4. hífen e pontuação  "São João del-Rei", "Biritiba Mirim"
     Regra geral, não alias: normalizar hífen resolve a família inteira.

  5. distrito ou bairro "Jaibaras" (distrito de Sobral/CE)
     Cai no fuzzy com a UF conhecida, ou não resolve — e não resolver é
     melhor que apontar para o município errado.

  6. não é lugar        "45 followers", "1 follower"
     Sujeira de raspagem que chegava até a consulta paga.

REGRA DE CONFIANÇA: o fuzzy só responde com a UF conhecida e com semelhança
alta. Sem UF, a chance de "Bom Jesus" (que existe em 9 estados) cair no lugar
errado é grande demais, e telefone errado no funil é pior que telefone nenhum.
"""
import difflib
import json
import os
import re
import unicodedata
from typing import Any

MAPA_DDD = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"),
                        "cidade_ddd.json")

# ---------------------------------------------------------------- estados
UF_POR_NOME: dict[str, str] = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM",
    "BAHIA": "BA", "CEARA": "CE", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
    "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR",
    "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO",
    "RORAIMA": "RR", "SANTA CATARINA": "SC", "SAO PAULO": "SP",
    "SERGIPE": "SE", "TOCANTINS": "TO", "DISTRITO FEDERAL": "DF",
    # como o LinkedIn escreve, em inglês
    "FEDERAL DISTRICT": "DF", "STATE OF SAO PAULO": "SP",
    "STATE OF RIO DE JANEIRO": "RJ", "STATE OF MINAS GERAIS": "MG",
    "STATE OF BAHIA": "BA", "STATE OF PARANA": "PR",
    "STATE OF RIO GRANDE DO SUL": "RS", "STATE OF SANTA CATARINA": "SC",
    "STATE OF GOIAS": "GO", "STATE OF PERNAMBUCO": "PE",
    "STATE OF CEARA": "CE", "STATE OF ESPIRITO SANTO": "ES",
    "STATE OF PARA": "PA", "STATE OF AMAZONAS": "AM",
}

# Nomes que são de ESTADO e também de município. Escritos sozinhos, com
# "Brazil" atrás e sem mais nada, quase sempre querem dizer o estado.
AMBIGUOS_ESTADO = {"SAO PAULO", "RIO DE JANEIRO", "AMAZONAS", "PARA",
                   "SANTA CATARINA", "BAHIA", "SERGIPE", "RONDONIA", "ACRE"}

# ------------------------------------------- regiões administrativas do DF
# O DF tem um único município. Estas são RAs, e nenhuma existe na Receita.
RA_DF = {
    "CEILANDIA", "TAGUATINGA", "SAMAMBAIA", "PLANALTINA", "GAMA", "GUARA",
    "SANTA MARIA", "SAO SEBASTIAO", "RECANTO DAS EMAS", "SOBRADINHO",
    "SOBRADINHO II", "RIACHO FUNDO", "RIACHO FUNDO II", "PARANOA",
    "BRAZLANDIA", "NUCLEO BANDEIRANTE", "CANDANGOLANDIA", "LAGO NORTE",
    "LAGO SUL", "CRUZEIRO", "VARJAO", "SUDOESTE", "OCTOGONAL",
    "VICENTE PIRES", "FERCAL", "ITAPOA", "JARDIM BOTANICO", "AGUAS CLARAS",
    "PARK WAY", "SIA", "SCIA", "ESTRUTURAL", "ARNIQUEIRA", "PLANO PILOTO",
    "ASA NORTE", "ASA SUL",
}

# ------------------------------------------------------- nomes irregulares
# Só entra aqui o que NENHUMA regra geral resolve. Cada linha veio de um caso
# real do cache; alias inventado por precaução é dívida, não cobertura.
ALIAS: dict[str, tuple[str, str]] = {
    "NEW FRIBOURG": ("NOVA FRIBURGO", "RJ"),
    "MOGI DAS CRUZES": ("MOGI DAS CRUZES", "SP"),
    "MOJI DAS CRUZES": ("MOGI DAS CRUZES", "SP"),
    "MOGI MIRIM": ("MOGI MIRIM", "SP"),
    "MOJI MIRIM": ("MOGI MIRIM", "SP"),
    "FLORIPA": ("FLORIANOPOLIS", "SC"),
    "BH": ("BELO HORIZONTE", "MG"),
    "RIO": ("RIO DE JANEIRO", "RJ"),
    "SAMPA": ("SAO PAULO", "SP"),
    "BSB": ("BRASILIA", "DF"),
    "POA": ("PORTO ALEGRE", "RS"),
    "SAO PAULO CITY": ("SAO PAULO", "SP"),
    "SANTANA DE PARNAIBA": ("SANTANA DE PARNAIBA", "SP"),
    "EMBU": ("EMBU DAS ARTES", "SP"),
    "BALNEARIO CAMBORIU": ("BALNEARIO CAMBORIU", "SC"),
}

# Texto que não é lugar nenhum — sujeira de raspagem que chegava à consulta.
LIXO = re.compile(r"^\d+\s+followers?$|^brazil$|^brasil$|^remote$|^remoto$"
                  r"|^home\s*office$|^\d+$", re.I)

_mapa: dict[str, Any] | None = None
_por_nome: dict[str, set[str]] = {}
_por_uf: dict[str, list[str]] = {}


def norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    # hífen e ponto viram espaço: "São João del-Rei" e "Biritiba-Mirim" são a
    # mesma coisa que as versões sem hífen, e essa família sozinha respondia
    # por parte das falhas.
    s = re.sub(r"[-.'`]", " ", s)
    return " ".join(s.upper().split())


def _carregar() -> None:
    global _mapa, _por_nome, _por_uf
    if _mapa is not None:
        return
    try:
        _mapa = json.load(open(MAPA_DDD, encoding="utf-8"))
    except Exception:
        _mapa = {}
    for chave in _mapa:
        cidade, _, uf = chave.partition("|")
        c = norm(cidade)
        _por_nome.setdefault(c, set()).add(uf)
        _por_uf.setdefault(uf, []).append(c)


def existe(cidade: str, uf: str = "") -> bool:
    _carregar()
    ufs = _por_nome.get(norm(cidade))
    if not ufs:
        return False
    return (uf.upper() in ufs) if uf else True


def uf_unica(cidade: str) -> str:
    """UF do município quando o nome é único no país; senão "". """
    _carregar()
    ufs = _por_nome.get(norm(cidade)) or set()
    return next(iter(ufs)) if len(ufs) == 1 else ""


def resolver(texto: Any, uf_dica: str = "") -> dict[str, Any]:
    """Texto de localização do LinkedIn -> {cidade, uf, como, confianca}.

    `como` diz COMO casou, e a tela deve poder mostrar isso: um acerto por
    semelhança não vale o mesmo que um acerto exato, e esconder a diferença é
    o que faz alguém ligar para a pessoa errada achando que está certa.
    """
    _carregar()
    bruto = str(texto or "").strip()
    partes = [p.strip() for p in bruto.split(",") if p.strip()]
    # descarta o país no fim
    while partes and norm(partes[-1]) in ("BRAZIL", "BRASIL", "BR"):
        partes.pop()

    def saida(cidade, uf, como, confianca):
        return {"cidade": cidade, "uf": uf.upper()[:2] if uf else "",
                "como": como, "confianca": confianca, "bruto": bruto}

    if not partes or LIXO.match(bruto.strip()):
        return saida("", "", "nao_e_lugar", 0)

    # UF vinda do texto (2ª parte) ou da dica de quem chamou
    uf = ""
    for p in partes[1:]:
        uf = UF_POR_NOME.get(norm(p), "")
        if uf:
            break
    if not uf and len(norm(partes[-1])) == 2:
        uf = norm(partes[-1])
    if not uf:
        uf = (uf_dica or "").upper()[:2]

    c = norm(partes[0])
    if not c:
        return saida("", uf, "so_estado" if uf else "nao_e_lugar", 20 if uf else 0)

    # "Greater X Area" / "X Metropolitan Area" — convenção do LinkedIn.
    # `era_metro` importa: "Greater São Paulo Area" fala da CIDADE e sua região,
    # não do estado. Sem essa marca o texto caía na regra de "só o estado" logo
    # abaixo (sobra uma parte só depois de tirar "Brazil") e a cidade sumia.
    era_metro = bool(c.startswith("GREATER ") or c.endswith(" AREA")
                     or c.endswith(" REGION"))
    if era_metro:
        c = re.sub(r"^GREATER\s+", "", c)
        c = re.sub(r"\s+(METROPOLITAN\s+)?AREA$", "", c)
        c = re.sub(r"\s+REGION$", "", c).strip()

    # 1. o texto todo é só o nome de um estado
    so_estado = UF_POR_NOME.get(c, "")
    if so_estado and not era_metro and (
            len(partes) == 1 or (c in AMBIGUOS_ESTADO and not existe(c, uf))):
        return saida("", so_estado, "so_estado", 20)

    # 2. alias conhecido
    if c in ALIAS:
        cid, u = ALIAS[c]
        return saida(cid, uf or u, "alias", 90)

    # 3. região administrativa do DF
    if c in RA_DF:
        return saida("BRASILIA", "DF", "ra_do_df", 85)

    # 4. município exato (o norm já tirou hífen e acento)
    if existe(c, uf):
        return saida(c, uf or uf_unica(c), "exato", 100)
    if not uf and existe(c):
        u = uf_unica(c)
        return saida(c, u, "exato" if u else "exato_ambiguo", 100 if u else 60)

    # 5. semelhança — SÓ com UF conhecida. Sem UF o risco de acertar o
    #    município errado é grande demais: "Bom Jesus" existe em 9 estados.
    if uf and _por_uf.get(uf):
        perto = difflib.get_close_matches(c, _por_uf[uf], n=1, cutoff=0.88)
        if perto:
            return saida(perto[0], uf, "semelhanca", 70)

    return saida("", uf, "nao_encontrada", 0)


if __name__ == "__main__":
    # Casos que falharam de verdade no cache do CapiBLU.
    CASOS = [
        ("Niterói, Rio de Janeiro, Brazil", "NITEROI", "RJ"),
        ("Greater São Paulo Area", "SAO PAULO", "SP"),
        ("Santa Catarina, Brazil", "", "SC"),
        ("Federal District, Brazil", "", "DF"),
        ("Brazil", "", ""),
        ("45 followers", "", ""),
        ("New Fribourg, Rio de Janeiro, Brazil", "NOVA FRIBURGO", "RJ"),
        ("Ceilândia, Federal District, Brazil", "BRASILIA", "DF"),
        ("Lago Norte, Federal District, Brazil", "BRASILIA", "DF"),
        ("São João del-Rei, Minas Gerais, Brazil", "SAO JOAO DEL REI", "MG"),
        ("Biritiba Mirim, São Paulo, Brazil", "BIRITIBA MIRIM", "SP"),
        ("Balneário Camboriú, Santa Catarina, Brazil", "BALNEARIO CAMBORIU", "SC"),
        ("Sao Jose dos Campos, SP", "SAO JOSE DOS CAMPOS", "SP"),
        ("Floripa", "FLORIANOPOLIS", "SC"),
    ]
    falhas = 0
    for texto, cid_esp, uf_esp in CASOS:
        r = resolver(texto)
        ok = (r["cidade"] == cid_esp and r["uf"] == uf_esp)
        if not ok:
            falhas += 1
        print("%s %-44s -> %-22s %-3s (%s)"
              % ("  " if ok else "XX", texto[:44], r["cidade"][:22], r["uf"],
                 r["como"]))
    print("\n%d falha(s) de %d" % (falhas, len(CASOS)))
