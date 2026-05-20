"""
main.py — Mais Obras Enricher v1.2
Sem Playwright. Tudo via httpx direto na API interna do Mais Obras.
"""

import logging
import os
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles

load_dotenv()

from excel_handler import carregar_excel, enriquecer_excel, gerar_meetime_excel
from scraper import MaisObrasScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

MAISOBRAS_EMAIL    = os.getenv("MAISOBRAS_EMAIL", "")
MAISOBRAS_PASSWORD = os.getenv("MAISOBRAS_PASSWORD", "")
API_TOKEN          = os.getenv("API_TOKEN", "")
MAX_OBRAS          = int(os.getenv("MAX_OBRAS_PER_REQUEST", "1500"))

api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

def verificar_token(token: str = Security(api_key_header)):
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Token de API inválido.")
    return token

scraper = MaisObrasScraper()
jobs: dict[str, dict] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    await scraper.start()
    if MAISOBRAS_EMAIL and MAISOBRAS_PASSWORD:
        ok = await scraper.login(MAISOBRAS_EMAIL, MAISOBRAS_PASSWORD)
        if not ok:
            logger.error(
                "Autenticação inicial falhou. "
                "Use POST /reautenticar após verificar as credenciais."
            )
    else:
        logger.warning("MAISOBRAS_EMAIL/PASSWORD não configurados.")
    yield
    await scraper.stop()

app = FastAPI(
    title="Mais Obras Enricher",
    description=(
        "Enriquece o Excel de Favoritos do Mais Obras com telefones e e-mails "
        "via chamada direta à API interna da plataforma."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory="assets"), name="assets")

INDEX_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Auto ECO — Enriquecimento de favoritos</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
  <script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
  <script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>
  <style>
/* ============================================================
   AUTO ECO — plataforma padrão, amigável e clara
   ============================================================ */

:root {
  /* Brand kept as accents only */
  --wine: #6B2024;
  --wine-deep: #4D1416;
  --wine-soft: #8B3D40;
  --gold: #C9A95B;
  --gold-deep: #A6873C;
  --gold-soft: #F0E5C7;

  /* Neutral system */
  --bg: #F7F5F0;
  --surface: #FFFFFF;
  --surface-2: #FAF8F3;
  --ink: #1F1B1A;
  --ink-2: #4A4341;
  --ink-3: #7C7370;
  --ink-4: #A8A09D;
  --border: #E8E2D8;
  --border-soft: #F0EAE0;

  --ok: #1F7A3A;
  --ok-bg: #E8F4EB;
  --warn: #8A5A0B;
  --warn-bg: #FBEFD1;
  --err: #B1352A;
  --err-bg: #FBE5E1;

  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 14px;
  --r-xl: 20px;

  --shadow-1: 0 1px 2px rgba(31, 27, 26, 0.04), 0 1px 3px rgba(31, 27, 26, 0.06);
  --shadow-2: 0 4px 12px rgba(31, 27, 26, 0.06), 0 2px 4px rgba(31, 27, 26, 0.04);
  --shadow-3: 0 12px 32px rgba(31, 27, 26, 0.10), 0 4px 8px rgba(31, 27, 26, 0.05);

  --ease: cubic-bezier(0.4, 0, 0.2, 1);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }

body {
  font-family: "Bricolage Grotesque", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 15.5px;
  line-height: 1.55;
  color: var(--ink);
  background:
    radial-gradient(ellipse 800px 400px at 80% -200px, rgba(201, 169, 91, 0.10), transparent 60%),
    radial-gradient(ellipse 600px 400px at -200px 800px, rgba(107, 32, 36, 0.05), transparent 60%),
    var(--bg);
  background-attachment: fixed;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  position: relative;
}

/* Subtle paper grain across the whole page */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image: url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.12  0 0 0 0 0.10  0 0 0 0 0.10  0 0 0 0.045 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  mix-blend-mode: multiply;
  opacity: 0.55;
}
.shell { position: relative; z-index: 1; }

button { font-family: inherit; color: inherit; }
a { color: var(--wine); }

/* ============================================================
   APP SHELL
   ============================================================ */
.shell {
  width: min(1080px, 100%);
  margin: 0 auto;
  padding: 0 24px 80px;
}

/* Decorative colored stripe at very top */
.top-stripe {
  display: flex;
  height: 4px;
  width: 100%;
  margin-bottom: 20px;
}
.top-stripe span:nth-child(1) { background: var(--wine); flex: 0 0 32%; }
.top-stripe span:nth-child(2) { background: var(--gold); flex: 0 0 14%; }
.top-stripe span:nth-child(3) { background: var(--ink); flex: 0 0 6%; }
.top-stripe span:nth-child(4) { background: var(--gold-soft); flex: 1; }

/* ============================================================
   TOPBAR
   ============================================================ */
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 12px 16px;
  margin-bottom: 24px;
  box-shadow: var(--shadow-1);
}
.topbar-logo {
  width: 40px; height: 40px;
  border-radius: 8px;
  background: var(--surface-2);
  display: grid; place-items: center;
  padding: 5px;
  flex-shrink: 0;
}
.topbar-logo img { width: 100%; height: 100%; object-fit: contain; }

.topbar-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.topbar-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.015em;
  font-variation-settings: "opsz" 24;
}
.topbar-sub {
  font-size: 13px;
  color: var(--ink-3);
}

.topbar-actions { display: flex; align-items: center; gap: 8px; }

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-3);
}
.status-chip.ok { background: var(--ok-bg); border-color: #C7E2CE; color: var(--ok); }
.status-chip.warn { background: var(--warn-bg); border-color: #E9CE85; color: var(--warn); }
.status-chip.err { background: var(--err-bg); border-color: #F0B6AD; color: var(--err); }
.status-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: currentColor; position: relative;
}
.status-chip.ok .status-chip-dot::after {
  content: ""; position: absolute; inset: -3px;
  border-radius: 50%; background: currentColor; opacity: 0.3;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 0.3; }
  50% { transform: scale(1.8); opacity: 0; }
}

.icon-btn {
  width: 36px; height: 36px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface);
  display: grid; place-items: center;
  cursor: pointer;
  color: var(--ink-2);
  transition: all .15s var(--ease);
  padding: 0;
}
.icon-btn:hover { background: var(--surface-2); color: var(--wine); border-color: var(--gold); }

/* ============================================================
   HERO — left-aligned with asymmetric grid + watermark
   ============================================================ */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 28px;
  align-items: end;
  padding: 16px 4px 36px;
  position: relative;
  isolation: isolate;
}
.hero::before {
  content: "ECO";
  position: absolute;
  right: -10px; top: -28px;
  font-family: "Bricolage Grotesque", sans-serif;
  font-weight: 800;
  font-size: clamp(140px, 22vw, 240px);
  line-height: 0.85;
  letter-spacing: -0.05em;
  color: var(--wine);
  opacity: 0.05;
  font-style: italic;
  z-index: -1;
  pointer-events: none;
  font-variation-settings: "opsz" 96;
}
.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: "JetBrains Mono", monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--wine);
  font-weight: 600;
  margin-bottom: 10px;
}
.hero-eyebrow::before {
  content: "";
  width: 22px; height: 1.5px;
  background: var(--gold);
}
.hero h1 {
  margin: 0;
  font-size: clamp(30px, 4.2vw, 44px);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.02;
  color: var(--ink);
  font-variation-settings: "opsz" 96;
}
.hero h1 .accent {
  color: var(--wine);
  font-style: italic;
  font-weight: 600;
  position: relative;
  display: inline-block;
}
.hero h1 .accent::after {
  content: "";
  position: absolute;
  left: 0; right: 4%; bottom: 2px;
  height: 8px;
  background: var(--gold-soft);
  z-index: -1;
  border-radius: 2px;
}
.hero p {
  margin: 0;
  font-size: 15.5px;
  color: var(--ink-3);
  line-height: 1.55;
  max-width: 42ch;
  padding-bottom: 4px;
}
@media (max-width: 720px) {
  .hero { grid-template-columns: 1fr; gap: 14px; }
}

/* Ornamental section divider */
.ornament {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 18px;
}
.ornament .dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--gold);
}
.ornament .dot.wine { background: var(--wine); }
.ornament .line {
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, var(--border) 0%, var(--border) 50%, transparent 100%);
}
.ornament .diamond {
  width: 6px; height: 6px;
  background: var(--gold);
  transform: rotate(45deg);
}

/* ============================================================
   STEPS — friendly horizontal progress
   ============================================================ */
.steps {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto 1fr;
  align-items: center;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 14px 18px;
  margin-bottom: 24px;
  box-shadow: var(--shadow-1);
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.step-num {
  width: 28px; height: 28px;
  border-radius: 50%;
  background: var(--surface-2);
  border: 1.5px solid var(--border);
  color: var(--ink-4);
  font-weight: 700;
  font-size: 13px;
  display: grid; place-items: center;
  flex-shrink: 0;
  transition: all .25s var(--ease);
}
.step.active .step-num {
  background: var(--wine);
  border-color: var(--wine);
  color: #fff;
  box-shadow: 0 0 0 4px rgba(107, 32, 36, 0.12);
}
.step.done .step-num {
  background: var(--ok);
  border-color: var(--ok);
  color: #fff;
}
.step-text { display: flex; flex-direction: column; min-width: 0; }
.step-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-4);
  line-height: 1;
}
.step.active .step-label, .step.done .step-label { color: var(--ink-3); }
.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-2);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.step.active .step-title { color: var(--ink); }

.step-connector {
  height: 1.5px;
  background: var(--border);
  border-radius: 1px;
  transition: background .25s var(--ease);
}
.step-connector.active { background: var(--ok); }

