"""
test_server.py — Servidor local de teste na porta 4000
=======================================================

Roda o pipeline completo localmente ANTES de fazer deploy no Railway.

Modos:
  --mock    Usa dados falsos (sem precisar de credenciais do Mais Obras)
  --real    Usa credenciais reais do .env (testa a API de verdade)

Como usar:
  python test_server.py --mock          # sem credenciais, dados fictícios
  python test_server.py --real          # com .env preenchido

Acesse: http://localhost:4000
"""

import argparse
import asyncio
import io
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path

import openpyxl
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modo de operação
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Servidor de teste Mais Obras Enricher")
parser.add_argument("--mock", action="store_true", help="Usa dados fictícios (sem credenciais)")
parser.add_argument("--real", action="store_true", help="Usa credenciais reais do .env")
parser.add_argument("--port", type=int, default=4000)
args, _ = parser.parse_known_args()

MOCK_MODE = args.mock or not args.real

if MOCK_MODE:
    logger.info("🟡 Modo MOCK ativo — dados fictícios, sem conexão com o Mais Obras")
else:
    logger.info("🟢 Modo REAL ativo — usando credenciais do .env")

# ---------------------------------------------------------------------------
# Importa módulos do projeto (excel_handler + scraper)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
from excel_handler import carregar_excel, enriquecer_excel
from scraper import ContatoObra, MaisObrasScraper

# ---------------------------------------------------------------------------
# Mock scraper
# ---------------------------------------------------------------------------
TELEFONES_MOCK = [
    "11 99999-0001", "11 99999-0002", "16 98888-1001", "16 98888-1002",
    "14 97777-2001", "14 97777-2002", "17 96666-3001", "18 95555-4001",
]
EMAILS_MOCK = [
    "arquiteto@escritorio.com.br", "contato@arqdesign.com",
    "proprietario@gmail.com", "cliente@empresa.com.br",
]

class MockScraper:
    _authenticated = True

    async def start(self): pass
    async def stop(self): pass
    async def login(self, *a): return True

    async def processar_lote(self, obras: list, **kw) -> list[ContatoObra]:
        resultados = []
        for obra in obras:
            # 80% tem telefone, 15% sem cadastro, 5% erro
            roll = random.random()
            c = ContatoObra(chave=obra.chave, row_index=obra.row_index)
            c.nome_arquiteto = obra.nome_profissional
            c.nome_proprietario = obra.nome_proprietario
            if roll < 0.80:
                tels = random.sample(TELEFONES_MOCK, k=random.randint(1, 2))
                c.tel_arq_1 = tels[0]
                if len(tels) > 1:
                    c.tel_arq_2 = tels[1]
                c.email_arq = random.choice(EMAILS_MOCK)
                tels2 = random.sample(TELEFONES_MOCK, k=random.randint(1, 2))
                c.tel_prop_1 = tels2[0]
                if len(tels2) > 1:
                    c.tel_prop_2 = tels2[1]
            elif roll < 0.95:
                pass  # sem telefone cadastrado
            else:
                c.erro = "Timeout ao consultar perfil"
            resultados.append(c)
            await asyncio.sleep(0.01)  # simula latência
        return resultados

# ---------------------------------------------------------------------------
# Escolhe scraper
# ---------------------------------------------------------------------------
scraper = MockScraper() if MOCK_MODE else MaisObrasScraper()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await scraper.start()
    if not MOCK_MODE:
        email = os.getenv("MAISOBRAS_EMAIL", "")
        pwd = os.getenv("MAISOBRAS_PASSWORD", "")
        if email and pwd:
            ok = await scraper.login(email, pwd)
            logger.info("Login: " + ("OK ✓" if ok else "FALHOU ✗"))
        else:
            logger.warning("Credenciais não encontradas no .env")
    yield
    await scraper.stop()

app = FastAPI(title="Test Server — Mais Obras Enricher", lifespan=lifespan)

