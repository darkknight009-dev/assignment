"use client";

import { useCallback, useEffect, useState } from "react";

/* ------------------------------------------------------------------ types */
interface ChecklistItem {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
}
interface SectionJ {
  key: string;
  process: string;
  body: string;
  citations: string[];
  warnings: string[];
  aiUsed: boolean;
  aiDiscarded: boolean;
  aiDiscardReason: string;
  aiModel: string;
  aiAttempts: [string, string][];
}
interface ArtifactJ {
  name: string;
  size: number;
  data: string;
}
interface ResultJ {
  scenario: string;
  runKey: string;
  aiRequested: boolean;
  draftBanner: string;
  checklist: ChecklistItem[];
  sections: SectionJ[];
  summaryEdited: boolean;
  artifacts: { docx: ArtifactJ; xlsx: ArtifactJ; pdf: ArtifactJ; zip: ArtifactJ };
  edits: {
    lower: number;
    upper: number;
    samples: string[];
    measurements: Record<string, number>;
  };
  engineNote: string;
}

/* --------------------------------------------------------------- stages */
const STAGES = [
  ["01", "parse inputs", "protocol · csv · template · references · pdf"],
  ["02", "evidence pass", "one pass/fail decision point"],
  ["03", "retrieval index", "tf-idf over rulebooks, citation-ready"],
  ["04", "sections", "deterministic · rag · evidence · ai"],
  ["05", "ai narrative", "6-model chain, fact-guarded"],
  ["06", "fact guard", "every number must trace back"],
  ["07", "artifacts", "docx · xlsx · combined pdf · zip"],
  ["08", "validation", "plan-vs-actual · gaps · range · placeholders"],
];

const SCENARIOS = [
  {
    id: "complete",
    name: "Complete input",
    sub: "Five samples, all evidence present. The clean case.",
    meta: "0 expected findings",
  },
  {
    id: "failing",
    name: "Failing result",
    sub: "One measurement beyond the acceptance limit. Must stay visible.",
    meta: "1 expected error",
  },
  {
    id: "incomplete",
    name: "Incomplete input",
    sub: "Sample dropped, attachment gone. Nothing may be fabricated.",
    meta: "3 expected errors",
  },
] as const;

const PROCESS_TAG: Record<string, string> = {
  deterministic: "DETERMINISTIC",
  rag: "RAG",
  evidence: "EVIDENCE",
  ai: "AI-ASSISTED",
};

function processTag(process: string): string {
  const exact: Record<string, string> = {
    "deterministic (AI unavailable)": "DETERMINISTIC · AI UNAVAILABLE",
    "deterministic (AI draft discarded)": "DETERMINISTIC · AI DISCARDED",
  };
  return (
    exact[process] ||
    PROCESS_TAG[process.split(" ")[0]] ||
    process.toUpperCase()
  );
}

function chipClass(process: string): string {
  const head = process.split(" ")[0];
  if (process.includes("discarded")) return "process-chip";
  return "process-chip " + (PROCESS_TAG[head]?.toLowerCase() ?? "deterministic");
}

function humanSize(n: number): string {
  return n > 1024 * 1024 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}

function download(name: string, b64: string) {
  const Bin = { name, b64 };
  const a = document.createElement("a");
  a.href = `data:application/octet-stream;base64,${b64}`;
  a.download = name;
  a.click();
}

