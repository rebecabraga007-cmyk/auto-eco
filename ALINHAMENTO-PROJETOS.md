# Alinhamento de Projetos — Blu Sales Group

> Documento de alinhamento gerado a partir da reunião entre **João Gonçalves** (demandante) e **Rebeca Sampaio** (desenvolvimento).
> Objetivo: consolidar o escopo, as tecnologias, as metodologias e os fluxos de cada projeto, e definir a fila de execução.

**Data da reunião:** referência registrada em 30/06/2026
**Participantes:** João Gonçalves, Rebeca Sampaio

---

## Visão geral e priorização

| # | Projeto | Cliente / Dono | Tipo | Prioridade | Responsável pela entrega |
|---|---------|----------------|------|------------|--------------------------|
| 1 | **Vânia** — Centralizador de WhatsApp | Movida (Inbound) — demanda da Vânia | Produto Blu / extensão do Dashboard | 🔴 Top 1 — começar agora | Rebeca (dev) |
| 2 | **Capiblu** — Enriquecedor de leads próprio | Blu (produto proprietário) | Produto Blu — substitui Datastone | 🟠 Em paralelo, logo após APIs | João (consegue APIs) → Rebeca (front/integração) |
| 3 | **Eproc** — Prospecção de empresas processadas | Escritório de advocacia (redução de dívida) | Geração de leads (inbound diário) | 🟡 Depois do Capiblu | Rebeca (dev) — João valida regra |
| 4 | **Pedreira** — Telemetria de mineração | João (projeto pessoal, fora da Blu) | IoT + Dashboard | ⚪ Fim da fila | Rebeca (pago à parte) |

**Sequência acordada:** João dedica a semana entrante a fechar as APIs (Serasa, Claro, Vivo etc.) para o Capiblu. Em paralelo, Rebeca inicia o projeto Vânia (WhatsApp), que é o de maior prioridade imediata. Eproc entra na sequência após o Capiblu. Pedreira fica para o fim da fila.

---

## Projeto 1 — Vânia (Centralizador de WhatsApp da Movida)

### Objetivo
Centralizar e ler os WhatsApps dos executivos de venda da Movida (inbound) para extrair **métricas de atendimento** que hoje não existem, porque o CRM (Meetime) não é atualizado em tempo real e toda a conversa com o lead acontece dentro do WhatsApp.

### Contexto de negócio (fluxo atual da Movida)
1. SDR recebe lead de inbound dentro do Meetime e qualifica.
2. SDR repassa o lead a um executivo (vendedor) e o avisa **pelo WhatsApp**.
3. O executivo contata o lead **pelo WhatsApp** para vender (ex.: aluguel de frota).
4. Hoje não há visibilidade sobre o que acontece a partir daí.

### Métricas a extrair (via LLM lendo as conversas)
- **Tempo de resposta do SDR → executivo:** intervalo entre o SDR repassar o lead e o executivo efetivamente chamar o lead.
- **Conteúdo e desfecho da conversa:** objeções do lead (ex.: "achei caro", "a Localiza é mais barata"), adiamentos ("só ano que vem"), motivo da não contratação.
- **Falha de follow-up:** identificar quando o executivo não deu sequência (não mandou mensagem quando deveria).
- **Volume por executivo:** quantos leads cada executivo recebeu por semana e tempo médio de resposta.

### Escopo (o que é e o que NÃO é)
- ✅ **Apenas leitura** das conversas — ver o que está acontecendo e coletar métricas.
- ❌ **Não** envia nem responde mensagens (não é um CRM operacional tipo CRM Como).
- ✅ Interface de **conexão** por QR Code (igual WhatsApp Web) para o executivo reconectar quando a sessão cair.
- ✅ Acesso de **administrador** para a gestora abrir e visualizar a conversa de qualquer executivo.
- ✅ As informações alimentam um **dashboard / e-mail / relatório**.

### Tecnologias
- **Linguagem:** Python.
- **Conexão WhatsApp:** biblioteca de integração via WhatsApp Web protocol (QR Code), mesma lógica usada por CRMs que plugam o WhatsApp.
- **LLM:** **API da Anthropic (Claude)** — chave própria da Blu — para ler e interpretar as conversas (decisão: usar Claude em vez de Mistral neste caso).
- **Entrega de dados:** integração com o **Dashboard** existente (ver abaixo).

### Metodologia / fluxo de implementação
```
Executivo conecta WhatsApp via QR Code (interface de conexão)
        ↓
Sincronização das conversas (somente leitura)
        ↓
LLM (Claude) lê cada conversa e extrai:
  • tempo de resposta  • objeções  • desfecho  • follow-up pendente
        ↓
Métricas estruturadas
        ↓
Painel admin (gestora vê qualquer executivo)  +  Dashboard / e-mail
```

