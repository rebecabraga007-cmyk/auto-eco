@echo off
echo ===================================
echo   bludata B2B Prospecting Platform
echo ===================================
echo.

cd /d "%~dp0backend"

echo [bludata] Verificando dependencias...
python -c "import fastapi" 2>nul || (
  echo [bludata] Instalando dependencias...
  pip install -r requirements.txt
)

echo.
echo [bludata] Iniciando backend em http://localhost:8001
echo [bludata] Documentacao da API: http://localhost:8001/docs
echo [bludata] Frontend: abra o arquivo frontend\index.html no navegador
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
pause
