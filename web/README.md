# minireport web UI

The Next.js 15 (React 19, TypeScript) frontend for the Python `minireport`
report-generation engine in `../src/minireport`. A single-page app that drives
the same tested engine the CLI and Streamlit UI use.

## Prerequisites

- Python 3.11+ with the repo requirements installed:

  ```bash
  pip install -r ../requirements.txt   # from web/
  pip install -e ..
  ```

- Node 18+

## Run

```bash
npm install
npm run dev    # runs scripts/preflight.mjs first, then next dev --turbopack
```

Open http://localhost:3000.

## How it works

The single page `app/page.tsx` POSTs to `app/api/generate/route.ts`, which
spawns `python3 -m minireport.webapi_cli <json>` with the repo root as cwd and
`PYTHONPATH=src`. The bridge answers with one JSON object containing the
validation checklist, per-section provenance (citations plus the AI
fallback-chain log showing which model answered), and base64-encoded
docx/xlsx/pdf/zip artifacts for one-click download. Edit state persists in
`/tmp/minireport/webcache/<run_key>/state.json`, so summary and
limit/measurement edits survive across separate requests.

## Features

- Three built-in demo scenarios: complete / failing / incomplete.
- Optional custom input-set upload (multipart form): protocol.md, results.csv,
  report_template.docx, plus reference files and PDF attachments.
- AI toggle for the summary narrative — needs `OPENROUTER_API_KEY` in the
  repo-root `.env` or environment; without it the deterministic fallback
  summary is used and nothing breaks.
- Animated 8-stage pipeline view.
- Validation checklist after every run.
- Editable summary and acceptance limits/measurements with live regenerate —
  the whole package rebuilds from one evidence decision point.
- One-click downloads of DOCX / XLSX / PDF / ZIP.

## Environment

- `OPENROUTER_API_KEY` (optional) — enables the AI-assisted summary via
  OpenRouter; put it in the repo-root `.env` or export it before starting.

