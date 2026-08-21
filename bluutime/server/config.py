"""Caminhos e ligação com o backend do CapiBLU."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # bluutime/
REPO = os.path.dirname(ROOT)                       # maisobras-enricher/
WEB = os.path.join(ROOT, "web")
CAPIBLU_BACKEND = os.path.join(REPO, "lupa-empresas", "backend")
CAPIBLU_FRONTEND = os.path.join(REPO, "lupa-empresas", "frontend")

DB_PATH = os.environ.get("BLUUTIME_DB", os.path.join(ROOT, "bluutime.db"))
DB_URL = f"sqlite:///{DB_PATH}"

# O auth do CapiBLU guarda usuários no próprio SQLite; apontamos para o mesmo
# arquivo para que o login seja um só entre as duas ferramentas.
os.environ.setdefault("AUTH_DB_PATH", os.path.join(CAPIBLU_BACKEND, "capiblu_auth.db"))


def capiblu_on_path() -> None:
    """backend/ do CapiBLU usa imports achatados (`import assertiva`)."""
    if CAPIBLU_BACKEND not in sys.path:
        sys.path.insert(0, CAPIBLU_BACKEND)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(REPO, "lupa-empresas", ".env"))
    except Exception:
        pass
