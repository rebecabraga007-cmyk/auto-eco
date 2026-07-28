@echo off
REM Lupa de Empresas - inicia o backend (que tambem serve o frontend)
cd /d "%~dp0backend"

echo Instalando dependencias...
python -m pip install -r requirements.txt

echo.
echo Iniciando em http://localhost:8010
python -m uvicorn main:app --host 0.0.0.0 --port 8010
