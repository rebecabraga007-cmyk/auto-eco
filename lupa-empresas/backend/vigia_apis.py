# -*- coding: utf-8 -*-
"""Vigia de APIs: testa cada fornecedor a cada X horas e liga/desliga a troca sozinho.

POR QUE EXISTE
--------------
Em setembro/2026 três fornecedores caíram sem ninguém perceber: a WorkAPI
(523, origem deles fora), a conta da Bright Data (suspensa entre 17 e 25/set)
e o token da FDX/RAIS (vencido). Nos três casos as telas mostravam "bloqueado"
ou HTML da Cloudflare, e o log do serviço registrava 200 OK -- a queda só
aparecia quando alguém reclamava. Ver lupa-empresas/APIS_FORA_DO_AR.md.

O QUE ELE FAZ, A CADA VERIFICAÇÃO
---------------------------------
1. Testa cada API com uma chamada que NÃO GASTA crédito (a mesma tabela de
   sondas do APIS_FORA_DO_AR.md). Falhou? Repete antes de acreditar: um soluço
   de rede não pode ligar consulta paga.
2. API caiu E tem substituta no ar -> liga a contingência (contingencias.py)
   e abre um chamado dizendo o que foi trocado.
3. API voltou -> desliga a contingência QUE ELE MESMO LIGOU e fecha o chamado.
   Troca ligada à mão pelo admin fica ligada: é decisão humana, e o chamado
   avisa que a API voltou para o admin decidir.
4. API sem substituta (FDX/RAIS, BrasilAPI...) -> só abre/fecha o chamado.

| API                         | Substituta automática            |
|-----------------------------|----------------------------------|
| WorkAPI                     | Assertiva (workapi_suspensa.py)  |
| Bright Data - leitura viva  | Bright Data Search (base)        |
| FDX / RAIS                  | nenhuma -- só a FDX tem a RAIS   |
|                             | completa com CPF; renovar token  |
| demais                      | só alerta                        |

QUANDO RODA
-----------
O timer do systemd (`capiblu-vigia-apis.timer`) acorda a cada 10 min, e o
script só trabalha se já passou o intervalo que o admin escolheu no painel
(`vigia_apis.intervalo_h` no capiblu_config.json, padrão 1 h). Assim mudar o
intervalo não exige mexer no systemd. O botão "Verificar agora" do painel
roda a mesma função, dentro do serviço de dados.

Roda fora do app, como o `saude.py`, pelo mesmo motivo: o vigia não pode
depender do processo que ele vigia estar saudável.
"""
import asyncio
import json
import os
import sys
import time
from typing import Any

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
if __name__ == "__main__":
    # As chaves precisam estar no ambiente ANTES de importar os clientes, que
    # leem o .env no import (mesmo arranjo do main.py).
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(_AQUI), ".env"))
    except Exception:
        pass

import httpx

import chamados
import config_store
import contingencias

CFG = "vigia_apis"
PADRAO = {"ligado": True, "intervalo_h": 1.0}
TENTATIVAS = 3
_UA = {"User-Agent": "Mozilla/5.0 (CapiBLU vigia)"}


def _estado_path() -> str:
    return os.path.join(os.path.dirname(config_store._path()), "vigia_apis_estado.json")


def config() -> dict[str, Any]:
    c = config_store.get(CFG) or {}
    out = dict(PADRAO)
    out.update({k: v for k, v in c.items() if k in PADRAO})
    try:
        out["intervalo_h"] = max(0.25, min(float(out["intervalo_h"]), 72.0))
    except (TypeError, ValueError):
        out["intervalo_h"] = PADRAO["intervalo_h"]
    out["ligado"] = bool(out["ligado"])
    return out


def salvar_config(ligado: bool | None = None, intervalo_h: float | None = None) -> dict[str, Any]:
    c = config()
    if ligado is not None:
        c["ligado"] = bool(ligado)
    if intervalo_h is not None:
        c["intervalo_h"] = float(intervalo_h)
    config_store.set_many({CFG: c})
    return config()


