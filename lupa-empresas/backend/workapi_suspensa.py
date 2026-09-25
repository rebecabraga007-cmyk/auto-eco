# -*- coding: utf-8 -*-
"""Contingência "Work API Suspenso": troca as três funções da WorkAPI pela Assertiva.

POR QUE EXISTE
--------------
Em 23 e 25/set/2026 a WorkAPI saiu do ar (522/523: a origem DELES não responde),
e com ela pararam: CPF -> telefones, telefone -> dono e nome -> pessoas. A tela
mostrava HTML da Cloudflare e o log registrava 200 OK. A Assertiva faz as três
coisas (ver lupa-empresas/APIS_FORA_DO_AR.md, tabela de funções), mas cada tela
só sabia chamar a WorkAPI.

COMO FUNCIONA
-------------
O admin liga um interruptor no painel. A troca acontece na CAMADA DE BAIXO --
`mkbuscas.consulta_cpf`, `mkbuscas.consulta_telefone` e `workapi.nome_search`
perguntam `ativo()` e, se ligado, vêm para cá. Este módulo chama a Assertiva e
devolve a resposta NO FORMATO DA WORKAPI, então nenhuma tela, nenhuma rota do
Bluutime e nenhum endpoint da API v1 precisou mudar para funcionar.

| Função da WorkAPI              | Substituta na Assertiva         |
|--------------------------------|---------------------------------|
| integrax-cpf     (CPF -> ficha) | /localize/v3/cpf                |
| intelgrax-tel    (tel -> dono)  | /localize/v3/telefone           |
| intelgrax-nomev2 (nome -> CPFs) | /localize/v3/nome-endereco      |

O QUE MUDA DE VERDADE: DINHEIRO
-------------------------------
A WorkAPI é cota diária (grátis por consulta); a Assertiva cobra cada uma. Os
lugares que usavam a WorkAPI EM LAÇO como conferência grátis não foram trocados
1 por 1 -- ver `funil._pelo_mk`, `funil._pela_workapi`, `funil._telefones_do_cpf`
e a desambiguação de `/api/company/{cnpj}/employees` no main. Cada consulta
paga daqui passa por `assertiva._get`, que já lança no livro de custos.

O que a Assertiva NÃO tem e a WorkAPI tinha: renda/score (`DadosEconomicos`),
parentes na mesma consulta e CBO. Esses campos voltam vazios enquanto a
contingência estiver ligada.
"""
import re
import time
import unicodedata
from typing import Any

import httpx

import contingencias

_nomes: dict[tuple[str, str], dict[str, Any]] = {}   # busca por nome: a tela pede 2x (exata + ampla)
_tels: dict[str, dict[str, Any]] = {}                 # /pertence e /reverse do mesmo número pagam 1x


# --------------------------------------------------------------------------
# Interruptor (o estado mora em contingencias.py, junto com o da Bright Data)
# --------------------------------------------------------------------------

def estado() -> dict[str, Any]:
    """{ativo, desde, por, auto, motivo}."""
    return contingencias.estado("workapi")


def ativo() -> bool:
    return contingencias.ativo("workapi")


def definir(ligar: bool, usuario: str = "", auto: bool = False, motivo: str = "") -> dict[str, Any]:
    novo = contingencias.definir("workapi", ligar, usuario, auto=auto, motivo=motivo)
    if ligar:
        _nomes.clear()
        _tels.clear()
    return novo


async def sondar_workapi() -> dict[str, Any]:
    """A WorkAPI está respondendo agora? Não gasta cota: bate na raiz do gateway.

    523/522/timeout = fora do ar (origem deles). 401/403/404 = o gateway está
    vivo e só recusou a chamada sem chave, que é o esperado.
    """
    t = time.time()
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get("https://api.workapi.dev/v1/gateway")
        cod = r.status_code
    except Exception as exc:
        return {"no_ar": False, "codigo": None, "ms": int((time.time() - t) * 1000),
                "motivo": "sem resposta (%s)" % type(exc).__name__}
    fora = cod >= 500
    return {"no_ar": not fora, "codigo": cod, "ms": int((time.time() - t) * 1000),
            "motivo": ("origem da WorkAPI não responde (Cloudflare %d)" % cod) if fora
            else "gateway respondendo"}


# --------------------------------------------------------------------------
# Conversores
# --------------------------------------------------------------------------

