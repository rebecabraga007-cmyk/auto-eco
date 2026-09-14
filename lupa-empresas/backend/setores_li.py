# -*- coding: utf-8 -*-
"""Traduz o setor que a pessoa digita para o vocabulario do LinkedIn.

POR QUE EXISTE
--------------
O campo "Setor" da tela e livre, com o exemplo "Software", e quem usa escreve
em portugues. O dataset de empresas do LinkedIn guarda `industries` em ingles,
com uma lista fechada de rotulos ("Civil Engineering", "Food & Beverages").
Medido em 14/set/2026, em SC:

    industries includes "engenharia"   ->      0 empresas
    industries includes "Engineering"  ->  1.197 empresas

Ou seja: o campo mais obvio da tela devolvia zero por uma diferenca de idioma,
e a busca entao caia no banco -- que, sem receber o filtro, respondia com
camara municipal, clube nautico e comunidade evangelica. Uma lista bonita de
empresas erradas e pior que uma lista vazia, porque quem liga confia nela.

O QUE ESTE ARQUIVO NAO E
------------------------
Nao e tradutor de portugues. E um dicionario de SETOR -> rotulos do LinkedIn,
escrito a mao, porque a lista deles e fechada e cada entrada precisa casar
exatamente com o que esta la. Termo desconhecido passa direto: quem digita
"Software" ou "Retail" ja esta falando a lingua do dataset.

O TETO DE QUATRO
----------------
A Bright Data recusa um grupo `or` com mais de 4 termos. Por isso cada setor
lista os rotulos mais frequentes no Brasil primeiro -- perder o quinto rotulo
e melhor que perder a consulta inteira.
"""
import re
import unicodedata

TETO = 4


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


# Chave normalizada (sem acento, minuscula) -> rotulos do LinkedIn, do mais
# comum para o menos comum. A ordem importa por causa do teto de quatro.
MAPA: dict[str, list[str]] = {
    "engenharia": ["Civil Engineering", "Mechanical Or Industrial Engineering",
                   "Industrial Automation", "Architecture & Planning"],
    "construcao": ["Construction", "Civil Engineering", "Building Materials",
                   "Architecture & Planning"],
    "construcao civil": ["Construction", "Civil Engineering", "Building Materials"],
    "arquitetura": ["Architecture & Planning", "Design", "Construction"],
    # "alimentos" NAO leva Farming: medido, a primeira pagina vinha cheia de
    # assessoria agricola e agropecuaria -- que e agro, nao alimento. Quem
    # quer os dois escreve "alimentos, agro", e ai o intercalado cuida.
    "alimentos": ["Food & Beverages", "Food Production", "Restaurants",
                  "Supermarkets"],
    "alimenticio": ["Food & Beverages", "Food Production", "Restaurants"],
    "bebidas": ["Food & Beverages", "Wine & Spirits", "Food Production"],
    "restaurante": ["Restaurants", "Food & Beverages", "Hospitality"],
    "agro": ["Farming", "Agriculture", "Food Production", "Dairy"],
    "agronegocio": ["Farming", "Agriculture", "Food Production", "Dairy"],
    "agricultura": ["Farming", "Agriculture", "Food Production"],
    "pecuaria": ["Ranching", "Farming", "Dairy"],
    "tecnologia": ["Information Technology & Services", "Computer Software",
                   "Internet", "Computer & Network Security"],
    "ti": ["Information Technology & Services", "Computer Software", "Internet"],
    "software": ["Computer Software", "Information Technology & Services",
                 "Internet"],
    "informatica": ["Information Technology & Services", "Computer Software",
                    "Computer Hardware"],
    "saude": ["Hospital & Health Care", "Medical Practice", "Medical Devices",
              "Pharmaceuticals"],
    "hospital": ["Hospital & Health Care", "Medical Practice"],
    "farmaceutico": ["Pharmaceuticals", "Biotechnology", "Hospital & Health Care"],
    "odontologia": ["Medical Practice", "Hospital & Health Care"],
    "educacao": ["Education Management", "Higher Education",
                 "E-Learning", "Professional Training & Coaching"],
    "ensino": ["Education Management", "Higher Education", "E-Learning"],
    "juridico": ["Law Practice", "Legal Services"],
    "advocacia": ["Law Practice", "Legal Services"],
    "contabilidade": ["Accounting", "Financial Services"],
    "financeiro": ["Financial Services", "Banking", "Investment Management",
                   "Capital Markets"],
    "banco": ["Banking", "Financial Services"],
    "seguros": ["Insurance", "Financial Services"],
    "imobiliario": ["Real Estate", "Commercial Real Estate", "Construction"],
    "imoveis": ["Real Estate", "Commercial Real Estate"],
    "industria": ["Machinery", "Industrial Automation",
                  "Mechanical Or Industrial Engineering",
                  "Electrical & Electronic Manufacturing"],
    "metalurgia": ["Mining & Metals", "Machinery",
                   "Mechanical Or Industrial Engineering"],
    "textil": ["Textiles", "Apparel & Fashion", "Consumer Goods"],
    "moda": ["Apparel & Fashion", "Textiles", "Retail"],
    "vestuario": ["Apparel & Fashion", "Textiles", "Retail"],
    "quimica": ["Chemicals", "Plastics", "Pharmaceuticals"],
    "plastico": ["Plastics", "Chemicals", "Packaging & Containers"],
    "embalagem": ["Packaging & Containers", "Plastics", "Paper & Forest Products"],
    "madeira": ["Paper & Forest Products", "Furniture", "Building Materials"],
    "moveis": ["Furniture", "Building Materials", "Design"],
    "logistica": ["Logistics & Supply Chain", "Transportation/Trucking/Railroad",
                  "Package/Freight Delivery", "Warehousing"],
    "transporte": ["Transportation/Trucking/Railroad", "Logistics & Supply Chain",
                   "Package/Freight Delivery"],
    "varejo": ["Retail", "Consumer Goods", "Supermarkets", "Apparel & Fashion"],
    "comercio": ["Retail", "Wholesale", "Consumer Goods"],
    "atacado": ["Wholesale", "Retail", "Consumer Goods"],
    "supermercado": ["Supermarkets", "Retail", "Food & Beverages"],
    "marketing": ["Marketing & Advertising", "Public Relations & Communications",
                  "Media Production"],
    "publicidade": ["Marketing & Advertising", "Public Relations & Communications"],
    "consultoria": ["Management Consulting", "Business Supplies & Equipment",
                    "Professional Training & Coaching"],
    "rh": ["Human Resources", "Staffing & Recruiting",
           "Professional Training & Coaching"],
    "recursos humanos": ["Human Resources", "Staffing & Recruiting"],
    "energia": ["Renewables & Environment", "Oil & Energy", "Utilities",
                "Electrical & Electronic Manufacturing"],
    "energia solar": ["Renewables & Environment", "Oil & Energy", "Utilities"],
    "petroleo": ["Oil & Energy", "Mining & Metals", "Utilities"],
    "mineracao": ["Mining & Metals", "Oil & Energy"],
    "telecomunicacoes": ["Telecommunications", "Wireless",
                         "Information Technology & Services"],
    "turismo": ["Leisure, Travel & Tourism", "Hospitality", "Airlines/Aviation"],
    "hotelaria": ["Hospitality", "Leisure, Travel & Tourism", "Restaurants"],
    "eventos": ["Events Services", "Marketing & Advertising", "Hospitality"],
    "seguranca": ["Security & Investigations", "Computer & Network Security"],
    "limpeza": ["Facilities Services", "Environmental Services"],
    "automotivo": ["Automotive", "Machinery", "Transportation/Trucking/Railroad"],
    "veiculos": ["Automotive", "Machinery"],
    "cosmeticos": ["Cosmetics", "Consumer Goods", "Health, Wellness & Fitness"],
    "estetica": ["Cosmetics", "Health, Wellness & Fitness", "Medical Practice"],
    "academia": ["Health, Wellness & Fitness", "Sports"],
    "esporte": ["Sports", "Health, Wellness & Fitness"],
    "grafica": ["Printing", "Publishing", "Marketing & Advertising"],
    "papel": ["Paper & Forest Products", "Packaging & Containers", "Printing"],
    "governo": ["Government Administration", "Public Policy",
                "Government Relations"],
    "ong": ["Nonprofit Organization Management", "Civic & Social Organization",
            "Philanthropy"],
}


