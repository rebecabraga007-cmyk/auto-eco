# -*- coding: utf-8 -*-
"""O chão de toda prova: ambiente isolado e a TRAVA DE GASTO.

POR QUE A TRAVA EXISTE
----------------------
Este sistema gasta dinheiro de verdade a cada chamada -- R$ 0,119 na Assertiva,
US$ 0,0025 na Bright Data. Uma suite de testes que possa gastar vai gastar: um
dia alguem esquece de dublar uma fonte, roda em cima de uma lista de 2.000
linhas e a fatura chega no fim do mes sem ninguem entender de onde veio.

Por isso a trava nao e "lembre-se de dublar". E um bloqueio: qualquer chamada
de rede que saia para fora da maquina LEVANTA. Se um teste precisa de uma
fonte, ele a dubla -- e se esquecer, o teste quebra na hora, com o nome do
endereco que ele tentou alcancar.

Custo de rodar a suite inteira: R$ 0,00, garantido por construcao e nao por
disciplina.
"""
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(RAIZ, "backend")

# Enderecos que podem ser alcancados: so a propria maquina. O TestClient do
# FastAPI usa "testserver" como host ficticio e nao sai pela rede.
LOCAIS = ("127.0.0.1", "localhost", "testserver", "::1")


class GastoProibido(RuntimeError):
    """Um teste tentou chamar fornecedor pago. Dubla a fonte."""


def _bloquear_rede():
    """Nenhuma chamada sai desta maquina enquanto a suite roda."""
    import httpx

    def _permitido(url) -> bool:
        h = (getattr(url, "host", None) or str(url)).lower()
        return any(x in h for x in LOCAIS)

    def _barra(nome):
        def _erro(self, method, url, *a, **kw):
            if not _permitido(url):
                raise GastoProibido(
                    "%s tentou sair para %s.\n"
                    "    Fonte paga não dublada. Troque-a por um dublê no teste."
                    % (nome, str(url)[:120]))
            return _original[nome](self, method, url, *a, **kw)
        return _erro

    _original = {"httpx.AsyncClient": httpx.AsyncClient.request,
                 "httpx.Client": httpx.Client.request}
    httpx.AsyncClient.request = _barra("httpx.AsyncClient")
    httpx.Client.request = _barra("httpx.Client")

    # A Cloudflare e a WorkAPI sao chamadas por urllib em alguns modulos.
    import urllib.request as ur
    _abrir = ur.urlopen

    def _urlopen(req, *a, **kw):
        alvo = getattr(req, "full_url", None) or str(req)
        if not any(x in str(alvo).lower() for x in LOCAIS):
            raise GastoProibido("urllib tentou sair para %s" % str(alvo)[:120])
        return _abrir(req, *a, **kw)
    ur.urlopen = _urlopen


def preparar(nome: str):
    """Ambiente limpo para um teste. Devolve o diretório de dados.

    Cada teste começa com banco vazio: teste que herda estado do anterior
    passa sozinho e falha em conjunto, e aí ninguém sabe qual é o culpado.
    """
    destino = os.path.join(tempfile.gettempdir(), "capiblu_testes", nome)
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino, exist_ok=True)
    os.environ["CAPIBLU_DATA_DIR"] = destino
    os.environ["LINKEDIN_CACHE_PATH"] = os.path.join(destino, "linkedin_cache.db")
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    _bloquear_rede()
    return destino


# ── dublês das fontes pagas ────────────────────────────────────────────
def falso_funil(com_telefone=True, nomes=("CARLOS MOTTA", "ANA BEATRIZ LIMA"),
                so_para=None):
    """Um funil do LinkedIn de mentira. `so_para` limita quais CNPJs rendem.

    Devolve telefone COM os sinais da Assertiva (relação, WhatsApp, meses,
    não perturbe) porque é assim que o de verdade devolve -- e vários testes
    são justamente sobre o que fazemos com esses sinais.
    """
    async def _falso(cnpj="", **kw):
        tem = com_telefone and (so_para is None or cnpj in so_para)
        return {"pessoas": [
            {"nome": nomes[0], "cargo": "DIRETOR", "cpf": "11122233344",
             "email": "carlos@exemplo.com.br",
             "telefones": ([
                 {"ddd": "47", "number": "999991111", "telefone": "47999991111",
                  "whatsapp": True, "relacao": "DIRETO", "meses_sem_contato": 0,
                  "nao_perturbe": False, "hotphone": True},
                 {"ddd": "47", "number": "988882222", "telefone": "47988882222",
                  "whatsapp": False, "relacao": "TERCEIRO",
                  "meses_sem_contato": 14, "nao_perturbe": True},
             ] if tem else [])}]}
    return _falso


def planilha_csv(n=10, base="8290100000"):
    """Uma planilha de teste, no formato que o upload aceita."""
    linhas = "\n".join("%s%04d;EMPRESA %d" % (base, i, i) for i in range(1, n + 1))
    return ("CNPJ;Empresa\n" + linhas + "\n").encode("utf-8")


def esperar_job(cliente, jid, cabecalhos, tentativas=80):
    """Espera o job sair de 'fila'/'processando'. Falha alto se travar."""
    import time
    for _ in range(tentativas):
        st = cliente.get("/api/enrich/job/%s" % jid, headers=cabecalhos).json()
        if st["estado"] not in ("fila", "processando"):
            return st
        time.sleep(0.3)
    raise AssertionError("o job %s não terminou -- travou?" % jid)