/* ============================================================
   MAIN CARD — the canvas for the workflow
   ============================================================ */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-2);
  overflow: hidden;
  margin-bottom: 24px;
  position: relative;
}
/* Ornamental corner brackets on main card */
.card::before, .card::after {
  content: "";
  position: absolute;
  width: 18px; height: 18px;
  pointer-events: none;
  z-index: 2;
}
.card::before {
  top: 10px; left: 10px;
  border-top: 2px solid var(--gold);
  border-left: 2px solid var(--gold);
}
.card::after {
  bottom: 10px; right: 10px;
  border-bottom: 2px solid var(--gold);
  border-right: 2px solid var(--gold);
}
.card-body { padding: 28px; }
.card-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border-soft);
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.card-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.005em;
}
.card-header .meta {
  font-size: 13px;
  color: var(--ink-3);
}

/* ============================================================
   DROPZONE — friendly cloud, big rounded
   ============================================================ */
.dropzone {
  position: relative;
  border: 2px dashed var(--border);
  border-radius: var(--r-lg);
  background:
    repeating-linear-gradient(135deg, rgba(201, 169, 91, 0.04) 0 14px, transparent 14px 28px),
    var(--surface-2);
  padding: 40px 24px;
  text-align: center;
  cursor: pointer;
  transition: all .15s var(--ease);
  min-height: 240px;
  display: grid;
  place-items: center;
  overflow: hidden;
}
.dropzone:hover {
  border-color: var(--gold);
  background: #FDFAF1;
}
.dropzone.dragover {
  border-color: var(--wine);
  background: #FBF4F5;
  transform: scale(1.005);
}
.dropzone.has-file {
  border-style: solid;
  border-color: var(--ok);
  background: #F2F9F4;
}

.dz-icon {
  width: 72px; height: 72px;
  border-radius: 50%;
  background: var(--surface);
  border: 1px solid var(--border);
  display: grid; place-items: center;
  margin: 0 auto 18px;
  color: var(--wine);
  transition: all .15s var(--ease);
  position: relative;
  box-shadow: 0 4px 14px rgba(107, 32, 36, 0.06);
}
.dz-icon::before {
  content: "";
  position: absolute;
  inset: -7px;
  border: 1px dashed var(--gold);
  border-radius: 50%;
  opacity: 0.5;
  animation: spin 24s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.dropzone:hover .dz-icon { color: var(--wine); border-color: var(--gold); transform: translateY(-2px); }
.dropzone.has-file .dz-icon {
  background: var(--ok);
  border-color: var(--ok);
  color: #fff;
}

.dz-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--ink);
  letter-spacing: -0.02em;
  font-variation-settings: "opsz" 48;
}
.dz-hint {
  font-size: 14px;
  color: var(--ink-3);
  margin: 0;
}
.dz-hint .accent { color: var(--wine); font-weight: 600; text-decoration: underline; text-decoration-color: var(--gold); text-underline-offset: 3px; }
.dz-formats {
  display: inline-flex;
  gap: 6px;
  margin-top: 16px;
  flex-wrap: wrap;
  justify-content: center;
}
.dz-format {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--ink-3);
}

.dz-file-name {
  font-weight: 700;
  font-size: 18px;
  color: var(--ink);
  margin: 0 0 4px;
  word-break: break-all;
  letter-spacing: -0.015em;
}
.dz-file-meta {
  font-size: 13px;
  color: var(--ink-3);
}
.dz-file-clear {
  background: none;
  border: 0;
  color: var(--wine);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
  margin-top: 10px;
}

input[type="file"] {
  position: absolute;
  width: 1px; height: 1px;
  opacity: 0;
  pointer-events: none;
}

/* ============================================================
   OPTION ROW — friendly check
   ============================================================ */
.option-row {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  margin-top: 18px;
  cursor: pointer;
  transition: all .12s var(--ease);
}
.option-row:hover { border-color: var(--gold); background: #FDFAF1; }
.option-row.checked {
  background: #FBF4F5;
  border-color: var(--wine);
}
.option-check {
  width: 20px; height: 20px;
  border-radius: 6px;
  border: 1.5px solid var(--border);
  background: var(--surface);
  display: grid; place-items: center;
  margin-top: 1px;
  transition: all .12s var(--ease);
}
.option-row.checked .option-check {
  background: var(--wine);
  border-color: var(--wine);
}
.option-check svg {
  width: 12px; height: 12px;
  stroke: #fff;
  stroke-width: 3;
  fill: none;
  opacity: 0;
  transition: opacity .12s var(--ease);
}
.option-row.checked .option-check svg { opacity: 1; }
.option-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--ink);
  margin-bottom: 2px;
}
.option-desc {
  font-size: 13px;
  color: var(--ink-3);
  line-height: 1.5;
}

/* ============================================================
   BUTTONS — rounded, accessible
   ============================================================ */
.cta-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 20px;
  justify-content: center;
}
.btn {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--ink);
  height: 44px;
  padding: 0 20px;
  border-radius: 10px;
  font-size: 14.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  transition: all .14s var(--ease);
  white-space: nowrap;
  letter-spacing: -0.005em;
}
.btn:hover { background: var(--surface-2); border-color: var(--gold); }
.btn-primary {
  background: var(--wine);
  color: #fff;
  border-color: var(--wine);
  padding: 0 24px;
  box-shadow: 0 4px 10px rgba(107, 32, 36, 0.18);
}
.btn-primary:hover:not(:disabled) {
  background: var(--wine-deep);
  border-color: var(--wine-deep);
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(107, 32, 36, 0.24);
}
.btn-primary:disabled, .btn-primary[aria-disabled="true"] {
  background: #D8D2C8;
  border-color: #D8D2C8;
  color: #fff;
  cursor: not-allowed;
  box-shadow: none;
}
.btn-gold {
  background: var(--gold);
  color: var(--wine-deep);
  border-color: var(--gold-deep);
  padding: 0 22px;
  box-shadow: 0 4px 10px rgba(201, 169, 91, 0.25);
}
.btn-gold:hover:not(:disabled) { background: var(--gold-deep); color: #fff; border-color: var(--gold-deep); }
.btn-ghost {
  border: 0;
  background: transparent;
  color: var(--ink-3);
}
.btn-ghost:hover { color: var(--wine); background: var(--surface-2); }

/* ============================================================
   PROGRESS — friendly, clear numbers
   ============================================================ */
.progress-block { display: grid; gap: 18px; }

.progress-summary {
  text-align: center;
  padding: 0 0 6px;
}
.progress-summary .pct {
  font-size: 56px;
  font-weight: 700;
  color: var(--wine);
  letter-spacing: -0.04em;
  line-height: 1;
  font-variation-settings: "opsz" 96;
}
.progress-summary .count {
  font-size: 14px;
  color: var(--ink-3);
  margin-top: 4px;
}

.progress-bar {
  height: 10px;
  background: var(--surface-2);
  border-radius: 999px;
  overflow: hidden;
  position: relative;
  border: 1px solid var(--border-soft);
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--wine), var(--wine-soft));
  border-radius: 999px;
  transition: width .35s var(--ease);
  position: relative;
  overflow: hidden;
}
.progress-bar-fill::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent 30%, rgba(255,255,255,0.35) 50%, transparent 70%);
  animation: shimmer 1.8s infinite;
}
@keyframes shimmer {
  from { transform: translateX(-100%); }
  to { transform: translateX(100%); }
}

.progress-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.stat {
  background: var(--surface-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-md);
  padding: 14px 16px;
  text-align: left;
}
.stat-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-4);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.01em;
}
.stat-sub {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}

.progress-now {
  background: var(--surface-2);
  border: 1px solid var(--border-soft);
  border-left: 3px solid var(--wine);
  border-radius: var(--r-md);
  padding: 12px 14px;
}
.progress-now-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--wine);
  margin-bottom: 4px;
}
.progress-now-line {
  font-size: 13.5px;
  color: var(--ink-2);
  line-height: 1.45;
  word-break: break-word;
}

/* ============================================================
   TERMINAL — collapsible details panel
   ============================================================ */
.terminal {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--surface-2);
  overflow: hidden;
  margin-top: 18px;
}
.terminal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-soft);
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 600;
}
.terminal-head .left { display: inline-flex; align-items: center; gap: 8px; }
.terminal-head svg { color: var(--ink-3); }
.terminal-lights { display: none; }
.terminal-body {
  max-height: 200px;
  overflow: auto;
  padding: 12px 14px;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-2);
}
.terminal-line { margin: 0 0 3px; white-space: pre-wrap; word-break: break-word; }
.terminal-line::before { content: "→ "; color: var(--ink-4); }
.terminal-line.warn { color: var(--warn); }
.terminal-line.err { color: var(--err); }
.terminal-line.ok { color: var(--ok); }
.terminal-stamp { color: var(--ink-4); margin-right: 6px; }
.terminal-empty {
  color: var(--ink-4);
  font-style: italic;
}
.terminal-toggle {
  background: none; border: 0; color: var(--ink-3);
  cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
}
.terminal-toggle:hover { background: var(--surface-2); color: var(--ink); }

/* ============================================================
   SUCCESS — friendly checkmark + clear stats
   ============================================================ */
