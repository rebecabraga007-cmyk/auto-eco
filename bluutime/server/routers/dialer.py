"""Ligações: lista, estatísticas, extrato e click-to-call."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Call, CallFeedback, Company, Lead, Team, User
from .. import agenda, perm, serial
from .analytics import ids_de, usuarios_do_time

router = APIRouter(prefix="/api/dialer")

MINUTE_PRICE = 0.47  # padrão quando a empresa não informou a tarifa dela


def _preco_minuto(db: Session) -> float:
    """Tarifa da empresa, com o padrão como rede de segurança.

    O Meetime lê da fatura da operadora; aqui quem informa é quem paga a
    conta. Melhor um número que alguém digitou sabendo de onde veio do que uma
    constante escondida no código.
    """
    c = db.query(Company).first()
    return float(getattr(c, "minute_price", 0) or MINUTE_PRICE) if c else MINUTE_PRICE


def _company(db: Session) -> Company:
    c = db.query(Company).first()
    if not c:
        raise HTTPException(500, "Empresa não inicializada.")
    return c


def _normaliza_numero(bruto: str) -> str:
    """Aceita o que o gestor digitar e devolve só dígitos com + na frente.

    O Meetime valida o formato na linha; aqui a validação também protege a
    ligação, porque este número vai como bina para a operadora.
    """
    limpo = "".join(ch for ch in str(bruto) if ch.isdigit() or ch == "+")
    digitos = limpo.lstrip("+")
    if not digitos.isdigit() or not 10 <= len(digitos) <= 15:
        raise HTTPException(400, f"Número inválido: {bruto}. Use DDD + número, "
                                 "com ou sem o código do país.")
    # Dez ou onze dígitos é número brasileiro sem país; o 55 entra para que a
    # lista não misture dois formatos.
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    return "+" + digitos


def _caller_ids(c) -> list[dict]:
    """Cada linha é `numero|rótulo`; linhas antigas, sem rótulo, seguem valendo."""
    saida = []
    for linha in c.caller_ids.splitlines():
        if not linha.strip():
            continue
        numero, _, rotulo = linha.partition("|")
        numero = numero.strip()
        saida.append({"number": numero, "label": rotulo.strip(),
                      "default": numero == (c.default_caller_id or "")})
    # Sem padrão marcado, o primeiro é o padrão: alguém tem que ser, e é o
    # que o SDR vê pré-selecionado.
    if saida and not any(n["default"] for n in saida):
        saida[0]["default"] = True
    return saida


@router.get("/configuration")
def dialer_configuration(db: Session = Depends(get_db)):
    c = _company(db)
    lista = _caller_ids(c)
    return {"voipEnabled": c.voip_enabled, "phoneEnabled": c.phone_enabled,
            "defaultType": c.default_call_type,
            # `callerIds` continua sendo a lista de strings que o resto da
            # tela já consumia; `callerIdList` é a versão com rótulo e padrão.
            "callerIds": [n["number"] for n in lista],
            "callerIdList": lista,
            "defaultCallerId": next((n["number"] for n in lista if n["default"]), "")}


@router.patch("/configuration")
def update_dialer_configuration(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Não existia tela nenhuma pra isso — o SDR registrava a ligação sem
    escolher de qual número da empresa ela saiu."""
    perm.ator(db).exigir("gestor", "configurar o dialer")
    c = _company(db)
    if "voipEnabled" in payload:
        c.voip_enabled = bool(payload["voipEnabled"])
    if "phoneEnabled" in payload:
        c.phone_enabled = bool(payload["phoneEnabled"])
    if "defaultType" in payload and payload["defaultType"] in ("VOIP", "PHONE"):
        c.default_call_type = payload["defaultType"]
    if "callerIdList" in payload:
        linhas, vistos, padrao = [], set(), ""
        for item in payload["callerIdList"]:
            if isinstance(item, str):
                item = {"number": item}
            numero = _normaliza_numero(item.get("number", ""))
            if numero in vistos:
                raise HTTPException(400, f"Número repetido na lista: {numero}.")
            vistos.add(numero)
            rotulo = (item.get("label") or "").strip().replace("|", " ")
            linhas.append(f"{numero}|{rotulo}" if rotulo else numero)
            if item.get("default"):
                padrao = numero
        c.caller_ids = chr(10).join(linhas)
        c.default_caller_id = padrao or (linhas[0].split("|")[0] if linhas else "")
    elif "callerIds" in payload:
        c.caller_ids = chr(10).join(_normaliza_numero(n) for n in payload["callerIds"]
                                    if str(n).strip())
    db.commit()
    return dialer_configuration(db)