def ler_estado() -> dict[str, Any]:
    try:
        with open(_estado_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ultima": 0, "resultados": {}, "eventos": []}


def _gravar_estado(e: dict[str, Any]) -> None:
    alvo = _estado_path()
    tmp = alvo + ".parcial"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(tmp, alvo)


# --------------------------------------------------------------------------
# Sondas: nenhuma gasta crédito. Cada uma devolve (no_ar, codigo, motivo).
# --------------------------------------------------------------------------

async def _workapi(cli):
    r = await cli.get("https://api.workapi.dev/v1/gateway")
    if r.status_code >= 500:
        return False, r.status_code, "origem da WorkAPI não responde (Cloudflare %d)" % r.status_code
    return True, r.status_code, "gateway respondendo"


async def _brightdata(cli):
    chave = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
    if not chave:
        return None, None, "sem BRIGHTDATA_API_KEY"
    # Corpo vazio: produto ativo responde erro de VALIDAÇÃO ("No data to
    # trigger"); conta suspensa responde "Customer is not active". Sem custo.
    r = await cli.post("https://api.brightdata.com/datasets/v3/scrape",
                       params={"dataset_id": "gd_l1viktl72bvl7bjuj0", "format": "json"},
                       headers={"Authorization": "Bearer " + chave}, json=[])
    txt = r.text[:200]
    if "not active" in txt.lower() or "suspend" in txt.lower():
        return False, r.status_code, "conta sem acesso ao Web Scraper: %s" % txt[:80]
    if r.status_code in (401, 403) or r.status_code >= 500:
        return False, r.status_code, txt[:80] or "HTTP %d" % r.status_code
    return True, r.status_code, "Web Scraper ativo"


async def _brightdata_search(cli):
    chave = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
    if not chave:
        return None, None, "sem BRIGHTDATA_API_KEY"
    # Busca que não acha nada: não entrega registro, não cobra.
    r = await cli.post("https://api.brightdata.com/datasets/search/gd_l1vikfnt1wgvvqz95w",
                       headers={"Authorization": "Bearer " + chave},
                       json={"size": 1, "filter": {"operator": "and", "filters": [
                           {"name": "country_code", "operator": "=", "value": "BR"},
                           {"name": "website_simplified", "operator": "=",
                            "value": "vigia-capiblu-inexistente.com.br"}]}})
    if r.status_code == 200:
        return True, 200, "busca nas bases respondendo"
    return False, r.status_code, r.text[:80]


async def _assertiva(cli):
    import assertiva
    if not assertiva.enabled():
        return None, None, "Assertiva não configurada"
    r = await cli.post(assertiva.BASE_URL + assertiva.TOKEN_PATH,
                       headers={"Authorization": "Basic " + assertiva._basic_header(),
                                "Content-Type": "application/x-www-form-urlencoded"},
                       data={"grant_type": "client_credentials"})
    if r.status_code == 200 and "access_token" in r.text:
        return True, 200, "autenticação ok"
    return False, r.status_code, r.text[:80] or "HTTP %d" % r.status_code


async def _fdx(cli):
    tok = os.environ.get("FDX_TOKEN", "").strip()
    if not tok:
        return None, None, "sem FDX_TOKEN"
    r = await cli.get(os.environ.get("FDX_BASE_URL", "https://api.fdxapis.us/api.php"),
                      params={"token": tok, "raispj": "00000000000000"})
    if r.status_code in (401, 403):
        try:
            motivo = str((r.json() or {}).get("response") or "")
        except Exception:
            motivo = ""
        return False, r.status_code, "acesso recusado" + (" (%s)" % motivo if motivo else "")
    if r.status_code >= 500:
        return False, r.status_code, "HTTP %d" % r.status_code
    return True, r.status_code, "token aceito"


async def _brasilapi(cli):
    r = await cli.get("https://brasilapi.com.br/api/cnpj/v1/00000000000191", headers=_UA)
    return (r.status_code == 200), r.status_code, "ok" if r.status_code == 200 else r.text[:80]


async def _meetime(cli):
    tok = os.environ.get("MEETIME_TOKEN", "").strip()
    if not tok:
        return None, None, "sem MEETIME_TOKEN"
    r = await cli.get("https://api.meetime.com.br/v2/leads", params={"limit": 1, "start": 0},
                      headers={"Authorization": tok})
    return (r.status_code == 200), r.status_code, "ok" if r.status_code == 200 else r.text[:80]


async def _mistral(cli):
    k = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not k:
        return None, None, "sem MISTRAL_API_KEY"
    r = await cli.get("https://api.mistral.ai/v1/models", headers={"Authorization": "Bearer " + k})
    return (r.status_code == 200), r.status_code, "ok" if r.status_code == 200 else r.text[:80]


# substituta: (contingência, API da qual a substituta depende, rótulo)
APIS: list[dict[str, Any]] = [
    {"id": "workapi", "nome": "WorkAPI (CPF, telefone reverso, nome)", "sonda": _workapi,
     "substituta": ("workapi", "assertiva", "Assertiva")},
    {"id": "brightdata", "nome": "Bright Data — leitura ao vivo do LinkedIn", "sonda": _brightdata,
     "substituta": ("brightdata", "brightdata_search", "Bright Data — busca nas bases")},
    {"id": "brightdata_search", "nome": "Bright Data — busca nas bases", "sonda": _brightdata_search},
    {"id": "assertiva", "nome": "Assertiva Localize", "sonda": _assertiva},
    {"id": "fdx", "nome": "FDX / RAIS (vínculos)", "sonda": _fdx,
     "sem_substituta": "Nenhuma API integrada entrega a lista RAIS completa com CPF — "
                       "é preciso renovar o token com a FDX."},
    {"id": "brasilapi", "nome": "BrasilAPI (CNPJ)", "sonda": _brasilapi},
    {"id": "meetime", "nome": "Meetime", "sonda": _meetime},
    {"id": "mistral", "nome": "Mistral (dossiê)", "sonda": _mistral},
]
_POR_ID = {a["id"]: a for a in APIS}


async def _sondar(api: dict[str, Any], espera: float) -> dict[str, Any]:
    """Até TENTATIVAS vezes antes de declarar queda."""
    ultimo = {}
    for n in range(TENTATIVAS):
        t = time.time()
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                no_ar, cod, motivo = await api["sonda"](cli)
        except Exception as exc:
            no_ar, cod, motivo = False, None, "sem resposta (%s)" % type(exc).__name__
        ultimo = {"no_ar": no_ar, "codigo": cod, "motivo": motivo,
                  "ms": int((time.time() - t) * 1000), "tentativas": n + 1}
        if no_ar is not False:          # True = ok; None = não configurada (não insiste)
            break
        if n + 1 < TENTATIVAS:
            await asyncio.sleep(espera)
    return ultimo


def _evento(estado: dict, texto: str) -> None:
    estado.setdefault("eventos", []).insert(0, {"quando": int(time.time()), "texto": texto})
    del estado["eventos"][60:]


async def verificar(forcar: bool = False, espera: float = 20.0, quem: str = "timer") -> dict[str, Any]:
    cfg = config()
    estado = ler_estado()
    agora = time.time()
    if not forcar:
        if not cfg["ligado"]:
            return {"status": "pulado", "motivo": "vigia desligado no painel"}
        falta = estado.get("ultima", 0) + cfg["intervalo_h"] * 3600 - 120 - agora
        if falta > 0:
            return {"status": "pulado", "motivo": "próxima verificação em %d min" % (falta // 60)}

    res_lista = await asyncio.gather(*[_sondar(a, espera) for a in APIS])
    res = {a["id"]: r for a, r in zip(APIS, res_lista)}
    acoes = []

    for a in APIS:
        r = res[a["id"]]
        chave = "api:%s" % a["id"]
        if r["no_ar"] is None:                       # não configurada: nada a vigiar
            chamados.resolver_alerta(chave)
            continue
        sub = a.get("substituta")
        if sub:
            cid, dep, rotulo = sub
            c = contingencias.estado(cid)
            sub_ok = bool(res.get(dep, {}).get("no_ar"))
            if not r["no_ar"]:
                if sub_ok and cfg["ligado"]:
                    if not c.get("ativo"):
                        if cid == "workapi":
                            import workapi_suspensa
                            workapi_suspensa.definir(True, "vigia automático", auto=True,
                                                     motivo=r["motivo"])
                        else:
                            contingencias.definir(cid, True, "vigia automático", auto=True,
                                                  motivo=r["motivo"])
                        acoes.append("%s caiu → troca por %s LIGADA" % (a["nome"], rotulo))
                        _evento(estado, "%s fora do ar (%s) — troca por %s ligada automaticamente"
                                % (a["nome"], r["motivo"], rotulo))
                    chamados.alertar(
                        chave, "%s fora do ar — trocada por %s" % (a["nome"], rotulo),
                        "O vigia de APIs testou %s e ela não respondeu (%s). Enquanto isso, "
                        "as mesmas funções estão sendo atendidas por %s. A troca é desligada "
                        "sozinha na primeira verificação em que %s voltar.\n\n"
                        "Painel administrativo → Vigia de APIs."
                        % (a["nome"], r["motivo"], rotulo, a["nome"]),
                        "fora (%s)" % (r["codigo"] or "sem resposta"))
                else:
                    chamados.alertar(
                        chave, "%s fora do ar — SEM substituta" % a["nome"],
                        "O vigia de APIs testou %s e ela não respondeu (%s). A substituta "
                        "(%s) %s, então nada foi trocado e as telas que dependem dela estão "
                        "sem resposta." % (a["nome"], r["motivo"], rotulo,
                                           "também está fora" if not sub_ok
                                           else "não foi ligada porque o vigia está desligado"),
                        "fora (%s)" % (r["codigo"] or "sem resposta"))
            else:
                chamados.resolver_alerta(chave)
                if c.get("ativo") and c.get("auto"):
                    if cid == "workapi":
                        import workapi_suspensa
                        workapi_suspensa.definir(False, "vigia automático", auto=True, motivo="voltou")
                    else:
                        contingencias.definir(cid, False, "vigia automático", auto=True, motivo="voltou")
                    acoes.append("%s voltou → troca DESLIGADA" % a["nome"])
                    _evento(estado, "%s voltou — troca por %s desligada automaticamente"
                            % (a["nome"], rotulo))
                    chamados.resolver_alerta(chave + ":manual")
                elif c.get("ativo"):
                    chamados.alertar(
                        chave + ":manual", "%s voltou, mas a troca manual segue ligada" % a["nome"],
                        "%s está respondendo de novo, e a troca por %s foi ligada à mão por %s — "
                        "o vigia não desfaz decisão de admin. Desligue no painel se não houver "
                        "outro motivo para mantê-la (a substituta é paga ou mais lenta)."
                        % (a["nome"], rotulo, c.get("por") or "um admin"), "no ar, troca manual")
                else:
                    chamados.resolver_alerta(chave + ":manual")
        else:
            if not r["no_ar"]:
                chamados.alertar(chave, "%s fora do ar" % a["nome"],
                                 "O vigia de APIs testou %s e ela não respondeu (%s). %s"
                                 % (a["nome"], r["motivo"], a.get("sem_substituta")
                                    or "Não há substituta automática para esta API."),
                                 "fora (%s)" % (r["codigo"] or "sem resposta"))
            else:
                chamados.resolver_alerta(chave)

    anterior = estado.get("resultados") or {}
    for aid, r in res.items():
        antes = anterior.get(aid) or {}
        if r["no_ar"] is False:
            r["fora_desde"] = antes.get("fora_desde") if antes.get("no_ar") is False else int(agora)
    estado["ultima"] = int(agora)
    estado["quem"] = quem
    estado["resultados"] = res
    envio = await _avisar_admins(estado, res, acoes)
    _gravar_estado(estado)
    return {"status": "ok", "quando": int(agora), "resultados": res, "acoes": acoes,
            "email": envio}


# --------------------------------------------------------------------------
# E-mail para os administradores
# --------------------------------------------------------------------------
# UM e-mail por queda e UM por volta -- nunca um a cada verificação. O estado
# guarda quais APIs já foram avisadas como fora (`avisadas`): enquanto a queda
# durar, silêncio; quando voltar, avisa e tira da lista. Assim uma queda de
# três dias com o vigia de hora em hora gera dois e-mails, não setenta e dois.

def _hora(ts) -> str:
    """Horário de Brasília: o servidor roda em UTC e o e-mail é lido aqui."""
    if not ts:
        return "?"
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(ts, ZoneInfo("America/Sao_Paulo")).strftime("%d/%m %H:%M")


def _admins() -> list[str]:
    try:
        import auth
        return [u["email"] for u in auth.list_users()
                if u.get("role") == "admin" and u.get("ativo") and u.get("email")]
    except Exception:
        return []


async def _avisar_admins(estado: dict, res: dict, acoes: list[str]) -> dict[str, Any]:
    avisadas = set(estado.get("avisadas") or [])
    caiu, voltou = [], []
    for a in APIS:
        r = res.get(a["id"]) or {}
        if r.get("no_ar") is False and a["id"] not in avisadas:
            caiu.append(a)
        elif r.get("no_ar") is True and a["id"] in avisadas:
            voltou.append(a)
    if not caiu and not voltou:
        return {"enviado": False, "motivo": "nada mudou"}

    linhas = []
    for a in caiu:
        r = res[a["id"]]
        sub = a.get("substituta")
        if sub and contingencias.ativo(sub[0]):
            situacao = "TROCADA automaticamente por %s — as telas seguem funcionando" % sub[2]
            if sub[0] == "workapi":
                situacao += " (atenção: cada consulta da Assertiva é cobrada)"
        elif sub:
            situacao = "SEM troca: a substituta (%s) %s" % (
                sub[2], "também está fora" if (res.get(sub[1]) or {}).get("no_ar") is False
                else "não foi ligada (vigia com troca automática desligada)")
        else:
            situacao = a.get("sem_substituta") or "sem substituta automática"
        linhas.append("🔴 FORA DO AR: %s\n   Resposta: %s %s\n   Desde: %s\n   %s"
                      % (a["nome"], r.get("codigo") or "", r.get("motivo") or "",
                         _hora(r.get("fora_desde")), situacao))
    for a in voltou:
        sub = a.get("substituta")
        linhas.append("🟢 VOLTOU: %s%s" % (
            a["nome"], (" — a troca por %s foi desligada" % sub[2]
                        if sub and not contingencias.ativo(sub[0]) else
                        " — a troca manual continua ligada; desligue no painel" if sub else "")))

    if len(caiu) == 1 and not voltou:
        assunto = "[CapiBLU] %s fora do ar" % caiu[0]["nome"].split(" (")[0]
    elif len(voltou) == 1 and not caiu:
        assunto = "[CapiBLU] %s voltou" % voltou[0]["nome"].split(" (")[0]
    else:
        assunto = "[CapiBLU] %d API(s) fora do ar, %d de volta" % (len(caiu), len(voltou))
    corpo = ("O vigia de APIs do CapiBLU verificou os fornecedores em %s.\n\n%s\n\n"
             "Detalhes, histórico e botões para ligar/desligar as trocas:\n"
             "https://app.capiblu.net → Painel administrativo → Vigia de APIs\n\n"
             "— Este e-mail sai uma vez quando uma API cai e uma vez quando ela volta."
             % (_hora(time.time()), "\n\n".join(linhas)))

    import correio
    destinos = _admins()
    if not correio.configurado() or not destinos:
        motivo = correio.por_que_nao() if not correio.configurado() else "nenhum admin ativo"
        _evento(estado, "E-mail de aviso NÃO enviado: %s" % motivo)
        return {"enviado": False, "motivo": motivo}
    ok, falhas = [], []
    for para in destinos:
        r = await asyncio.to_thread(correio.enviar, para, assunto, corpo)
        (ok if r.get("status") == "ok" else falhas).append(para)
    if ok:
        # Só marca como avisado se ALGUÉM recebeu; senão tenta de novo na próxima.
        avisadas |= {a["id"] for a in caiu}
        avisadas -= {a["id"] for a in voltou}
        estado["avisadas"] = sorted(avisadas)
    _evento(estado, "E-mail \"%s\" enviado a %d admin(s)%s" % (
        assunto, len(ok), (" — falhou para %d" % len(falhas)) if falhas else ""))
    return {"enviado": bool(ok), "para": ok, "falhas": falhas, "assunto": assunto}


# --------------------------------------------------------------------------
# Aviso de "Manutenção!" nas telas
# --------------------------------------------------------------------------
# Rota -> (API da qual ela depende, nome da função como a tela chama). Uma rota
# pode depender de mais de uma API. Quando a API está fora no ÚLTIMO resultado
# do vigia e não há troca funcionando, a resposta da rota sai com o cabeçalho
# `X-Manutencao` e a tela põe o aviso em cima do resultado (authx.js).
import re as _re

ROTAS_MANUTENCAO: list[tuple[Any, str, str]] = [
    (_re.compile(r"^/api/person/[^/]+/mk$"), "workapi", "Ficha do CPF (telefones, endereços, empregos)"),
    (_re.compile(r"^/api/phone/[^/]+/(reverse|pertence)"), "workapi", "Telefone reverso e validação de telefone"),
    (_re.compile(r"^/api/telefone/planilha"), "workapi", "Validação de telefones da planilha"),
    (_re.compile(r"^/api/person/name-search"), "workapi", "Busca por nome (complemento online)"),
    (_re.compile(r"^/api/company/[^/]+/(employees|leads)$"), "workapi", "Telefones e CPF dos funcionários"),
    (_re.compile(r"^/api/company/[^/]+/vinculos"), "fdx", "Vínculos empregatícios (RAIS)"),
    (_re.compile(r"^/api/person/[^/]+/vinculos"), "fdx", "Vínculos empregatícios (RAIS)"),
    (_re.compile(r"^/api/linkedin/empresa$|^/api/company/[^/]+/employees$"), "brightdata",
     "Leitura ao vivo do LinkedIn"),
    (_re.compile(r"^/api/linkedin/funcionarios|^/api/prospeccao/(pessoas|b2b-linkedin)"
                 r"|^/api/empresas/unificada|^/api/funil/decisores-linkedin"), "brightdata_search",
     "Busca de pessoas e empresas no LinkedIn"),
    (_re.compile(r"^/api/assertiva/|^/api/company/[^/]+/(decisores|conexoes)|^/api/person/[^/]+/parentes"),
     "assertiva", "Consultas da Assertiva"),
    (_re.compile(r"^/api/meetime/"), "meetime", "Integração com a Meetime"),
    (_re.compile(r"^/api/dossie/"), "mistral", "Pesquisa na web do dossiê"),
]
_fora_cache: tuple[float, dict[str, dict]] = (0.0, {})


def _sem_substituta() -> dict[str, dict]:
    """APIs fora do ar SEM troca funcionando, segundo a última verificação.

    Com troca ligada, quem responde é a substituta: a função só está em
    manutenção se a SUBSTITUTA também estiver fora. Cache de 30 s porque isto
    roda em toda requisição.
    """
    global _fora_cache
    if time.time() - _fora_cache[0] < 30:
        return _fora_cache[1]
    res = (ler_estado().get("resultados") or {})
    fora: dict[str, dict] = {}
    for a in APIS:
        r = res.get(a["id"]) or {}
        sub = a.get("substituta")
        if sub and contingencias.ativo(sub[0]):
            dep = res.get(sub[1]) or {}
            if dep.get("no_ar") is False:
                fora[a["id"]] = {"api": a["nome"] + " e a substituta " + sub[2],
                                 "desde": dep.get("fora_desde")}
        elif r.get("no_ar") is False:
            fora[a["id"]] = {"api": a["nome"], "desde": r.get("fora_desde")}
    _fora_cache = (time.time(), fora)
    return fora


def manutencao_para(path: str) -> list[dict[str, Any]] | None:
    """None = rota fora do radar; [] = rota vigiada e tudo no ar; [..] = em manutenção."""
    casou, itens = False, []
    fora = None
    for rx, api, funcao in ROTAS_MANUTENCAO:
        if not rx.search(path):
            continue
        casou = True
        fora = _sem_substituta() if fora is None else fora
        if api in fora and not any(i["funcao"] == funcao for i in itens):
            itens.append({"funcao": funcao, **fora[api]})
    return itens if casou else None


def painel() -> dict[str, Any]:
    """Tudo que o cartão do painel precisa, sem rodar sonda nenhuma."""
    e = ler_estado()
    cfg = config()
    linhas = []
    for a in APIS:
        r = (e.get("resultados") or {}).get(a["id"]) or {}
        linha = {"id": a["id"], "nome": a["nome"], **{k: r.get(k) for k in
                 ("no_ar", "codigo", "motivo", "ms", "fora_desde", "tentativas")}}
        # Respondeu, mas só depois de repetir: não é queda, é aviso de instabilidade.
        linha["instavel"] = bool(r.get("no_ar") and (r.get("tentativas") or 1) > 1)
        if a.get("substituta"):
            cid, _, rotulo = a["substituta"]
            c = contingencias.estado(cid)
            linha["substituta"] = rotulo
            linha["troca"] = {"ativo": bool(c.get("ativo")), "auto": bool(c.get("auto")),
                              "por": c.get("por") or "", "desde": c.get("desde")}
        elif a.get("sem_substituta"):
            linha["substituta"] = "— (" + a["sem_substituta"].split(" — ")[0] + ")"
        linhas.append(linha)
    problemas = []
    for l in linhas:
        if l.get("no_ar") is False:
            t = l.get("troca") or {}
            problemas.append({"id": l["id"], "nome": l["nome"], "desde": l.get("fora_desde"),
                              "trocada": bool(t.get("ativo")), "substituta": l.get("substituta") or ""})
    proxima = (e.get("ultima") or 0) + cfg["intervalo_h"] * 3600 if e.get("ultima") else None
    return {"config": cfg, "ultima": e.get("ultima") or None, "quem": e.get("quem") or "",
            "proxima": int(proxima) if proxima else None, "apis": linhas,
            "problemas": problemas, "avisadas": e.get("avisadas") or [],
            "eventos": (e.get("eventos") or [])[:15]}


if __name__ == "__main__":
    forcar = "--agora" in sys.argv
    saida = asyncio.run(verificar(forcar=forcar, quem="linha de comando" if forcar else "timer"))
    if "--quieto" not in sys.argv or saida.get("acoes"):
        if saida["status"] != "ok":
            print("vigia: %s" % saida.get("motivo"))
        else:
            for aid, r in saida["resultados"].items():
                marca = "ok  " if r["no_ar"] else ("--  " if r["no_ar"] is None else "FORA")
                print("  %s %-18s %s %s" % (marca, aid, r.get("codigo") or "", r.get("motivo") or ""))
            for a in saida["acoes"]:
                print("  >> " + a)
