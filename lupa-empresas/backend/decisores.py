"""Classificação de cargo por poder de decisão (níveis 1, 2 e 3).

Serve à aba "Quem trabalha lá": a RAIS diz QUEM está na empresa, mas não diz o
CARGO de ninguém. O cargo vem de fora:

- Receita Federal (QSA)  → `qualificacao_socio` ("Sócio-Administrador",
  "Diretor", "Presidente"...). De graça, exato, mas só cobre sócios.
- LinkedIn (Bright Data) → título livre do perfil. Cobre funcionário comum,
  mas é lento/pago e o cruzamento é por nome, então é opt-in.

Níveis:
  1  decide sozinho — dono, sócio-administrador, presidente, CEO, diretor-geral
  2  decide na sua área, com verba própria — C-level, diretor, VP, head, sócio
  3  influencia, especifica e veta — gerente, coordenador, comprador, controller
  0  não é decisor (ou cargo desconhecido)

O que NÃO é decisor apesar do título: "Executivo/Gerente de Contas" (vende para
fora, não compra), "Consultor", "Analista", "Assistente", "Estagiário". Esses
entram em EXCLUSOES e são checados ANTES dos níveis — "Gerente de Contas" bate
em "gerente" e viraria nível 3 por engano.
"""

import re
import unicodedata

# ── Cargos por nível (regex, já normalizado: minúsculo, sem acento) ────────
# A ordem importa: o primeiro nível que casar vence, do mais alto pro mais baixo.

NIVEL_1 = [
    r"\bsocio[ -]administrador",
    r"\bsocio[ -]proprietario",
    r"\bsocio[ -]gerente",
    r"\bproprietari[oa]\b",
    r"\bdon[oa] d[ao]\b",
    r"\btitular\b",
    r"\bempresari[oa]\b",
    r"\bpresidente\b",
    r"\bdiretor[ -]presidente\b",
    r"\bdiretor[ea]?[ -]ger(al|ente)\b",
    r"\bsuperintendente\b",
    r"\bceo\b|\bc\.e\.o\b|chief executive",
    r"\bfundador[a]?\b|\bfounder\b|co[ -]founder",
    r"\badministrador[a]?\b",
    r"country manager|general manager",
]

NIVEL_2 = [
    r"\bc[foiter]o\b",                       # CFO, CIO, COO, CTO, CMO... (2 letras + O)
    r"chief (financial|operating|technology|information|marketing|revenue|people|data)",
    r"\bdiretor[a]?\b",
    r"\bvice[ -]presidente\b|\bvp\b",
    r"\bconselheir[oa]\b",
    r"\bhead\b",
    r"\bs[oó]ci[oa]\b",                      # sócio cotista: decide, mas com o time
]

NIVEL_3 = [
    r"\bgerente\b|\bmanager\b",
    r"\bcoordenador[a]?\b",
    r"\bsupervisor[a]?\b",
    r"\bcontroller\b|\bcontroladoria\b",
    r"\bcomprador[a]?\b|\bcompras\b|\bsuprimentos\b|supply chain",
    r"\bencarregad[oa]\b",
    r"\bl[ií]der\b|\bteam lead\b",
    r"\bpmo\b",
]

# Checado ANTES dos níveis — título que parece decisor e não é.
EXCLUSOES = [
    r"(gerente|executiv[oa]|assistente|analista) de (contas|vendas|relacionamento|clientes)",
    r"\bconsultor[a]?\b",
    r"\bespecialista\b",
    r"\banalista\b",
    r"\bassistente\b",
    r"\bauxiliar\b",
    r"\bestagiari[oa]\b|\btrainee\b|\baprendiz\b",
    r"\bt[eé]cnic[oa]\b",
    r"\bvendedor[a]?\b|\brepresentante comercial\b",
    r"\bsocio[ -]pessoa juridica\b",         # holding, não é gente
]