def _range(since: str | None, until: str | None) -> tuple[datetime, datetime]:
    end = serial.instante(until) or datetime.utcnow()
    start = serial.instante(since) or end.replace(day=1, hour=0, minute=0)
    return start, end + timedelta(days=1) if until else end


def _escopo(db: Session, q, team_id, user_id):
    """Recorte por time e por pessoa, na ordem que o original oferece.

    Os dois aceitam lista separada por vírgula: o Meetime deixa marcar vários
    times e vários usuários no mesmo filtro.
    """
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    pessoas = ids_de(user_id)
    if pessoas:
        q = q.filter(Call.user_id.in_(pessoas))
    return q


def _etapas(db: Session, inicio, fim, team_id, user_id) -> dict:
    base = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                   team_id, user_id)
    total = base.count()
    conectadas = base.filter(Call.status == "CONNECTED").count()
    significativas = base.filter(Call.status == "CONNECTED",
                                 Call.output == "MEANINGFUL").count()
    return {"total": total, "conectadas": conectadas, "significativas": significativas}


def _variacao(agora: int, antes: int) -> dict:
    """Quanto mudou em relação ao período anterior.

    Sem base de comparação (o período anterior foi zero) não existe variação
    percentual — devolver 100% ali seria inventar um crescimento que ninguém
    pode conferir, então o percentual vem nulo e a tela mostra o absoluto.
    """
    return {"diferenca": agora - antes,
            "percentual": round((agora - antes) / antes * 100, 1) if antes else None}


def _pode_ver_ligacao(db: Session, c: Call) -> None:
    ator = perm.ator(db)
    if ator.pelo_menos("gestor"):
        return
    empresa = db.query(Company).first()
    if c.user_id != ator.user_id and not (empresa and empresa.leads_visible_all):
        raise HTTPException(403, "Esta ligação é de outro usuário.")


def _ser_feedback(f) -> dict:
    return {"id": f.id, "callId": f.call_id, "text": f.text,
            "author": serial.user_min(f.author),
            "createdAt": serial.iso(f.created_at),
            "updatedAt": serial.iso(f.updated_at),
            "readAt": serial.iso(f.read_at)}


@router.get("/calls/{cid}/detail")
def call_detail(cid: int, db: Session = Depends(get_db)):
    """Detalhe da ligação com o histórico de coaching.

    É o `modalCallDetails` do original, menos o que depende de telefonia
    (gravação e transcrição): custo, resultado, o lead e os feedbacks.
    """
    c = db.get(Call, cid)
    if not c:
        raise HTTPException(404, "Ligação não encontrada.")
    _pode_ver_ligacao(db, c)
    feedbacks = (db.query(CallFeedback).filter(CallFeedback.call_id == cid)
                 .order_by(CallFeedback.created_at).all())
    return {**serial.call(c),
            "lead": serial.lead(c.lead) if c.lead else None,
            "feedbacks": [_ser_feedback(f) for f in feedbacks]}


