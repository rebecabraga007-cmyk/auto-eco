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