# Área do cargo — pra saber a quem oferecer o quê.
AREAS = [
    ("Financeiro", r"\bcfo\b|financ|controlad|controller|contabil|tesourari|chief financial"),
    ("Tecnologia", r"\bcto\b|\bcio\b|tecnologia|\bti\b|\bit\b|engenharia de software|dados|digital"
                   r"|chief (technology|information|data)"),
    ("Comercial", r"comercial|\bvendas\b|\bcro\b|chief revenue|neg[o]cios"),
    ("Marketing", r"marketing|\bcmo\b|growth|comunica[c]|chief marketing"),
    ("RH", r"\brh\b|recursos humanos|gente|people|\bchro\b|talento|chief people"),
    ("Operações", r"opera[c]|\bcoo\b|industrial|produ[c][a]o|log[i]stica|suprimentos|compras|comprador"
                  r"|supply|chief operating"),
    ("Jurídico", r"jur[i]dic|\blegal\b|compliance"),
]

_ROTULOS = {1: "Decide sozinho", 2: "Decide na área", 3: "Influencia e veta"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


def _casa(texto: str, padroes: list[str]) -> bool:
    return any(re.search(p, texto) for p in padroes)


def classificar(cargo: str) -> dict:
    """Classifica um cargo livre. Retorna {nivel, rotulo, area}.

    nivel 0 = não é decisor ou não deu pra dizer.
    """
    txt = _norm(cargo)
    if not txt:
        return {"nivel": 0, "rotulo": "", "area": ""}

    area = next((nome for nome, padrao in AREAS if re.search(padrao, txt)), "")

    if _casa(txt, EXCLUSOES):
        return {"nivel": 0, "rotulo": "", "area": ""}

    for nivel, padroes in ((1, NIVEL_1), (2, NIVEL_2), (3, NIVEL_3)):
        if _casa(txt, padroes):
            return {"nivel": nivel, "rotulo": _ROTULOS[nivel], "area": area}

    # Área sozinha, sem cargo de decisão, não diz nada — melhor não exibir.
    return {"nivel": 0, "rotulo": "", "area": ""}


def _chave_nome(nome: str) -> str:
    """Nome normalizado pra cruzamento entre fontes (sem acento, sem caixa)."""
    return _norm(nome)


def anexar_qsa(vinculos: list[dict], qsa: list[dict]) -> dict:
    """Marca quem, na lista da RAIS, também está no quadro de sócios da Receita.

    Cruza por CPF completo (quando o QSA foi resolvido na base JBR) e, na falta
    dele, por nome exato normalizado. Sócio que NÃO aparece na RAIS entra como
    linha nova — um sócio-administrador fora da folha continua sendo o decisor
    da empresa, e some da tela se a gente só listar empregado.

    Devolve {marcados, adicionados}.
    """
    por_cpf = {v["cpf"]: v for v in vinculos if v.get("cpf")}
    por_nome = {_chave_nome(v.get("nome")): v for v in vinculos if v.get("nome")}
    marcados = adicionados = 0

    for socio in qsa or []:
        if not isinstance(socio, dict):
            continue
        nome = (socio.get("nome_socio") or "").strip()
        qualificacao = (socio.get("qualificacao_socio") or "").strip()
        if not nome:
            continue
        # Sócio PJ (holding) não é gente — não entra numa lista de pessoas.
        if socio.get("identificador_de_socio") == 1 or "pessoa juridica" in _norm(qualificacao):
            continue
        cpf = (socio.get("cpf_completo") or "").strip()
        cls = classificar(qualificacao)
        # Sócio PF sem qualificação reconhecida ainda é sócio — nível 2.
        if cls["nivel"] == 0 and not _casa(_norm(qualificacao), EXCLUSOES):
            cls = {"nivel": 2, "rotulo": _ROTULOS[2], "area": cls["area"]}

        alvo = por_cpf.get(cpf) if cpf else None
        if alvo is None:
            alvo = por_nome.get(_chave_nome(nome))

        if alvo is not None:
            alvo["cargo"] = qualificacao or "Sócio"
            alvo["fonte_cargo"] = "Receita Federal (QSA)"
            alvo["socio"] = True
            alvo.update({k: cls[k] for k in ("nivel", "rotulo", "area")})
            marcados += 1
            continue

        vinculos.append({
            "cpf": cpf,
            "nome": nome,
            "admissao": "",
            "admissao_br": "",
            "desligamento": None,
            "desligamento_parcial": None,
            "desligamento_br": "",
            "ativo": True,
            "meses": None,
            "tempo_casa": "",
            "faixa_renda": "",
            "situacao": "",
            "cargo": qualificacao or "Sócio",
            "fonte_cargo": "Receita Federal (QSA)",
            "socio": True,
            "na_rais": False,
            "desde": socio.get("data_entrada_sociedade") or "",
            **{k: cls[k] for k in ("nivel", "rotulo", "area")},
        })
        adicionados += 1

    return {"marcados": marcados, "adicionados": adicionados}


def anexar_cargos_linkedin(vinculos: list[dict], employees: list[dict]) -> int:
    """Anexa cargo do LinkedIn por nome exato normalizado. Devolve quantos casaram.

    Só preenche quem ainda não tem cargo — o QSA da Receita é fonte melhor e
    não deve ser sobrescrito por título de perfil.
    """
    if not employees:
        return 0
    por_nome: dict[str, list[dict]] = {}
    for v in vinculos:
        por_nome.setdefault(_chave_nome(v.get("nome")), []).append(v)

    casados = 0
    for emp in employees:
        if not isinstance(emp, dict):
            continue
        titulo = (emp.get("title") or "").strip()
        if not titulo:
            continue
        alvos = por_nome.get(_chave_nome(emp.get("name")))
        if not alvos:
            continue
        cls = classificar(titulo)
        for alvo in alvos:
            if alvo.get("cargo"):
                continue
            alvo["cargo"] = titulo
            alvo["fonte_cargo"] = "LinkedIn"
            alvo.update({k: cls[k] for k in ("nivel", "rotulo", "area")})
            casados += 1
    return casados


def normalizar(vinculos: list[dict]) -> None:
    """Garante os campos de cargo em todo mundo (quem não tem fica nível 0)."""
    for v in vinculos:
        v.setdefault("cargo", "")
        v.setdefault("fonte_cargo", "")
        v.setdefault("nivel", 0)
        v.setdefault("rotulo", "")
        v.setdefault("area", "")
        v.setdefault("socio", False)
        v.setdefault("na_rais", True)


def ordenar(vinculos: list[dict]) -> None:
    """Decisor primeiro (nível 1 → 3), depois quem continua na empresa, depois
    admissão mais recente."""
    def chave(v):
        nivel = v.get("nivel") or 9          # 0 (sem cargo) vai pro fim
        adm = v.get("admissao") or ""
        try:
            data = tuple(-int(x) for x in adm.split("-"))
        except Exception:
            data = (0, 0, 0)
        return (nivel, not v.get("ativo"), data, v.get("nome") or "")
    vinculos.sort(key=chave)


def resumo(vinculos: list[dict]) -> dict:
    """Contagem por nível, pras abas de hierarquia."""
    cont = {"nivel_1": 0, "nivel_2": 0, "nivel_3": 0, "sem_cargo": 0, "socios": 0}
    for v in vinculos:
        n = v.get("nivel") or 0
        cont["nivel_1" if n == 1 else "nivel_2" if n == 2 else "nivel_3" if n == 3 else "sem_cargo"] += 1
        if v.get("socio"):
            cont["socios"] += 1
    cont["decisores"] = cont["nivel_1"] + cont["nivel_2"] + cont["nivel_3"]
    return cont
