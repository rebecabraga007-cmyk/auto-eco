"""Carga inicial com os dados reais da operação BLU capturados do Meetime
(conta 9210, agosto/2026). Roda uma vez, quando o banco está vazio.
"""
import random
import secrets
from datetime import date, datetime, timedelta

from .db import Base, SessionLocal, engine
from .models import (Activity, Cadence, CadenceStep, CadenceUser, Call, Client,
                     Company, Conversation, CustomField, Goal, Integration,
                     Lead, LeadActivity, LeadBase, LostReason, Message, Team,
                     User, Webhook)

CLIENTS = [
    ("BLU Sales Group", "blu", "#00a443"),
    ("Frotaí", "frotai", "#2196f3"),
    ("Planning", "planning", "#ff5722"),
    ("V4 Company", "v4", "#5e62ff"),
    ("Trentini Advocacia", "trentini", "#00bcd4"),
]

# nome, foco, prioridade, executando, cliente, descrição
CADENCES = [
    ("RECUPERAÇÃO", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group",
     "Leads de recuperação que entraram em cadência de e-mail marketing e abriram algum e-mail"),
    ("ADV [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group",
     "Cadência de advocacia para conseguir conexão"),
    ("IND [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group",
     "Cadência de indústria para conseguir conexão"),
    ("CNT [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group",
     "Cadência de contabilidade para conseguir conexão"),
    ("LISTA LULEADS [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group",
     "Cadência de logística para conseguir conexão"),
    ("DIVERSOS [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group", ""),
    ("HOSPITALAR [START]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group", ""),
    ("CONNECT [FELIPE]", "OUTBOUND", "VERY_HIGH", True, "BLU Sales Group", ""),
    ("FUP pós reunião", "OTHER", "MEDIUM", True, "BLU Sales Group",
     "Manter contato com leads que já fizeram reunião"),
    ("INDICAÇÕES [START]", "ACTIVE_INBOUND", "HIGH", True, "BLU Sales Group", ""),
    ("LEADS RICARDO", "OUTBOUND", "HIGH", True, "Frotaí", ""),
    ("FROTAÍ [START]", "OTHER", "LOW", False, "Frotaí", ""),
    ("ENERGIA", "OUTBOUND", "LOW", False, "Planning", ""),
    ("IMOB", "OUTBOUND", "VERY_HIGH", False, "Planning", ""),
    ("TRANSPORT", "OUTBOUND", "LOW", False, "Planning", ""),
    ("TELECOM", "OUTBOUND", "LOW", False, "Planning", ""),
    ("HOTELARIA", "OUTBOUND", "LOW", False, "Planning", ""),
    ("DISTRIBUIDORA / AUTOMOTIVO", "OUTBOUND", "LOW", False, "Planning", ""),
    ("CARTEIRA", "OTHER", "LOW", False, "Planning", ""),
    ("ESTRUTURAÇÃO", "ACTIVE_INBOUND", "VERY_HIGH", False, "V4 Company", ""),
]

LOST_REASONS = [
    "Não consegui contato", "Fim de cadência", "Reaproveitamento ruim",
    "Lead rejeitou a prospecção", "Lead sem estrutura", "Bloqueou",
    "REAPROVEITAMENTO", "LGPD OPT-OUT (não entrar em contato e nem recuperar)",
    "Lead duplicado", "Empresa pertence a um grupo",
    "Ponte/Carteira - entrar em contato no futuro", "Lead fora do ICP",
    "Lead inválido", "Não conseguimos atender",
]

CUSTOM_FIELDS = [
    ("CNPJ", "cnpj", 0), ("Razão social", "razaoSocial", 1),
    ("Cliente", "cliente", 2), ("Origem CapiBLU", "origemCapiblu", 3),
    ("Nível de decisão", "nivelDecisao", 4), ("Telefone validado", "telefoneValidado", 5),
]

# Modelo de cadência: (dia, tipo, rede, nome, instrução)
STEP_TEMPLATE = [
    (1, "SEARCH", "", "Dia 1.1 — Pesquisa", "Confirmar decisor, porte e dor provável antes do primeiro toque."),
    (1, "CALL", "", "Dia 1.2 — Ligação 1", "Primeira tentativa de conexão. Se não atender, WhatsApp no mesmo dia."),
    (1, "SOCIAL_POINT", "WHATSAPP", "Dia 1.3 — WhatsApp 1",
     "Olá {{firstName}}! Aqui é da BLU. Vi que a {{company}} atua na região — tem 2 minutos?"),
    (3, "CALL", "", "Dia 3.1 — Ligação 2", "Segunda tentativa, em janela de horário diferente da primeira."),
    (3, "E_MAIL", "", "Dia 3.2 — E-mail 1", ""),
    (5, "SOCIAL_POINT", "WHATSAPP", "Dia 5.1 — WhatsApp 2",
     "{{firstName}}, seguindo nosso contato: prefere que eu ligue de manhã ou no fim da tarde?"),
    (8, "CALL", "", "Dia 8.1 — Ligação 3", "Última tentativa antes da quebra."),
    (10, "E_MAIL", "", "Dia 10.1 — E-mail de quebra", ""),
]