@router.post("/calls/{cid}/feedback")
def add_call_feedback(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Coaching é do gestor para o SDR — quem fez a ligação não se avalia."""
    c = db.get(Call, cid)
    if not c:
        raise HTTPException(404, "Ligação não encontrada.")
    ator = perm.ator(db)
    ator.exigir("gestor", "dar feedback de ligação")
    texto = (payload.get("text") or "").strip()
    if not texto:
        raise HTTPException(400, "Escreva o feedback.")
    f = CallFeedback(call_id=cid, author_id=ator.user_id, text=texto)
    db.add(f)
    db.commit()
    return _ser_feedback(f)


@router.patch("/calls/feedback/{fid}")
def update_call_feedback(fid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Editar o próprio texto, ou marcar como lido — e só o DONO da ligação
    marca como lido, porque é ele quem leu."""
    f = db.get(CallFeedback, fid)
    if not f:
        raise HTTPException(404, "Feedback não encontrado.")
    ator = perm.ator(db)
    if "text" in payload:
        if f.author_id != ator.user_id:
            raise HTTPException(403, "Só o autor edita o próprio feedback.")
        texto = (payload["text"] or "").strip()
        if not texto:
            raise HTTPException(400, "O feedback não pode ficar vazio.")
        f.text = texto
        f.updated_at = datetime.utcnow()
    if payload.get("read"):
        if f.call.user_id != ator.user_id:
            raise HTTPException(403, "Quem marca como lido é quem recebeu o feedback.")
        f.read_at = f.read_at or datetime.utcnow()
    db.commit()
    return _ser_feedback(f)


@router.patch("/calls/{cid}")
def update_call(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Marcar como importante (a estrela da lista) e reclassificar o resultado.

    Reclassificar existe porque ouvir de novo muda a leitura: o que parecia
    significativa no calor da hora nem sempre era.
    """
    c = db.get(Call, cid)
    if not c:
        raise HTTPException(404, "Ligação não encontrada.")
    ator = perm.ator(db)
    if not ator.pelo_menos("gestor") and c.user_id != ator.user_id:
        raise HTTPException(403, "Só dá para alterar as próprias ligações.")
    if "important" in payload:
        c.important = bool(payload["important"])
    if "output" in payload:
        valor = (payload["output"] or "").strip()
        if valor and valor not in ("MEANINGFUL", "NOT_MEANINGFUL", "NO_CONTACT"):
            raise HTTPException(400, f"Resultado desconhecido: {valor}.")
        # Resultado só existe em ligação conectada — o registro já seguia essa
        # regra na criação, e reclassificar não é porta dos fundos para furá-la.
        if valor and c.status != "CONNECTED":
            raise HTTPException(400, "A ligação não conectou; não há resultado a classificar.")
        c.output = valor
    db.commit()
    return serial.call(c)


@router.get("/calls/export")
def export_calls(user_id: str | None = None, status: str | None = None,
                 output: str | None = None, since: str | None = None,
                 until: str | None = None, team_id: str | None = None,
                 q: str | None = None, db: Session = Depends(get_db)):
    """Exporta a lista filtrada, como o botão Exportar do original."""
    res = list_calls(user_id=user_id, status=status, output=output, since=since,
                     until=until, team_id=team_id, q=q, page=1, limit=20000, db=db)
    rotulo = {"MEANINGFUL": "Significativa", "NOT_MEANINGFUL": "Não significativa",
              "NO_CONTACT": "Sem contato"}
    linhas = [[c["originStarted"][:16].replace("T", " ") if c["originStarted"] else "",
               (c["user"] or {}).get("name", ""), c["flowLeadName"] or "",
               c["flowLeadCompany"] or "", c["originPhone"], c["receiverPhone"],
               "Celular" if c["receiverType"] == "MOBILE" else "Fixo",
               "Conectada" if c["status"] == "CONNECTED" else "Não conectada",
               rotulo.get(c["output"], ""), c["receiverConnectedDuration"],
               f'{c["receiverPrice"]:.4f}'.replace(".", ","),
               "sim" if c["important"] else ""]
              for c in res["data"]]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Data", "Usuário", "Lead", "Empresa", "Origem", "Destino", "Tipo",
                "Situação", "Resultado", "Duração (s)", "Custo (R$)", "Importante"])
    w.writerows(linhas)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      f'attachment; filename="ligacoes-{datetime.utcnow():%Y%m%d}.csv"'})


@router.get("/calls/statistics/funnel")
def funnel(since: str | None = None, until: str | None = None,
           team_id: str | None = None, user_id: str | None = None,
           db: Session = Depends(get_db)):
    """Realizadas → conectadas → significativas, contra o período anterior.

    O "anterior" é a janela de mesmo tamanho imediatamente antes: comparar um
    mês com a semana passada diria qualquer coisa.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    duracao = fim - inicio
    atual = _etapas(db, inicio, fim, team_id, user_id)
    anterior = _etapas(db, inicio - duracao, inicio, team_id, user_id)
    pct = lambda parte, todo: round(parte / todo * 100, 1) if todo else 0.0  # noqa: E731
    return {
        "atual": atual, "anterior": anterior,
        "periodoAnterior": {"since": (inicio - duracao).date().isoformat(),
                            "until": inicio.date().isoformat()},
        "taxas": {"conexao": pct(atual["conectadas"], atual["total"]),
                  "significancia": pct(atual["significativas"], atual["conectadas"])},
        "comparacao": {k: _variacao(atual[k], anterior[k]) for k in atual},
    }


@router.get("/calls/statistics/grouped")
def grouped(since: str | None = None, until: str | None = None,
            by: str = "user", db: Session = Depends(get_db)):
    """Volume de ligações por usuário ou por time."""
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    linhas = (db.query(Call.user_id, Call.status, func.count(Call.id))
              .filter(Call.started_at.between(inicio, fim))
              .group_by(Call.user_id, Call.status).all())
    usuarios = {u.id: u for u in db.query(User).all()}
    times = {t.id: t.name for t in db.query(Team).all()}

    acumulado: dict = {}
    for uid, status, n in linhas:
        u = usuarios.get(uid)
        if by == "team":
            chave = u.team_id if u and u.team_id else 0
            rotulo = times.get(chave, "Sem time")
        else:
            chave = uid or 0
            rotulo = u.name if u else "Sem usuário"
        linha = acumulado.setdefault(chave, {"label": rotulo, "total": 0, "conectadas": 0})
        linha["total"] += n
        if status == "CONNECTED":
            linha["conectadas"] += n
    dados = sorted(acumulado.values(), key=lambda r: r["total"], reverse=True)
    return {"by": by, "data": dados}


@router.get("/calls/statistics/history")
def history(since: str | None = None, until: str | None = None,
            interval: str = "day", team_id: str | None = None,
            status: str | None = None, db: Session = Depends(get_db)):
    """Série temporal de ligações por dia, semana ou mês."""
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    q = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                team_id, None)
    if status:
        q = q.filter(Call.status == status)
    formato = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m"}.get(interval, "%Y-%m-%d")
    contagem: dict = {}
    for c in q.all():
        chave = c.started_at.strftime(formato)
        linha = contagem.setdefault(chave, {"label": chave, "total": 0, "conectadas": 0})
        linha["total"] += 1
        if c.status == "CONNECTED":
            linha["conectadas"] += 1
    return {"interval": interval, "data": [contagem[k] for k in sorted(contagem)]}


@router.get("/calls/statistics/distribution")
def distribution(since: str | None = None, until: str | None = None,
                 team_id: str | None = None, user_id: str | None = None,
                 db: Session = Depends(get_db)):
    """Distribuição por status e por resultado — a rosca da visão geral.

    O funil responde quantas conectaram; isto responde o que aconteceu com as
    que não conectaram, que é onde mora o problema de lista ruim.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    q = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                team_id, user_id)
    linhas = q.all()
    por_status: dict[str, int] = {}
    por_resultado: dict[str, int] = {}
    for c in linhas:
        por_status[c.status or "—"] = por_status.get(c.status or "—", 0) + 1
        if c.status == "CONNECTED":
            por_resultado[c.output or "SEM_CLASSIFICACAO"] = \
                por_resultado.get(c.output or "SEM_CLASSIFICACAO", 0) + 1
    # A rosca do original é UMA classificação com cinco fatias, não duas
    # listas: status e resultado combinados no que a pessoa de fato quer
    # saber — falou bem, falou mal, ocupado, não falou, não conectou.
    fatias = {"MEANINGFUL": 0, "NOT_MEANINGFUL": 0, "BUSY": 0,
              "NO_CONTACT": 0, "NOT_CONNECTED": 0}
    total_seg = 0
    for c in linhas:
        if c.status == "BUSY":
            fatias["BUSY"] += 1
        elif c.status != "CONNECTED":
            fatias["NOT_CONNECTED"] += 1
        elif c.output in ("MEANINGFUL", "NOT_MEANINGFUL", "NO_CONTACT"):
            fatias[c.output] += 1
        else:
            fatias["NO_CONTACT"] += 1
        total_seg += c.duration or 0
    conectadas = [c for c in linhas if c.status == "CONNECTED"]
    # "Média em conversa" conta só o que conectou: incluir as não atendidas
    # puxaria a média para zero e não diria nada sobre a conversa.
    media_seg = round(sum(c.duration or 0 for c in conectadas) / len(conectadas)) if conectadas else 0
    dias = len({c.started_at.date() for c in linhas}) or 1
    vendedores = len({c.user_id for c in linhas if c.user_id}) or 1
    return {"total": len(linhas),
            "status": [{"chave": k, "total": v} for k, v in
                       sorted(por_status.items(), key=lambda kv: -kv[1])],
            "resultado": [{"chave": k, "total": v} for k, v in
                          sorted(por_resultado.items(), key=lambda kv: -kv[1])],
            "fatias": [{"chave": k, "total": v} for k, v in fatias.items()],
            "tempoTotalSegundos": total_seg,
            "mediaConversaSegundos": media_seg,
            "diariasPorVendedor": round(len(linhas) / dias / vendedores, 1),
            "dias": dias, "vendedores": vendedores}


@router.get("/calls/statistics/cumulative")
def cumulative(since: str | None = None, until: str | None = None,
               team_id: str | None = None, status: str | None = None,
               db: Session = Depends(get_db)):
    """Acumulado dia a dia — o `cumulative` do original.

    A série diária diz se hoje foi bom; a acumulada diz se o mês está no
    ritmo, que é a pergunta de quem acompanha meta.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    q = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                team_id, None)
    if status:
        q = q.filter(Call.status == status)
    por_dia: dict[str, dict] = {}
    for c in q.all():
        chave = c.started_at.strftime("%Y-%m-%d")
        linha = por_dia.setdefault(chave, {"data": chave, "total": 0, "conectadas": 0,
                                           "significativas": 0})
        linha["total"] += 1
        if c.status == "CONNECTED":
            linha["conectadas"] += 1
        if c.output == "MEANINGFUL":
            linha["significativas"] += 1
    # Dias sem ligação entram zerados: sem eles a linha do acumulado dá saltos
    # que somem com os fins de semana e enganam a leitura do ritmo.
    serie, acc = [], {"total": 0, "conectadas": 0, "significativas": 0}
    dia = inicio.date()
    ultimo = min(fim.date(), datetime.utcnow().date())
    while dia <= ultimo:
        chave = dia.isoformat()
        d = por_dia.get(chave, {"total": 0, "conectadas": 0, "significativas": 0})
        for k in acc:
            acc[k] += d[k]
        serie.append({"data": chave, **{f"dia{k.capitalize()}": d[k] for k in acc},
                      **{k: acc[k] for k in acc}})
        dia += timedelta(days=1)
    return {"data": serie}