### Integração com o Dashboard
O WhatsApp será tratado como **mais um canal/API** do dashboard existente (que já consome Meetime, Zenvia e planilha). É o "passo 2" do dashboard: Rebeca constrói o projeto separadamente e depois conecta as informações como uma API adicional, exportável no "modo Movida".

### Pontos de atenção
- **Estabilidade da sessão:** prever reconexão fácil (QR Code) — a sessão pode cair com frequência ("vai quebrar o processo várias vezes").
- **Privacidade / LGPD:** monitoramento de comunicação de colaboradores e de dados de leads exige base legal e transparência. Recomenda-se validar política interna e consentimento antes do go-live.
- **Nome do projeto:** **Vânia** (homenagem à responsável que solicitou).

---

## Projeto 2 — Capiblu (Enriquecedor de leads proprietário)

### Objetivo
Construir um enriquecedor de leads **próprio da Blu** para deixar de depender da Datastone. A ideia é integrar diretamente as fontes (Serasa, telefonias) e oferecer uma interface com **chat** onde o usuário pede leads em linguagem natural.

### Escopo
- Enriquecimento a partir de fontes próprias contratadas: **Serasa**, **Claro**, **Vivo**, e outras telefonias/bureaus a negociar.
- **Interface com chat** (estilo Claude/assistente): o usuário pede, por exemplo, *"quero 50 leads de contabilidade"* e o sistema retorna.
- Base visual: aproveitar a **interface já clonada da Datastone** ("Testone"), **adicionando** a camada de chat que ela não tem.

### Tecnologias
- **APIs de dados:** Serasa, Claro, Vivo, demais bureaus (a serem negociadas e contratadas por João).
- **Front-end:** reaproveitar o clone da interface da Datastone + módulo de chat (interpretação de pedido em linguagem natural → consulta às APIs).
- **Back-end:** orquestração das chamadas às APIs de enriquecimento.

### Metodologia / fluxo
```
[Fase João — semana entrante]
Negociar e contratar as APIs (Serasa, Claro, Vivo, ...)
        ↓
Entregar credenciais/contratos das APIs à Rebeca
        ↓
[Fase Rebeca]
Montar o back-end de orquestração das APIs
        ↓
Construir o chat sobre a interface clonada (Testone)
        ↓
Usuário pede em linguagem natural → sistema enriquece e retorna leads
```

### Pré-requisito / bloqueio
- ⛔ **Depende das APIs.** Rebeca só inicia o desenvolvimento quando João entregar as APIs negociadas. João assumiu esse compromisso para a semana entrante.

### Pontos de atenção
- **Não usar a API da Datastone** — o objetivo é justamente substituí-la por fontes próprias.
- *(Observação de viabilidade/compliance: a coleta de "sinais"/engenharia reversa de APIs de terceiros mencionada na reunião é juridicamente sensível. Recomenda-se priorizar a contratação oficial das APIs, que é o caminho já acordado para o Capiblu.)*
- **Nome do projeto:** **Capiblu**.

---

## Projeto 3 — Eproc (Prospecção de empresas processadas)

### Objetivo
Gerar leads para um **escritório de advocacia** que vende serviço de **redução/defesa de dívida**. O escritório atende **empresas que estão sendo processadas por bancos**. A ideia é extrair, de fontes públicas, o **CNPJ das empresas que estão sendo processadas** para prospectá-las.

### Contexto de negócio
- Quando um banco entra com ação de cobrança contra uma empresa, **a informação é pública** (Tribunal de Justiça / sistema **Eproc**).
- O escritório quer chegar nessas empresas — muitas vezes a empresa sabe da dívida, mas **não sabe que ela já foi judicializada** → **timing é o diferencial**.
- O cliente do escritório é a **empresa processada** (não o banco). O objetivo é prospectá-la para ajudá-la a se defender.

### Escopo
- Extrair **diariamente** a lista de empresas processadas (comporta-se como **inbound contínuo** — todo dia há novas ações).
- Capturar o **CNPJ da empresa processada** (não é necessário lead 100% enriquecido nessa etapa).
- O **enriquecimento** posterior pode usar a Datastone (sem problema nesse projeto), ou o próprio Capiblu quando pronto.

### Tecnologias
- **Fonte:** **Eproc** (sistema de processos eletrônicos / dados públicos do Tribunal de Justiça).
- **Automação:** sistema de **busca/raspagem agendada** que roda sozinho todos os dias.
- **Enriquecimento:** Datastone (ou Capiblu).

