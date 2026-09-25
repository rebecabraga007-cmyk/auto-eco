# Auditoria das telas: Bluutime contra o Meetime da reunião de 22/09/2026

Referência: a demonstração do David Schuster (BDR) gravada em 22/09/2026, com as 16
telas levantadas no relatório "Meetime na rotina do BDR". Comparação feita lendo o
`web/app.js` tela a tela e procurando cada rótulo e comportamento que aparece na
gravação.

A paleta continua a da BLU (azul-noite no lugar do verde Meetime), por decisão
anterior registrada no `app.css`. A meta de semelhança aqui é de estrutura, texto e
comportamento, não de cor.

## Placar

| # | Tela da reunião | Situação | Semelhança estimada |
|---|---|---|---|
| 1 | Execução de cadência | Diferente | 45% |
| 2 | Iniciar novos leads (modal) | **Falta** | 0% |
| 3 | Dashboard pessoal | Parcial | 55% |
| 4 | Lista de leads | Correta | 90% |
| 5 | Adicionar lead | Parcial | 60% |
| 6 | Atividade: Pesquisa | Diferente | 35% |
| 7 | Atividade: E-mail | Diferente | 40% |
| 8 | Atividade: Ligação (discador + classificação) | Diferente | 25% |
| 9 | Barra pós-atividade + Atividade extra | **Falta** | 10% |
| 10 | Detalhes do lead | Parcial | 70% |
| 11 | Marcar como ganho (campos obrigatórios + modal) | Diferente | 20% |
| 12 | Marcar como perdido (motivo + reaproveitamento) | Parcial | 45% |
| 13 | Estatísticas › Conversão | Correta | 80% |
| 14 | Estatísticas › Atividades (visão da equipe) | Parcial | 75% |
| 15 | Menu do perfil | Correta | 85% |
| 16 | Login / Relatórios só para gestor | Correta | 85% |

Média ponderada pelo uso diário (as telas 1, 6, 7, 8, 9, 11 e 12 são o dia do BDR):
**cerca de 45%**. As telas de consulta (lista, estatísticas, menus) já estão perto; as
de execução, que são onde o BDR passa o dia, estão longe.

## Tela a tela

### 1 · Execução de cadência — diferente (45%)

Tem: "Meu progresso hoje", objetivo diário, "Leads aguardando primeira ligação",
separação "Atividades das Cadências" / "Atividades Extras", modo execução rápida.

Diferente do Meetime:
- O topo é uma barra com seis selects. No Meetime o topo é a faixa **"Você está
  prospectando X leads e existem Y leads disponíveis para serem iniciados"** com o botão
  verde **Iniciar novos leads** à direita.
- "Meu progresso hoje" no Meetime é o número grande (**43** / 47 atividades) com a barra
  e, à direita, o troféu com "Objetivo diário (200) · Para alcançar seu objetivo diário,
  adicione atividades à lista iniciando novos leads".
- O Meetime tem um bloco **Execução** com a chave **Modo Execução rápida** (toggle) e a
  engrenagem. Aqui é um botão.
- A lista no Meetime é uma **tabela** (Atividade · Cadência · Lead · botão Executar com
  seta), com o título **"ATIVIDADES (4 DE 47)"** e os filtros **Status · Atividade ·
  Cadência · Passo · Lista de importação** mais a busca "Nome, email ou telefone". Aqui
  são cartões com score, cinco botões por linha e KPIs que o Meetime não tem.

### 2 · Iniciar novos leads — falta (0%)

O botão hoje só leva para a lista de leads filtrada por "Esperando início". Falta o modal
inteiro: **Leads a iniciar** (quantidade + "Novas atividades para hoje"), **Preencher**
até o objetivo diário, **seleção de cadências ou listas de importação** (Selecionados /
Disponíveis, Atividades para hoje) e o gráfico **Previsão de atividades futuras** por dia
e tipo. O backend precisa de um endpoint que calcule a previsão e inicie N leads.

### 3 · Dashboard — parcial (55%)

Tem: oportunidades no mês com gráfico contra a meta, ranking, motivos de perda.

