# -*- coding: utf-8 -*-
"""O LAYOUT do enriquecimento: as quantidades viram colunas.

DE ONDE VEIO
------------
Da Datastone, analisada em 17/09/2026. A tela de enriquecimento deles nao
pede "marque os campos que quer": pede QUANTOS. Selecionadores de 0 a 5 para
endereco, telefone, e-mail e socios, e o layout escolhido declara na API o que
entra e o que sai, com exemplo de ida e de volta.

    "parameters": ["Quantidade de fixos", "Quantidade de celulares",
                   "Quantidade de emails", "Quantidade de socios"]

A diferenca nao e cosmetica. Marcar treze caixas ("Decisor 1 Celular",
"Decisor 2 Celular", "Decisor 3 Celular"...) obriga a pessoa a montar na
cabeca a planilha que ela quer; dizer "3 decisores, 2 telefones cada" e a
frase que ela ja tem pronta. E o numero e o mesmo botao do CUSTO: cada
telefone a mais e uma consulta paga a mais, entao o controle que descreve a
planilha e o mesmo que controla a conta.

POR QUE UM ARQUIVO SO
---------------------
As colunas precisam ser as MESMAS em tres lugares: no que a tela mostra como
exemplo antes de rodar, no que o enriquecedor preenche, e no cabecalho do
arquivo exportado. Tres listas separadas divergem no primeiro ajuste -- e o
sintoma seria a coluna prometida no exemplo chegar vazia no arquivo.
"""
import re

# Teto por tipo. Cinco e o mesmo teto da Datastone, e nao e arbitrario: a
# Assertiva devolve os telefones ja ordenados por chance de alguem atender, e
# do quinto em diante a lista vira numero velho -- pagar por eles e comprar
# ruido.
TETO = 5

# O que cada quantidade gera, na ordem em que a planilha le. A ordem importa:
# quem abre o arquivo le da esquerda para a direita e espera nome, cargo,
# documento, e so entao os contatos.
ROTULOS = {
    "nome": "%s %d Nome",
    "cargo": "%s %d Cargo",
    "cpf": "%s %d CPF",
    "tel": "%s %d Telefone %d",
    "email": "%s %d E-mail %d",
    "whatsapp": "%s %d WhatsApp",
    # OS SINAIS DO TELEFONE, que a Assertiva manda e nos jogavamos fora.
    #
    # `nao_perturbe` e o mais importante e nao e conveniencia: e o cadastro de
    # quem pediu para nao ser incomodado. O SDR recebia o numero sem saber, e
    # a responsabilidade era da casa.
    #
    # `sinal` e a frase curta que explica por que AQUELE numero e o primeiro
    # -- "do titular, WhatsApp, contato nos ultimos dias". Sem ela a ordem
    # parece arbitraria e a pessoa liga na que preferir.
    "naoperturbe": "%s %d NÃO PERTURBE",
    "sinal": "%s %d Telefone — sinais",
}

_RE_CHAVE = re.compile(
    r"^(de_dec|so_socio)(\d+)_"
    r"(nome|cargo|cpf|whatsapp|naoperturbe|sinal|tel\d+|email\d+)$")


def chave_valida(chave: str) -> bool:
    """A chave dinamica existe? Usado na validacao da rota.

    As chaves fixas do catalogo continuam sendo validadas contra a lista de
    sempre; estas aqui nascem da quantidade escolhida e por isso nao cabem
    numa lista fixa.
    """
    return bool(_RE_CHAVE.match(chave or ""))


def colunas(quantos_dec: int = 0, tel_por_pessoa: int = 1,
            email_por_pessoa: int = 0, quantos_socios: int = 0,
            com_cpf: bool = True, com_whatsapp: bool = False,
            com_sinais: bool = True) -> list:
    """As colunas do layout, em ordem, como [(chave, rotulo)].

    Decisor vem antes de socio de proposito: decisor e quem MANDA na empresa
    e e o alvo da ligacao; socio e quem e dono, e nem sempre atende.
    """
    saida = []
    for prefixo, rotulo, quantos in (("de_dec", "Decisor", quantos_dec),
                                     ("so_socio", "Sócio", quantos_socios)):
        for n in range(1, min(int(quantos or 0), TETO) + 1):
            saida.append(("%s%d_nome" % (prefixo, n), ROTULOS["nome"] % (rotulo, n)))
            if prefixo == "de_dec":
                saida.append(("%s%d_cargo" % (prefixo, n), ROTULOS["cargo"] % (rotulo, n)))
            if com_cpf:
                saida.append(("%s%d_cpf" % (prefixo, n), ROTULOS["cpf"] % (rotulo, n)))
            for t in range(1, min(int(tel_por_pessoa or 0), TETO) + 1):
                saida.append(("%s%d_tel%d" % (prefixo, n, t),
                              ROTULOS["tel"] % (rotulo, n, t)))
            for e in range(1, min(int(email_por_pessoa or 0), TETO) + 1):
                saida.append(("%s%d_email%d" % (prefixo, n, e),
                              ROTULOS["email"] % (rotulo, n, e)))
            if com_whatsapp:
                saida.append(("%s%d_whatsapp" % (prefixo, n),
                              ROTULOS["whatsapp"] % (rotulo, n)))
            if com_sinais:
                # Depois do telefone, nunca antes: o sinal explica o numero,
                # e explicacao que vem antes do dado faz reler.
                saida.append(("%s%d_naoperturbe" % (prefixo, n),
                              ROTULOS["naoperturbe"] % (rotulo, n)))
                saida.append(("%s%d_sinal" % (prefixo, n),
                              ROTULOS["sinal"] % (rotulo, n)))
    return saida


