#!/usr/bin/env bash
# Sobe a Evolution API do Bluutime.
#
# O `--env-file` aponta para o .env do CapiBLU de propósito: a chave mora num
# lugar só, que já está no .gitignore. Sem isso o Compose procuraria um .env ao
# lado do docker-compose.yml e a chave acabaria duplicada — dois lugares para
# esquecer de girar quando ela vazar.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$AQUI/../../lupa-empresas/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Não achei $ENV_FILE" >&2
  exit 1
fi
if ! grep -q "^EVOLUTION_API_KEY=." "$ENV_FILE"; then
  echo "EVOLUTION_API_KEY está vazia em $ENV_FILE" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$AQUI/docker-compose.yml" "${@:-up -d}"
