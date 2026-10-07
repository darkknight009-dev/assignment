# Mini Protocol-Based Report Generator

A working prototype that turns a **sample protocol**, **reference documents**,
**raw test data (CSV)** and a **supporting PDF attachment** into a complete,
reviewable report package:

- `generated_report.docx` — editable report built from the supplied template
- `results_table.xlsx` — deterministic results workbook (Pass/Fail + summary)
- `combined_report.pdf` — report + readable rendering of the Excel table + the
  original PDF attachment, all in one document
- `report_package.zip` — DOCX + combined PDF + original PDF + XLSX

Every generated artifact is marked **Draft - Requires Review**.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
pip install -e .

python scripts/make_inputs.py          # create the sample input set
python -m minireport.cli inputs outputs            # demo case 1: complete
python -m minireport.cli inputs/demo_variants/failing outputs_failing       # case 2
python -m minireport.cli inputs/demo_variants/incomplete outputs_incomplete # case 3

streamlit run src/minireport/ui.py     # or use the UI
```

Requires Python 3.11+. All processing is local; no network access is needed.

Optional AI narrative: `export OPENAI_API_KEY=...` then use `--ai openai`
(CLI) or the AI toggle (UI). Without a key the app uses the deterministic
fallback summary — nothing breaks.

## Input set

| File | Role |
|---|---|
| `protocol.md` | Planned sample IDs, test method, acceptance range, expected attachments |
| `results.csv` | Raw data: `sample_id, measurement, unit, observation` |
| `report_template.docx` | Report template: fixed wording + `[[PLACEHOLDER]]` fields + four section headings |
| `TQ-7_method_summary.md`, `Reporting_guidance.md`, `Measurement_practice_notes.md` | Reference documents (retrieval corpus) |
| `equipment_calibration_record.pdf` | Supporting attachment (fictional calibration record) |

`scripts/make_inputs.py` writes all of the above plus the two demo variants:
`failing` (S-02 = 58.4 Nm, above the 55 Nm limit) and `incomplete` (S-04 row
removed, calibration PDF removed).

## How each report section is generated

The assignment's four generation modes map 1:1 to sections; every section
carries a visible "Process control:" marker in the DOCX, PDF and UI.

| Section | Process | Where content comes from |
|---|---|---|
| Project information and fixed statements | **Deterministic / template-based** | Fields parsed from `protocol.md` fill `[[PLACEHOLDERS]]`; template wording (fixed statements, approval block) is preserved verbatim; attachment index uses stable labels. `src/minireport/sections.py: build_project_info`, `report.py`. |
| Test method and reference guidance | **RAG** | Paragraph chunks of the reference docs are embedded in a local TF-IDF index (no hosted vector DB); top-matching paragraphs are quoted **verbatim** with `[source para N]` citations. `src/minireport/retrieval.py`, `docreader.py`. |
| Results and evidence | **Evidence-based, deterministic** | `results.csv` rows are evaluated **once** against the protocol range (`src/minireport/evidence.py`); the table, per-row verdicts with CSV row references, and totals in the DOCX, XLSX and PDF all read from that one Evidence object. |
| Summary and observations | **AI-assisted narrative** (or deterministic fallback) | Optional LLM draft is written from a structured fact sheet + retrieved excerpts, then checked by a **deterministic fact guard**: any number not traceable to results, limits or cited reference text causes the draft to be discarded and the deterministic summary used instead. `src/minireport/factguard.py`, `sections.py: build_summary_section`. |

### Why the numbers can't disagree

All Pass/Fail decisions live in `evidence.py` and are computed exactly once.
The report DOCX table, the Excel sheet, the combined PDF table and the
narrative's fact sheet are renderings of the same object. AI text never
recomputes anything; it can only restate values that already exist, and the
fact guard enforces that mechanically.

### How AI is prevented from inventing results

1. Prompt restricts the draft to the supplied fact sheet and cited excerpts.
2. The fact guard extracts every number from the draft and discards the draft
   if any number is not in the allow-list (results, limits, counts, cited text).
3. On discard or API failure, a deterministic summary is used; the discarded
   draft's reason is shown in the UI. No number ever enters a report unverified.

## Validation checklist (section D)

Rendered in the UI after every generation (and reflected in the report):

- **Planned vs actual**: sample count and per-ID comparison both directions
  (missing planned samples and unplanned CSV rows).
- **Missing measurements / required attachments**: listed explicitly, matched
  case-insensitively against the protocol's expected attachment list.
- **Out-of-range results**: flagged with values; never rewritten, rounded or
  removed anywhere in the package.
- **Unfilled template placeholders**: detected during DOCX build and reported.

## Demo cases

| Case | Command | Expected findings |
|---|---|---|
| Complete | `python -m minireport.cli inputs outputs` | 0 errors; 5/5 pass; all placeholders filled |
| Failing result | `... inputs/demo_variants/failing outputs_failing` | S-02 = 58.4 Nm flagged in checklist, report table (red), Excel (red row), PDF; summary states it verbatim |
| Incomplete | `... inputs/demo_variants/incomplete outputs_incomplete` | Missing planned sample S-04 (planned 5, received 4) and missing calibration attachment; summary mentions both; nothing fabricated |

In the UI, the same cases are the three entries in the "Demo scenario"
dropdown. You can also edit the acceptance limits or a measurement in the
sidebar and regenerate — every artifact and the checklist update from the same
evidence engine.

## Architecture

```
inputs/ ──► inputs.py (locate & load)
             parsers.py (protocol / CSV / template)
             docreader.py (PDF/DOCX/TXT text extraction)
                  │
                  ├──► evidence.py  ← the ONLY Pass/Fail decision point
                  ├──► retrieval.py (local TF-IDF index, paragraph chunks)
                  │        └── factguard.py (number allow-list check)
                  ├──► sections.py (4 section builders + provenance)
                  │
                  └──► pipeline.py ──► report.py (DOCX from template)
                                     ──► xlsx.py (workbook)
                                     ──► pdfbuild.py (combined PDF + attachments)
                                     ──► ZIP package
             validation.py ──► checklist (planned/actual, missing, range, placeholders)
```

UI: `src/minireport/ui.py` (Streamlit) — input source, generation, checklist,
per-section provenance, summary editing, limit/result editing with full
regeneration, artifact downloads. CLI: `src/minireport/cli.py`.

## Known limitations

- One template, one test scenario supported well (per scope). Heading matching
  is by section name; a template with renamed headings needs `_match_section` updates.
- TF-IDF retrieval (not semantic embeddings) — fine for a small curated corpus,
  misses paraphrases.
- The combined PDF re-typesets the report with ReportLab rather than converting
  the DOCX (no LibreOffice dependency by design); content is identical because
  both render the same objects, but DOCX page layout is not reproduced.
- The fact guard checks numbers, not phrasing: an AI draft could still
  misattribute a *correct* number, which is why outputs stay drafts for review.
- No authentication, deployment, OCR, statistics or multi-template support —
  out of scope by the assignment.

## AI tools used

Developed with the assistance of an AI coding agent (Codebuff) for scaffolding
and boilerplate; architecture, section-generation strategy, fact-guard rules
and demo design were defined against the assignment brief and are documented
in-source. All code was reviewed and exercised via the automated test suite
(19 tests) and the three demo cases. No other developers contributed.