.success-panel {
  text-align: center;
  padding: 16px 0 8px;
  position: relative;
}
.success-panel::before {
  content: "";
  position: absolute;
  left: 50%; top: 24px;
  transform: translate(-50%, 0);
  width: 160px; height: 160px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(31, 122, 58, 0.10) 0%, transparent 70%);
  z-index: 0;
  pointer-events: none;
}
.success-panel > * { position: relative; z-index: 1; }
.success-icon {
  width: 80px; height: 80px;
  border-radius: 50%;
  background: var(--ok);
  display: grid; place-items: center;
  color: #fff;
  margin: 0 auto 18px;
  box-shadow: 0 14px 30px rgba(31, 122, 58, 0.28), 0 0 0 6px rgba(31, 122, 58, 0.08);
  animation: pop .4s var(--ease);
  position: relative;
}
.success-icon::after {
  content: "";
  position: absolute;
  inset: -16px;
  border: 1px dashed var(--ok);
  border-radius: 50%;
  opacity: 0.4;
  animation: spin 30s linear infinite;
}
@keyframes pop {
  from { transform: scale(0.6); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
.success-title {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--ink);
  margin: 0 0 6px;
  font-variation-settings: "opsz" 72;
}
.success-sub {
  font-size: 15px;
  color: var(--ink-3);
  margin: 0 auto 22px;
  max-width: 48ch;
  line-height: 1.5;
}
.success-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  max-width: 480px;
  margin: 0 auto 24px;
}
.success-stat {
  background: var(--surface-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-md);
  padding: 14px 8px;
}
.success-stat-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.028em;
  line-height: 1;
  font-variation-settings: "opsz" 72;
}
.success-stat:nth-child(2) .success-stat-value { color: var(--ok); }
.success-stat:nth-child(3) .success-stat-value { color: var(--gold-deep); }
.success-stat-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-4);
  margin-top: 4px;
}

/* ============================================================
   SIDE CARDS — Como funciona / Dicas
   ============================================================ */
.side-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.side-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 22px 22px 20px;
  box-shadow: var(--shadow-1);
  position: relative;
  overflow: hidden;
}
/* Side card decorative tab */
.side-card::before {
  content: "";
  position: absolute;
  top: 0; left: 22px;
  width: 36px; height: 4px;
  background: var(--wine);
  border-radius: 0 0 2px 2px;
}
.side-card:nth-child(2)::before { background: var(--gold); }
.side-card h3 {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.015em;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-variation-settings: "opsz" 32;
}
.side-card h3::before {
  content: "";
  width: 6px; height: 6px;
  background: var(--gold);
  border-radius: 50%;
}

.flow-list { display: grid; gap: 10px; }
.flow-item {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 12px;
  align-items: flex-start;
  font-size: 13.5px;
}
.flow-num {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--ink-3);
  font-weight: 700;
  font-size: 12px;
  display: grid; place-items: center;
  flex-shrink: 0;
}
.flow-item.active .flow-num { background: var(--wine); border-color: var(--wine); color: #fff; box-shadow: 0 0 0 3px rgba(107, 32, 36, 0.1); }
.flow-item.done .flow-num { background: var(--ok); border-color: var(--ok); color: #fff; }
.flow-item strong {
  display: block;
  font-weight: 600;
  font-size: 13.5px;
  color: var(--ink);
}
.flow-item span {
  font-size: 12.5px;
  color: var(--ink-3);
  line-height: 1.5;
}

.tips-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 11px;
}
.tips-list li {
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 10px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.5;
}
.tips-list li::before {
  content: "";
  width: 6px; height: 6px;
  background: var(--gold);
  border-radius: 50%;
  margin-top: 7px;
}
.tips-list li strong { color: var(--wine); font-weight: 600; }
.tips-list li code {
  font-family: "JetBrains Mono", monospace;
  font-size: 11.5px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
  color: var(--ink-2);
}

/* ============================================================
   FOOTER
   ============================================================ */
.foot {
  margin-top: 36px;
  padding-top: 18px;
  display: flex;
  justify-content: center;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--ink-4);
}

/* ============================================================
   ONBOARDING — clean modal slides
   ============================================================ */
.onboarding-backdrop {
  position: fixed; inset: 0;
  background: rgba(31, 27, 26, 0.55);
  backdrop-filter: blur(6px);
  display: grid; place-items: center;
  z-index: 100;
  animation: fadeIn .25s var(--ease);
  padding: 20px;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.onboarding-card {
  width: min(820px, 100%);
  max-height: calc(100vh - 40px);
  background: var(--surface);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-3);
  overflow: hidden;
  display: grid;
  grid-template-rows: auto 1fr auto;
  animation: rise .35s var(--ease);
}
@keyframes rise {
  from { transform: translateY(12px) scale(0.98); opacity: 0; }
  to { transform: none; opacity: 1; }
}

.onb-head {
  padding: 16px 22px;
  border-bottom: 1px solid var(--border-soft);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.onb-progress { display: flex; gap: 6px; }
.onb-dot {
  width: 28px; height: 4px;
  border-radius: 2px;
  background: var(--border);
  transition: background .25s var(--ease);
}
.onb-dot.active { background: var(--wine); }
.onb-dot.done { background: var(--gold); }

.onb-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 380px;
  overflow: hidden;
}
.onb-text {
  padding: 36px 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  justify-content: center;
  overflow: auto;
}
.onb-eyebrow {
  font-size: 12px;
  font-weight: 700;
  color: var(--wine);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.onb-title {
  font-size: clamp(26px, 3.2vw, 34px);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.028em;
  color: var(--ink);
  margin: 0;
  font-variation-settings: "opsz" 72;
}
.onb-title em {
  font-style: italic;
  color: var(--wine);
  font-weight: 600;
}
.onb-desc {
  font-size: 15px;
  line-height: 1.6;
  color: var(--ink-3);
  margin: 4px 0 0;
}
.onb-desc strong { color: var(--ink); font-weight: 700; }
.onb-desc code {
  font-family: "JetBrains Mono", monospace;
  font-size: 12.5px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
}
.onb-callout {
  background: #FDF6E3;
  border: 1px solid var(--gold-soft);
  border-radius: var(--r-md);
  padding: 10px 14px;
  font-size: 13.5px;
  color: var(--ink-2);
  line-height: 1.5;
  margin-top: 8px;
}
.onb-list {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.onb-list li {
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 10px;
  font-size: 14px;
  color: var(--ink-2);
  line-height: 1.5;
}
.onb-list li svg { margin-top: 3px; color: var(--ok); }

.onb-visual {
  background: var(--surface-2);
  border-left: 1px solid var(--border-soft);
  position: relative;
  overflow: hidden;
  display: grid;
  place-items: center;
  padding: 24px;
}

.onb-foot {
  padding: 14px 22px;
  border-top: 1px solid var(--border-soft);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: var(--surface-2);
}
.onb-step-info {
  font-size: 13px;
  color: var(--ink-3);
}
.onb-step-info strong { color: var(--ink); font-weight: 700; }
.onb-actions { display: flex; gap: 8px; }

/* ============================================================
   ONBOARDING VISUALS — friendly, illustrative, not stock
   ============================================================ */
.visual-welcome {
  display: flex; flex-direction: column;
  align-items: center; gap: 18px;
}
.visual-welcome .logo {
  width: 96px; height: 96px;
  border-radius: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-2);
  display: grid; place-items: center;
  padding: 18px;
}
.visual-welcome .logo img { width: 100%; height: 100%; object-fit: contain; }
.visual-welcome .arrow {
  color: var(--gold);
  font-size: 28px;
  line-height: 1;
}
.visual-welcome .pill {
  background: var(--wine);
  color: #fff;
  border-radius: 999px;
  padding: 10px 18px;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.02em;
}

.visual-browser {
  background: var(--surface);
  border-radius: var(--r-md);
  width: 100%;
  max-width: 320px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-2);
  overflow: hidden;
}
.visual-browser-chrome {
  background: var(--surface-2);
  padding: 8px 12px;
  display: flex; align-items: center; gap: 8px;
  font-size: 11px;
  color: var(--ink-3);
  border-bottom: 1px solid var(--border-soft);
}
.visual-browser-chrome::before {
  content: "● ● ●";
  color: var(--ink-4);
  letter-spacing: 1px;
  font-size: 8px;
  margin-right: 4px;
}
.visual-browser-body {
  padding: 12px;
}
.visual-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
  border-radius: 6px;
}
.visual-row + .visual-row { margin-top: 2px; }
.visual-row .star { color: var(--gold); font-size: 13px; }
.visual-row .name { color: var(--ink); font-weight: 600; flex: 1; }
.visual-row .city { font-size: 10.5px; color: var(--ink-3); }
.visual-export {
  margin-top: 10px;
  background: var(--wine);
  color: #fff;
  padding: 9px 12px;
  border-radius: 8px;
  text-align: center;
  font-size: 12px;
  font-weight: 700;
  animation: hint 2s ease-in-out infinite;
}
.visual-export::after { content: " ↓"; }
@keyframes hint {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

.visual-upload {
  width: 100%; max-width: 280px;
  aspect-ratio: 4/3;
  background: var(--surface);
  border: 2px dashed var(--gold);
  border-radius: var(--r-md);
  display: grid; place-items: center;
  box-shadow: var(--shadow-1);
}
.visual-upload .file-mock {
  width: 72px; height: 92px;
  background: var(--surface);
  border: 2px solid var(--wine);
  border-radius: 8px;
  position: relative;
  animation: floatv 3s ease-in-out infinite;
}
.visual-upload .file-mock::before {
  content: ""; position: absolute; top: -2px; right: -2px;
  width: 18px; height: 18px;
  background: var(--gold);
  border-left: 2px solid var(--wine);
  border-bottom: 2px solid var(--wine);
}
.visual-upload .file-mock::after {
  content: "XLS";
  position: absolute;
  bottom: 12px; left: 50%;
  transform: translateX(-50%);
  font-family: "JetBrains Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  color: var(--wine);
}
@keyframes floatv {
  0%, 100% { transform: translateY(0) rotate(-2deg); }
  50% { transform: translateY(-8px) rotate(2deg); }
}

.visual-cols {
  background: var(--surface);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-2);
  width: 100%; max-width: 320px;
  font-size: 10px;
  overflow: hidden;
}
.visual-cols-row {
  display: grid;
  grid-template-columns: 1fr 1fr 0.7fr 0.7fr;
}
.visual-cols-row + .visual-cols-row { border-top: 1px solid var(--border-soft); }
.visual-cols-cell {
  padding: 6px 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-right: 1px solid var(--border-soft);
  font-family: "JetBrains Mono", monospace;
}
.visual-cols-cell:last-child { border-right: 0; }
.visual-cols-row.header .visual-cols-cell {
  background: var(--ink);
  color: var(--surface);
  font-weight: 700;
  font-size: 9px;
}
.visual-cols-row.new .visual-cols-cell {
  background: #FDF6E3;
  color: var(--wine-deep);
  font-weight: 600;
}
.visual-cols-row.header.new .visual-cols-cell {
  background: var(--gold);
  color: var(--wine-deep);
}