def _dig(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def _telefones(src: Any) -> list[dict[str, Any]]:
    """`telefones` da Assertiva ({fixos:[], moveis:[]}) -> lista no formato rico
    do MK, que `mkbuscas._extract_phones` lê. Leva junto os sinais que só a
    Assertiva tem (não perturbe, último contato, relação, hotphone) para o
    `refine_phones` ordenar por eles."""
    import assertiva
    out = []
    grupos = src.items() if isinstance(src, dict) else [("", src or [])]
    for chave, lista in grupos:
        tipo = "MOVEL" if "movel" in chave.lower() or "móve" in chave.lower() else (
            "FIXO" if "fixo" in chave.lower() else "")
        for t in lista if isinstance(lista, list) else []:
            n = assertiva._norm_tel(t)
            if not n:
                continue
            num = n["number"]
            out.append({
                "telefone": num,
                "numero": num,
                "ddd": num[:2] if len(num) >= 10 else "",
                "tipo": tipo or n.get("tipo") or "",
                "operadora": (t.get("operadora") if isinstance(t, dict) else "") or "",
                "whatsapp": n.get("whatsapp"),
                "nao_perturbe": n.get("nao_perturbe"),
                "ultimo_contato": n.get("ultimo_contato") or "",
                "meses_sem_contato": n.get("meses_sem_contato"),
                "hotphone": n.get("hotphone"),
                "plus": n.get("plus"),
                "relacao": n.get("relacao") or "",
                "fonte": "assertiva",
            })
    return out


def ficha_cpf(resp: dict[str, Any]) -> dict[str, Any]:
    """`resposta` do /localize/v3/cpf -> objeto de pessoa no formato do integrax-cpf.

    As chaves são as que as telas e o dossiê leem do MK: DadosBasicos (nome,
    nascimento, mãe, sexo, situação), telefones, enderecos, emails, empresas
    (com CNPJ, que o funil cruza com a Receita), empregos e profissao.
    """
    dc = resp.get("dadosCadastrais") or {}
    obito = dc.get("obitoProvavel")
    ends = []
    for e in (resp.get("enderecos") or []) + (resp.get("enderecosAdicionados") or []):
        if not isinstance(e, dict):
            continue
        rua = " ".join(x for x in (e.get("tipoLogradouro"), e.get("logradouro")) if x)
        ends.append({
            "logradouro": rua,
            "logradouroNumero": str(e.get("numero") or ""),
            "numero": str(e.get("numero") or ""),
            "complemento": e.get("complemento") or "",
            "bairro": e.get("bairro") or "",
            "cidade": e.get("cidade") or "",
            "uf": e.get("uf") or "",
            "cep": e.get("cep") or "",
        })
    emails = []
    for e in (resp.get("emails") or []) + (resp.get("emailsAdicionados") or []):
        val = (e.get("email") or e.get("enderecoEmail")) if isinstance(e, dict) else e
        if val:
            emails.append({"email": str(val)})
    empresas = []
    for p in resp.get("participacoesEmpresas") or resp.get("participacoesSocietarias") or []:
        if isinstance(p, dict) and (p.get("cnpj") or p.get("razaoSocial")):
            empresas.append({"cnpj": _dig(p.get("cnpj")), "razaoSocial": p.get("razaoSocial") or "",
                             "relacao": p.get("cargo") or "", "admissao": p.get("dataEntrada") or "",
                             "demissao": ""})
    empregos = []
    for h in resp.get("possivelHistoricoProfissional") or []:
        if not isinstance(h, dict):
            continue
        empregos.append({
            **h,
            "razaoSocial": (h.get("razaoSocial") or h.get("empresa")
                            or h.get("nomeEmpresa") or h.get("nome") or ""),
            "cnpj": _dig(h.get("cnpj")),
            "cargo": h.get("cargo") or h.get("profissao") or h.get("ocupacao") or "",
        })
    # Sócio também é vínculo: o desempate por empresa (`company_matches`) lê empregos.
    empregos += [{"razaoSocial": e["razaoSocial"], "cnpj": e["cnpj"], "cargo": e["relacao"]}
                 for e in empresas if e["razaoSocial"]]
    regs = [r for r in resp.get("registrosProfissionais") or [] if isinstance(r, dict)]
    return {
        "cpf": _dig(dc.get("cpf")),
        "nome": dc.get("nome") or "",
        "DadosBasicos": {
            "nome": dc.get("nome") or "",
            "cpf": _dig(dc.get("cpf")),
            "dataNascimento": dc.get("dataNascimento") or "",
            "nomeMae": dc.get("maeNome") or "",
            "sexo": dc.get("sexo") or "",
            "idade": dc.get("idade"),
            "situacaoCadastral": {
                "descricaoSituacaoCadastral": dc.get("situacaoCadastral") or "",
                "dataSituacaoCadastral": dc.get("dataSituacaoCadastral") or "",
            },
            "obito": {"obito": "SIM" if obito else "NÃO"} if obito is not None else {},
        },
        "DadosEconomicos": {},          # a Assertiva não tem renda/score
        "profissao": {"cboDescricao": regs[0].get("profissao") or ""} if regs else {},
        "telefones": _telefones(resp.get("telefones")) + _telefones(resp.get("telefonesAdicionados")),
        "enderecos": ends,
        "emails": emails,
        "empresas": empresas,
        "empregos": empregos,
        "parentes": [],                 # na Assertiva é outra consulta paga (pessoas-de-referencia)
        "fonte": "Assertiva (WorkAPI suspensa)",
    }


# --------------------------------------------------------------------------
# As três substituições
# --------------------------------------------------------------------------

async def cpf(doc: str) -> dict[str, Any]:
    """No lugar de `mkbuscas.consulta_cpf`. Mesmo retorno: {status, data}."""
    import assertiva
    d = _dig(doc).zfill(11)[:11]
    r = await assertiva.consulta_cpf(d)
    if r.get("status") != "ok":
        return {"status": r.get("status") or "error",
                "message": "Assertiva (WorkAPI suspensa): %s" % (r.get("message") or "sem resposta"),
                "fonte": "assertiva"}
    resp = (r.get("data") or {}).get("resposta") or {}
    return {"status": "ok", "data": ficha_cpf(resp), "fonte": "assertiva"}


async def telefone(phone: str) -> dict[str, Any]:
    """No lugar de `mkbuscas.consulta_telefone`. Mesmo retorno:
    {status, phone, total, registros:[{cpf_cnpj, nome, endereco}]}.

    "Não localizamos" da Assertiva (404) vira total 0 -- é a mesma leitura que
    a tela já faz de um número sem vínculo, e não um erro.
    """
    import assertiva
    d = _dig(phone)
    if len(d) < 10:
        return {"status": "error", "message": "Telefone inválido."}
    d = d[-11:] if len(d) > 11 else d
    if d in _tels:
        return _tels[d]
    r = await assertiva.consulta_telefone(d)
    if r.get("status") == "not_found":
        _tels[d] = {"status": "ok", "phone": d, "total": 0, "registros": [], "fonte": "assertiva"}
        return _tels[d]
    if r.get("status") != "ok":
        return {"status": r.get("status") or "error",
                "message": "Assertiva (WorkAPI suspensa): %s" % (r.get("message") or "sem resposta")}
    resp = (r.get("data") or {}).get("resposta") or {}
    regs = []
    for p in resp.get("pessoaFisica") or []:
        if isinstance(p, dict):
            regs.append({"cpf_cnpj": _dig(p.get("cpf")), "nome": p.get("nome") or "",
                         "endereco": {"cidade": p.get("cidade") or "", "uf": p.get("uf") or ""}})
    for p in resp.get("pessoaJuridica") or []:
        if isinstance(p, dict):
            regs.append({"cpf_cnpj": _dig(p.get("cnpj")),
                         "nome": p.get("razaoSocial") or p.get("nome") or p.get("nomeFantasia") or "",
                         "endereco": {"cidade": p.get("cidade") or "", "uf": p.get("uf") or ""}})
    if len(_tels) > 2000:
        _tels.clear()
    _tels[d] = {"status": "ok", "phone": d, "total": len(regs), "registros": regs,
                "fonte": "assertiva"}
    return _tels[d]


async def nome(q: str, limit: int = 40, uf: str = "") -> dict[str, Any]:
    """No lugar de `workapi.nome_search`. Mesmo retorno: {status, pessoas:[...]}.

    `pago` diz se houve consulta nova (e não cache): a rota de busca por nome
    é gratuita na cota diária e passa a custar enquanto a contingência durar.
    """
    import assertiva
    q = (q or "").strip()
    if not q:
        return {"status": "error", "message": "q obrigatório", "pessoas": []}
    chave = (_norm(q), (uf or "").strip().upper())
    pago = False
    if chave in _nomes:
        r = _nomes[chave]
    else:
        filtros = {"buscarPor": "pessoas", "nomeOuRazaoSocial": q}
        if chave[1]:
            filtros["uf"] = chave[1]
        r = await assertiva.busca_nome_endereco(filtros)
        pago = r.get("status") not in ("unavailable", "auth_error")
        if r.get("status") in ("ok", "not_found"):
            if len(_nomes) > 500:
                _nomes.clear()
            _nomes[chave] = r
    if r.get("status") == "not_found":
        return {"status": "ok", "pessoas": [], "message": "Sem resultados", "pago": pago,
                "fonte": "assertiva"}
    if r.get("status") != "ok":
        return {"status": r.get("status") or "error", "pessoas": [], "pago": pago,
                "message": "Assertiva (WorkAPI suspensa): %s" % (r.get("message") or "sem resposta")}
    pessoas = []
    for p in ((r.get("data") or {}).get("resposta") or {}).get("pessoaFisica") or []:
        if not isinstance(p, dict):
            continue
        cidade = p.get("cidade") or ""
        pessoas.append({
            "nome": p.get("nome") or "",
            "cpf": _dig(p.get("cpf")),
            "cpf_mascarado": False,
            "data_nascimento": p.get("dataNascimento") or "",
            "sexo": p.get("sexo") or "",
            "nome_mae": p.get("nomeMae") or "",
            "situacao_cadastral": "",
            "endereco": {
                "logradouro": p.get("logradouro") or "",
                "numero": str(p.get("numero") or ""),
                "complemento": p.get("complemento") or "",
                "bairro": p.get("bairro") or "",
                "municipio": cidade,
                "cidade": cidade,
                "uf": p.get("uf") or "",
                "cep": p.get("cep") or "",
            },
            "fonte": "Assertiva",
        })
        if len(pessoas) >= limit:
            break
    return {"status": "ok", "pessoas": pessoas, "pago": pago, "fonte": "assertiva"}