def _termos(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        bruto = list(valor)
    else:
        bruto = re.split(r"[;,]", str(valor))
    return [t.strip() for t in bruto if str(t).strip()]


def traduzir(valor) -> str:
    """Setor em portugues -> rotulos do LinkedIn, separados por virgula.

    Termo que nao esta no dicionario passa intacto: pode ser um rotulo em
    ingles que a pessoa copiou do proprio LinkedIn, e nesse caso traduzir
    seria estragar.
    """
    listas: list[list[str]] = []
    for t in _termos(valor):
        chave = _norm(t)
        achou = MAPA.get(chave)
        if not achou:
            # "engenharia civil" casa por "engenharia"; "industria alimenticia"
            # casa por "alimenticio". Pega a chave mais longa que aparece
            # dentro do que foi digitado -- a mais longa e a mais especifica.
            candidatas = [k for k in MAPA if k in chave or chave in k]
            if candidatas:
                achou = MAPA[max(candidatas, key=len)]
        listas.append(achou or [t])

    # INTERCALADO, e nao um setor atras do outro. Quem escolhe "saude" e
    # "tecnologia" quer os dois; concatenar gastaria as quatro vagas do teto
    # com o primeiro setor e o segundo sumiria da busca sem aviso.
    saida: list[str] = []
    for i in range(max((len(x) for x in listas), default=0)):
        for lista in listas:
            if i < len(lista):
                saida.append(lista[i])
    # dict.fromkeys mantem a ordem; o teto e da Bright Data, nao nosso
    return ", ".join(list(dict.fromkeys(saida))[:TETO])


def conhecido(valor) -> bool:
    """Se o dicionario reconheceu o termo -- a tela usa para explicar."""
    for t in _termos(valor):
        chave = _norm(t)
        if chave in MAPA or any(k in chave or chave in k for k in MAPA):
            return True
    return False
