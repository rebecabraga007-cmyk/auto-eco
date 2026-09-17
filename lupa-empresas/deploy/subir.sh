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
[ "${1:-}" = "--so-conferir" ] && SO_CONFERIR=1

sr() { ssh -i "$CHAVE" -o BatchMode=yes "$HOST" "$@"; }

BACKEND="backend/main.py backend/mkbuscas.py backend/correio.py
         backend/enrich_jobs.py backend/enriquecimentos.py backend/enrich_layout.py"
ONLINE="app_online/main.py"
FRONT="frontend/index.html frontend/capiblux.js frontend/capiblux.css frontend/authx.js"
DOCS="deploy/EMAIL.md deploy/cloudflare_email_dns.py deploy/conferir_email_dns.py deploy/subir.sh"

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
sr "cd $REMOTO && for f in backend/main.py backend/correio.py backend/enrich_jobs.py \
      backend/enriquecimentos.py backend/enrich_layout.py backend/mkbuscas.py app_online/main.py; do
      /opt/capiblu/venv/bin/python -m py_compile \$f || { echo \"QUEBRADO: \$f\"; exit 1; }
    done; echo 'todos compilam'" || {
  echo "Sintaxe quebrada. NAO reiniciei nada -- o sistema continua no ar com a versao velha."
  exit 1
}

echo
echo "== reiniciando =="
sr "systemctl restart capiblu-data && sleep 4 && systemctl restart capiblu-app && sleep 3"

# A PROVA E A APLICACAO RESPONDER, nao o systemd dizer que iniciou.
echo
echo "== conferindo de dentro do servidor =="
OK=$(sr "curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8011/api/enrich/catalog")
echo "  /api/enrich/catalog -> HTTP $OK"

if [ "$OK" != "200" ]; then
  echo
  echo "NAO SUBIU. Voltando para a versao anterior..."
  sr "cd $REMOTO && tar xzf $DEST/antes.tar.gz && systemctl restart capiblu-data && sleep 4 && systemctl restart capiblu-app"
  echo "voltou. Ultimas linhas do log:"
  sr "tail -25 /var/log/capiblu-data.log"
  exit 1
fi

echo "  jobs      -> HTTP $(sr "curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'X-User-Email: deploy@blusalesgroup.com.br' http://127.0.0.1:8011/api/enrich/jobs")"
echo "  e-mail    -> $(sr "curl -s --max-time 10 -H 'X-User-Email: deploy@blusalesgroup.com.br' -H 'X-User-Role: admin' http://127.0.0.1:8011/api/admin/email/status")"
echo
echo "NO AR. Backup em $DEST (para voltar: tar xzf $DEST/antes.tar.gz dentro de $REMOTO)."
