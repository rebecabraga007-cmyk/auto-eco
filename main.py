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
  <title>Auto ECO</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #251517;
      --muted: #6f5d5f;
      --line: #e6ddd6;
      --panel: #ffffff;
      --page: #f8f5ef;
      --wine: #56181b;
      --wine-dark: #3d1013;
      --wine-soft: #7b3033;
      --gold: #cbb068;
      --gold-dark: #a98d46;
      --cream: #fffaf0;
      --ok-bg: #f1f8ef;
      --warn-bg: #fff6df;
      --err-bg: #fdecea;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      background:
        linear-gradient(180deg, rgba(86, 24, 27, .08), rgba(203, 176, 104, .08) 42%, var(--page) 100%);
      color: var(--ink);
    }
    .shell {
      width: min(1040px, calc(100% - 32px));
      margin: 0 auto;
      padding: 30px 0 42px;
    }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 18px;
      margin-bottom: 18px;
      padding: 18px;
      border: 1px solid rgba(86, 24, 27, .12);
      border-radius: 8px;
      background: rgba(255, 255, 255, .78);
      box-shadow: 0 16px 38px rgba(86, 24, 27, .08);
    }
    .brand-lockup {
      display: flex;
      align-items: center;
      gap: 16px;
      min-width: 0;
    }
    .brand-lockup > div {
      flex: 1 1 0;
      min-width: 0;
    }
    .brand-logo-img {
      flex-shrink: 0;
      width: 80px;
      height: 80px;
      object-fit: contain;
      border-radius: 8px;
      background: #fff;
      padding: 6px;
      border: 1px solid rgba(203, 176, 104, .6);
    }
    .wordmark {
      display: block;
      width: auto;
      max-width: 240px;
      height: auto;
      margin-bottom: 4px;
    }
    h1 {
      margin: 0;
      font-size: clamp(25px, 4vw, 38px);
      line-height: 1.05;
      letter-spacing: 0;
      color: var(--wine);
    }
    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.45;
    }
    .status-pill {
      min-width: 230px;
      border: 1px solid rgba(203, 176, 104, .55);
      background: var(--cream);
      border-radius: 8px;
      padding: 12px 14px;
      font-size: 14px;
      color: var(--muted);
    }
    .status-pill strong {
      display: block;
      color: var(--ink);
      font-size: 15px;
      margin-bottom: 3px;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(280px, .9fr);
      gap: 18px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgba(86, 24, 27, .09);
    }
    .upload-panel { padding: 18px; }
    .dropzone {
      min-height: 250px;
      border: 2px dashed rgba(86, 24, 27, .35);
      border-radius: 8px;
      display: grid;
      place-items: center;
      padding: 22px;
      text-align: center;
      background: linear-gradient(180deg, #fffdf8, #fff8ec);
      transition: border-color .18s ease, background .18s ease;
    }
    .dropzone.dragover {
      border-color: var(--gold);
      background: #fff4d8;
    }
    .file-icon {
      width: 66px;
      height: 82px;
      margin: 0 auto 14px;
      border: 2px solid var(--wine);
      border-radius: 6px;
      position: relative;
      background: #fff;
    }
    .file-icon::after {
      content: "";
      position: absolute;
      right: -2px;
      top: -2px;
      width: 20px;
      height: 20px;
      border-left: 2px solid var(--wine);
      border-bottom: 2px solid var(--wine);
      background: #f5e8bf;
    }
    .dropzone h2 {
      margin: 0 0 8px;
      font-size: 22px;
      letter-spacing: 0;
      color: var(--wine);
    }
    .file-name {
      min-height: 24px;
      margin: 12px 0 0;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    input[type="file"] {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }
    button, .choose, .download-btn {
      border: 0;
      border-radius: 8px;
      min-height: 46px;
      padding: 0 18px;
      font-weight: 700;
      font-size: 15px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
    }
    .choose {
      background: #f2e7c7;
      color: var(--wine);
      border: 1px solid rgba(203, 176, 104, .75);
    }
    .primary {
      background: var(--wine);
      color: #fff;
      min-width: 210px;
      box-shadow: 0 9px 18px rgba(86, 24, 27, .22);
    }
    .primary:hover { background: var(--wine-dark); }
    .primary:disabled {
      cursor: not-allowed;
      background: #b8a9a0;
      box-shadow: none;
    }
    .download-btn {
      background: var(--gold);
      color: var(--wine);
      border: 1px solid var(--gold-dark);
      min-width: 190px;
      box-shadow: 0 9px 18px rgba(203, 176, 104, .24);
    }
    .download-btn.disabled {
      pointer-events: none;
      cursor: not-allowed;
      opacity: .48;
      background: #efe5cf;
      color: #8c7a66;
      border-color: #e1d1aa;
    }
    .side {
      padding: 16px;
    }
    .side h2 {
      margin: 0 0 12px;
      font-size: 18px;
      letter-spacing: 0;
    }
    .steps {
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .steps li {
      display: grid;
      grid-template-columns: 34px 1fr;
      gap: 10px;
      align-items: center;
      min-height: 48px;
      color: var(--muted);
    }
    .steps span {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: #e9f2f5;
      color: var(--wine);
      font-weight: 700;
    }
    .message {
      margin-top: 14px;
      padding: 12px 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #f9fbfc;
      min-height: 46px;
      line-height: 1.4;
    }
    .message.ok { background: var(--ok-bg); color: #2d6b3f; border-color: #b8e2ca; }
    .message.warn { background: var(--warn-bg); color: #73520b; border-color: #d9bd6f; }
    .message.err { background: var(--err-bg); color: #923322; border-color: #f0b6ad; }
    .terminal {
      margin-top: 16px;
      border: 1px solid #2f171a;
      border-radius: 8px;
      overflow: hidden;
      background: #130b0c;
      color: #f4e8c4;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04);
    }
    .terminal-head {
      min-height: 36px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 0 12px;
      background: #56181b;
      border-bottom: 1px solid #2f171a;
      color: #f1ddb0;
      font-size: 13px;
      font-weight: 700;
    }
    .terminal-lights {
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }
    .terminal-lights span {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      display: inline-block;
      background: #8d6f42;
    }
    .terminal-lights span:nth-child(1) { background: #d85c47; }
    .terminal-lights span:nth-child(2) { background: #b58414; }
    .terminal-lights span:nth-child(3) { background: #cbb068; }
    .terminal-body {
      height: 176px;
      overflow: auto;
      padding: 12px;
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .terminal-line {
      margin: 0 0 5px;
      white-space: pre-wrap;
    }
    .terminal-line::before {
      content: "> ";
      color: #cbb068;
    }
    .terminal-line.warn { color: #ffe6a6; }
    .terminal-line.err { color: #ffb6aa; }
    .terminal-line.ok { color: #bdf5d1; }
    .bar {
      height: 8px;
      border-radius: 999px;
      overflow: hidden;
      background: #e2ebf0;
      margin-top: 14px;
    }
    .bar div {
      width: 0%;
      height: 100%;
      background: linear-gradient(90deg, var(--wine), var(--gold));
      transition: width .2s ease;
    }
    @media (max-width: 760px) {
      header, .layout { grid-template-columns: 1fr; }
      header { align-items: stretch; flex-direction: column; }
      .brand-lockup { flex-wrap: wrap; }
      .brand-logo-img { width: 60px; height: 60px; }
      .wordmark { max-width: 200px; }
      .status-pill { min-width: 0; }
      .shell { width: min(100% - 22px, 1040px); padding-top: 18px; }
      .primary, .choose { width: 100%; }
      .dropzone { min-height: 220px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div class="brand-lockup">
        <img class="brand-logo-img" src="/assets/ecorio-logo.jpeg" alt="Ecorio">
        <div>
          <img class="wordmark" src="/assets/auto-eco-wordmark.svg" alt="Auto ECO">
          <p class="subtitle">Enriquecimento de favoritos para prospeccao comercial.</p>
        </div>
      </div>
      <div class="status-pill" id="statusBox">
        <strong>Conferindo conexão</strong>
        <span>Aguarde um instante.</span>
      </div>
    </header>

    <section class="layout">
      <div class="panel upload-panel">
        <form id="uploadForm">
          <label class="dropzone" id="dropzone" for="arquivo">
            <div>
              <div class="file-icon" aria-hidden="true"></div>
              <h2>Meus_favoritos.xls</h2>
              <div class="file-name" id="fileName">Selecione o arquivo exportado do Mais Obras.</div>
            </div>
          </label>
          <input id="arquivo" name="arquivo" type="file" accept=".xls,.xlsx,.xlsm,.csv">
          <div style="margin:12px 0 4px;display:flex;align-items:center;gap:8px;">
            <input type="checkbox" id="modoMeetime" name="modoMeetime"
              style="width:15px;height:15px;accent-color:#56181b;cursor:pointer;flex-shrink:0;">
            <label for="modoMeetime" style="cursor:pointer;font-size:13px;color:#251517;line-height:1.4;">
              <strong>Modo Meetime</strong> &mdash; exporta 1 linha por contato, abas separadas por cidade, telefones sem formatacao
            </label>
          </div>
          <div class="actions">
            <label class="choose" for="arquivo">Escolher arquivo</label>
            <button class="primary" id="submitBtn" type="submit" disabled>Enriquecer planilha</button>
            <a class="download-btn disabled" id="downloadBtn" href="#" download aria-disabled="true">Baixar resultado</a>
          </div>
          <div class="bar" aria-hidden="true"><div id="progress"></div></div>
          <div class="message" id="message">A planilha pronta sera baixada automaticamente.</div>
          <section class="terminal" aria-label="Andamento do processamento">
            <div class="terminal-head">
              <span>Andamento</span>
              <span class="terminal-lights" aria-hidden="true"><span></span><span></span><span></span></span>
            </div>
            <div class="terminal-body" id="terminalBody"></div>
          </section>
        </form>
      </div>

      <aside class="panel side">
        <h2>Fluxo</h2>
        <ol class="steps">
          <li><span>1</span><strong>Arquivo recebido</strong></li>
          <li><span>2</span><strong>Contatos buscados</strong></li>
          <li><span>3</span><strong>Excel pronto</strong></li>
        </ol>
        <div class="message warn" id="authNote">Conferindo login no Mais Obras.</div>
      </aside>
    </section>
  </main>

  <script>
    const input = document.getElementById("arquivo");
    const fileName = document.getElementById("fileName");
    const submitBtn = document.getElementById("submitBtn");
    const form = document.getElementById("uploadForm");
    const message = document.getElementById("message");
    const progress = document.getElementById("progress");
    const dropzone = document.getElementById("dropzone");
    const statusBox = document.getElementById("statusBox");
    const authNote = document.getElementById("authNote");
    const terminalBody = document.getElementById("terminalBody");
    const downloadBtn = document.getElementById("downloadBtn");
    let processingTimer = null;
    let downloadUrl = "";
    let downloadName = "";

    function setMessage(text, kind = "") {
      message.className = "message" + (kind ? " " + kind : "");
      message.textContent = text;
    }

    function logLine(text, kind = "") {
      const line = document.createElement("div");
      line.className = "terminal-line" + (kind ? " " + kind : "");
      const now = new Date();
      const stamp = now.toLocaleTimeString("pt-BR", { hour12: false });
      line.textContent = `[${stamp}] ${text}`;
      terminalBody.appendChild(line);
      terminalBody.scrollTop = terminalBody.scrollHeight;
    }

    function clearLog() {
      terminalBody.innerHTML = "";
    }

    function disableDownload() {
      if (downloadUrl) {
        URL.revokeObjectURL(downloadUrl);
      }
      downloadUrl = "";
      downloadName = "";
      downloadBtn.href = "#";
      downloadBtn.removeAttribute("download");
      downloadBtn.classList.add("disabled");
      downloadBtn.setAttribute("aria-disabled", "true");
    }

    function enableDownload(blob, outputName) {
      disableDownload();
      downloadUrl = URL.createObjectURL(blob);
      downloadName = outputName;
      downloadBtn.href = downloadUrl;
      downloadBtn.download = downloadName;
      downloadBtn.classList.remove("disabled");
      downloadBtn.setAttribute("aria-disabled", "false");
    }

    function triggerDownload() {
      if (!downloadUrl) return;
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = downloadName || "Meus_favoritos_enriquecido.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
    }

    function startProcessingLog() {
      const steps = [
        "Convertendo planilha quando necessario...",
        "Lendo linhas de obras e contatos...",
        "Consultando Mais Obras: pesquisa_perfil...",
        "Consultando Ver Mais: pesquisa_contatos_api...",
        "Montando o arquivo enriquecido..."
      ];
      let index = 0;
      processingTimer = setInterval(() => {
        logLine(steps[index % steps.length], "warn");
        index += 1;
      }, 7000);
    }

    function stopProcessingLog() {
      if (processingTimer) {
        clearInterval(processingTimer);
        processingTimer = null;
      }
    }

    function setProgress(value) {
      progress.style.width = value + "%";
    }

    function selectedFile() {
      return input.files && input.files[0] ? input.files[0] : null;
    }

    function refreshFileState() {
      const file = selectedFile();
      submitBtn.disabled = !file;
      fileName.textContent = file ? file.name : "Selecione o arquivo exportado do Mais Obras.";
      setMessage(file ? "Arquivo selecionado. Pode iniciar." : "A planilha pronta sera baixada automaticamente.");
      setProgress(file ? 12 : 0);
      if (file) {
        disableDownload();
        clearLog();
        logLine(`Arquivo selecionado: ${file.name}`, "ok");
        logLine("Aguardando comando para enriquecer.");
      }
    }

    input.addEventListener("change", refreshFileState);

    ["dragenter", "dragover"].forEach(eventName => {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(eventName => {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });
    dropzone.addEventListener("drop", event => {
      const files = event.dataTransfer.files;
      if (files.length) {
        input.files = files;
        refreshFileState();
      }
    });

    async function refreshHealth() {
      try {
        const response = await fetch("/health");
        const data = await response.json();
        statusBox.innerHTML = data.scraper_autenticado
          ? "<strong>Mais Obras conectado</strong><span>Pronto para enriquecer.</span>"
          : "<strong>Login pendente</strong><span>Verifique as credenciais do Mais Obras.</span>";
        authNote.textContent = data.scraper_autenticado
          ? "Login ativo. O processamento pode comecar."
          : "O servidor esta online, mas ainda nao autenticou no Mais Obras.";
        authNote.className = data.scraper_autenticado ? "message ok" : "message warn";
        if (!terminalBody.children.length) {
          logLine(data.scraper_autenticado ? "Mais Obras conectado." : "Login pendente no Mais Obras.", data.scraper_autenticado ? "ok" : "warn");
        }
      } catch (error) {
        statusBox.innerHTML = "<strong>Servidor indisponivel</strong><span>Atualize a pagina.</span>";
        authNote.textContent = "Nao consegui consultar o status agora.";
        authNote.className = "message err";
        if (!terminalBody.children.length) {
          logLine("Nao foi possivel consultar o status do servidor.", "err");
        }
      }
    }

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const file = selectedFile();
      if (!file) return;

      submitBtn.disabled = true;
      disableDownload();
      setProgress(35);
      setMessage("Processando. Mantenha esta aba aberta.", "warn");
      clearLog();
      logLine(`Iniciando processamento: ${file.name}`);
      logLine("Enviando arquivo para o servidor...");

      const meetime = document.getElementById("modoMeetime").checked;
      const formData = new FormData();
      formData.append("arquivo", file);
      formData.append("modo_meetime", meetime ? "1" : "0");
      if (meetime) logLine("Modo Meetime ativado: exportara 1 linha por contato.", "warn");

      try {
        const response = await fetch("/enriquecer_async", { method: "POST", body: formData });
        setProgress(28);
        logLine("Arquivo recebido pelo servidor.");

        if (!response.ok) {
          let detail = "Nao foi possivel enriquecer esta planilha.";
          try {
            const error = await response.json();
            detail = error.detail || detail;
          } catch (_) {}
          throw new Error(detail);
        }

        const created = await response.json();
        const jobId = created.job_id;
        logLine(`Job criado: ${jobId}`);

        let done = false;
        let lastLine = "";
        while (!done) {
          await new Promise(resolve => setTimeout(resolve, 1200));
          const statusResponse = await fetch(`/progresso/${jobId}`);
          if (!statusResponse.ok) throw new Error("Nao consegui consultar o andamento.");
          const status = await statusResponse.json();
          const percent = status.total ? Math.max(28, Math.round((status.processed / status.total) * 88)) : 32;
          setProgress(percent);

          const currentLine = status.current_line || status.message || status.status;
          if (currentLine && currentLine !== lastLine) {
            const kind = status.status === "failed" ? "err" : status.status === "done" ? "ok" : "";
            logLine(currentLine, kind);
            lastLine = currentLine;
          }

          if (status.status === "failed") {
            throw new Error(status.error || "Processamento falhou.");
          }
          done = status.status === "done";
        }

        setProgress(92);
        logLine("Baixando arquivo pronto...");
        const downloadResponse = await fetch(`/resultado/${jobId}`);
        if (!downloadResponse.ok) throw new Error("Nao consegui baixar o arquivo final.");

        const blob = await downloadResponse.blob();
        const disposition = downloadResponse.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="([^"]+)"/);
        const outputName = match ? match[1] : "Meus_favoritos_enriquecido.xlsx";
        enableDownload(blob, outputName);
        triggerDownload();

        setProgress(100);
        setMessage("Planilha enriquecida pronta. Use Baixar resultado se precisar baixar novamente.", "ok");
        logLine(`Download iniciado: ${outputName}`, "ok");
        logLine("Processamento concluido.", "ok");
      } catch (error) {
        setProgress(0);
        setMessage(error.message, "err");
        logLine(error.message, "err");
      } finally {
        submitBtn.disabled = !selectedFile();
        refreshHealth();
      }
    });

    downloadBtn.addEventListener("click", event => {
      if (!downloadUrl) {
        event.preventDefault();
      }
    });

    refreshFileState();
    refreshHealth();
    setInterval(refreshHealth, 20000);
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
