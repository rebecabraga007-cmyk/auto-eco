#!/usr/bin/env bash
# Sobe o CapiBLU para o servidor -- com volta automatica se nao subir.
#
# POR QUE ISTO E UM SCRIPT
# ------------------------
# Porque /opt/capiblu NAO e um checkout git: os arquivos foram copiados na
# mao, sem remote e sem historico. Entao nao existe "git pull" nem "git
# revert" la -- o backup e o unico caminho de volta, e ele so serve se for
# feito ANTES e se alguem souber onde esta.
#
# A parte que este script existe para garantir e a ultima: ele nao confia no
# systemd dizer "started". Um processo Python que morre no import sobe,
# aparece como ativo por um segundo e o `Restart=always` fica reiniciando em
# loop -- e a tela, de fora, fica com 502 sem explicacao. Aqui ele espera,
# bate na aplicacao de verdade, e se ela nao responder DESFAZ sozinho.
#
#   bash deploy/subir.sh              # sobe, confere e volta se quebrar
#   bash deploy/subir.sh --so-conferir # nao copia nada, so diz o que faria
#
# Roda de dentro de lupa-empresas/.
set -u

HOST=${CAPIBLU_HOST:-root@167.233.71.218}
CHAVE=${CAPIBLU_SSH_KEY:-$HOME/.ssh/capiblu_vps}
REMOTO=/opt/capiblu/lupa-empresas
SO_CONFERIR=0
SEM_TESTES=0
for a in "$@"; do
  [ "$a" = "--so-conferir" ] && SO_CONFERIR=1
  [ "$a" = "--sem-testes" ] && SEM_TESTES=1
done
# Olhar o que subiria nao precisa da suite: e leitura, nao deploy. Mas isso
# NAO e "pular os testes" -- a mensagem tem que dizer a verdade sobre qual
# dos dois casos e, senao ela assusta a toa em quem so quis conferir.
[ "$SO_CONFERIR" = "1" ] && SEM_TESTES=1

sr() { ssh -i "$CHAVE" -o BatchMode=yes "$HOST" "$@"; }

# A LISTA NAO E MAIS ESCRITA A MAO. Ela era, e falhou do jeito previsivel:
# criei `memoria_empresa.py`, esqueci de acrescentar aqui, e o deploy subiu um
# `main.py` que importava um modulo inexistente no servidor. O servico morreu
# no import e o rollback devolveu a versao boa -- funcionou, mas o defeito nao
# era o codigo, era a lista.
#
# Lista que alguem precisa lembrar de atualizar e lista que vai ficar
# desatualizada. `git ls-files` sabe quais arquivos sao do projeto.
BACKEND=$(git ls-files 'backend/*.py' | tr '\n' ' ')
ONLINE=$(git ls-files 'app_online/*.py' | tr '\n' ' ')
FRONT=$(git ls-files 'frontend/*.html' 'frontend/*.js' 'frontend/*.css' | tr '\n' ' ')
DOCS="deploy/EMAIL.md deploy/cloudflare_email_dns.py deploy/conferir_email_dns.py deploy/subir.sh"

# ── A SUITE, ANTES DE TUDO ────────────────────────────────────────────
#
# Antes de olhar arquivo, antes de fazer backup: se a suite esta vermelha,
# nao ha o que subir. Roda em ~30s e nao gasta nada -- a rede para fora esta
# bloqueada em testes/base.py.
#
# Sete defeitos apareceram em um unico dia de trabalho, e cinco deles no
# codigo que eu tinha acabado de escrever. O que mudou nao foi eu passar a
# escrever melhor; foi isto aqui existir.
#
# `--sem-testes` existe para a emergencia de precisar subir um conserto com a
# suite quebrada por outro motivo. Usar isso e uma decisao, e por isso ele
# grita.
if [ "$SO_CONFERIR" = "1" ]; then
  :                       # so mostrando o que subiria; nao ha o que testar
elif [ "$SEM_TESTES" = "1" ]; then
  echo "!! SUBINDO SEM RODAR OS TESTES -- voce pediu. Confira na mao depois."
  echo
else
  echo "== suite de testes =="
  python testes/rodar.py || {
    echo
    echo "A SUITE ESTA VERMELHA. Nada foi copiado e nada foi reiniciado."
    echo "Conserte, ou repita com --sem-testes se souber o que esta fazendo."
    exit 1
  }
  echo
fi

echo "== arquivos que vao subir =="
for f in $BACKEND $ONLINE $FRONT $DOCS; do
  [ -f "$f" ] || { echo "FALTA no seu disco: $f"; exit 1; }
  printf '  %-40s %s bytes\n' "$f" "$(wc -c < "$f")"
done

# TRABALHO EM ANDAMENTO? Reiniciar no meio de um job nao perde as linhas ja
# gravadas (elas estao em disco) e a subida retoma de onde parou -- mas quem
# esta olhando a barra ve ela congelar por alguns segundos, e e melhor saber
# disso antes do que ser perguntado depois.
echo
echo "== jobs rodando agora =="
sr "ls /opt/capiblu/lupa-empresas/backend/enrich_jobs.db >/dev/null 2>&1 &&
    sqlite3 /opt/capiblu/lupa-empresas/backend/enrich_jobs.db \
      \"SELECT count(*) FROM enrich_job WHERE status IN ('fila','processando')\" 2>/dev/null ||
    echo '0 (a base de jobs ainda nao existe -- primeira subida)'"

