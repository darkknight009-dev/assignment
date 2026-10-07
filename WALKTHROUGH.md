# 15-Minute Walkthrough Guide

Suggested flow with talking points (run `streamlit run src/minireport/ui.py`).

## 1. Inputs & scenario (2 min)

- Open `inputs/`: protocol, results CSV, DOCX template, three reference docs,
  calibration PDF. Show the `[[PLACEHOLDER]]` fields in the template.
- Point out the single-template, single-scenario scope choice from the brief.

## 2. Demo case 1 — complete input (3 min)

- Select "1) Complete input" → **Generate report package**.
- Walk the validation checklist: samples match, inputs complete, all in range,
  placeholders filled.
- Open each section expander and name its process control:
  deterministic / RAG / evidence / AI.
- Show RAG citations: `[Reporting_guidance.md p? para4]` style references with
  relevance scores.
- Download the XLSX and open it: same totals as the report; note the DRAFT
  banner inside the workbook.

## 3. Demo case 2 — failing result (4 min)

- Switch to "2) Failing result" → generate.
- Checklist flags S-02 = 58.4 Nm > 55 Nm. Show it consistently in: the results
  table in the UI, the red rows in the DOCX (`outputs_failing/`), the red row
  in the Excel file, and the narrative stating "S-02 measured 58.4 Nm".
- Key point: **nothing rewrote the value**; the summary reports it verbatim and
  explicitly declines to invent a cause.

## 4. Demo case 3 — incomplete input (3 min)

- Switch to "3) Incomplete input" → generate.
- Checklist shows: planned sample S-04 missing (planned 5, received 4) and the
  calibration attachment missing.
- Summary and report name both gaps; no replacement data or evidence appears
  anywhere (Excel has exactly 4 rows).

## 5. Edit & regenerate (2 min)

- Back on case 1: change the upper limit 55 → 50, regenerate, and watch S-02
  and S-04 flip to Fail everywhere at once — demonstrating the single
  evidence-decision-point design.
- Edit the summary text, apply, and show the DOCX/PDF picking it up.

## 6. Key code paths (1 min)

- `src/minireport/evidence.py` — the only Pass/Fail decision point.
- `src/minireport/factguard.py` — number allow-list that disqualifies invented
  AI numbers.
- `src/minireport/retrieval.py` — local TF-IDF chunks with para citations.
- `src/minireport/report.py` — template-preserving DOCX assembly.

Suggested small change to make live: adjust the acceptance range in
`inputs/protocol.md` and rerun the CLI — one file, every artifact follows.