.visual-done {
  display: flex; flex-direction: column;
  align-items: center; gap: 14px;
}
.visual-done .check {
  width: 96px; height: 96px;
  border-radius: 50%;
  background: var(--ok);
  display: grid; place-items: center;
  color: #fff;
  box-shadow: 0 16px 36px rgba(31, 122, 58, 0.25);
  animation: pulseRing 2s ease-in-out infinite;
}
.visual-done .caption {
  font-weight: 700;
  color: var(--ink);
}
@keyframes pulseRing {
  0%, 100% { box-shadow: 0 16px 36px rgba(31, 122, 58, 0.25), 0 0 0 0 rgba(31, 122, 58, 0.3); }
  50% { box-shadow: 0 16px 36px rgba(31, 122, 58, 0.25), 0 0 0 16px rgba(31, 122, 58, 0); }
}

/* ============================================================
   RESPONSIVE
   ============================================================ */
@media (max-width: 760px) {
  .shell { padding: 16px 14px 60px; }
  .topbar { flex-wrap: wrap; }
  .topbar-actions { width: 100%; justify-content: space-between; }
  .steps {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .step-connector { display: none; }
  .side-grid { grid-template-columns: 1fr; }
  .progress-stats { grid-template-columns: 1fr; }
  .onb-body { grid-template-columns: 1fr; min-height: 0; }
  .onb-visual { min-height: 180px; border-left: 0; border-top: 1px solid var(--border-soft); }
  .hero h1 { font-size: 26px; }
}
@media (max-width: 480px) {
  .success-stats { grid-template-columns: 1fr; }
}

  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" data-presets="react">
/* global React */
const { useState, useEffect } = React;

const ONB_STEPS = [
  {
    eyebrow: "Boas-vindas",
    title: "Bem-vinda ao Auto ECO",
    desc: (
      <>
        Esta ferramenta enriquece sua planilha de favoritos do <strong>Mais Obras </strong>
        com telefones e e-mails de arquitetos e proprietários. Em poucos minutos
        você baixa o arquivo pronto pra importar no <strong>Meetime</strong>.
      </>
    ),
    callout: "Sem mexer no Excel. Sem digitação manual. Você só sobe o arquivo.",
    visual: "welcome",
  },
  {
    eyebrow: "Passo 1 de 3",
    title: "Exporte do Mais Obras",
    desc: (
      <>
        Na plataforma do Mais Obras, abra <em>Meus Favoritos</em> e clique em
        <strong> Exportar</strong>. Você vai baixar um arquivo <code>Meus_favoritos.xls</code>.
      </>
    ),
    list: [
      "Marque as obras como favoritas durante a prospecção",
      "Clique em Exportar no topo da lista",
      "Salve o arquivo no computador",
    ],
    visual: "browser",
  },
  {
    eyebrow: "Passo 2 de 3",
    title: "Solte o arquivo aqui",
    desc: (
      <>
        Arraste o <code>.xls</code> direto pra zona de upload ou clique em
        <strong> Escolher arquivo</strong>. Aceitamos <code>.xls</code>,
        <code>.xlsx</code> e <code>.csv</code>.
      </>
    ),
    callout: "Ative o Modo Meetime se for importar direto pro CRM — sai 1 linha por contato.",
    visual: "upload",
  },
  {
    eyebrow: "Passo 3 de 3",
    title: "Baixe a planilha pronta",
    desc: (
      <>
        Você recebe o arquivo com <strong>7 colunas novas</strong> de contato.
        As colunas em dourado são as que o Auto ECO preencheu pra você.
      </>
    ),
    list: [
      "Telefone Arquiteto 1, 2 e e-mail do arquiteto",
      "Telefone Proprietário 1, 2 e e-mail do proprietário",
      "Status: OK, sem telefone, ou erro de consulta",
    ],
    visual: "columns",
  },
  {
    eyebrow: "Tudo pronto",
    title: "Bora começar?",
    desc: (
      <>
        Você pode rever este tour a qualquer momento pelo ícone de
        <strong> ajuda</strong> no topo da página.
      </>
    ),
    callout: "Mantenha a aba aberta durante o processamento — o resultado baixa automaticamente.",
    visual: "done",
  },
];

function VisualPanel({ kind }) {
  if (kind === "welcome") {
    return (
      <div className="visual-welcome">
        <div className="logo"><img src="assets/ecorio-logo.jpeg" alt="Ecorio" /></div>
        <div className="arrow">↓</div>
        <div className="pill">Auto ECO</div>
      </div>
    );
  }
  if (kind === "browser") {
    return (
      <div className="visual-browser">
        <div className="visual-browser-chrome">maisobras.com.br</div>
        <div className="visual-browser-body">
          {[
            ["Residencial Vila Nova", "SAO CARLOS"],
            ["Edif. Mirante", "RIB. PRETO"],
            ["Casa Anhanguera", "ARARAQUARA"],
          ].map(([n, c], i) => (
            <div className="visual-row" key={i}>
              <span className="star">★</span>
              <span className="name">{n}</span>
              <span className="city">{c}</span>
            </div>
          ))}
          <div className="visual-export">Exportar planilha</div>
        </div>
      </div>
    );
  }
  if (kind === "upload") {
    return (
      <div className="visual-upload">
        <div className="file-mock"></div>
      </div>
    );
  }
  if (kind === "columns") {
    return (
      <div className="visual-cols">
        <div className="visual-cols-row header">
          <div className="visual-cols-cell">Profissional</div>
          <div className="visual-cols-cell">Cidade</div>
          <div className="visual-cols-cell">UF</div>
          <div className="visual-cols-cell">Status</div>
        </div>
        <div className="visual-cols-row header new">
          <div className="visual-cols-cell">Tel Arq 1</div>
          <div className="visual-cols-cell">Tel Arq 2</div>
          <div className="visual-cols-cell">Email</div>
          <div className="visual-cols-cell">Tel Prop</div>
        </div>
        {[
          ["A. Silva", "SAO PAULO", "SP", "OK"],
          ["M. Lima", "CAMPINAS", "SP", "OK"],
          ["J. Souza", "SANTOS", "SP", "OK"],
        ].map((row, i) => (
          <React.Fragment key={i}>
            <div className="visual-cols-row">
              {row.map((c, j) => <div className="visual-cols-cell" key={j}>{c}</div>)}
            </div>
            <div className="visual-cols-row new">
              <div className="visual-cols-cell">16 9999-9999</div>
              <div className="visual-cols-cell">16 8888-8888</div>
              <div className="visual-cols-cell">arq@mail</div>
              <div className="visual-cols-cell">11 7777</div>
            </div>
          </React.Fragment>
        ))}
      </div>
    );
  }
  if (kind === "done") {
    return (
      <div className="visual-done">
        <div className="check">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <div className="caption">Tudo pronto.</div>
      </div>
    );
  }
  return null;
}

function Onboarding({ onClose }) {
  const [step, setStep] = useState(0);
  const total = ONB_STEPS.length;
  const current = ONB_STEPS[step];

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && step < total - 1) setStep(step + 1);
      if (e.key === "ArrowLeft" && step > 0) setStep(step - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const isLast = step === total - 1;

  return (
    <div className="onboarding-backdrop" role="dialog" aria-modal="true" aria-labelledby="onb-title">
      <div className="onboarding-card">
        <div className="onb-head">
          <div className="onb-progress" aria-label={`Passo ${step + 1} de ${total}`}>
            {ONB_STEPS.map((_, i) => (
              <div
                key={i}
                className={"onb-dot " + (i === step ? "active" : i < step ? "done" : "")}
              />
            ))}
          </div>
          <button className="btn btn-ghost" style={{height: 32, padding: "0 12px", fontSize: 13}} onClick={onClose}>
            Pular tour
          </button>
        </div>

        <div className="onb-body">
          <div className="onb-text">
            <div className="onb-eyebrow">{current.eyebrow}</div>
            <h2 className="onb-title" id="onb-title">{current.title}</h2>
            <p className="onb-desc">{current.desc}</p>
            {current.list && (
              <ul className="onb-list">
                {current.list.map((item, i) => (
                  <li key={i}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            )}
            {current.callout && <div className="onb-callout">{current.callout}</div>}
          </div>
          <div className="onb-visual">
            <VisualPanel kind={current.visual} />
          </div>
        </div>

        <div className="onb-foot">
          <div className="onb-step-info">
            <strong>{step + 1}</strong> de {total}
          </div>
          <div className="onb-actions">
            {step > 0 && (
              <button className="btn" onClick={() => setStep(step - 1)}>
                Voltar
              </button>
            )}
            {!isLast ? (
              <button className="btn btn-primary" onClick={() => setStep(step + 1)}>
                Continuar
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                  <polyline points="12 5 19 12 12 19"></polyline>
                </svg>
              </button>
            ) : (
              <button className="btn btn-primary" onClick={onClose}>
                Começar
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

window.Onboarding = Onboarding;

  </script>
  <script type="text/babel" data-presets="react">
/* global React */
const { useState, useEffect, useRef } = React;

function bytes(n) {
  if (!n) return "0 KB";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

function Topbar({ status, onHelp, onSettings }) {
  const statusMap = {
    checking: { cls: "", text: "Conferindo conexão" },
    connected: { cls: "ok", text: "Conectado" },
    pending: { cls: "warn", text: "Login pendente" },
    offline: { cls: "err", text: "Servidor offline" },
  };
  const s = statusMap[status] || statusMap.checking;
  return (
    <header className="topbar">
      <div className="topbar-logo">
        <img src="assets/ecorio-logo.jpeg" alt="Ecorio" />
      </div>
      <div className="topbar-meta">
        <div className="topbar-title">Auto ECO</div>
        <div className="topbar-sub">Enriquecimento de favoritos · Ecorio</div>
      </div>
      <div className="topbar-actions">
        <div className={"status-chip " + s.cls}>
          <span className="status-chip-dot"></span>
          {s.text}
        </div>
        <button className="icon-btn" onClick={onHelp} title="Reabrir tour" aria-label="Reabrir tour">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
        </button>
        <button className="icon-btn" onClick={onSettings} title="Configurações" aria-label="Configurações">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <div className="hero">
      <div>
        <div className="hero-eyebrow">Mais Obras → Meetime</div>
        <h1>Enriqueça sua planilha<br/>de <span className="accent">favoritos</span>.</h1>
      </div>
      <p>
        Suba o arquivo exportado do Mais Obras e baixe a planilha com telefones,
        e-mails e status de cada contato — pronta pra importar no Meetime.
      </p>
    </div>
  );
}

function Ornament() {
  return (
    <div className="ornament" aria-hidden="true">
      <div className="dot"></div>
      <div className="diamond"></div>
      <div className="dot wine"></div>
      <div className="line"></div>
    </div>
  );
}

function Steps({ stage }) {
  const items = [
    { num: 1, label: "Passo 1", title: "Enviar arquivo" },
    { num: 2, label: "Passo 2", title: "Processando" },
    { num: 3, label: "Passo 3", title: "Baixar resultado" },
  ];
  const idxMap = { idle: 0, uploading: 0, processing: 1, done: 2 };
  const activeIdx = idxMap[stage] ?? 0;
  const out = [];
  items.forEach((it, i) => {
    const cls = i < activeIdx ? "done" : i === activeIdx ? "active" : "";
    out.push(
      <div className={"step " + cls} key={it.num}>
        <div className="step-num">
          {i < activeIdx ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          ) : it.num}
        </div>
        <div className="step-text">
          <span className="step-label">{it.label}</span>
          <span className="step-title">{it.title}</span>
        </div>
      </div>
    );
    if (i < items.length - 1) {
      out.push(<div key={"c" + i} className={"step-connector" + (i < activeIdx ? " active" : "")}></div>);
    }
  });
  return <nav className="steps" aria-label="Progresso">{out}</nav>;
}

function Dropzone({ file, onPick, onClear, disabled }) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <label
      className={"dropzone " + (file ? "has-file " : "") + (dragOver ? "dragover" : "")}
      onDragEnter={(e) => { e.preventDefault(); if (!disabled) setDragOver(true); }}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (disabled) return;
        const f = e.dataTransfer.files?.[0];
        if (f) onPick(f);
      }}
      htmlFor="file-input"
    >
      <input
        id="file-input"
        type="file"
        accept=".xls,.xlsx,.xlsm,.csv"
        disabled={disabled}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
        }}
      />
      <div>
        <div className="dz-icon" aria-hidden="true">
          {file ? (
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          ) : (
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
          )}
        </div>
        {file ? (
          <>
            <h2 className="dz-title">Arquivo selecionado</h2>
            <p className="dz-file-name">{file.name}</p>
            <p className="dz-file-meta">{bytes(file.size)} · {(file.name.split(".").pop() || "").toUpperCase()}</p>
            <button
              type="button"
              className="dz-file-clear"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClear(); }}
            >
              Trocar arquivo
            </button>
          </>
        ) : (
          <>
            <h2 className="dz-title">Arraste seu arquivo aqui</h2>
            <p className="dz-hint">
              ou <span className="accent">clique para escolher</span> do computador
            </p>
            <div className="dz-formats">
              <span className="dz-format">.xls</span>
              <span className="dz-format">.xlsx</span>
              <span className="dz-format">.csv</span>
              <span className="dz-format">até 1500 obras</span>
            </div>
          </>
        )}
      </div>
    </label>
  );
}

