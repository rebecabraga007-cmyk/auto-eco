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