### Metodologia / fluxo
```
[Diariamente — automático]
Consultar o Eproc por novas ações de bancos contra empresas
        ↓
Extrair o CNPJ da empresa processada (parte ré)
        ↓
Montar lista de leads do dia
        ↓
Enriquecer (Datastone / Capiblu)
        ↓
Entregar ao escritório de advocacia para prospecção
```

### Pesquisa pendente (a fazer antes de desenvolver)
- ❓ **Verificar se o Eproc exige acesso/credenciais de advogado (OAB)** para consultar os processos. Rebeca pesquisa a viabilidade de acesso.

### Pontos de atenção
- Sem material escrito do cliente — escopo levantado em reunião/ligação. Validar regra de negócio com João conforme o desenvolvimento avança.
- **Confirmar a grafia/sistema correto:** "Eproc" (e-Proc).
- Atenção a termos de uso e limites de consulta de dados judiciais públicos.

---

## Projeto 4 — Pedreira (Telemetria de mineração) — *fora da Blu*

### Objetivo
Dar visibilidade de **estoque e produção** das pedreiras/mineradoras de João (12 unidades). Hoje o controle é **manual** — uma pessoa percorre as pedreiras e anota tudo num caderno.

### Contexto de negócio
- A rocha é explodida, britada e separada por granularidade (rachão, brita, pó de brita, concreto).
- Falta visibilidade de: **quanto entrou** de pedra, **quanto saiu** (por granularidade/peneira) e **quanto há em estoque**.

### Escopo
- Pesar o material **na entrada** e **na saída**, por peneira/granularidade.
- Enviar os dados para um computador e processá-los em um **dashboard** de entrada × produção × estoque × vendas.

### Tecnologias
- **Hardware:** **balanças de esteira** com sensores.
- **Aquisição de sinal:** módulos tipo **Arduino** para ler as balanças e transmitir os dados.
- **Software:** ingestão dos dados → processamento → dashboard.
- ✅ **Vantagem:** o hardware já existe no mercado — é "montar as peças do quebra-cabeça", não desenvolver hardware do zero.

### Metodologia / fluxo
```
Balança de esteira (sensor) → módulo Arduino
        ↓
Transmissão dos dados de peso (entrada / saída por peneira)
        ↓
Computador / servidor processa
        ↓
Dashboard: entrou X t → britas Y, pó Z, rachão W → estoque + vendido
```

### Pontos de atenção
- **Projeto pessoal de João, fora da Blu** — remuneração à parte.
- Requer **visita presencial** (Itajaí) — passagem/hospedagem custeadas por João.
- João fará visita a uma pedreira na semana seguinte para mapear a montagem.
- **Prioridade:** fim da fila, após o Capiblu.

---

## Resumo de tecnologias por projeto

| Projeto | Linguagem/Stack | Fontes/APIs | LLM | Hardware | Entrega |
|---------|-----------------|-------------|-----|----------|---------|
| **Vânia** | Python | WhatsApp Web (QR Code) | Claude (Anthropic) | — | Dashboard + admin + e-mail |
| **Capiblu** | Front (clone Datastone) + back | Serasa, Claro, Vivo, bureaus | LLM no chat (interpretação) | — | Interface com chat |
| **Eproc** | Python (scraper agendado) | Eproc + Datastone/Capiblu | — | — | Lista diária de CNPJs |
| **Pedreira** | Ingestão + dashboard | — | — | Balança de esteira + Arduino | Dashboard de estoque |

---

## Próximos passos / checklist

**João**
- [ ] Negociar e contratar APIs do Capiblu (Serasa, Claro, Vivo, demais) — *semana entrante*.
- [ ] Entregar credenciais/contratos das APIs à Rebeca quando fechadas.
- [ ] Visitar pedreira para mapear montagem das balanças (projeto Pedreira).
- [ ] Responder dúvidas pontuais (pode enviar perguntas que Rebeca compilar).

**Rebeca**
- [ ] **Iniciar Projeto Vânia (WhatsApp)** — prioridade imediata.
- [ ] Validar biblioteca de conexão WhatsApp (QR Code) e teste de leitura.
- [ ] Definir prompt/estrutura da LLM (Claude) para extrair as métricas.
- [ ] Pesquisar acesso ao **Eproc** (exige OAB?).
- [ ] Planejar integração do canal WhatsApp como nova API do Dashboard.
- [ ] Aguardar APIs para iniciar o **Capiblu**.

---

*Documento de alinhamento interno — Blu Sales Group. Sujeito a revisão conforme validações de negócio e viabilidade técnica.*