# ---------------------------------------------------------------------------
# UI HTML
# ---------------------------------------------------------------------------
HTML = """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mais Obras Enricher — Teste Local</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #f0f2f5;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
    color: #1a1a2e;
  }

  .card {
    background: #fff;
    border-radius: 16px;
    padding: 36px 40px;
    width: 100%;
    max-width: 680px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    margin-bottom: 24px;
  }

  .badge-mode {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 999px;
    margin-bottom: 20px;
    letter-spacing: 0.04em;
  }
  .badge-mock { background: #FEF3C7; color: #92400E; }
  .badge-real { background: #D1FAE5; color: #065F46; }

  h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; color: #1a1a2e; }
  .subtitle { font-size: 13px; color: #6b7280; margin-bottom: 28px; }

  .drop-zone {
    border: 2px dashed #d1d5db;
    border-radius: 12px;
    padding: 40px 24px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    background: #fafafa;
    position: relative;
  }
  .drop-zone:hover, .drop-zone.drag-over {
    border-color: #6366f1;
    background: #eef2ff;
  }
  .drop-zone input[type=file] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .drop-icon { font-size: 36px; margin-bottom: 12px; }
  .drop-title { font-size: 15px; font-weight: 600; color: #374151; margin-bottom: 4px; }
  .drop-sub { font-size: 13px; color: #9ca3af; }
  .file-selected { font-size: 13px; color: #6366f1; font-weight: 600; margin-top: 8px; }

  .btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 12px 28px; border-radius: 10px;
    font-size: 14px; font-weight: 600; cursor: pointer;
    border: none; transition: all 0.15s;
    width: 100%; justify-content: center; margin-top: 16px;
  }
  .btn-primary {
    background: #6366f1; color: #fff;
  }
  .btn-primary:hover { background: #4f46e5; transform: translateY(-1px); }
  .btn-primary:disabled { background: #a5b4fc; cursor: not-allowed; transform: none; }
  .btn-download {
    background: #10b981; color: #fff; text-decoration: none;
  }
  .btn-download:hover { background: #059669; transform: translateY(-1px); }

  .progress-wrap {
    background: #e5e7eb; border-radius: 999px; height: 6px; margin: 16px 0 4px; overflow: hidden;
  }
  .progress-bar {
    height: 100%; border-radius: 999px; background: #6366f1;
    width: 0; transition: width 0.3s ease;
  }
  .progress-label { font-size: 12px; color: #6b7280; }

  .result-card {
    background: #fff;
    border-radius: 16px;
    padding: 28px 32px;
    width: 100%;
    max-width: 680px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    display: none;
  }
  .result-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; }

  .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
  .stat { background: #f9fafb; border-radius: 10px; padding: 12px; text-align: center; }
  .stat-num { font-size: 22px; font-weight: 700; }
  .stat-lbl { font-size: 11px; color: #6b7280; margin-top: 2px; }

  .preview-table { width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 8px; }
  .preview-table th {
    background: #f3f4f6; padding: 8px 10px; text-align: left;
    font-size: 11px; color: #374151; border-bottom: 1px solid #e5e7eb;
    white-space: nowrap;
  }
  .preview-table td {
    padding: 7px 10px; border-bottom: 1px solid #f3f4f6; color: #374151;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;
  }
  .preview-table tr:hover td { background: #f9fafb; }

  .tag { display: inline-block; font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 999px; }
  .tag-ok { background: #D1FAE5; color: #065F46; }
  .tag-sem { background: #FEF3C7; color: #92400E; }
  .tag-erro { background: #FEE2E2; color: #991B1B; }

  .log-box {
    background: #1e1e2e; color: #cdd6f4; border-radius: 10px;
    padding: 16px; font-family: 'Courier New', monospace; font-size: 12px;
    max-height: 200px; overflow-y: auto; margin-top: 16px; line-height: 1.6;
  }
  .log-ok { color: #a6e3a1; }
  .log-warn { color: #f9e2af; }
  .log-err { color: #f38ba8; }

  .health-bar {
    display: flex; gap: 8px; align-items: center;
    font-size: 12px; color: #6b7280; margin-bottom: 24px; flex-wrap: wrap;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; }
  .dot-green { background: #10b981; }
  .dot-red { background: #ef4444; }
  .dot-yellow { background: #f59e0b; }
</style>
</head>
<body>

<div class="card">
  <div class="badge-mode __BADGE_CLASS__">__BADGE_ICON__ __BADGE_TEXT__</div>
  <h1>Mais Obras Enricher</h1>
  <p class="subtitle">Servidor local de teste — porta 4000</p>

  <div class="health-bar" id="healthBar">
    <span class="dot dot-yellow"></span> Verificando conexão...
  </div>

  <div class="drop-zone" id="dropZone">
    <input type="file" id="fileInput" accept=".xls,.xlsx">
    <div class="drop-icon">📂</div>
    <div class="drop-title">Arraste o arquivo aqui ou clique para selecionar</div>
    <div class="drop-sub">Meus_favoritos.xls exportado do Mais Obras</div>
    <div class="file-selected" id="fileLabel" style="display:none"></div>
  </div>

  <div class="progress-wrap" id="progressWrap" style="display:none">
    <div class="progress-bar" id="progressBar"></div>
  </div>
  <div class="progress-label" id="progressLabel"></div>

  <button class="btn btn-primary" id="btnEnriquecer" disabled onclick="enriquecer()">
    ⚡ Enriquecer Excel
  </button>
</div>

<div class="result-card" id="resultCard">
  <div class="result-title">✅ Enriquecimento concluído</div>

  <div class="stat-grid">
    <div class="stat"><div class="stat-num" id="stTotal" style="color:#6366f1">0</div><div class="stat-lbl">Total obras</div></div>
    <div class="stat"><div class="stat-num" id="stOk" style="color:#10b981">0</div><div class="stat-lbl">Com telefone</div></div>
    <div class="stat"><div class="stat-num" id="stSem" style="color:#f59e0b">0</div><div class="stat-lbl">Sem cadastro</div></div>
    <div class="stat"><div class="stat-num" id="stErro" style="color:#ef4444">0</div><div class="stat-lbl">Com erro</div></div>
  </div>

  <div style="overflow-x:auto">
    <table class="preview-table" id="previewTable">
      <thead>
        <tr>
          <th>Profissional</th>
          <th>Proprietário</th>
          <th>Cidade</th>
          <th>Tel Arq</th>
          <th>Tel Prop</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="previewBody"></tbody>
    </table>
  </div>

  <div class="log-box" id="logBox"></div>

  <a class="btn btn-download" id="btnDownload" href="#" download>
    ⬇️ Baixar Excel Enriquecido
  </a>
</div>

<script>
const fileInput = document.getElementById('fileInput');
const fileLabel = document.getElementById('fileLabel');
const btnEnriquecer = document.getElementById('btnEnriquecer');
const dropZone = document.getElementById('dropZone');
let selectedFile = null;
let downloadBlob = null;

// Health check
async function checkHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    const hb = document.getElementById('healthBar');
    const auth = d.scraper_autenticado;
    const modo = d.modo || '';
    hb.innerHTML = `
      <span class="dot ${auth ? 'dot-green' : 'dot-red'}"></span>
      Scraper: <strong>${auth ? 'autenticado ✓' : 'não autenticado ✗'}</strong>
      &nbsp;|&nbsp; Modo: <strong>${modo}</strong>
      &nbsp;|&nbsp; Limite: <strong>${d.max_obras_por_request} obras/req</strong>
    `;
  } catch(e) {
    document.getElementById('healthBar').innerHTML =
      '<span class="dot dot-red"></span> Servidor não respondeu';
  }
}
checkHealth();

// Drag & drop
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

function setFile(f) {
  selectedFile = f;
  fileLabel.textContent = `📄 ${f.name} (${(f.size/1024).toFixed(1)} KB)`;
  fileLabel.style.display = 'block';
  btnEnriquecer.disabled = false;
}

function addLog(msg, type='ok') {
  const box = document.getElementById('logBox');
  const span = document.createElement('span');
  span.className = `log-${type}`;
  const time = new Date().toLocaleTimeString('pt-BR');
  span.textContent = `[${time}] ${msg}\n`;
  box.appendChild(span);
  box.scrollTop = box.scrollHeight;
}

async function enriquecer() {
  if (!selectedFile) return;

  btnEnriquecer.disabled = true;
  btnEnriquecer.textContent = '⏳ Processando...';
  document.getElementById('progressWrap').style.display = 'block';
  document.getElementById('progressLabel').textContent = 'Enviando arquivo...';
  document.getElementById('resultCard').style.display = 'none';
  document.getElementById('logBox').innerHTML = '';

  const pb = document.getElementById('progressBar');
  pb.style.width = '10%';

  // Simula progresso enquanto aguarda
  let prog = 10;
  const timer = setInterval(() => {
    prog = Math.min(prog + Math.random() * 8, 88);
    pb.style.width = prog + '%';
    const obras = Math.floor(prog / 2);
    document.getElementById('progressLabel').textContent =
      `Consultando contatos... ~${obras} obras processadas`;
  }, 800);

  try {
    addLog(`Enviando ${selectedFile.name} (${(selectedFile.size/1024).toFixed(1)} KB)...`);
    const fd = new FormData();
    fd.append('arquivo', selectedFile);

    const r = await fetch('/enriquecer', { method: 'POST', body: fd });

    clearInterval(timer);
    pb.style.width = '100%';

    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      addLog(`Erro ${r.status}: ${err.detail}`, 'err');
      document.getElementById('progressLabel').textContent = '❌ Erro no processamento';
      btnEnriquecer.disabled = false;
      btnEnriquecer.textContent = '⚡ Enriquecer Excel';
      return;
    }

    const blob = await r.blob();
    downloadBlob = blob;

    // Lê o resumo da resposta (JSON no header se implementado, ou via /resumo)
    const resumo = await fetch('/ultimo_resumo').then(r => r.json()).catch(() => null);
    if (resumo) mostrarResultado(resumo, blob);
    else mostrarResultadoSimples(blob);

  } catch(e) {
    clearInterval(timer);
    addLog(`Erro de rede: ${e.message}`, 'err');
    document.getElementById('progressLabel').textContent = '❌ Falha na requisição';
  } finally {
    btnEnriquecer.disabled = false;
    btnEnriquecer.textContent = '⚡ Enriquecer Excel';
  }
}

function mostrarResultado(resumo, blob) {
  document.getElementById('stTotal').textContent = resumo.total;
  document.getElementById('stOk').textContent = resumo.com_telefone;
  document.getElementById('stSem').textContent = resumo.sem_telefone;
  document.getElementById('stErro').textContent = resumo.com_erro;

  const tbody = document.getElementById('previewBody');
  tbody.innerHTML = '';
  (resumo.preview || []).slice(0, 10).forEach(row => {
    const tr = document.createElement('tr');
    const statusClass = row.status === 'OK' ? 'tag-ok' : (row.status.startsWith('Erro') ? 'tag-erro' : 'tag-sem');
    tr.innerHTML = `
      <td title="${row.profissional}">${row.profissional.slice(0,22)}</td>
      <td title="${row.proprietario}">${row.proprietario.slice(0,22)}</td>
      <td>${row.cidade}</td>
      <td>${row.tel_arq || '—'}</td>
      <td>${row.tel_prop || '—'}</td>
      <td><span class="tag ${statusClass}">${row.status}</span></td>
    `;
    tbody.appendChild(tr);
  });

  addLog(`Total: ${resumo.total} obras | Com telefone: ${resumo.com_telefone} | Sem: ${resumo.sem_telefone} | Erros: ${resumo.com_erro}`, 'ok');
  if (resumo.com_telefone > 0)
    addLog(`Taxa de sucesso: ${Math.round(resumo.com_telefone/resumo.total*100)}%`, 'ok');

  const url = URL.createObjectURL(blob);
  const nome = selectedFile.name.replace(/[.](xls|xlsx)$/i, '_enriquecido.xlsx');
  const dl = document.getElementById('btnDownload');
  dl.href = url;
  dl.download = nome;

  document.getElementById('resultCard').style.display = 'block';
  document.getElementById('progressLabel').textContent = `✅ Concluído — ${resumo.total} obras processadas`;
  document.getElementById('resultCard').scrollIntoView({ behavior: 'smooth' });
}

function mostrarResultadoSimples(blob) {
  addLog('Arquivo enriquecido recebido — baixando...', 'ok');
  const url = URL.createObjectURL(blob);
  const nome = selectedFile.name.replace(/[.](xls|xlsx)$/i, '_enriquecido.xlsx');
  const dl = document.getElementById('btnDownload');
  dl.href = url;
  dl.download = nome;
  document.getElementById('resultCard').style.display = 'block';
  document.getElementById('progressLabel').textContent = '✅ Arquivo pronto para download';
  document.getElementById('resultCard').scrollIntoView({ behavior: 'smooth' });
}
</script>
</body>
</html>
"""