if [ "$SO_CONFERIR" = "1" ]; then
  echo; echo "--so-conferir: nada foi copiado."; exit 0
fi

CARIMBO=$(date +%Y%m%d-%H%M%S)
DEST=/opt/capiblu/backups/deploy-$CARIMBO
echo
echo "== backup em $DEST =="
sr "mkdir -p $DEST && cd $REMOTO && tar czf $DEST/antes.tar.gz \
    backend/main.py backend/mkbuscas.py app_online/main.py frontend/ && ls -lh $DEST/antes.tar.gz | awk '{print \$5}'" || exit 1

echo
echo "== copiando =="
scp -q -i "$CHAVE" -o BatchMode=yes $BACKEND "$HOST:$REMOTO/backend/"    || exit 1
scp -q -i "$CHAVE" -o BatchMode=yes $ONLINE  "$HOST:$REMOTO/app_online/" || exit 1
scp -q -i "$CHAVE" -o BatchMode=yes $FRONT   "$HOST:$REMOTO/frontend/"   || exit 1
scp -q -i "$CHAVE" -o BatchMode=yes $DOCS    "$HOST:$REMOTO/deploy/"     || true
echo "copiado."

# SINTAXE ANTES DE REINICIAR. Um erro de sintaxe so aparece no import, ou
# seja, DEPOIS de o servico velho ja ter morrido. Conferir agora custa dois
# segundos e evita derrubar o sistema por uma virgula.
echo
echo "== sintaxe no servidor =="
# Compila TUDO que subiu, nao uma lista escolhida: o modulo esquecido some
# justamente da lista que alguem manteve a mao.
sr "cd $REMOTO && for f in $BACKEND $ONLINE; do
      /opt/capiblu/venv/bin/python -m py_compile \$f || { echo \"QUEBRADO: \$f\"; exit 1; }
    done; echo 'todos compilam'" || {
  echo "Sintaxe quebrada. NAO reiniciei nada -- o sistema continua no ar com a versao velha."
  exit 1
}

# COMPILAR NAO PEGA MODULO AUSENTE -- foi exatamente o que passou: todos os
# arquivos compilavam, e o `import memoria_empresa` so estourou quando o
# processo subiu. Importar o app aqui, com o sistema ainda no ar, pega isso
# antes de derrubar nada.
echo
echo "== o app IMPORTA? (compilar nao pega modulo faltando) =="
sr "cd $REMOTO/backend && /opt/capiblu/venv/bin/python -c \
    'import main; print(\"importou -- %d rotas\" % len(main.app.routes))'" || {
  echo "O app nao importa. NAO reiniciei -- o sistema segue no ar com a versao velha."
  exit 1
}

echo
echo "== reiniciando =="
sr "systemctl restart capiblu-data && sleep 4 && systemctl restart capiblu-app && sleep 3"

# A PROVA E A APLICACAO RESPONDER, nao o systemd dizer que iniciou.
#
# COM O SEGREDO DE PROXY. O servico de dados recusa qualquer /api sem o
# cabecalho `X-Proxy-Secret` -- ele so aceita chamada vinda do app-online.
# Minha primeira versao nao mandava o segredo, levou 401, concluiu "nao subiu"
# e DESFEZ um deploy que estava perfeito. O log dizia "Application startup
# complete" uma linha antes.
#
# Licao que vale alem deste script: um teste que falha por motivo proprio e
# pior que teste nenhum, porque ele desfaz trabalho bom com ar de prudencia.
echo
echo "== conferindo de dentro do servidor =="
SEGREDO=$(sr "grep -m1 '^PROXY_SECRET=' /opt/capiblu/lupa-empresas/.env | cut -d= -f2-")
OK=$(sr "curl -s -o /dev/null -w '%{http_code}' --max-time 15         -H 'X-Proxy-Secret: $SEGREDO' http://127.0.0.1:8011/api/enrich/catalog")
echo "  /api/enrich/catalog -> HTTP $OK"

# 000 = nao respondeu nada (processo morto ou em loop de restart). Qualquer
# codigo HTTP prova que a aplicacao esta VIVA -- e um 401 ali em cima seria
# problema do meu cabecalho, nao do deploy.
if [ "$OK" != "200" ]; then
  echo
  echo "NAO SUBIU. Voltando para a versao anterior..."
  sr "cd $REMOTO && tar xzf $DEST/antes.tar.gz && systemctl restart capiblu-data && sleep 4 && systemctl restart capiblu-app"
  echo "voltou. Ultimas linhas do log:"
  sr "tail -25 /var/log/capiblu-data.log"
  exit 1
fi

echo "  jobs      -> HTTP $(sr "curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'X-Proxy-Secret: $SEGREDO' -H 'X-User-Email: deploy@blusalesgroup.com.br' http://127.0.0.1:8011/api/enrich/jobs")"
echo "  e-mail    -> $(sr "curl -s --max-time 10 -H 'X-Proxy-Secret: $SEGREDO' -H 'X-User-Email: deploy@blusalesgroup.com.br' -H 'X-User-Role: admin' http://127.0.0.1:8011/api/admin/email/status")"
APP=$(sr "curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8021/")
echo "  app-online-> HTTP $APP"
echo
echo "NO AR. Backup em $DEST (para voltar: tar xzf $DEST/antes.tar.gz dentro de $REMOTO)."