@router.get("/calls/statistics/best-hour")
def best_hour(since: str | None = None, until: str | None = None,
              team_id: str | None = None, user_id: str | None = None,
              db: Session = Depends(get_db)):
    """Taxa de conexão por hora do dia — o "horário ideal" do original.

    Sai das ligações que já aconteceram, não de palpite: a hora com mais
    conexão é a que merece a fila de amanhã.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    inicio, fim = _range(since, until)
    q = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                team_id, user_id)
    horas = {h: {"hora": h, "total": 0, "conectadas": 0, "significativas": 0}
             for h in range(24)}
    for c in q.all():
        # `started_at` é UTC; a leitura é de quem liga, então vai para o fuso
        # local — senão o pico das 9h aparece às 12h.
        h = agenda.to_local(c.started_at).hour
        horas[h]["total"] += 1
        if c.status == "CONNECTED":
            horas[h]["conectadas"] += 1
        if c.output == "MEANINGFUL":
            horas[h]["significativas"] += 1
    linhas = [{**v, "conexao": round(100 * v["conectadas"] / v["total"]) if v["total"] else 0}
              for v in horas.values()]
    total = sum(l["total"] for l in linhas)
    # Hora com cinco ligações e 100% de conexão não é a melhor hora, é ruído.
    # O corte exige volume mínimo antes de a hora poder ser eleita.
    minimo = max(10, round(total * 0.02))
    candidatas = [l for l in linhas if l["total"] >= minimo]
    melhor = max(candidatas, key=lambda l: (l["conexao"], l["total"]), default=None)
    return {"data": linhas, "melhorHora": melhor["hora"] if melhor else None,
            "melhorHoraLigacoes": melhor["total"] if melhor else 0,
            "volumeMinimo": minimo, "total": total}


@router.get("/calls")
def list_calls(user_id: str | None = None, status: str | None = None,
               output: str | None = None, lead_id: int | None = None,
               since: str | None = None, until: str | None = None,
               team_id: str | None = None, q: str | None = None,
               important: bool | None = None,
               page: int = 1, limit: int = Query(50, le=500),
               db: Session = Depends(get_db)):
    ator = perm.ator(db)
    if not ator.pelo_menos("gestor"):
        empresa = _company(db)
        # Sem isso, um SDR listava ligação (telefone e empresa do lead
        # incluídos) de qualquer colega só passando outro user_id/lead_id —
        # a listagem nunca filtrava por dono, só as telas de lead filtravam.
        if not empresa.leads_visible_all:
            user_id = ator.user_id or -1
    start, end = _range(since, until)
    query = db.query(Call).filter(Call.started_at.between(start, end))
    pessoas = ids_de(user_id)
    if pessoas:
        query = query.filter(Call.user_id.in_(pessoas))
    if status:
        query = query.filter(Call.status == status)
    if output:
        query = query.filter(Call.output == output)
    if lead_id:
        query = query.filter(Call.lead_id == lead_id)
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        query = query.filter(Call.user_id.in_(do_time))
    if important is not None:
        query = query.filter(Call.important.is_(important))
    if q:
        # Busca pelo número discado ou pelo nome do lead — as duas formas de
        # procurar "aquela ligação" quando não se lembra da data.
        alvo = f"%{q}%"
        query = query.outerjoin(Lead, Call.lead_id == Lead.id).filter(
            or_(Call.receiver_phone.ilike(alvo), Lead.name.ilike(alvo),
                Lead.company.ilike(alvo)))
    total = query.count()
    rows = (query.order_by(Call.started_at.desc())
            .offset((page - 1) * limit).limit(limit).all())
    return {"data": [serial.call(c) for c in rows],
            "pagination": {"page": page, "perPage": limit, "totalRowCount": total,
                           "totalPageCount": max(1, -(-total // limit))}}


@router.post("/calls")
def register_call(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Registra o resultado de uma ligação feita pelo softphone."""
    ator = perm.ator(db)
    # userId vinha livre do payload — um SDR registrava ligação em nome de
    # outro colega e inflava (ou sabotava) o ranking dele.
    user_id = payload.get("userId")
    if not ator.pelo_menos("gestor"):
        user_id = ator.user_id
    lead = db.get(Lead, payload["leadId"]) if payload.get("leadId") else None
    if payload.get("leadId") and not lead:
        raise HTTPException(404, "Lead não encontrado.")
    # Ligação em lead alheio sujava o histórico do colega e tirava o lead da
    # lista de "aguardando primeira ligação" dele.
    perm.exigir_dono_lead(db, ator, lead)
    # O sinal de "não perturbe" vinha da Assertiva, era guardado e nunca
    # consultado — dava para registrar ligação para quem pediu para não ser
    # incomodado.
    if lead and lead.do_not_call:
        raise HTTPException(403, "Lead marcado como 'não perturbe'. "
                                 "Remova a marca no cadastro do lead.")
    status = payload.get("status", "NOT_PERFORMED")
    c = Call(user_id=user_id, lead_id=payload.get("leadId"),
             origin_phone=payload.get("originPhone", ""),
             receiver_phone=payload.get("receiverPhone") or (lead.phone if lead else ""),
             receiver_type=payload.get("receiverType", "MOBILE"),
             status=status,
             output=payload.get("output", "") if status == "CONNECTED" else "",
             duration=int(payload.get("duration") or 0),
             important=bool(payload.get("important")))
    c.price = round(c.duration / 60 * _preco_minuto(db), 4)
    db.add(c)
    db.commit()
    return serial.call(c)


