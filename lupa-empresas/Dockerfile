# App Online do CapiBLU (front door do Render): frontend + auth + proxy.
# NÃO contém bases pesadas nem chaves — só reencaminha ao serviço de dados local.
# Build context = esta pasta (lupa-empresas/).
FROM python:3.12-slim

WORKDIR /app

# Deps enxutas (auth + proxy). As libs pesadas do serviço de dados NÃO entram aqui.
COPY app_online/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Código: app-online + o módulo de auth (mora em backend/) + o frontend.
COPY app_online/ ./app_online/
COPY backend/auth.py ./backend/auth.py
COPY frontend/ ./frontend/

# Render injeta $PORT. Users DB persistente deve apontar p/ um disco (AUTH_DB_PATH).
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app_online.main:app --host 0.0.0.0 --port ${PORT}"]
