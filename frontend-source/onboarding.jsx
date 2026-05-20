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