/* ================================================================== app */
export default function Home() {
  const [scenario, setScenario] = useState<string>("complete");
  const [ai, setAi] = useState<boolean>(true);
  const [uploading, setUploading] = useState(false);
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [stageStates, setStageStates] = useState<boolean[]>(
    Array(STAGES.length).fill(false)
  );
  const [result, setResult] = useState<ResultJ | null>(null);
  const [error, setError] = useState<string>("");
  const [toast, setToast] = useState<string>("");

  /* edits */
  const [lower, setLower] = useState("45");
  const [upper, setUpper] = useState("55");
  const [sample, setSample] = useState("");
  const [value, setValue] = useState("");
  /* summary */
  const [summary, setSummary] = useState("");
  /* uploaded files (own-input mode) */
  const [protocolFile, setProtocolFile] = useState<File | null>(null);
  const [resultsFile, setResultsFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [refFiles, setRefFiles] = useState<File[]>([]);
  const [attFiles, setAttFiles] = useState<File[]>([]);

  /* pipeline animation while the engine runs */
  useEffect(() => {
    if (phase !== "running") return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    stageStates.forEach((_, i) => {
      timers.push(
        setTimeout(() => {
          setStageStates((prev) => {
            const next = [...prev];
            next[i] = true;
            return next;
          });
        }, 260 * (i + 1))
      );
    });
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const flash = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3200);
  }, []);

  const adoptResult = useCallback((data: ResultJ) => {
    setResult(data);
    setLower(String(data.edits.lower));
    setUpper(String(data.edits.upper));
    setSample(data.edits.samples[0] ?? "");
    setValue(String(data.edits.measurements[data.edits.samples[0]] ?? ""));
    const sum = data.sections.find(
      (s: SectionJ) => s.key === "Summary and observations"
    );
    setSummary(sum?.body ?? "");
    setPhase("done");
  }, []);

  const runScenario = useCallback(
    async (scen: string, useAi: boolean) => {
      setPhase("running");
      setStageStates(Array(STAGES.length).fill(false));
      setError("");
      setResult(null);
      try {
        const res = await fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "generate", scenario: scen, ai: useAi }),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        adoptResult(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    },
    [adoptResult]
  );

  const runUpload = useCallback(
    async (useAi: boolean) => {
      if (!protocolFile || !resultsFile || !templateFile) {
        setError("upload all three required files first (protocol, results, template).");
        setPhase("error");
        return;
      }
      setPhase("running");
      setStageStates(Array(STAGES.length).fill(false));
      setError("");
      setResult(null);
      try {
        const fd = new FormData();
        fd.append("ai", String(useAi));
        fd.append("protocol", protocolFile);
        fd.append("results", resultsFile);
        fd.append("template", templateFile);
        refFiles.forEach((f) => fd.append("references", f));
        attFiles.forEach((f) => fd.append("attachments", f));
        const res = await fetch("/api/generate", { method: "POST", body: fd });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        adoptResult(data);
        flash("uploaded inputs processed — outputs ready");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    },
    [protocolFile, resultsFile, templateFile, refFiles, attFiles, adoptResult, flash]
  );

  const applySummary = useCallback(async () => {
    if (!result) return;
    setPhase("running");
    setStageStates((p) => p.map(() => false));
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "apply_summary",
          run: result.runKey,
          text: summary,
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setResult(data);
      setPhase("done");
      flash("summary applied — docx, pdf, zip rewritten");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [result, summary, flash]);

  const applyEdits = useCallback(async () => {
    if (!result) return;
    setPhase("running");
    setStageStates((p) => p.map(() => false));
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "apply_edits",
          run: result.runKey,
          lower: parseFloat(lower),
          upper: parseFloat(upper),
          sample_id: sample,
          value: parseFloat(value),
          value_changed: true,
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setResult(data);
      const sum = data.sections.find(
        (s: SectionJ) => s.key === "Summary and observations"
      );
      setSummary(sum?.body ?? "");
      setPhase("done");
      flash("limits + data applied — every artifact re-decided");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [result, lower, upper, sample, value, flash]);

  const summarySec = result?.sections.find(
    (s) => s.key === "Summary and observations"
  );

  /* ====================================================== render */
  return (
    <div className="app-shell">
      {/* masthead */}
      <header className="masthead">
        <div className="brand">
          <div className="brand-name">
            substrate<span className="dot">.</span>
          </div>
          <div className="brand-tag">protocol → report · rev B · engine v0.3</div>
        </div>
        <div className="mast-pip">
          <span
            className={`pip-dot ${phase === "running" ? "processing" : ''}`}
          />
          {phase === "running"
            ? "engine running"
            : phase === "done"
            ? "package ready — draft"
            : phase === "error"
            ? "engine fault"
            : "engine idle"}
        </div>
      </header>

      {/* hero */}
      <section className="hero">
        <div className="hero-kicker">
          deterministic reporting <span className="rev">// assignment build</span>
        </div>
        <h1 className="hero-title">
          Truth, typeset.
          <br />
          <span className="accent">Once, then everywhere.</span>
        </h1>
        <hr className="hero-rule" />
        <p className="hero-sub">
          A protocol-based report generator. Pass/Fail is decided exactly once by
          code; the narrative is AI-assisted under a number-level fact guard; and
          the Word, Excel, and PDF outputs all render from the same single
          verdict object — so they cannot disagree.
        </p>
      </section>

      {/* doctrine ticker */}
      <div className="ticker" aria-hidden>
        <div className="ticker-track">
          {[0, 1].map((rep) => (
            <span key={rep}>
              <span>one verdict object</span> <b>·</b>
              <span> rag cites paragraph &amp; page</span> <b>·</b>
              <span> ai is a draft, always</span> <b>·</b>
              <span> failures are never rewritten</span> <b>·</b>
              <span> draft — requires review</span> <b>·</b>
              <span> docx ≡ xlsx ≡ pdf</span> <b>·</b>
              <span> out-of-range stays visible</span> <b>·</b>
            </span>
          ))}
        </div>
      </div>

      {/* scenario picker */}
      <section style={{ margin: "34px 0 0" }}>
        <div className="sheet">
          <div className="sheet-head">
            <span className="sheet-title">01 · choose the demo case</span>
            <span className="sheet-index">3 scenarios / 1 scenario template</span>
          </div>
          <div className="sheet-body">
            <div className="scenario-grid">
              {SCENARIOS.map((s, i) => (
                <button
                  key={s.id}
                  className={`scenario-card ${scenario === s.id ? "selected" : ''}`}
                  onClick={() => {
                    setScenario(s.id);
                    setPhase("idle");
                    setResult(null);
                  }}
                  disabled={phase === "running"}
                >
                  <div className="sc-index">CASE {String(i + 1).padStart(2, "0")}</div>
                  <div className="sc-name">{s.name}</div>
                  <div className="sc-sub">{s.sub}</div>
                  <div className="sc-meta">{s.meta}</div>
                </button>
              ))}
            </div>
            <div
              style={{
                display: "flex",
                gap: 14,
                alignItems: "center",
                marginTop: 20,
                flexWrap: "wrap",
              }}
            >
              <label
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  fontFamily: "var(--mono)", fontSize: 11,
                  textTransform: "uppercase", letterSpacing: "0.08em",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={ai}
                  onChange={(e) => setAi(e.target.checked)}
                  style={{ accentColor: "#ff4d00", width: 15, height: 15 }}
                />
                ai-assisted summary (openrouter · 6-model chain)
              </label>
              <div style={{ flex: 1 }} />
              <button
                className="btn"
                onClick={() => runScenario(scenario, ai)}
                disabled={phase === "running" || uploading}
              >
                {phase === "running" ? "working —" : phase === "done" ? "regenerate —" : "generate —"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* upload your own inputs */}
      <section style={{ margin: "20px 0 0" }}>
        <div className="sheet">
          <div className="sheet-head">
            <span className="sheet-title">01b · bring your own inputs</span>
            <span className="sheet-index">same engine, your files</span>
          </div>
          <div className="sheet-body">
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 14,
              }}
            >
              <div>
                <label className="field-label">protocol (protocol.md / .txt)</label>
                <input
                  className="field"
                  type="file"
                  accept=".md,.txt"
                  onChange={(e) => setProtocolFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div>
                <label className="field-label">raw results (results.csv)</label>
                <input
                  className="field"
                  type="file"
                  accept=".csv"
                  onChange={(e) => setResultsFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div>
                <label className="field-label">report template (report_template.docx)</label>
                <input
                  className="field"
                  type="file"
                  accept=".docx"
                  onChange={(e) => setTemplateFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div>
                <label className="field-label">reference documents (md / txt / docx)</label>
                <input
                  className="field"
                  type="file"
                  multiple
                  accept=".md,.txt,.docx"
                  onChange={(e) => setRefFiles(Array.from(e.target.files ?? []))}
                />
              </div>
              <div>
                <label className="field-label">pdf attachments</label>
                <input
                  className="field"
                  type="file"
                  multiple
                  accept=".pdf"
                  onChange={(e) => setAttFiles(Array.from(e.target.files ?? []))}
                />
              </div>
            </div>
            <div
              style={{
                display: "flex", gap: 14, alignItems: "center", marginTop: 18,
                flexWrap: "wrap",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--ink-faint)", maxWidth: "46ch" }}>
                tip: copy the files from <b>inputs/</b> as templates — the csv must have
                sample_id, measurement, unit, observation columns; the protocol is
                key: value lines; the template holds [[PLACEHOLDERS]].
              </span>
              <div style={{ flex: 1 }} />
              <button
                className="btn secondary"
                onClick={() => runUpload(ai)}
                disabled={phase === "running"}
              >
                upload &amp; generate —
              </button>
            </div>
            {(protocolFile || resultsFile || templateFile || refFiles.length || attFiles.length) ? (
              <div
                style={{
                  marginTop: 12, fontFamily: "var(--mono)", fontSize: 11,
                  color: "var(--chip-green)", lineHeight: 1.9,
                }}
              >
                queued: {[protocolFile, resultsFile, templateFile].filter(Boolean).map((f) => f!.name).join(", ")}
                {refFiles.length ? ` · ${refFiles.length} reference(s)` : ""}
                {attFiles.length ? ` · ${attFiles.length} pdf(s)` : ""}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {/* pipeline */}
      {(phase === "running" || phase === "done") && (
        <section style={{ margin: "24px 0 0" }}>
          <div className="sheet">
            <div className="sheet-head">
              <span className="sheet-title">02 · engine pipeline</span>
              <span className="sheet-index">
                {phase === "running" ? "executing" : "complete"}
              </span>
            </div>
            <div className="sheet-body">
              <div className="stage-list">
                {STAGES.map(([idx, name, note], i) => {
                  const done = stageStates[i];
                  const cls = done
                    ? "stage done"
                    : phase === "running" && i === stageStates.filter(Boolean).length
                    ? "stage running"
                    : "stage";
                  return (
                    <div key={idx} className={`${cls} ${done ? '' : ''}`}>
                      <span className="idx">{idx}</span>
                      <span style={{ width: 150 }}>{name}</span>
                      <span style={{ color: "var(--ink-faint)", fontSize: 11 }}>{note}</span>
                      <span className="bar">
                        <span
                          className="bar-fill"
                          style={{
                            transform: done ? "scaleX(1)" : "scaleX(0)",
                            transition: "transform .45s ease",
                          }}
                        />
                      </span>
                      <span className="state">
                        {done ? "done" : phase === "running" ? "…  " : "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* error */}
      {phase === "error" && (
        <section style={{ margin: "24px 0 0" }}>
          <div className="sheet">
            <div className="sheet-head">
              <span className="sheet-title" style={{ color: "var(--chip-red)" }}>
                ⨯ engine fault
              </span>
            </div>
            <div className="sheet-body" style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}>
              {error}
              <div style={{ marginTop: 12, color: "var(--ink-faint)", fontSize: 11 }}>
                hint: export OPENROUTER_API_KEY — or add it to .env at the repo root —
                or switch the ai toggle off; the deterministic summary works without it.
              </div>
            </div>
          </div>
        </section>
      )}

      {/* results */}
      {result && phase === "done" && (
        <>
          <section style={{ margin: "24px 0 0" }}>
            <div className="results-grid">
              {/* left column */}
              <div style={{ display: "grid", gap: 24 }}>
                <div className="sheet">
                  <div className="sheet-head">
                    <span className="sheet-title">03 · validation</span>
                    <span className="sheet-index">live findings</span>
                  </div>
                  <div className="sheet-body">
                    {result.checklist.map((c, i) => (
                      <div
                        key={c.code + i}
                        className={`check-row sev-${c.severity}`}
                        style={{ animationDelay: `${i * 70}ms` }}
                      >
                        <span className="check-mark">
                          {c.severity === "error" ? "✗" : c.severity === "warning" ? "!" : "✓"}
                        </span>
                        <div>
                          <div className="check-msg">{c.message}</div>
                          <div className="check-code">{c.code.toLowerCase()}</div>
                        </div>
                      </div>
                    ))}
                    <div
                      style={{
                        marginTop: 14,
                        fontFamily: "var(--mono)",
                        fontSize: 10.5,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "var(--signal-ink)",
                      }}
                    >
                      {result.draftBanner}
                    </div>
                  </div>
                </div>

                {/* downloads */}
                <div className="sheet">
                  <div className="sheet-head">
                    <span className="sheet-title">04 · package</span>
                    <span className="sheet-index">pickup</span>
                  </div>
                  <div className="sheet-body">
                    <div className="dl-grid">
                      <a
                        className="dl-chip"
                        href={`data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${result.artifacts.docx.data}`}
                        download={result.artifacts.docx.name}
                      >
                        <span>{result.artifacts.docx.name}</span>
                        <span className="dl-size">{humanSize(result.artifacts.docx.size)}</span>
                      </a>
                      <a
                        className="dl-chip"
                        href={`data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${result.artifacts.xlsx.data}`}
                        download={result.artifacts.xlsx.name}
                      >
                        <span>{result.artifacts.xlsx.name}</span>
                        <span className="dl-size">{humanSize(result.artifacts.xlsx.size)}</span>
                      </a>
                      <a
                        className="dl-chip"
                        href={`data:application/pdf;base64,${result.artifacts.pdf.data}`}
                        download={result.artifacts.pdf.name}
                      >
                        <span>{result.artifacts.pdf.name}</span>
                        <span className="dl-size">{humanSize(result.artifacts.pdf.size)}</span>
                      </a>
                      <a
                        className="dl-chip"
                        href={`data:application/zip;base64,${result.artifacts.zip.data}`}
                        download={result.artifacts.zip.name}
                      >
                        <span>{result.artifacts.zip.name}</span>
                        <span className="dl-size">{humanSize(result.artifacts.zip.size)}</span>
                      </a>
                    </div>
                    <div style={{ marginTop: 12, fontSize: 12, color: "var(--ink-faint)" }}>
                      {result.engineNote}
                    </div>
                  </div>
                </div>

                {/* edits */}
                <div className="sheet">
                  <div className="sheet-head">
                    <span className="sheet-title">05 · edit &amp; re-decide</span>
                    <span className="sheet-index">one verdict → all artifacts</span>
                  </div>
                  <div className="sheet-body">
                    <div style={{ display: "grid", gap: 14 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                        <div>
                          <label className="field-label">lower limit</label>
                          <input
                            className="field"
                            type="number"
                            step="0.1"
                            value={lower}
                            onChange={(e) => setLower(e.target.value)}
                          />
                        </div>
                        <div>
                          <label className="field-label">upper limit</label>
                          <input
                            className="field"
                            type="number"
                            step="0.1"
                            value={upper}
                            onChange={(e) => setUpper(e.target.value)}
                          />
                        </div>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                        <div>
                          <label className="field-label">sample</label>
                          <select
                            className="field"
                            value={sample}
                            onChange={(e) => {
                              setSample(e.target.value);
                              setValue(
                                String(result.edits.measurements[e.target.value] ?? "")
                              );
                            }}
                          >
                            {result.edits.samples.map((s) => (
                              <option key={s}>{s}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="field-label">new measurement</label>
                          <input
                            className="field"
                            type="number"
                            step="0.1"
                            value={value}
                            onChange={(e) => setValue(e.target.value)}
                          />
                        </div>
                      </div>
                      <button className="btn" onClick={applyEdits}>
                        apply limits + data · regenerate
                      </button>
                      <div style={{ fontSize: 12, color: "var(--ink-faint)", lineHeight: 1.55 }}>
                        changing a limit or value re-runs the whole engine: the checklist,
                        report table, Excel sheet, PDF and the AI narrative all update from
                        one decision point.
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* right column: sections */}
              <div style={{ display: "grid", gap: 16 }}>
                {result.sections.map((s, i) => (
                  <details key={s.key} className="section-block" open={i >= 2}>
                    <summary className="section-head">
                      <span className="section-title">{s.key}</span>
                      <span className={chipClass(s.process)}>{processTag(s.process)}</span>
                      <span style={{ flex: 1 }} />
                      <span
                        className="sheet-index"
                        style={{ fontFamily: "var(--mono)", fontSize: 10 }}
                      >
                        section {String(i + 1).padStart(2, "0")}
                      </span>
                    </summary>
                    <div className="section-body">{s.body}</div>
                    {s.citations.length > 0 && (
                      <div className="citation-line">
                        sources: {s.citations.join(" · ")}
                      </div>
                    )}
                    {s.aiAttempts.length > 0 && (
                      <div style={{ padding: "0 18px 14px" }}>
                        <div className="chain-log">
                          ai chain:{" "}
                          {s.aiAttempts.map(([m, o], j) => (
                            <div key={m + j}>
                              {o === "ok" ? (
                                <span className="ok">✓ {m}</span>
                              ) : (
                                <span className="err">✗ {m} — {o.slice(0, 60)}</span>
                              )}
                            </div>
                          ))}
                          {s.aiModel && (
                            <div style={{ marginTop: 4 }}>
                              draft by <b>{s.aiModel}</b>
                              {s.aiDiscarded ? " — discarded by fact guard" : s.aiUsed ? " — fact-checked, kept" : ""}
                            </div>
                          )}
                          {s.aiDiscarded && (
                            <div className="err" style={{ marginTop: 4 }}>
                              reason: {s.aiDiscardReason}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                    {s.warnings.map((w, j) => (
                      <div
                        key={j}
                        style={{
                          padding: "10px 18px", borderTop: "1px dashed var(--line)",
                          fontFamily: "var(--mono)", fontSize: 11, color: "var(--chip-amber)",
                        }}
                      >
                        note: {w}
                      </div>
                    ))}
                  </details>
                ))}

                {/* summary editor */}
                {summarySec && (
                  <div className="sheet">
                    <div className="sheet-head">
                      <span className="sheet-title">06 · review the ai summary</span>
                      <span className="sheet-index">
                        {result.summaryEdited ? "edited" : "as generated"}
                      </span>
                    </div>
                    <div className="sheet-body">
                      <textarea
                        className="summary-editor"
                        value={summary}
                        onChange={(e) => setSummary(e.target.value)}
                      />
                      <div
                        style={{
                          display: "flex", gap: 12, alignItems: "center", marginTop: 14,
                        }}
                      >
                        <button className="btn" onClick={applySummary}>
                          apply to exports
                        </button>
                        <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
                          rewrites the docx, pdf and zip with your wording.
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>
        </>
      )}

      <footer className="colophon">
        <span>substrate · built as the assignment deliverable</span>
        <span>
          engine: <a href="https://localhost/minireport">python · evidence → sections → artifacts</a>
        </span>
      </footer>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