Diferente: o Meetime tem filtros no topo (período, cadências, usuários, "Limpar
filtros"); **Ranking** em três cartões (Leads Finalizados · Atividades Realizadas · Taxa
de Conversão, cada um com a linha por vendedor e a média); **Insights** com Motivos de
perda (barras horizontais com %), **Conversão por origem** (barras empilhadas, filtro
"Canais") e **Tempo de resposta**. Aqui o ranking é uma tabela, e "Conversão por origem"
e o título "Insights" não existem. Há blocos a mais ("Para bater a meta", "Resultado
por cliente") que podem ficar, abaixo dos do Meetime.

### 4 · Lista de leads — correta (90%)

Refeita contra a captura real: busca, "Adicionar Filtro", contagem, Exportar, itens por
página, quatro colunas e menu de três pontos. Falta só o filtro no formato do Meetime
("Status atual é igual a…" com "Fixar filtro"), que aqui é uma caixa de selects.

### 5 · Adicionar lead — parcial (60%)

Tem os campos. Falta a estrutura do Meetime: bloco **Configurações de entrada**
(Adicionar como lead inbound · **Início imediato** / **Aguardar início** como rádio ·
Responsável · Cadência), bloco **Informações do lead** com os quatro obrigatórios (e-mail,
empresa, primeiro nome, nome completo) e **"+ Ver mais"** para cargo, site, estado,
cidade, telefones e campos personalizados. O formulário atual mostra tudo de uma vez e
não tem "primeiro nome".

### 6, 7, 8 · Execução de uma atividade — diferente (25% a 40%)

Hoje as três usam o mesmo modal genérico. No Meetime a execução é uma **tela dividida**:
- à esquerda, o **painel do lead** (nome, empresa, cadência, "X de Y atividades
  completadas", abas de dados/histórico/anotações/agenda, histórico com as anotações da
  pesquisa em amarelo);
- no topo, o navegador **"‹ 1 de N ›"**;
- no centro, o conteúdo da atividade:
  - **Pesquisa**: ícone, roteiro, campo Anotações, botão **Marcar como feita**;
  - **E-mail**: editor com Para, Cc/Cco, Assunto, corpo e **Enviar**;
  - **Ligação**: discador "Bina inteligente ativa · Realizar Ligação" com teclado e
    número; tela de chamada (origem, número, encerrar, teclado, mudo, **Salvar
    gravação**, **Bloco de anotações**, "Relatar um problema"); e a classificação em
    **quatro botões grandes** — Significativa · Não significativa · **Cliente ocupado** ·
    Sem contato — com **Refazer chamada** (ligar para novo número) e **Finalizar**.

Aqui a ligação é um select "Resultado da ligação" e um campo de duração. "Cliente
ocupado", "Refazer chamada", o teclado e a tela de chamada não existem.

### 9 · Barra pós-atividade e Atividade extra — falta (10%)

No Meetime, toda atividade concluída mostra a barra inferior **"Atividade completada:
Ligação (lead)"** com **Agendar atividade extra · Ganho · Perdido**. O modal **Adicionar
Atividade Extra** tem data e hora, tipo, "Utilizar instruções de uma atividade" e
anotações. Aqui existe "Adiar" (reagendar a mesma atividade), que é outra coisa; a
atividade extra só pode ser criada pela página do lead.

### 10 · Detalhes do lead — parcial (70%)

Tem página própria, Ganho/Perdido, abas Histórico · Agendar atividade · Registrar reunião
· Dados, e linha do tempo agrupada. Falta: a **barra de passos da cadência** (verde nos
feitos), os contadores **Completado · Aberto(s) · Conversa(s)**, o bloco **Geral**
(status, cadência, responsável) e a **URL pública** do lead.

### 11 · Marcar como ganho — diferente (20%)

Aqui é um "Confirmar" genérico. No Meetime são dois passos: **Campos obrigatórios**
("Cargo da pessoa que marcou", "BDR Responsável") e depois **Marcar como ganho**, com
atividades planejadas, atividades completadas, dias em prospecção e o campo de anotações
onde vai o BANT. Depois do ganho, o lead mostra **Ganho** e o botão **Reabrir**.

### 12 · Marcar como perdido — parcial (45%)

Tem motivo e anotações. Falta a chave **Agendar nova prospecção** com **data de início**
e **cadência** ("uma nova prospecção será iniciada na data e cadência especificadas e
você permanecerá como responsável"). O backend precisa guardar o reagendamento e o
`tick` precisa reiniciar o lead na data.

### 13 · Estatísticas › Conversão — correta (80%)

Menu lateral com as seis seções do Meetime e a pergunta como título. Os números estão em
KPIs no lugar das três roscas (Leads Finalizados · Engajados · Ganhos).

### 14 · Estatísticas › Atividades — parcial (75%)

Tem a linha que expande por usuário com "Progresso por atividade" e "Distribuição dos
leads". Falta o topo no formato do Meetime (leads com atividade no período, perdas e
ganhos com %, e os quatro círculos de percentual concluído por tipo) e o aviso de
descontinuação, que no Bluutime não se aplica e deve ficar de fora.

### 15 e 16 · Menus e login — corretos (85%)

Os menus têm mais itens que o Meetime (CapiBLU, WhatsApp, Integrações), o que é
intencional. "Relatórios" já é só para gestor.

## Ordem de correção

Pelo peso no dia do BDR, e porque as telas dependem umas das outras:

1. **Execução** (tela 1) no layout do Meetime.
2. **Execução de atividade em tela dividida** (6, 7, 8), com o discador e os quatro
   botões de classificação.
3. **Barra pós-atividade + Atividade extra** (9).
4. **Ganho em dois passos** (11) e **Perdido com reaproveitamento** (12), incluindo o
   backend do reagendamento.
5. **Iniciar novos leads** (2), com o endpoint de previsão.
6. **Adicionar lead** no formato do Meetime (5).
7. **Dashboard** com Ranking em cartões e Insights (3).
8. **Detalhes do lead**: barra de passos, contadores, Geral e URL pública (10).
9. Topo das **Estatísticas › Atividades** e roscas da **Conversão** (13, 14).

A Academia (tour guiado) usa os seletores dessas telas; cada correção acima atualiza
também os passos das missões.

## Correções feitas (25/09/2026)

| # | Tela | O que mudou | Semelhança agora (estimada, antes do teste visual) |
|---|---|---|---|
| 1 | Execução | Faixa "Você está prospectando…" com Iniciar novos leads; "Meu progresso hoje" com número grande, barra e troféu; painel Execução com chave Modo Execução rápida e engrenagem; Leads aguardando a primeira ligação recolhível; tabela ATIVIDADES (x DE y) com Status · Atividade · Cadência · Passo · Lista de importação e busca; grupos Extras/Cadências; botão Executar ▾ | 85% |
| 2 | Iniciar novos leads | Modal completo: Preencher até o objetivo, Leads a iniciar com novas atividades de hoje, cadências com Selecionados/Disponíveis e Atividades para hoje, previsão de 5 dias úteis por tipo. Backend: `GET /api/flow/execution/start-preview`, `POST /api/flow/execution/start-leads` | 85% |
| 3 | Dashboard | "Oportunidades em {mês}"; Ranking em três cartões com linha por vendedor e média; Insights com motivos de perda em %, conversão por origem (Canais/Fontes/Campanhas/Listas) e tempo de resposta | 80% |
| 5 | Adicionar lead | Configurações de entrada (inbound, Início imediato / Aguardar início, Responsável, Cadência), quatro obrigatórios, primeiro nome, "+ Ver mais" | 85% |
| 6-8 | Execução de atividade | Tela dividida: painel do lead (Dados, Histórico com anotações em amarelo, Anotações, Próximas), navegador "‹ 1 de N ›" com ⋮, Pesquisa com Marcar como feita, editor de e-mail/WhatsApp com Para/Assunto/corpo editáveis (backend: `GET /api/envio/atividades/{id}/previa` e overrides no envio), discador com teclado e validação de número completo, tela de chamada com cronômetro, Salvar gravação e Bloco de anotações, classificação em 4 botões (incluindo Cliente ocupado → status BUSY), Refazer chamada ▾ e Finalizar | 80% |
| 9 | Barra pós-atividade + extra | Barra "Atividade completada" com Agendar atividade extra · Ganho · Perdido; modal Adicionar Atividade Extra com data/hora, tipo, instruções da biblioteca e anotações | 85% |
| 10 | Detalhes do lead | Barra de passos da cadência, painel Geral (com nova prospecção agendada), painel Dados com link do lead copiável | 80% |
| 11 | Ganho | Dois passos: Campos obrigatórios (campos marcados como obrigatórios no ganho) e Marcar como ganho com atividades planejadas/completadas/dias em prospecção e anotações (somadas às do lead, não substituídas) | 85% |
| 12 | Perdido | Motivo, anotações e Agendar nova prospecção (data + cadência); "Reaproveitamento" liga a chave sozinho. Backend: `lead.reprospect_at` / `reprospect_cadence_id` e reabertura automática no `tick` | 85% |

Pendentes: roscas da Estatísticas › Conversão (13) e o topo da Estatísticas › Atividades (14),
que já tinham boa parte; validação visual de todas as telas acima com login real.