function OptionRow({ checked, onChange, title, desc }) {
  return (
    <div
      className={"option-row" + (checked ? " checked" : "")}
      onClick={() => onChange(!checked)}
      role="checkbox"
      aria-checked={checked}
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onChange(!checked); } }}
    >
      <div className="option-check">
        <svg viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </div>
      <div className="option-text">
        <div className="option-title">{title}</div>
        <div className="option-desc">{desc}</div>
      </div>
    </div>
  );
}

function ProgressBlock({ processed, total, percent, currentLine }) {
  const remaining = Math.max(0, total - processed);
  return (
    <div className="progress-block">
      <div className="progress-summary">
        <div className="pct">{percent}%</div>
        <div className="count">{processed} de {total} obras processadas</div>
      </div>
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{width: percent + "%"}}></div>
      </div>
      <div className="progress-stats">
        <div className="stat">
          <div className="stat-label">Processadas</div>
          <div className="stat-value">{processed}</div>
          <div className="stat-sub">de {total} obras</div>
        </div>
        <div className="stat">
          <div className="stat-label">Restantes</div>
          <div className="stat-value">{remaining}</div>
          <div className="stat-sub">obras a consultar</div>
        </div>
        <div className="stat">
          <div className="stat-label">Estimativa</div>
          <div className="stat-value">~ {Math.max(1, Math.round(remaining * 0.3))}s</div>
          <div className="stat-sub">para concluir</div>
        </div>
      </div>
      {currentLine && (
        <div className="progress-now">
          <div className="progress-now-label">Consultando agora</div>
          <div className="progress-now-line">{currentLine}</div>
        </div>
      )}
    </div>
  );
}