COMPANIES = [
    ("SAMPEL INDUSTRIA E COMERCIO DE PECAS AUTOMOTIVAS LTDA", "Paloma Queiroz", "Diretora"),
    ("MOTOMAN EQUIPAMENTOS LTDA", "Ricardo Silveira", "Sócio-Administrador"),
    ("SEPAC SERRADOS E PASTA DE CELULOSE LTDA", "Rodrigo Wawruk Viana", "Gerente Industrial"),
    ("CONCRELAGOS CONCRETO S/A", "Flavio Santana", "Diretor Comercial"),
    ("RD DISTRIBUIDORA E FOOD SERVICE LTDA", "Valdecir Nunes Pereira", "Sócio"),
    ("DISTRIBUIDORA DE BEBIDAS VIRGINIA LTDA", "Waldemar Buosi Filho", "Proprietário"),
    ("PICORELLI TRANSPORTES LTDA", "Fernanda Cecília", "Gerente Administrativa"),
    ("POTENZA FACILITIES LTDA", "Maria do Carmo Dornellas", "Sócia"),
    ("PACK ON EMBALAGENS LTDA", "Renan Petrin", "Diretor"),
    ("VOGES & BARBACOVI ADVOGADOS ASSOCIADOS", "Jose Inacio Barbacovi", "Sócio"),
    ("TICIAN ADVOCACIA", "Daniel Tician", "Sócio-Administrador"),
    ("WOIDA, MAGNAGO, SKREBSKY & COLLA ADVOGADOS", "Leonidas Colla", "Sócio"),
    ("HICKMANN ADVOGADOS ASSOCIADOS", "Samuel Hickmann", "Sócio"),
    ("BLUEFIT FRANQUIAS LTDA", "Adriano Venturini", "Diretor de Expansão"),
    ("ZETA ENERGIA SOLAR LTDA", "Vagner Nacin", "Sócio"),
    ("TECNOFRIO REFRIGERACAO INDUSTRIAL LTDA", "Roberto Carlos Gomes", "Gerente de Compras"),
    ("LOGISTICA SUL TRANSPORTES EIRELI", "Fabiano Gueireza", "Proprietário"),
    ("METALURGICA SANTA RITA LTDA", "Fabio Santana", "Diretor Industrial"),
    ("AGROPECUARIA VALE VERDE S/A", "Célio Coutinho da Cunha", "Sócio-Administrador"),
    ("CLINICA SAO LUCAS SERVICOS MEDICOS LTDA", "Juliana Prado", "Diretora Clínica"),
    ("CONSTRUTORA HORIZONTE NORTE LTDA", "Marcelo Andrade", "Diretor de Obras"),
    ("SUPERMERCADOS BOM PRECO LTDA", "Patricia Nunes", "Gerente Geral"),
    ("TRANSPORTADORA RAPIDO OESTE LTDA", "Anderson Luiz Ferreira", "Sócio"),
    ("INDUSTRIA DE ALIMENTOS SABOR MINEIRO LTDA", "Cristiane Melo", "Diretora Comercial"),
    ("CONTABILIDADE PRECISA LTDA", "Eduardo Ramos", "Sócio-Contador"),
]

STATE_CITY = [("PR", "Curitiba"), ("SC", "Joinville"), ("SP", "São Paulo"),
              ("MG", "Belo Horizonte"), ("RS", "Porto Alegre"), ("MG", "Governador Valadares")]


