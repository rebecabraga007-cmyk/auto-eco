#!/usr/bin/env bash
# Lupa de Empresas - inicia o backend (que tambem serve o frontend)
set -e
cd "$(dirname "$0")/backend"

echo "Instalando dependencias..."
python -m pip install -r requirements.txt

echo
echo "Iniciando em http://localhost:8010"
python -m uvicorn main:app --host 0.0.0.0 --port 8010
