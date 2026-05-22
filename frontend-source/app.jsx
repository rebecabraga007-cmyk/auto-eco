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
  const [jobId, setJobId] = useState(null);
  const cancelRef = useRef({ cancelled: false });

  useEffect(() => {
    if (!localStorage.getItem(ONBOARDING_KEY)) setShowOnboarding(true);
  }, []);

  // Verifica conexão real com o servidor
  useEffect(() => {
    fetch("/health")
      .then(r => r.json())
      .then(data => {
        if (data.status === "ok") {
          setServerStatus(data.scraper_autenticado ? "connected" : "pending");
        } else {
          setServerStatus("offline");
        }
      })
      .catch(() => setServerStatus("offline"));
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
    if (!file || stage === "processing" || stage === "uploading") return;
    cancelRef.current = { cancelled: false };
    setStage("uploading");
    setResult(null);
    setJobId(null);
    pushLog(`Iniciando processamento: ${file.name}`);
    if (meetime) pushLog("Modo Meetime ativado — exportará 1 linha por contato.", "warn");

    // 1. Envia o arquivo e obtém job_id
    const formData = new FormData();
    formData.append("arquivo", file);
    formData.append("modo_meetime", meetime ? "1" : "0");

    let jid;
    try {
      pushLog("Enviando arquivo para o servidor…");
      const res = await fetch("/enriquecer_async", { method: "POST", body: formData });
      if (!res.ok) {
        let detail = res.statusText;
        try { const j = await res.json(); detail = j.detail || detail; } catch {}
        pushLog(`Erro: ${detail}`, "err");
        setStage("idle");
        return;
      }
      const data = await res.json();
      jid = data.job_id;
      setJobId(jid);
      pushLog("Arquivo recebido. Detectando colunas com IA…", "ok");
    } catch (err) {
      pushLog(`Erro de conexão: ${err.message}`, "err");
      setStage("idle");
      return;
    }

    // 2. Polling de progresso real
    setStage("processing");
    let lastLine = "";
    while (true) {
      if (cancelRef.current.cancelled) return;
      await sleep(1200);
      if (cancelRef.current.cancelled) return;

      try {
        const prog = await fetch(`/progresso/${jid}`).then(r => r.json());

        // Exibe nova linha no terminal só quando mudar
        if (prog.current_line && prog.current_line !== lastLine) {
          lastLine = prog.current_line;
          const kind = prog.status === "failed" ? "err"
            : (prog.current_line || "").includes("OK") ? "ok"
            : (prog.current_line || "").includes("sem telefone") ? "warn" : "";
          pushLog(prog.current_line, kind);
        }

        setProgress({
          processed: prog.processed || 0,
          total: prog.total || 0,
          currentLine: prog.current_contact || prog.current_line || "",
        });

        if (prog.status === "done") {
          const outputName = (file.name.replace(/\.[^.]+$/, "")) +
            (meetime ? "_meetime.xlsx" : "_enriquecido.xlsx");
          const total = prog.total || 0;
          const m = (prog.current_line || "").match(/(\d+)\/(\d+)/);
          const success = m ? parseInt(m[1]) : 0;
          pushLog(`Concluído: ${success}/${total} obras com telefone encontrado.`, "ok");
          setStage("done");
          setResult({ total, success, outputName, jobId: jid });
          break;
        }

        if (prog.status === "failed") {
          pushLog(`Erro: ${prog.error || "falha no processamento"}`, "err");
          setStage("idle");
          break;
        }

      } catch (err) {
        pushLog(`Erro ao verificar progresso: ${err.message}`, "err");
      }
    }
  };

  const handleDownload = async () => {
    if (!result || !result.jobId) return;
    pushLog(`Baixando ${result.outputName}…`, "ok");
    try {
      const res = await fetch(`/resultado/${result.jobId}`);
      if (!res.ok) {
        pushLog("Erro ao baixar o arquivo.", "err");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = result.outputName;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      pushLog(`Erro ao baixar: ${err.message}`, "err");
    }
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