@router.get("/calls/statistics/overview")
def overview(since: str | None = None, until: str | None = None,
             user_id: str | None = None, team_id: str | None = None,
             db: Session = Depends(get_db)):
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    start, end = _range(since, until)
    query = db.query(Call).filter(Call.started_at.between(start, end))
    pessoas = ids_de(user_id)
    if pessoas:
        query = query.filter(Call.user_id.in_(pessoas))
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        query = query.filter(Call.user_id.in_(do_time))
    calls = query.all()
    connected = [c for c in calls if c.status == "CONNECTED"]
    by_hour = defaultdict(lambda: [0, 0])
    for c in calls:
        by_hour[c.started_at.hour][0] += 1
        if c.status == "CONNECTED":
            by_hour[c.started_at.hour][1] += 1
    best_hour, best_pct = None, 0
    for hour, (total, ok) in by_hour.items():
        if total >= 5:
            pct = round(ok / total * 100)
            if pct > best_pct:
                best_hour, best_pct = hour, pct
    duration = sum(c.duration for c in connected)
    days = max(1, (end - start).days)
    reps = max(1, len({c.user_id for c in calls}))
    outputs = Counter(c.output for c in connected if c.output)
    return {"data": [{
        "startDate": serial.iso(start), "endDate": serial.iso(end),
        "totalCalls": len(calls), "totalConnected": len(connected),
        "totalMobile": sum(1 for c in calls if c.receiver_type == "MOBILE"),
        "totalLandline": sum(1 for c in calls if c.receiver_type == "LANDLINE"),
        "totalDurationInSeconds": duration,
        "averageDuration": round(duration / len(connected)) if connected else 0,
        "averageDailyCallsPerRep": round(len(calls) / days / reps, 1),
        "bestHourToCall": ({"bestStartHour": best_hour, "bestEndHour": best_hour + 1,
                            "connectedPercentage": best_pct} if best_hour is not None else None),
        "byHour": [{"hour": h, "total": t, "connected": ok}
                   for h, (t, ok) in sorted(by_hour.items())],
        "statuses": [
            {"status": "CONNECTED", "count": len(connected),
             "outputs": [{"output": k, "count": v} for k, v in outputs.items()]},
            {"status": "NOT_PERFORMED", "count": len(calls) - len(connected), "outputs": []},
        ],
        "meaningfulRate": round(outputs.get("MEANINGFUL", 0) / len(calls) * 100, 1) if calls else 0,
    }], "additionalInfo": {}}