function Terminal({ lines, open, onToggle }) {
  const bodyRef = useRef(null);
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [lines]);
  return (
    <section className="terminal" aria-label="Log detalhado">
      <div className="terminal-head">
        <span className="left">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4 17 10 11 4 5"></polyline>
            <line x1="12" y1="19" x2="20" y2="19"></line>
          </svg>
          Detalhes do processamento
        </span>
        <button className="terminal-toggle" onClick={onToggle}>
          {open ? "Ocultar" : "Mostrar"}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{transform: open ? "rotate(180deg)" : "none", transition: "transform .2s"}}>
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
      </div>
      {open && (
        <div className="terminal-body" ref={bodyRef}>
          {lines.length === 0 ? (
            <div className="terminal-empty">Aguardando comando…</div>
          ) : lines.map((l, i) => (
            <div key={i} className={"terminal-line " + (l.kind || "")}>
              <span className="terminal-stamp">[{l.t}]</span>
              {l.text}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SuccessPanel({ result, onDownload, onReset }) {
  const pct = Math.round(100 * result.success / Math.max(1, result.total));
  return (
    <div className="success-panel">
      <div className="success-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </div>
      <h3 className="success-title">Tudo pronto!</h3>
      <p className="success-sub">
        Sua planilha foi enriquecida. {result.success < result.total
          ? `${result.total - result.success} obras ficaram sem telefone — é comum em cadastros recentes.`
          : `Todas as obras retornaram contato com sucesso.`}
      </p>
      <div className="success-stats">
        <div className="success-stat">
          <div className="success-stat-value">{result.total}</div>
          <div className="success-stat-label">Total</div>
        </div>
        <div className="success-stat">
          <div className="success-stat-value">{result.success}</div>
          <div className="success-stat-label">Com telefone</div>
        </div>
        <div className="success-stat">
          <div className="success-stat-value">{pct}%</div>
          <div className="success-stat-label">Taxa</div>
        </div>
      </div>
      <div className="cta-row">
        <button className="btn btn-primary" onClick={onDownload}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          Baixar planilha
        </button>
        <button className="btn" onClick={onReset}>
          Enriquecer outra
        </button>
      </div>
    </div>
  );
}

function FlowCard({ stage }) {
  const items = [
    { title: "Arquivo recebido", desc: "Validamos e convertemos o .xls se precisar." },
    { title: "Buscando contatos", desc: "Consultamos a base do Mais Obras, linha a linha." },
    { title: "Planilha pronta", desc: "Resultado liberado pra você baixar." },
  ];
  const idx = { idle: -1, uploading: 0, processing: 1, done: 2 }[stage];
  return (
    <div className="side-card">
      <h3>Como funciona</h3>
      <div className="flow-list">
        {items.map((it, i) => {
          const cls = i < idx ? "done" : i === idx ? "active" : "";
          return (
            <div className={"flow-item " + cls} key={i}>
              <div className="flow-num">
                {i < idx ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                ) : i + 1}
              </div>
              <div>
                <strong>{it.title}</strong>
                <span>{it.desc}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TipsCard() {
  return (
    <div className="side-card">
      <h3>Boas práticas</h3>
      <ul className="tips-list">
        <li>Exporte favoritos com no máximo <strong>1500 obras</strong> por arquivo.</li>
        <li>Ative o <strong>Modo Meetime</strong> se for importar direto no CRM.</li>
        <li>Telefones do arquiteto e do proprietário entram em colunas separadas.</li>
        <li>Mantenha esta aba aberta durante o processamento.</li>
      </ul>
    </div>
  );
}

Object.assign(window, {
  Topbar, Hero, Ornament, Steps, Dropzone, OptionRow,
  ProgressBlock, Terminal, SuccessPanel,
  FlowCard, TipsCard, bytes,
});

  </script>
  <script type="text/babel" data-presets="react">

// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null
      ? keyOrEdits : { [keyOrEdits]: val };
    setValues((prev) => ({ ...prev, ...edits }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', { detail: edits }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({ title = 'Tweaks', noDeckControls = false, children }) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  // Auto-inject a rail toggle when a <deck-stage> is on the page. The
  // toggle drives the deck's per-viewer _railVisible via window message;
  // state is mirrored from the same localStorage key the deck reads so
  // the control reflects reality across reloads. The mechanism is the
  // message — authors who want custom placement can post it directly
  // and pass noDeckControls to suppress this one.
  const hasDeckStage = React.useMemo(
    () => typeof document !== 'undefined' && !!document.querySelector('deck-stage'),
    [],
  );
  // deck-stage enables its rail in connectedCallback, but this panel can
  // mount before that element has upgraded. The initial read catches the
  // common case; the listener covers mounting first. (Older deck-stage.js
  // copies still wait for the host's __omelette_rail_enabled postMessage —
  // same listener handles those.)
  const [railEnabled, setRailEnabled] = React.useState(
    () => hasDeckStage && !!document.querySelector('deck-stage')?._railEnabled,
  );
  React.useEffect(() => {
    if (!hasDeckStage || railEnabled) return undefined;
    const onMsg = (e) => {
      if (e.data && e.data.type === '__omelette_rail_enabled') setRailEnabled(true);
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [hasDeckStage, railEnabled]);
  const [railVisible, setRailVisible] = React.useState(() => {
    try { return localStorage.getItem('deck-stage.railVisible') !== '0'; } catch (e) { return true; }
  });
  const toggleRail = (on) => {
    setRailVisible(on);
    window.postMessage({ type: '__deck_rail_visible', on }, '*');
  };
  const offsetRef = React.useRef({ x: 16, y: 16 });
  const PAD = 16;

  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth, h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y)),
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);

  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);

  React.useEffect(() => {
    const onMsg = (e) => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);
      else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({ type: '__edit_mode_dismissed' }, '*');
  };

  const onDragStart = (e) => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX, sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = (ev) => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy),
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  if (!open) return null;
  return (
    <>
      <style>{__TWEAKS_STYLE}</style>
      <div ref={dragRef} className="twk-panel" data-noncommentable=""
           style={{ right: offsetRef.current.x, bottom: offsetRef.current.y }}>
        <div className="twk-hd" onMouseDown={onDragStart}>
          <b>{title}</b>
          <button className="twk-x" aria-label="Close tweaks"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={dismiss}>✕</button>
        </div>
        <div className="twk-body">
          {children}
          {hasDeckStage && railEnabled && !noDeckControls && (
            <TweakSection label="Deck">
              <TweakToggle label="Thumbnail rail" value={railVisible} onChange={toggleRail} />
            </TweakSection>
          )}
        </div>
      </div>
    </>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({ label, children }) {
  return (
    <>
      <div className="twk-sect">{label}</div>
      {children}
    </>
  );
}

function TweakRow({ label, value, children, inline = false }) {
  return (
    <div className={inline ? 'twk-row twk-row-h' : 'twk-row'}>
      <div className="twk-lbl">
        <span>{label}</span>
        {value != null && <span className="twk-val">{value}</span>}
      </div>
      {children}
    </div>
  );
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({ label, value, min = 0, max = 100, step = 1, unit = '', onChange }) {
  return (
    <TweakRow label={label} value={`${value}${unit}`}>
      <input type="range" className="twk-slider" min={min} max={max} step={step}
             value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </TweakRow>
  );
}

function TweakToggle({ label, value, onChange }) {
  return (
    <div className="twk-row twk-row-h">
      <div className="twk-lbl"><span>{label}</span></div>
      <button type="button" className="twk-toggle" data-on={value ? '1' : '0'}
              role="switch" aria-checked={!!value}
              onClick={() => onChange(!value)}><i /></button>
    </div>
  );
}

function TweakRadio({ label, value, options, onChange }) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = (o) => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({ 2: 16, 3: 10 }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = (s) => {
      const m = options.find((o) => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return <TweakSelect label={label} value={value} options={options}
                        onChange={(s) => onChange(resolve(s))} />;
  }
  const opts = options.map((o) => (typeof o === 'object' ? o : { value: o, label: o }));
  const idx = Math.max(0, opts.findIndex((o) => o.value === value));
  const n = opts.length;

  const segAt = (clientX) => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor(((clientX - r.left - 2) / inner) * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };

  const onPointerDown = (e) => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = (ev) => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <TweakRow label={label}>
      <div ref={trackRef} role="radiogroup" onPointerDown={onPointerDown}
           className={dragging ? 'twk-seg dragging' : 'twk-seg'}>
        <div className="twk-seg-thumb"
             style={{ left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
                      width: `calc((100% - 4px) / ${n})` }} />
        {opts.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={o.value === value}>
            {o.label}
          </button>
        ))}
      </div>
    </TweakRow>
  );
}

function TweakSelect({ label, value, options, onChange }) {
  return (
    <TweakRow label={label}>
      <select className="twk-field" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const v = typeof o === 'object' ? o.value : o;
          const l = typeof o === 'object' ? o.label : o;
          return <option key={v} value={v}>{l}</option>;
        })}
      </select>
    </TweakRow>
  );
}

function TweakText({ label, value, placeholder, onChange }) {
  return (
    <TweakRow label={label}>
      <input className="twk-field" type="text" value={value} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} />
    </TweakRow>
  );
}

function TweakNumber({ label, value, min, max, step = 1, unit = '', onChange }) {
  const clamp = (n) => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({ x: 0, val: 0 });
  const onScrubStart = (e) => {
    e.preventDefault();
    startRef.current = { x: e.clientX, val: value };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = (ev) => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div className="twk-num">
      <span className="twk-num-lbl" onPointerDown={onScrubStart}>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step}
             onChange={(e) => onChange(clamp(Number(e.target.value)))} />
      {unit && <span className="twk-num-unit">{unit}</span>}
    </div>
  );
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, (c) => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}

const __TwkCheck = ({ light }) => (
  <svg viewBox="0 0 14 14" aria-hidden="true">
    <path d="M3 7.2 5.8 10 11 4.2" fill="none" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
          stroke={light ? 'rgba(0,0,0,.78)' : '#fff'} />
  </svg>
);

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({ label, value, options, onChange }) {
  if (!options || !options.length) {
    return (
      <div className="twk-row twk-row-h">
        <div className="twk-lbl"><span>{label}</span></div>
        <input type="color" className="twk-swatch" value={value}
               onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = (o) => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return (
    <TweakRow label={label}>
      <div className="twk-chips" role="radiogroup">
        {options.map((o, i) => {
          const colors = Array.isArray(o) ? o : [o];
          const [hero, ...rest] = colors;
          const sup = rest.slice(0, 4);
          const on = key(o) === cur;
          return (
            <button key={i} type="button" className="twk-chip" role="radio"
                    aria-checked={on} data-on={on ? '1' : '0'}
                    aria-label={colors.join(', ')} title={colors.join(' · ')}
                    style={{ background: hero }}
                    onClick={() => onChange(o)}>
              {sup.length > 0 && (
                <span>
                  {sup.map((c, j) => <i key={j} style={{ background: c }} />)}
                </span>
              )}
              {on && <__TwkCheck light={__twkIsLight(hero)} />}
            </button>
          );
        })}
      </div>
    </TweakRow>
  );
}

function TweakButton({ label, onClick, secondary = false }) {
  return (
    <button type="button" className={secondary ? 'twk-btn secondary' : 'twk-btn'}
            onClick={onClick}>{label}</button>
  );
}

Object.assign(window, {
  useTweaks, TweaksPanel, TweakSection, TweakRow,
  TweakSlider, TweakToggle, TweakRadio, TweakSelect,
  TweakText, TweakNumber, TweakColor, TweakButton,
});

  </script>
  <script type="text/babel" data-presets="react">
/* global React, ReactDOM, Topbar, Hero, Ornament, Steps, Dropzone, OptionRow, ProgressBlock, Terminal, SuccessPanel, FlowCard, TipsCard, Onboarding, useTweaks, TweaksPanel, TweakSection, TweakToggle, TweakButton */
const { useState, useEffect, useRef, useCallback } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "showTips": true,
  "showFlow": true
}/*EDITMODE-END*/;

const ONBOARDING_KEY = "auto-eco:onboarded:v3";

const SAMPLE_NAMES = [
  "ARQ. CARLA MENDES", "ESCRIT. ROCHA & SANTOS", "STUDIO ARQ. M.PEREIRA",
  "ANDRE FERREIRA ARQUITETURA", "CONSTRUTORA VILA RICA",
  "ARQ. BIANCA LOPES", "ROBERTO ALMEIDA", "MARIA EDUARDA TAVARES",
  "ESCRITORIO JARDIM SUL", "CONSTRUMAX LTDA", "ARQ. LUIS GONZAGA",
  "ENG. AMANDA DUARTE", "STUDIO 28 ARQ.", "OLIVEIRA EMPREENDIMENTOS",
];
const SAMPLE_CITIES = ["SAO CARLOS · SP", "RIBEIRAO PRETO · SP", "BAURU · SP", "ARARAQUARA · SP", "CAMPINAS · SP"];

function nowStamp() { return new Date().toLocaleTimeString("pt-BR", { hour12: false }); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [serverStatus, setServerStatus] = useState("checking");
  const [stage, setStage] = useState("idle");
  const [file, setFile] = useState(null);
  const [meetime, setMeetime] = useState(false);
  const [progress, setProgress] = useState({ processed: 0, total: 0, currentLine: "" });
  const [logLines, setLogLines] = useState([]);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [result, setResult] = useState(null);
  const cancelRef = useRef({ cancelled: false });

  useEffect(() => {
    if (!localStorage.getItem(ONBOARDING_KEY)) setShowOnboarding(true);
  }, []);
  useEffect(() => {
    const tick = setTimeout(() => setServerStatus("connected"), 900);
    return () => clearTimeout(tick);
  }, []);

  const pushLog = useCallback((text, kind = "") => {
    setLogLines((l) => [...l, { t: nowStamp(), text, kind }]);
  }, []);

  const closeOnboarding = () => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    setShowOnboarding(false);
  };
  const replayOnboarding = () => {
    localStorage.removeItem(ONBOARDING_KEY);
    setShowOnboarding(true);
  };

  const handlePick = (f) => {
    setFile(f);
    setLogLines([]);
    setResult(null);
    setStage("idle");
    setProgress({ processed: 0, total: 0, currentLine: "" });
    pushLog(`Arquivo selecionado: ${f.name}`, "ok");
  };
  const handleClear = () => {
    setFile(null);
    setStage("idle");
    setResult(null);
    setLogLines([]);
    setProgress({ processed: 0, total: 0, currentLine: "" });
  };

  const handleSubmit = async () => {
    if (!file || stage === "processing") return;
    cancelRef.current = { cancelled: false };
    setStage("uploading");
    setResult(null);
    pushLog(`Iniciando processamento: ${file.name}`);
    pushLog("Enviando arquivo para o servidor…");
    if (meetime) pushLog("Modo Meetime ativado — exportará 1 linha por contato.", "warn");

    await sleep(700);
    if (cancelRef.current.cancelled) return;
    pushLog("Arquivo recebido pelo servidor.", "ok");
    await sleep(500);
    pushLog("Convertendo planilha para .xlsx…");
    await sleep(600);
    pushLog("Lendo linhas de obras e contatos…");

    const total = 47 + Math.floor(Math.random() * 30);
    await sleep(400);
    pushLog(`${total} obras encontradas. Iniciando consultas…`, "ok");
    setStage("processing");
    setProgress({ processed: 0, total, currentLine: "preparando…" });

    let processed = 0, success = 0;
    while (processed < total) {
      if (cancelRef.current.cancelled) return;
      await sleep(110 + Math.random() * 160);
      processed++;
      const name = SAMPLE_NAMES[Math.floor(Math.random() * SAMPLE_NAMES.length)];
      const city = SAMPLE_CITIES[Math.floor(Math.random() * SAMPLE_CITIES.length)];
      const found = Math.random() > 0.18;
      if (found) success++;
      const tag = found ? "OK" : "sem telefone";
      const kind = found ? "ok" : "warn";
      setProgress({
        processed, total,
        currentLine: `${name} · ${city}`,
      });
      if (processed % 4 === 0 || processed === total) {
        pushLog(`${processed}/${total} · ${name.slice(0, 32)} · ${tag}`, kind);
      }
    }

    await sleep(350);
    pushLog("Gerando Excel final…");
    await sleep(500);
    const outputName = (file.name.replace(/\.[^.]+$/, "")) + (meetime ? "_meetime.xlsx" : "_enriquecido.xlsx");
    pushLog(`Concluído: ${success}/${total} obras com telefone encontrado.`, "ok");
    setStage("done");
    setResult({ total, success, outputName });
  };

  const handleDownload = () => {
    pushLog(`Baixando ${result.outputName}…`, "ok");
    const blob = new Blob(["Demo result for " + result.outputName], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = result.outputName;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const percent = progress.total
    ? Math.min(100, Math.round((progress.processed / progress.total) * 100))
    : (stage === "uploading" ? 12 : stage === "done" ? 100 : 0);

  return (
    <>
      {showOnboarding && <Onboarding onClose={closeOnboarding} />}

      <div className="shell">
        <div className="top-stripe" aria-hidden="true">
          <span></span><span></span><span></span><span></span>
        </div>
        <Topbar
          status={serverStatus}
          onHelp={replayOnboarding}
          onSettings={() => alert("Configurações em breve.")}
        />

        <Hero />

        <Ornament />

        <Steps stage={stage === "uploading" ? "uploading" : stage} />

        <div className="card">
          <div className="card-body">
            {(stage === "idle" || stage === "uploading") && (
              <>
                <Dropzone
                  file={file}
                  onPick={handlePick}
                  onClear={handleClear}
                  disabled={stage === "uploading"}
                />
                <OptionRow
                  checked={meetime}
                  onChange={setMeetime}
                  title="Modo Meetime"
                  desc="Exporta 1 linha por contato, abas separadas por cidade, telefones sem formatação — pronto pra importar direto no CRM."
                />
                <div className="cta-row">
                  <button
                    className="btn btn-primary"
                    onClick={handleSubmit}
                    disabled={!file || stage === "uploading"}
                  >
                    {stage === "uploading" ? "Enviando…" : (
                      <>
                        Enriquecer planilha
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="5" y1="12" x2="19" y2="12"></line>
                          <polyline points="12 5 19 12 12 19"></polyline>
                        </svg>
                      </>
                    )}
                  </button>
                </div>
              </>
            )}

            {stage === "processing" && (
              <ProgressBlock
                processed={progress.processed}
                total={progress.total}
                percent={percent}
                currentLine={progress.currentLine}
              />
            )}

            {stage === "done" && result && (
              <SuccessPanel
                result={result}
                onDownload={handleDownload}
                onReset={handleClear}
              />
            )}

            {stage !== "idle" && (
              <Terminal
                lines={logLines}
                open={terminalOpen}
                onToggle={() => setTerminalOpen((v) => !v)}
              />
            )}
          </div>
        </div>

        <div className="side-grid">
          {t.showFlow && <FlowCard stage={stage} />}
          {t.showTips && <TipsCard />}
        </div>

        <footer className="foot">
          <span>Auto ECO · v1.2</span>
          <span>·</span>
          <span>Ecorio · Tintas & Revestimentos</span>
        </footer>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection title="Layout">
          <TweakToggle
            label="Mostrar painel de fluxo"
            value={t.showFlow}
            onChange={(v) => setTweak("showFlow", v)}
          />
          <TweakToggle
            label="Mostrar boas práticas"
            value={t.showTips}
            onChange={(v) => setTweak("showTips", v)}
          />
        </TweakSection>
        <TweakSection title="Demonstração">
          <TweakButton label="Reabrir onboarding" onClick={replayOnboarding} />
          <TweakButton
            label="Rodar simulação"
            onClick={() => {
              if (!file) {
                const fake = new File(["demo"], "Meus_favoritos_demo.xls", { type: "application/vnd.ms-excel" });
                handlePick(fake);
                setTimeout(handleSubmit, 200);
              } else {
                handleSubmit();
              }
            }}
          />
          <TweakButton
            label="Resetar"
            onClick={() => { handleClear(); setLogLines([]); }}
          />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, tags=["Interface"])
async def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/health", tags=["Sistema"])
async def health():
    return {
        "status": "ok",
        "scraper_autenticado": scraper._authenticated,
        "max_obras_por_request": MAX_OBRAS,
        "versao": "1.2.0",
        "modo": "httpx (sem browser)",
    }


def _converter_xls_para_xlsx(conteudo_xls: bytes) -> bytes:
    """Converte .xls legado para .xlsx via LibreOffice."""
    import io
    import shutil

    from openpyxl import Workbook
    from openpyxl.styles import Font

    def converter_com_xlrd() -> bytes:
        try:
            from python_calamine import load_workbook as load_calamine_workbook

            book = load_calamine_workbook(io.BytesIO(conteudo_xls))
            sheet = book.get_sheet_by_index(0)
            rows = list(sheet.iter_rows())
            wb = Workbook()
            ws = wb.active
            ws.title = (book.sheet_names[0] if book.sheet_names else "Planilha")[:31]

            for row_idx, row in enumerate(rows, start=1):
                for col_idx, value in enumerate(row, start=1):
                    ws.cell(row=row_idx, column=col_idx, value=value)

            if ws.max_row >= 4:
                for cell in ws[4]:
                    cell.font = Font(bold=True)

            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            return output.read()
        except Exception as calamine_error:
            logger.warning(f"Falha ao converter .xls com python-calamine: {calamine_error}")

        import xlrd

        book = xlrd.open_workbook(file_contents=conteudo_xls, formatting_info=False)
        sheet = book.sheet_by_index(0)
        wb = Workbook()
        ws = wb.active
        ws.title = sheet.name[:31] or "Planilha"

        for row_idx in range(sheet.nrows):
            for col_idx in range(sheet.ncols):
                cell = sheet.cell(row_idx, col_idx)
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate.xldate_as_datetime(value, book.datemode)
                    except Exception:
                        pass
                elif cell.ctype == xlrd.XL_CELL_NUMBER and float(value).is_integer():
                    value = int(value)
                ws.cell(row=row_idx + 1, column=col_idx + 1, value=value)

        if ws.max_row >= 4:
            for cell in ws[4]:
                cell.font = Font(bold=True)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.read()

    if not shutil.which("libreoffice"):
        return converter_com_xlrd()

    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp_in:
        tmp_in.write(conteudo_xls)
        tmp_path = tmp_in.name

    out_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "xlsx",
             "--outdir", out_dir, tmp_path],
            capture_output=True, timeout=60, check=True,
        )
        import os, glob
        xlsx_files = glob.glob(os.path.join(out_dir, "*.xlsx"))
        if not xlsx_files:
            raise RuntimeError("LibreOffice não gerou arquivo .xlsx")
        with open(xlsx_files[0], "rb") as f:
            return f.read()
    finally:
        import os, shutil
        try:
            os.unlink(tmp_path)
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass


def _converter_csv_para_xlsx(conteudo_csv: bytes) -> bytes:
    """Converte CSV exportado do Mais Obras para .xlsx, detectando encoding automaticamente."""
    import csv

    texto: str | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            texto = conteudo_csv.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("Nao foi possivel decodificar o CSV.")

    leitor = csv.reader(io.StringIO(texto))
    linhas = list(leitor)
    if not linhas:
        raise ValueError("CSV vazio.")

    wb_csv = openpyxl.Workbook()
    ws_csv = wb_csv.active
    ws_csv.title = "Planilha"

    # Se o cabecalho real esta na linha 1 (sem titulo), insere as 3 linhas do padrao Mais Obras
    primeira = [str(v).lower() for v in linhas[0]]
    if any("profissional" in v for v in primeira):
        ws_csv.append(["Meus Favoritos"])
        ws_csv.append([])
        ws_csv.append([])

    for linha in linhas:
        ws_csv.append(linha)

    if ws_csv.max_row >= 4:
        from openpyxl.styles import Font as _Font
        for cell in ws_csv[4]:
            cell.font = _Font(bold=True)

    output = io.BytesIO()
    wb_csv.save(output)
    output.seek(0)
    return output.read()


async def _processar_job(job_id: str, filename: str, conteudo: bytes, modo_meetime: bool = False):
    job = jobs[job_id]
    try:
        job.update(status="running", message="Preparando arquivo...", current_line="Preparando arquivo...")

        if modo_meetime:
            job.update(current_line="Modo Meetime ativado: exportara 1 linha por contato, separado por cidade.")

        ext = (filename or "").lower().rsplit(".", 1)[-1]
        if ext == "xls":
            job.update(message="Convertendo .xls para .xlsx...", current_line="Convertendo .xls para .xlsx...")
            conteudo = _converter_xls_para_xlsx(conteudo)
        elif ext == "csv":
            job.update(message="Convertendo .csv para .xlsx...", current_line="Convertendo .csv para .xlsx...")
            conteudo = _converter_csv_para_xlsx(conteudo)

        job.update(message="Lendo planilha...", current_line="Lendo planilha...")
        wb, obras = carregar_excel(conteudo)

        if not obras:
            raise ValueError("Nenhuma obra encontrada no arquivo.")
        if len(obras) > MAX_OBRAS:
            raise ValueError(f"O arquivo tem {len(obras)} obras, limite é {MAX_OBRAS}.")

        job.update(
            total=len(obras),
            processed=0,
            message=f"{len(obras)} obras encontradas.",
            current_line=f"{len(obras)} obras encontradas. Iniciando consultas...",
        )

        def progress_callback(obra, contato):
            processed = int(job.get("processed", 0)) + 1
            nome = obra.nome_profissional or obra.nome_proprietario or "sem nome"
            status = "OK" if (contato.tel_arq_1 or contato.tel_prop_1) else "sem telefone"
            job.update(
                processed=processed,
                current_row=obra.row_index,
                current_contact=nome,
                current_line=(
                    f"Linha {obra.row_index} | {processed}/{len(obras)} | "
                    f"{nome[:55]} | {status}"
                ),
            )

        contatos = await scraper.processar_lote(obras, progress_callback=progress_callback)

        job.update(message="Gerando Excel final...", current_line="Gerando Excel final...")
        if modo_meetime:
            excel_bytes = gerar_meetime_excel(obras, contatos)
            nome_saida = (filename or "favoritos").rsplit(".", 1)[0] + "_meetime.xlsx"
        else:
            excel_bytes = enriquecer_excel(wb, obras, contatos)
            nome_saida = (filename or "favoritos").rsplit(".", 1)[0] + "_enriquecido.xlsx"

        sucesso = sum(1 for c in contatos if c.tel_arq_1 or c.tel_prop_1)
        job.update(
            status="done",
            result=excel_bytes,
            output_name=nome_saida,
            current_line=f"Concluido: {sucesso}/{len(contatos)} linhas com telefone encontrado.",
            message="Concluido.",
        )
    except Exception as e:
        logger.exception("Falha no job de enriquecimento")
        job.update(status="failed", error=str(e), current_line=f"Erro: {e}", message="Falha.")


@app.post("/enriquecer_async", tags=["Enriquecimento"])
async def enriquecer_async(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    modo_meetime: str = Form("0"),
    _token: str = Security(verificar_token),
):
    if not scraper._authenticated:
        raise HTTPException(503, "Scraper não autenticado.")

    ext = (arquivo.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ("xls", "xlsx", "xlsm", "csv"):
        raise HTTPException(400, "Envie um arquivo .xls, .xlsx ou .csv exportado do Mais Obras.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")

    job_id = uuid.uuid4().hex
    jobs[job_id] = {
        "status": "queued",
        "filename": arquivo.filename or "favoritos",
        "total": 0,
        "processed": 0,
        "current_row": None,
        "current_contact": "",
        "current_line": "Na fila para processamento...",
        "message": "Na fila.",
        "result": None,
        "output_name": "",
        "error": "",
    }
    meetime = modo_meetime.strip() in ("1", "true", "on", "yes")
    background_tasks.add_task(_processar_job, job_id, arquivo.filename or "favoritos", conteudo, meetime)
    return {"job_id": job_id}


@app.get("/progresso/{job_id}", tags=["Enriquecimento"])
async def progresso(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "total": job.get("total", 0),
        "processed": job.get("processed", 0),
        "current_row": job.get("current_row"),
        "current_contact": job.get("current_contact"),
        "current_line": job.get("current_line"),
        "message": job.get("message"),
        "error": job.get("error"),
    }


@app.get("/resultado/{job_id}", tags=["Enriquecimento"])
async def resultado(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")
    if job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, "Resultado ainda não está pronto.")

    return Response(
        content=job["result"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{job.get("output_name") or "Meus_favoritos_enriquecido.xlsx"}"'},
    )


@app.post(
    "/enriquecer",
    tags=["Enriquecimento"],
    response_class=Response,
    summary="Enriquece o Excel com telefones e e-mails",
    responses={
        200: {"description": "Excel enriquecido (.xlsx)"},
        400: {"description": "Arquivo inválido"},
        401: {"description": "Token inválido"},
        429: {"description": "Limite de obras excedido"},
        503: {"description": "Scraper não autenticado"},
    },
)
async def enriquecer(
    arquivo: UploadFile = File(
        ...,
        description="Arquivo 'Meus_favoritos.xls' exportado do Mais Obras"
    ),
    modo_meetime: str = Form("0"),
    _token: str = Security(verificar_token),
):
    """
    Recebe o Excel de favoritos exportado do Mais Obras,
    consulta o endpoint /pesquisa_perfil para cada obra,
    e devolve o Excel com 7 novas colunas de contato.
    """
    if not scraper._authenticated:
        raise HTTPException(
            503,
            "Scraper não autenticado. "
            "Configure MAISOBRAS_EMAIL e MAISOBRAS_PASSWORD e chame POST /reautenticar.",
        )

    ext = (arquivo.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ("xls", "xlsx", "xlsm", "csv"):
        raise HTTPException(400, "Envie um arquivo .xls, .xlsx ou .csv exportado do Mais Obras.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")

    # Converte formatos legados/alternativos para .xlsx
    if ext == "xls":
        try:
            conteudo = _converter_xls_para_xlsx(conteudo)
        except Exception as e:
            raise HTTPException(400, f"Erro ao converter .xls para .xlsx: {e}")
    elif ext == "csv":
        try:
            conteudo = _converter_csv_para_xlsx(conteudo)
        except Exception as e:
            raise HTTPException(400, f"Erro ao converter .csv para .xlsx: {e}")

    # Carrega e valida estrutura do Excel
    try:
        wb, obras = carregar_excel(conteudo)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Erro ao ler arquivo: {e}")

    if not obras:
        raise HTTPException(400, "Nenhuma obra encontrada no arquivo.")

    if len(obras) > MAX_OBRAS:
        raise HTTPException(
            429,
            f"O arquivo tem {len(obras)} obras, limite é {MAX_OBRAS}. "
            "Divida em arquivos menores ou aumente MAX_OBRAS_PER_REQUEST no Railway.",
        )

    logger.info(f"Enriquecendo {len(obras)} obras de '{arquivo.filename}'...")

    # Coleta contatos via API
    contatos = await scraper.processar_lote(obras)

    # Gera Excel enriquecido
    meetime = modo_meetime.strip() in ("1", "true", "on", "yes")
    try:
        if meetime:
            excel_bytes = gerar_meetime_excel(obras, contatos)
        else:
            excel_bytes = enriquecer_excel(wb, obras, contatos)
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar arquivo: {e}")

    sucesso = sum(1 for c in contatos if c.tel_arq_1 or c.tel_prop_1)
    logger.info(f"Concluído: {sucesso}/{len(contatos)} obras com telefone encontrado.")

    sufixo = "_meetime.xlsx" if meetime else "_enriquecido.xlsx"
    nome_saida = (arquivo.filename or "favoritos").rsplit(".", 1)[0] + sufixo

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_saida}"'},
    )


@app.post("/reautenticar", tags=["Sistema"])
async def reautenticar(_token: str = Security(verificar_token)):
    """Força novo login no Mais Obras (usar quando a sessão expirar)."""
    if not MAISOBRAS_EMAIL or not MAISOBRAS_PASSWORD:
        raise HTTPException(400, "Configure MAISOBRAS_EMAIL e MAISOBRAS_PASSWORD.")
    ok = await scraper.login(MAISOBRAS_EMAIL, MAISOBRAS_PASSWORD)
    if ok:
        return {"status": "autenticado"}
    raise HTTPException(503, "Falha na autenticação. Verifique as credenciais.")