# Injeta classe do badge conforme modo
if MOCK_MODE:
    HTML_RENDERED = HTML.replace("__BADGE_CLASS__", "badge-mock") \
                        .replace("__BADGE_ICON__", "🟡") \
                        .replace("__BADGE_TEXT__", "MODO MOCK — Dados fictícios")
else:
    HTML_RENDERED = HTML.replace("__BADGE_CLASS__", "badge-real") \
                        .replace("__BADGE_ICON__", "🟢") \
                        .replace("__BADGE_TEXT__", "MODO REAL — Conectado ao Mais Obras")


# ---------------------------------------------------------------------------
# Estado global para o resumo da última requisição
# ---------------------------------------------------------------------------
_ultimo_resumo: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTML_RENDERED


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "scraper_autenticado": scraper._authenticated,
        "max_obras_por_request": int(os.getenv("MAX_OBRAS_PER_REQUEST", "100")),
        "versao": "1.2.0 (test)",
        "modo": "mock (dados fictícios)" if MOCK_MODE else "httpx (Mais Obras real)",
    }


@app.get("/ultimo_resumo")
async def ultimo_resumo():
    return _ultimo_resumo


def _converter_xls_para_xlsx(conteudo: bytes) -> bytes:
    """Converte .xls → .xlsx via LibreOffice."""
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as f:
        f.write(conteudo)
        tmp_path = f.name
    out_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "xlsx",
             "--outdir", out_dir, tmp_path],
            capture_output=True, timeout=60, check=True,
        )
        import glob
        xlsx = glob.glob(os.path.join(out_dir, "*.xlsx"))
        if not xlsx:
            raise RuntimeError("LibreOffice não gerou .xlsx")
        with open(xlsx[0], "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.post("/enriquecer")
async def enriquecer(arquivo: UploadFile = File(...)):
    global _ultimo_resumo

    ext = (arquivo.filename or "").lower().rsplit(".", 1)[-1]
    conteudo = await arquivo.read()

    if ext == "xls":
        try:
            conteudo = _converter_xls_para_xlsx(conteudo)
        except Exception as e:
            return JSONResponse({"detail": f"Erro ao converter .xls: {e}"}, status_code=400)

    try:
        wb, obras = carregar_excel(conteudo)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)

    if not obras:
        return JSONResponse({"detail": "Nenhuma obra encontrada."}, status_code=400)

    logger.info(f"Processando {len(obras)} obras...")
    contatos = await scraper.processar_lote(obras)

    # Gera Excel enriquecido
    excel_bytes = enriquecer_excel(wb, obras, contatos)

    # Monta resumo para a UI
    preview = []
    for obra, c in zip(obras[:10], contatos[:10]):
        status = "OK" if (c.tel_arq_1 or c.tel_prop_1) else (
            f"Erro: {c.erro[:40]}" if c.erro else "Sem telefone cadastrado"
        )
        preview.append({
            "profissional": obra.nome_profissional,
            "proprietario": obra.nome_proprietario,
            "cidade": obra.cidade,
            "tel_arq": c.tel_arq_1,
            "tel_prop": c.tel_prop_1,
            "status": status,
        })

    _ultimo_resumo = {
        "total": len(contatos),
        "com_telefone": sum(1 for c in contatos if c.tel_arq_1 or c.tel_prop_1),
        "sem_telefone": sum(1 for c in contatos if not c.tel_arq_1 and not c.tel_prop_1 and not c.erro),
        "com_erro": sum(1 for c in contatos if c.erro),
        "preview": preview,
    }

    nome_saida = (arquivo.filename or "favoritos").rsplit(".", 1)[0] + "_enriquecido.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_saida}"'},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = args.port
    print()
    print("=" * 55)
    print(f"  🚀  Mais Obras Enricher — Servidor de Teste")
    print(f"  📍  http://localhost:{port}")
    print(f"  🔧  Modo: {'MOCK (dados fictícios)' if MOCK_MODE else 'REAL (Mais Obras)'}")
    print(f"  📄  Acesse o navegador e faça upload do .xls")
    print("=" * 55)
    print()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
