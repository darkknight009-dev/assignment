"""Streamlit UI: upload/select inputs -> generate -> review -> download.

Run with:  streamlit run src/minireport/ui.py
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import streamlit as st

DRAFT = "Draft - Requires Review"

st.set_page_config(page_title="Mini Report Generator", page_icon="📄", layout="wide")


def _fresh_workspace(name: str) -> Path:
    d = Path(tempfile.gettempdir()) / "minireport" / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _use_builtin_demo(demo_choice: str) -> Path:
    d = _fresh_workspace(demo_choice)
    src = Path(__file__).resolve().parents[2] / "templates" / demo_choice
    if not src.is_dir():
        raise FileNotFoundError(f"Built-in demo inputs not found: {src}")
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, d / f.name)
    return d


def _save_uploads(uploads: dict[str, object]) -> Path:
    d = _fresh_workspace("upload")
    for f in uploads.values():
        if f is None:
            continue
        data: object = f
        (d / data.name).write_bytes(data.getvalue())
    return d


# ------------------------------------------------------------------ sidebar --
with st.sidebar:
    st.title("Mini Report Generator")
    st.caption("Protocol-based report, Excel and PDF package generator")

    source = st.radio("Input source", ["Built-in demo inputs", "Upload files"], index=0)

    input_dir: Path | None = None
    if source == "Built-in demo inputs":
        demo_choice = st.selectbox(
            "Demo scenario",
            ["1) Complete input", "2) Failing result", "3) Incomplete input"],
            key="demo_choice",
        )
        demo_dir = {"1) Complete input": "demo_complete",
                    "2) Failing result": "demo_failing",
                    "3) Incomplete input": "demo_incomplete"}[demo_choice]
        try:
            input_dir = _use_builtin_demo(demo_dir)
        except FileNotFoundError as exc:
            st.sidebar.error(str(exc))
            input_dir = None
    else:
        st.caption("Expected files: protocol.md, results.csv, report_template.docx, "
                   "reference .md/.txt documents, PDF attachments (optional).")
        up = {}
        up["protocol"] = st.file_uploader("Protocol (Markdown)", type=["md", "txt"])
        up["results"] = st.file_uploader("Raw results (CSV)", type=["csv"])
        up["template"] = st.file_uploader("Report template (DOCX)", type=["docx"])
        up["refs"] = st.file_uploader("Reference documents (md/txt/docx)",
                                      type=["md", "txt", "docx"], accept_multiple_files=True)
        up["atts"] = st.file_uploader("Supporting PDF attachments", type=["pdf"],
                                      accept_multiple_files=True)
        if up["protocol"] and up["results"] and up["template"]:
            input_dir = _save_uploads(up)
        else:
            st.info("Protocol, results CSV and template are required.")

    ai_mode = st.toggle("AI-assisted summary (OpenAI)", value=False,
                        help="Requires OPENAI_API_KEY in the environment. "
                             "Without it the deterministic fallback is used.")

    go = st.button("Generate report package", type="primary", disabled=input_dir is None)

if input_dir is None:
    st.title("Mini Report Generator")
    st.warning("Choose an input source in the sidebar to begin.")
    st.stop()

# ------------------------------------------------------------------ generate --
result = None
error = None
stale = st.session_state.get("input_dir") != str(input_dir)
if go or "cached_result" not in st.session_state or stale:
    try:
        llm = None
        if ai_mode:
            try:
                from .llm import OpenAILLM
            except ImportError:  # streamlit runs this file standalone
                from minireport.llm import OpenAILLM
            llm = OpenAILLM()
        try:
            from .pipeline import generate
        except ImportError:
            from minireport.pipeline import generate

        with st.spinner("Generating report package..."):
            result = generate(input_dir, _fresh_workspace("out"), llm=llm)
        st.session_state.cached_result = result
        st.session_state.input_dir = str(input_dir)
        st.session_state.pop("summary_text", None)
        st.session_state.pop("summary_editor", None)
    except Exception as exc:
        error = str(exc)
        result = st.session_state.get("cached_result")
else:
    result = st.session_state.cached_result

if error and result is None:
    st.error(f"Generation failed: {error}")
    st.stop()
if error:
    st.warning(f"Last regeneration failed ({error}); showing previous outputs.")

result = st.session_state.cached_result
st.title("Generated report package")
st.error(f"🚩 {DRAFT} — review and edit before export.", icon="⚠")

# --------------------------------------------------------------- checklist ----
left, right = st.columns([2, 3])

with left:
    st.subheader("Validation checklist")
    icons = {"error": "❌", "warning": "⚠️", "info": "✅"}
    for item in result.checklist:
        st.markdown(f"{icons.get(item.severity, '·')} {item.message}")

    att = st.container()
    with att:
        st.subheader("Artifacts")
        for p in (result.docx_path, result.xlsx_path, result.combined_pdf_path, result.zip_path):
            with open(p, "rb") as fh:
                st.download_button(
                    f"⬇ {p.name} ({p.stat().st_size:,} B)", fh.read(), file_name=p.name
                )

with right:
    st.subheader("Sections & provenance")
    process_tag = {
        "deterministic": "DETERMINISTIC",
        "rag": "RAG",
        "evidence": "EVIDENCE",
        "ai": "AI-ASSISTED",
    }
    for sec in result.sections:
        tag = process_tag.get(sec.process.split(" ")[0], sec.process.upper())
        with st.expander(f"{sec.key}  ·  {tag}", expanded=sec.key.startswith("Summary")):
            st.markdown(f"**Body** — generated with process control: `{tag}`")
            st.text_area("visible_body", sec.body, height=220, key=f"body_{sec.key}",
                         label_visibility="collapsed")
            if sec.citations:
                st.caption("Sources:")
                for c in sec.citations:
                    st.markdown(f"- `{c.reference}` (score {c.score})")
            for w in sec.warnings:
                st.caption(f"⚠️ {w}")
            if sec.ai_discarded:
                st.error("AI draft discarded: " + sec.ai_discard_reason)

    # ------------------------------------------------- summary editing --------
    st.subheader("Review: edit the AI-generated summary")
    st.caption("Edits here are written into the exported DOCX/PDF. The rest of the "
               "report stays process-controlled.")
    idx_summary = next(i for i, s in enumerate(result.sections) if s.key == "Summary and observations")
    current = st.session_state.get("summary_text") or result.sections[idx_summary].body
    edited = st.text_area("Summary text", value=current, height=260, key="summary_editor")

    if st.button("Apply edited summary to exports"):
        result.sections[idx_summary].body = edited
        result.sections[idx_summary].ai_used = True
        st.session_state.summary_text = edited
        # rebuild artifacts from the edited state
        try:
            from .pipeline import regenerate_artifacts
        except ImportError:
            from minireport.pipeline import regenerate_artifacts
        regenerate_artifacts(result, input_dir)
        st.success("Summary applied — DOCX, PDF, ZIP regenerated.")

    # --------------------------------------------- editing + regeneration -----
    st.subheader("Editing + regeneration")
    st.caption("Change protocol limits or a measurement, then regenerate: Pass/Fail, "
               "report, Excel, PDF, ZIP and checklist must all update consistently.")

    proto = result.protocol  # typed object stashed on the result by the pipeline
    col1, col2 = st.columns(2)
    with col1:
        new_low = st.number_input("Lower limit", value=float(proto.lower_limit or 0.0),
                                  key="edit_lower")
        new_high = st.number_input("Upper limit", value=float(proto.upper_limit or 0.0),
                                   key="edit_upper")
    with col2:
        sample_ids = [ev["sample_id"] for ev in result.evidence.evaluations]
        if "edit_sample" not in st.session_state:
            st.session_state.edit_sample = sample_ids[0] if sample_ids else ""
        chosen = st.selectbox("Sample to edit", sample_ids, key="edit_sample")
        values = {ev["sample_id"]: ev["measurement"] for ev in result.evidence.evaluations}
        default = values.get(chosen) or 0.0
        new_val = st.number_input("New measurement", value=float(default), key="edit_value")

    limit_changed = (float(new_low) != float(proto.lower_limit or 0.0)
                     or float(new_high) != float(proto.upper_limit or 0.0))
    value_changed = (float(new_val) != float(values.get(chosen) or 0.0))
    if st.button("Apply edits & regenerate", type="primary"):
        try:
            try:
                from .pipeline import apply_edits_and_regenerate
            except ImportError:
                from minireport.pipeline import apply_edits_and_regenerate

            new_result = apply_edits_and_regenerate(
                result, input_dir,
                new_lower=float(new_low), new_upper=float(new_high),
                sample_id=chosen, new_value=float(new_val),
                limit_changed=limit_changed, value_changed=value_changed,
            )
            st.session_state.cached_result = new_result
            st.session_state.pop("summary_text", None)
            st.session_state.pop("summary_editor", None)
            st.rerun()
        except Exception as exc:
            st.error(f"Regeneration failed: {exc}")

st.caption(f"{DRAFT} • all numeric values derive from results.csv evaluated against "
           "template/protocol limits, in one place (minireport/evidence.py).")
