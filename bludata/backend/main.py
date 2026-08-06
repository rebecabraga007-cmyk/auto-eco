"""
bludata — B2B prospecting platform backend
FastAPI app with CORS, rate limiting, and all v1 routes.
"""
import sys
import os
import time
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Add backend directory to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

from db.database import create_tables, seed_database
from api.v1 import persons, companies, contact, enrich, search

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="bludata API",
    description="Plataforma B2B de prospecção de dados — clone funcional Datastone",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (libera tudo para desenvolvimento) ───────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting (in-memory, por IP) ────────────────────────────────────────

RATE_LIMIT_REQUESTS = 60   # requests
RATE_LIMIT_WINDOW = 60     # seconds

_rate_counters: dict = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries
    _rate_counters[ip] = [t for t in _rate_counters[ip] if now - t < RATE_LIMIT_WINDOW]

    if len(_rate_counters[ip]) >= RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={
                "sucesso": False,
                "error": "Rate limit exceeded",
                "retry_after": RATE_LIMIT_WINDOW,
            },
        )

    _rate_counters[ip].append(now)
    return await call_next(request)


# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(persons.router, prefix="/v1", tags=["Pessoas"])
app.include_router(companies.router, prefix="/v1", tags=["Empresas"])
app.include_router(contact.router, prefix="/v1", tags=["Contatos"])
app.include_router(enrich.router, prefix="/v1", tags=["Enrich"])
app.include_router(search.router, prefix="/v1", tags=["Busca"])


# ── Health / Root ─────────────────────────────────────────────────────────────

@app.get("/", tags=["Status"])
def root():
    return {
        "app": "bludata",
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health", tags=["Status"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    print("[bludata] Initializing database...")
    create_tables()
    seed_database()
    print("[bludata] Ready. Docs at http://localhost:8001/docs")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