def exemplo(quantos_dec: int = 0, tel_por_pessoa: int = 1,
            email_por_pessoa: int = 0, quantos_socios: int = 0,
            com_cpf: bool = True, com_whatsapp: bool = False,
            com_sinais: bool = True) -> dict:
    """Uma linha de MENTIRA, para a tela mostrar antes de gastar.

    A Datastone faz isso ("Exemplo de envio" / "Exemplo de retorno") e e o
    unico jeito honesto de responder "o que eu vou receber?" antes de cobrar.
    Os valores sao obviamente ficticios -- nome de exemplo, telefone com
    99999 -- para ninguem confundir preview com resultado.
    """
    cols = colunas(quantos_dec, tel_por_pessoa, email_por_pessoa,
                   quantos_socios, com_cpf, com_whatsapp, com_sinais)
    fake = {
        "nome": ["CARLOS MOTTA DOS SANTOS", "ANA BEATRIZ LIMA",
                 "PEDRO HENRIQUE COSTA", "MARIA APARECIDA REIS", "JOÃO VITOR SÁ"],
        "cargo": ["DIRETOR", "GERENTE", "COORDENADOR", "DIRETOR", "GERENTE"],
        "cpf": ["93387628749", "11122233344", "55566677788", "99988877766",
                "12312312312"],
    }
    linha = {}
    for chave, _ in cols:
        m = _RE_CHAVE.match(chave)
        n = int(m.group(2)) - 1
        campo = m.group(3)
        if campo in fake:
            linha[chave] = fake[campo][n % len(fake[campo])]
        elif campo.startswith("tel"):
            # O numero da ORDEM entra no valor de proposito: com dois
            # telefones iguais lado a lado, o exemplo parece um bug e nao da
            # para conferir se "Telefone 2" e mesmo outro telefone.
            # Onze digitos, com DDD e o 9 na frente: um exemplo com nove
            # digitos nao parece celular, e quem confere o exemplo iria achar
            # que o retorno vem truncado.
            i = int(campo[3:] or 1)
            linha[chave] = "479%d%d%06d" % (9 - n, i, 100000 + n * 10 + i)
        elif campo.startswith("email"):
            i = int(campo[5:] or 1)
            linha[chave] = "contato%d.p%d@empresa.com.br" % (i, n + 1)
        elif campo == "naoperturbe":
            linha[chave] = "" if n else "SIM"     # so um, para mostrar a cara
        elif campo == "sinal":
            linha[chave] = ["do titular · WhatsApp · contato nos últimos dias",
                            "do titular · sem contato há 8 meses",
                            "de terceiro · WhatsApp"][n % 3]
        else:
            linha[chave] = "sim"
    return {"colunas": [{"key": k, "label": r} for k, r in cols], "linha": linha}


def consultas_por_linha(quantos_dec: int = 0, tel_por_pessoa: int = 1,
                        email_por_pessoa: int = 0,
                        quantos_socios: int = 0) -> int:
    """Quantas consultas PAGAS uma linha custa, no pior caso.

    Existe para a tela poder dizer o tamanho da conta ANTES, que e o unico
    momento em que o numero muda alguma decisao. E o pior caso de proposito:
    prometer barato e cobrar caro e o erro que nao se conserta depois.

    A conta: uma consulta por empresa (a lista de decisores/socios) mais uma
    por pessoa que tiver contato buscado. Telefone e e-mail da mesma pessoa
    saem da MESMA consulta -- por isso pedir e-mail junto nao dobra o preco.
    """
    pessoas = min(int(quantos_dec or 0), TETO) + min(int(quantos_socios or 0), TETO)
    quer_contato = (int(tel_por_pessoa or 0) > 0) or (int(email_por_pessoa or 0) > 0)
    return (1 if pessoas else 0) + (pessoas if quer_contato else 0)
