#!/bin/bash
# bludata — startup script
set -e

echo "==================================="
echo "  bludata B2B Prospecting Platform"
echo "==================================="

BACKEND_DIR="$(dirname "$0")/backend"
FRONTEND_DIR="$(dirname "$0")/frontend"

# Install dependencies if needed
if ! python -c "import fastapi" 2>/dev/null; then
  echo "[bludata] Installing Python dependencies..."
  pip install -r "$BACKEND_DIR/requirements.txt"
fi

# Start backend
echo "[bludata] Starting backend on http://localhost:8001"
echo "[bludata] API docs at http://localhost:8001/docs"
echo "[bludata] Open frontend: file://$FRONTEND_DIR/index.html"
echo ""
cd "$BACKEND_DIR" && python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