def _digits(rng, n):
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def seed_if_empty() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(Company).first():
            return
        rng = random.Random(9210)
        today = datetime.utcnow()

        db.add(Company(id=9210, name="BLU Sales Group", phone="41999999999",
                       site="http://blusalesgroup.com.br",
                       modules="FLOW,DIALER,WHATSAPP",
                       add_ons="CALLER_ID_NUMBERS,PREDICTIVE_DIALER",
                       monthly_value=1789.98))

        clients = {}
        for name, slug, color in CLIENTS:
            c = Client(name=name, slug=slug, color=color)
            db.add(c)
            clients[name] = c
        db.flush()

        team = Team(name="BLU")
        db.add(team)
        db.flush()

        users = [
            User(name="ADM BLU", email="luiz@blusalesgroup.com.br",
                 roles="ADMINISTRATOR,MANAGER,SDR,SALESMAN", team_id=team.id, daily_goal=170),
            User(name="Felipe Oliveira", email="j.felipe.oliveira088@gmail.com",
                 roles="SDR,SALESMAN", team_id=team.id, daily_goal=200, online=True),
            User(name="Rebeca", email="rebeca@blusalesgroup.com.br",
                 roles="ADMINISTRATOR,MANAGER", team_id=team.id, daily_goal=170),
        ]
        db.add_all(users)
        db.flush()
        sdr = users[1]

        for name in LOST_REASONS:
            db.add(LostReason(name=name))
        for name, ident, idx in CUSTOM_FIELDS:
            db.add(CustomField(name=name, identifier=ident, index=idx))
        db.flush()

        for cad_name, focus, prio, executing, client_name, desc in CADENCES:
            cad = Cadence(name=cad_name, focus=focus, priority=prio, executing=executing,
                          description=desc, client_id=clients[client_name].id)
            db.add(cad)
            db.flush()
            for day, atype, social, step_name, instruction in STEP_TEMPLATE:
                act = Activity(name=f"[{cad_name}] {step_name}", type=atype,
                               social_network=social, instruction=instruction,
                               client_id=cad.client_id)
                if atype == "E_MAIL":
                    act.email_subject = "Contato {{company}}"
                    act.email_html = ("<p>Olá {{firstName}}, tudo bem?</p><p>Sou da BLU Sales Group "
                                      "e trabalhamos com prospecção para o setor da {{company}}.</p>")
                db.add(act)
                db.flush()
                db.add(CadenceStep(cadence_id=cad.id, activity_id=act.id, day=day,
                                   order_in_day=len([s for s in STEP_TEMPLATE if s[0] == day])))
            if executing:
                db.add(CadenceUser(cadence_id=cad.id, user_id=sdr.id, daily_goal=200))
        db.flush()

        active_cadences = db.query(Cadence).filter_by(executing=True).all()
        bases = []
        for i, label in enumerate(["[Lista Luleads]", "[ADV 72]", "[CNT 34]", "[IND 63]",
                                   "[TECHS_DIV 10]", "[leads lista 12]"]):
            lb = LeadBase(name=f"{label} - [AGO 26]", source="CSV" if i % 2 else "CAPIBLU",
                          client_id=clients["BLU Sales Group"].id, created_by_id=users[0].id,
                          created_at=today - timedelta(days=40 - i * 5))
            if lb.source == "CAPIBLU":
                lb.source_query = ('{"uf":"PR","porte":"05","capital_min":1000000,'
                                   '"cnae":"4930202","com_telefone":true}')
            db.add(lb)
            bases.append(lb)
        db.flush()

        statuses = (["EXECUTING"] * 9 + ["WAITING"] * 6 + ["WON"] * 2 +
                    ["LOST"] * 5 + ["ON_EXTRA_ACTIVITY"] * 1 + ["PAUSED_FROM_EXECUTING"] * 1)
        reasons = db.query(LostReason).all()
        leads = []
        for i, (company, person, position) in enumerate(COMPANIES):
            cad = active_cadences[i % len(active_cadences)]
            uf, city = STATE_CITY[i % len(STATE_CITY)]
            status = statuses[i % len(statuses)]
            first = person.split()[0]
            lead = Lead(
                name=person, first_name=first, company=company, position=position,
                email=f"{first.lower()}@{company.split()[0].lower()}.com.br",
                phone=f"+55{rng.choice([41, 47, 11, 31, 51])}9{_digits(rng, 8)}",
                site=f"http://www.{company.split()[0].lower()}.com.br",
                state=uf, city=city, cnpj=_digits(rng, 14), razao_social=company,
                status=status, cadence_id=cad.id, sdr_id=sdr.id,
                lead_base_id=bases[i % len(bases)].id, client_id=cad.client_id,
                current_step=rng.randint(0, 5), best_hour=rng.choice([9, 10, 14, 17, 18, 18, 18]),
                created_at=today - timedelta(days=rng.randint(1, 45)),
            )
            if status == "WON":
                lead.won_at = today - timedelta(days=rng.randint(0, 15))
            if status == "LOST":
                lead.lost_at = today - timedelta(days=rng.randint(0, 15))
                lead.lost_reason_id = rng.choice(reasons).id
            db.add(lead)
            leads.append(lead)
        db.flush()

        for lb in bases:
            lb.number_of_leads = sum(1 for l in leads if l.lead_base_id == lb.id)

        # Fila: cada lead ativo ganha atividades pendentes e um histórico.
        for lead in leads:
            steps = lead.cadence.steps if lead.cadence else []
            if not steps:
                continue
            for idx, step in enumerate(steps[:6]):
                done = idx < lead.current_step
                overdue_days = rng.choice([0, 0, 0, 1, 2, 4])
                sched = today - timedelta(days=overdue_days, hours=rng.randint(0, 8)) \
                    if (done or overdue_days) else today + timedelta(hours=rng.randint(0, 30))
                la = LeadActivity(
                    lead_id=lead.id, activity_id=step.activity_id, cadence_step_id=step.id,
                    user_id=lead.sdr_id, type=step.activity.type,
                    social_network=step.activity.social_network,
                    status="DONE" if done else ("SKIPPED" if rng.random() < 0.08 else "PENDING"),
                    scheduled_at=sched,
                )
                if la.status in ("DONE", "SKIPPED"):
                    la.done_at = sched + timedelta(minutes=rng.randint(1, 240))
                if lead.status in ("WON", "LOST") and la.status == "PENDING":
                    la.status = "SKIPPED"
                    la.done_at = sched
                db.add(la)
        db.flush()

        # Ligações — proporções reais de agosto/26: 170 ligações, 11% significativas.
        outputs = ["NO_CONTACT"] * 113 + ["NOT_MEANINGFUL"] * 3 + ["MEANINGFUL"] * 19
        for i in range(170):
            lead = rng.choice(leads)
            connected = i < 145
            started = today - timedelta(days=rng.randint(0, 19),
                                        hours=rng.randint(0, 11), minutes=rng.randint(0, 59))
            db.add(Call(
                user_id=sdr.id, lead_id=lead.id, origin_phone="+5547976020161",
                receiver_phone=lead.phone,
                receiver_type="MOBILE" if rng.random() > 0.05 else "LANDLINE",
                status="CONNECTED" if connected else "NOT_PERFORMED",
                output=rng.choice(outputs) if connected else "",
                duration=rng.randint(3, 620) if connected else 0,
                started_at=started.replace(hour=rng.choice([9, 10, 11, 14, 15, 16, 17, 18, 18, 18])),
            ))

        month = date(today.year, today.month, 1)
        db.add(Goal(user_id=sdr.id, target_month=month, opportunities_goal=25,
                    conversion_rate_goal=0.15))
        db.add(Goal(user_id=users[0].id, target_month=month, opportunities_goal=10,
                    conversion_rate_goal=0.12))

        # Segredo sorteado a cada carga: o do webhook real da conta não entra no
        # repositório.
        db.add(Webhook(events="LEAD.WON", target_url="https://exemplo.crm/callback/bdd5712",
                       secret=secrets.token_urlsafe(15), enabled=True))
        for key, name, kind, connected in [
            ("pipedrive", "Pipedrive", "CRM", True), ("salesforce", "Salesforce", "CRM", False),
            ("rdstation", "RD Station", "Marketing/CRM", True),
            ("hubspot", "HubSpot", "CRM", False), ("ploomes", "Ploomes", "CRM", True),
            ("gcalendar", "Google Agenda", "Calendário", True),
            ("emailbox", "Caixa de e-mail", "E-mail", True),
            ("capiblu", "CapiBLU", "Dados e enriquecimento", True),
            ("evolution", "Evolution API", "WhatsApp", True),
        ]:
            db.add(Integration(key=key, name=name, kind=kind, connected=connected,
                               last_sync=today - timedelta(hours=rng.randint(1, 30)) if connected else None))

        for lead in leads[:6]:
            conv = Conversation(lead_id=lead.id, phone=lead.phone, title=lead.name,
                                last_message_at=today - timedelta(hours=rng.randint(1, 60)))
            db.add(conv)
            db.flush()
            db.add(Message(conversation_id=conv.id, direction="OUT",
                           body=f"Olá {lead.first_name}! Aqui é da BLU Sales Group. "
                                f"Vi que a {lead.company} atua na região — tem 2 minutos?",
                           sent_at=conv.last_message_at - timedelta(minutes=30)))
            if rng.random() > 0.4:
                db.add(Message(conversation_id=conv.id, direction="IN",
                               body="Oi, pode me mandar por e-mail que eu olho hoje à tarde.",
                               sent_at=conv.last_message_at))

        db.commit()
    finally:
        db.close()