@router.get("/calls/statistics/dropped")
def dropped(since: str | None = None, until: str | None = None,
            team_id: str | None = None, db: Session = Depends(get_db)):
    """Relatório de ligações derrubadas: conectadas e encerradas em até 10s."""
    ator = perm.ator(db)
    start, end = _range(since, until)
    q = db.query(Call).filter(Call.started_at.between(start, end),
                              Call.status == "CONNECTED", Call.duration <= 10)
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    # SDR vê só as próprias: a lista traz telefone e nome do lead de cada uma.
    if not ator.pelo_menos("gestor"):
        q = q.filter(Call.user_id == (ator.user_id or -1))
    rows = q.order_by(Call.started_at.desc()).all()
    return {"data": [serial.call(c) for c in rows], "meta": {"total": len(rows)}}


@router.get("/calls/statements")
def statement(since: str | None = None, until: str | None = None,
              team_id: str | None = None, db: Session = Depends(get_db)):
    ator = perm.ator(db)
    start, end = _range(since, until)
    q = (db.query(Call.user_id, func.count(Call.id), func.sum(Call.duration))
         .filter(Call.started_at.between(start, end)))
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    # SDR vê o próprio extrato; minutos e custo dos colegas são assunto de gestor.
    if not ator.pelo_menos("gestor"):
        q = q.filter(Call.user_id == (ator.user_id or -1))
    preco = _preco_minuto(db)
    rows = q.group_by(Call.user_id).all()
    users = {u.id: u for u in db.query(User).all()}
    data, total_min, total_cost = [], 0, 0.0
    for uid, count, seconds in rows:
        minutes = round((seconds or 0) / 60, 1)
        cost = round(minutes * preco, 2)
        total_min += minutes
        total_cost += cost
        data.append({"user": serial.user_min(users.get(uid)), "calls": count,
                     "minutes": minutes, "cost": cost})
    return {"data": data, "meta": {"totalMinutes": round(total_min, 1),
                                   "totalCost": round(total_cost, 2),
                                   "pricePerMinute": preco,
                                   "startDate": serial.iso(start), "endDate": serial.iso(end)}}
