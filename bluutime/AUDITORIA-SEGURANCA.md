# Auditoria de segurança e de papéis: Bluutime, CapiBLU e servidor (25/09/2026)

Três frentes: matriz de papéis e permissões rota a rota, segurança da informação
(código e servidor, este só com comandos de leitura), e o CapiBLU usado de dentro do
Bluutime. Cada achado foi conferido no código antes da correção. Testes sobre cópias
dos bancos: 13 + 16 + 16 casos passando.

## Corrigido

### Crítico

| Achado | Correção |
|---|---|
| **app.capiblu.net:** o proxy copiava os cabeçalhos do navegador e só depois acrescentava `X-User-Role`. O Starlette entrega a chave em minúsculas e o serviço de dados lia a do cliente: qualquer usuário virava admin (config, tokens do Meetime, dossiês, custos, dados de outros grupos) | Cabeçalhos de identidade vindos do cliente são descartados (`app_online/main.py`). **Em produção desde o commit 8b76170.** O mesmo tipo de falha no Bluutime já tinha sido corrigido antes |

### Alto

| Achado | Correção |
|---|---|
| Conversa de WhatsApp sem lead (número desconhecido) aberta a qualquer SDR: lia e respondia pelo número da empresa | Conversa sem lead é de gestor; SDR só assume conversa para si |
| Login sem cadastro de SDR agia sobre todo lead sem dono (`None == None`) | Sem cadastro nada é "seu"; o mesmo em ligações, feedbacks e exclusão em massa |
| Usuário desativado no Bluutime seguia com o mesmo nível | Desativado perde o papel operacional na hora |
| Dossiê e cobertura de decisores furavam a cota diária de consultas pagas | Entraram na lista de rotas pagas |

### Médio

- "Ver leads de outros usuários" liberava também editar, dar ganho, executar, enviar e discar: agora é só **ver**.
- O ranking do Dashboard e as metas mostravam o desempenho de todos ao SDR: ele vê a própria linha.
- `GET /api/webhooks` só exigia login e as URLs costumam levar token: agora exige gestor.
- O sync do Meetime disparado por gestor desfazia papel e desativação feitos pelo admin: agora só define papel de quem está chegando.
- Gestor apagava leads em massa sem limite, enquanto apagar base com leads exige admin: acima de 200, só admin.
- Token de API seguia valendo com o dono desativado ou excluído: agora cai junto.
- SDR assinava a cadência como `diretoria@`: o remetente precisa ser o próprio nome no domínio verificado.
- O celular pessoal do SDR aparecia na lista de usuários: agora só em `/me`.
- **Sessão sem revogação:** trocar senha ou sair agora invalida os tokens em todo aparelho (`users.token_version`), e a sessão tem validade máxima de 7 dias desde o login. Tokens já emitidos continuam valendo até lá, então ninguém é deslogado no deploy.
- **Trava de força bruta por IP nunca ligava:** agora usa o IP real (30 erros por IP ou 8 por e-mail em 15 min), com o dicionário limitado.
- **Sem cabeçalhos de segurança:** o Bluutime agora manda CSP (`script-src 'self'`, `frame-ancestors 'none'`), `nosniff`, `Referrer-Policy`, `X-Frame-Options` e `Permissions-Policy`.
- **Injeção de fórmula em XLSX/CSV:** células que começam com `= + - @` são neutralizadas em todas as exportações dos dois apps.
- **Documentação da API aberta sem login:** no Bluutime ela pede login; no app.capiblu.net e no serviço de dados, o Swagger automático saiu. A `/docs` escrita à mão continua.
- **Token do webhook e CPFs em claro nos logs:** o access log do Bluutime mascara `token=` e CPFs, e a trilha de auditoria também.
- **Trilha de auditoria:** passou a registrar Assertiva, enriquecimento e validação de lead, exportações e administração de usuários e tokens.
- **Upload sem teto:** 20 MB no CSV de leads, 30 MB na planilha do CapiBLU.
- **SSRF residual:** a entrega de webhook revalida o destino (contra DNS rebinding) e não segue redirecionamento; webhooks importados do Meetime passam pela mesma validação.
- **Rastreio de clique:** só redireciona para um link que está exatamente na mensagem.

### Baixo

- `dedup` respeita o escopo do SDR.
- Valores do contrato só para admin; saldo e números da telefonia só para gestor.
- Transferir lead leva as atividades pendentes junto.
- Feedback de oportunidade sem dono é de gestor.
- Iniciar novos leads respeita quem participa da cadência.
- Autoria (`createdById`) vem da sessão.
- Tirar "não perturbe" é de gestor.
- Papel inválido é recusado.
- Rascunho de importação: o criador descarta o próprio.
- Menu alinhado com o backend (Dossiê, Consumo e Contas: admin; Migração: gestor).
- Link de rede social só com `http(s)`.

## A fazer no servidor (não mexi: são configurações de sistema)

1. **Trocar o `EVOLUTION_WEBHOOK_TOKEN`**, que já foi gravado em claro no `/var/log/bluutime.log` antes do mascaramento. Depois, clicar em "Reconfigurar recebimento" em Canais e entregas. Depois do deploy, apagar ou girar o log antigo.
2. **Logs com permissão 644, lidos por `joao`/`pedro`, e sem rotação:**
   ```bash
   chmod 600 /var/log/bluutime.log /var/log/capiblu-app.log /var/log/capiblu-data.log
   ```
   Também falta um logrotate com retenção curta.
3. **Serviços rodando como root:** criar o usuário `capiblu` sem shell, dono de `/opt/capiblu`, e nos units usar `User=capiblu`, `NoNewPrivileges=yes`, `ProtectSystem=strict` e `ReadWritePaths` só onde o app grava.
4. **SSH:** `PasswordAuthentication no` (hoje todas as senhas já estão travadas) e ligar o fail2ban.
5. **Reboot pendente** (há atualização de kernel esperando).
6. **`data.capiblu.net`** está na internet protegido só pelo `PROXY_SECRET`. Colocar Cloudflare Access (service token) ou remover o hostname, se o `/api/v1` do Render não precisar mais dele.
7. **HSTS:** ligar no Cloudflare para os dois hostnames.
8. **Segredo do JWT:** está na tabela `meta` do banco de usuários. Mover para `JWT_SECRET` no `.env` (derruba todas as sessões uma vez).
9. **Versões:** fixar as versões no `requirements.txt` e a imagem do wuzapi (hoje `latest`).

## Fica registrado (não corrigido)

- Rotas GET pagas mudam estado (CSRF por navegação de topo com `SameSite=Lax`). O certo é virar POST, o que mexe no front do CapiBLU inteiro.
- A cota ainda é por request, não por unidade gasta, e a lista de rotas pagas do app.capiblu.net e a do Bluutime deveriam ser uma só, dentro do serviço de dados.
- O login devolve o token no corpo e o front do CapiBLU o guarda em `localStorage`. Com a revogação, um token roubado deixa de valer no "sair", mas o ideal é só cookie.
