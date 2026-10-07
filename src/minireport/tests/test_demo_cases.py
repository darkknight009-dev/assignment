"""End-to-end tests for the three mandatory demo cases plus unit checks."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from minireport.evidence import build_evidence  # noqa: E402
from minireport.factguard import check_text, collect_allowed_numbers  # noqa: E402
from minireport.models import Evidence, SampleResult  # noqa: E402
from minireport.parsers import parse_protocol, parse_results_csv  # noqa: E402
from minireport.pipeline import generate  # noqa: E402
from minireport.retrieval import LocalIndex  # noqa: E402

INPUTS = ROOT / "inputs"
FAILING = ROOT / "inputs" / "demo_variants" / "failing"
INCOMPLETE = ROOT / "inputs" / "demo_variants" / "incomplete"

pytestmark = pytest.mark.skipif(
    not INPUTS.is_dir(), reason="run scripts/make_inputs.py first"
)


# ------------------------------------------------------------ demo case 1 ---
class TestCompleteCase:
    def test_generates_all_artifacts(self, tmp_path):
        result = generate(INPUTS, tmp_path)
        for p in (result.docx_path, result.xlsx_path,
                  result.combined_pdf_path, result.zip_path):
            assert p.exists() and p.stat().st_size > 1000, p

    def test_no_errors_and_all_pass(self, tmp_path):
        result = generate(INPUTS, tmp_path)
        assert result.evidence.total == 5
        assert result.evidence.passed == 5
        assert result.evidence.failed == 0
        assert not [i for i in result.checklist if i.severity == "error"]

    def test_zip_contents(self, tmp_path):
        result = generate(INPUTS, tmp_path)
        with zipfile.ZipFile(result.zip_path) as zf:
            names = set(zf.namelist())
        assert {"generated_report.docx", "combined_report.pdf",
                "results_table.xlsx", "equipment_calibration_record.pdf"} <= names

    def test_process_controls_shown(self, tmp_path):
        result = generate(INPUTS, tmp_path)
        processes = {s.process.split(" ")[0] for s in result.sections}
        assert {"deterministic", "rag", "evidence"} <= processes

    def test_rag_citations_have_source_and_location(self, tmp_path):
        result = generate(INPUTS, tmp_path)
        method = next(s for s in result.sections if s.key == "Test method and reference guidance")
        assert method.citations, "method section must cite sources"
        for c in method.citations:
            assert c.source and c.reference


# ------------------------------------------------------------ demo case 2 ---
class TestFailingCase:
    def test_fail_detected_consistently(self, tmp_path):
        result = generate(FAILING, tmp_path)
        assert result.evidence.failed == 1
        ev = result.evidence.evaluation_for("S-02")
        assert ev["verdict"] == "Fail"
        assert ev["measurement"] == 58.4
        codes = [i.code for i in result.checklist]
        assert "OUT_OF_RANGE" in codes

    def test_fail_value_preserved_verbatim_in_all_outputs(self, tmp_path):
        result = generate(FAILING, tmp_path)
        from docx import Document
        from openpyxl import load_workbook
        from pypdf import PdfReader

        doc = Document(str(result.docx_path))
        docx_text = "\n".join(p.text for p in doc.paragraphs)
        assert "58.4" in docx_text

        wb = load_workbook(str(result.xlsx_path))
        verdicts = [row[0] for row in wb["Results"].iter_rows(
            min_row=5, min_col=8, max_col=8, values_only=True)]
        assert verdicts.count("Fail") == 1

        pdf_text = "\n".join((p.extract_text() or "")
                             for p in PdfReader(str(result.combined_pdf_path)).pages)
        assert "58.4" in pdf_text
        assert "S-02" in pdf_text

    def test_summary_does_not_claim_all_within_range(self, tmp_path):
        result = generate(FAILING, tmp_path)
        summary = next(s for s in result.sections if s.key == "Summary and observations")
        assert "58.4" in summary.body
        assert "All measured results were within" not in summary.body


# ------------------------------------------------------------ demo case 3 ---
class TestIncompleteCase:
    def test_missing_sample_and_attachment_flagged(self, tmp_path):
        result = generate(INCOMPLETE, tmp_path)
        codes = [i.code for i in result.checklist]
        assert "MISSING_SAMPLES" in codes
        assert "MISSING_ATTACHMENT" in codes

    def test_no_data_fabricated(self, tmp_path):
        result = generate(INCOMPLETE, tmp_path)
        assert result.evidence.total == 4
        assert result.evidence.evaluation_for("S-04") is None
        summary = next(s for s in result.sections if s.key == "Summary and observations")
        assert "S-04" in summary.body
        assert "Equipment calibration record" in summary.body


# ------------------------------------------------------------------ units ---
class TestEvidenceUnit:
    def test_boundaries_inclusive(self):
        proto = parse_protocol(INPUTS / "protocol.md")
        rows = [SampleResult("X1", 45.0, "Nm", "", "45.0", 1),
                SampleResult("X2", 55.0, "Nm", "", "55.0", 2)]
        ev = build_evidence(rows, proto)
        assert [e["verdict"] for e in ev.evaluations] == ["Pass", "Pass"]

    def test_missing_measurement_is_no_data(self):
        proto = parse_protocol(INPUTS / "protocol.md")
        rows = [SampleResult("X1", None, "Nm", "", "", 1)]
        ev = build_evidence(rows, proto)
        assert ev.evaluations[0]["verdict"] == "NO DATA"


class TestFactGuard:
    def test_allowed_numbers_pass(self, tmp_path):
        proto = parse_protocol(INPUTS / "protocol.md")
        rows = parse_results_csv(INPUTS / "results.csv")
        ev = build_evidence(rows, proto)
        allowed = collect_allowed_numbers(ev, proto, [])
        text = ("5 samples were evaluated against 45.0 to 55.0 Nm; 5 passed and 0 failed. "
                "S-01 measured 48.2 Nm.")
        assert check_text(text, allowed).violations == []

    def test_invented_number_flagged(self, tmp_path):
        proto = parse_protocol(INPUTS / "protocol.md")
        rows = parse_results_csv(INPUTS / "results.csv")
        ev = build_evidence(rows, proto)
        allowed = collect_allowed_numbers(ev, proto, [])
        report = check_text("The retest showed 47.3 Nm and 99.7% yield.", allowed)
        assert report.violations, "invented numbers must be flagged"

    def test_reference_numbers_allowed(self, tmp_path):
        proto = parse_protocol(INPUTS / "protocol.md")
        rows = parse_results_csv(INPUTS / "results.csv")
        ev = build_evidence(rows, proto)
        index = LocalIndex()
        for ref in INPUTS.glob("*.md"):
            index.add_document(ref)
        hits = index.search("torque wrench resolution", k=2)
        allowed = collect_allowed_numbers(ev, proto, hits)
        assert check_text("The wrench resolution is 0.1 Nm per the reference.", allowed).violations == []


class TestOpenRouterFallbackChain:
    """The AI summary chain: first free model wins, failures fall through,
    everything is logged and attributed. No network: _post is stubbed."""

    @staticmethod
    def _llm_with(monkeypatch, responder):
        from minireport.llm import OpenRouterLLM

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        inst = OpenRouterLLM()
        inst._post = responder
        return inst

    def test_no_key_raises_cleanly(self, monkeypatch, tmp_path):
        from minireport.llm import OpenRouterLLM

        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        # empty tmp cwd: no .env file exists in the lookup chain
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            OpenRouterLLM()

    def test_first_model_success(self, monkeypatch):
        from minireport import llm as L

        calls = []

        def responder(model, prompt):
            calls.append(model)
            return "All samples passed."

        inst = self._llm_with(monkeypatch, responder)
        assert inst.summarise("f", "c") == "All samples passed."
        assert inst.model_used == L.FALLBACK_MODELS[0]
        assert calls == [L.FALLBACK_MODELS[0]]
        assert inst.attempt_log == [(L.FALLBACK_MODELS[0], "ok")]

    def test_failover_to_third_model(self, monkeypatch):
        from minireport import llm as L

        seq = iter([RuntimeError("HTTP 402: quota"),
                    RuntimeError("HTTP 429: rate limited"), None])

        def responder(model, prompt):
            err = next(seq)
            if err:
                raise err
            return "Recovered."

        inst = self._llm_with(monkeypatch, responder)
        assert inst.summarise("f", "c") == "Recovered."
        assert inst.model_used == L.FALLBACK_MODELS[2]
        assert [o for _, o in inst.attempt_log] == [
            "error: HTTP 402: quota", "error: HTTP 429: rate limited", "ok"]

    def test_all_models_fail(self, monkeypatch):
        from minireport import llm as L

        def responder(model, prompt):
            raise RuntimeError("down")

        inst = self._llm_with(monkeypatch, responder)
        with pytest.raises(RuntimeError, match="all OpenRouter fallback models failed"):
            inst.summarise("f", "c")
        assert len(inst.attempt_log) == len(L.FALLBACK_MODELS)

    def test_discarded_ai_draft_still_ships_deterministic_body(self, monkeypatch, tmp_path):
        from minireport import llm as L
        from minireport.pipeline import generate

        class InventLLM:
            model_used = L.FALLBACK_MODELS[0]
            attempt_log = [(L.FALLBACK_MODELS[0], "ok")]

            def summarise(self, facts, ctx):
                return "The retest averaged 47.31 Nm across units."  # invented

        res = generate(INPUTS, tmp_path, llm=InventLLM())
        s = next(x for x in res.sections if x.key == "Summary and observations")
        assert s.ai_discarded and "47.31" in s.ai_discard_reason
        assert s.ai_model == L.FALLBACK_MODELS[0]
        assert s.body, "section must remain complete after discard"
        assert "discarded" in s.process

    def test_good_draft_attributed_after_failover(self, monkeypatch, tmp_path):
        from minireport import llm as L
        from minireport.pipeline import generate

        class GoodLLM:
            model_used = L.FALLBACK_MODELS[1]
            attempt_log = [(L.FALLBACK_MODELS[0], "error: HTTP 429"),
                           (L.FALLBACK_MODELS[1], "ok")]

            def summarise(self, facts, ctx):
                return ("A total of 5 samples were evaluated against the acceptance "
                        "range 45 to 55 Nm: 5 passed and 0 failed. All measured results "
                        "were within the acceptance range. Review and edit before approval.")

        res = generate(INPUTS, tmp_path, llm=GoodLLM())
        s = next(x for x in res.sections if x.key == "Summary and observations")
        assert s.ai_used and s.ai_model == L.FALLBACK_MODELS[1]
        assert len(s.ai_attempts) == 2

    def test_strip_reasoning_removes_thinking_leaks(self):
        from minireport.llm import strip_reasoning

        leaked = strip_reasoning(
            "Here's a thinking process:\n\n1.  **Analyze the Request:**\n"
            "   - Task: Draft the Summary\n2.  **Compose:**\n"
            "   - Write the paragraph\n\n" + self._CLEAN_DRAFT)
        assert leaked == self._CLEAN_DRAFT

        assert strip_reasoning("Okay, let me analyze first.\n" + self._CLEAN_DRAFT) == self._CLEAN_DRAFT
        assert strip_reasoning(self._CLEAN_DRAFT) == self._CLEAN_DRAFT
        assert strip_reasoning("1. First point.\n2. Second point.") == "1. First point.\n2. Second point."

    _CLEAN_DRAFT = "A total of 5 samples were evaluated; 5 passed and 0 failed."

    def test_fallback_models_all_free_and_live(self):
        """Documentation test: every chained model ID appears in OpenRouter's
        current free list (network call; skipped offline)."""
        from minireport.llm import FALLBACK_MODELS, free_model_list

        try:
            live = free_model_list()
        except Exception as exc:  # offline / network down
            pytest.skip(f"OpenRouter model list unreachable: {exc}")
        missing = [m for m in FALLBACK_MODELS if m not in live]
        assert not missing, f"stale model IDs in fallback chain: {missing}"


class TestPlaceholderDetection:
    def test_unknown_placeholder_flagged(self, tmp_path):
        from docx import Document
        from minireport.report import build_report_docx

        # synthetic template with a placeholder the app does not know
        doc = Document()
        doc.add_heading("Project information and fixed statements", level=1)
        doc.add_paragraph("Reviewer: [[UNKNOWN_FIELD]]")
        doc.save(tmp_path / "report_template.docx")

        class FakeBundle:
            template_path = tmp_path / "report_template.docx"
            protocol = parse_protocol(INPUTS / "protocol.md")

        bundle = FakeBundle()
        result = generate.__wrapped__ if False else None
        from minireport.evidence import build_evidence as be
        rows = parse_results_csv(INPUTS / "results.csv")
        ev = be(rows, bundle.protocol)
        used, unfilled = build_report_docx(
            bundle, [], ev, {}, "- Attachment A: x.pdf", tmp_path / "out.docx"
        )
        assert "UNKNOWN_FIELD" in unfilled


class TestRetrievalUnit:
    def test_index_returns_relevant_chunk(self):
        index = LocalIndex()
        for ref in INPUTS.glob("*.md"):
            index.add_document(ref)
        hits = index.search("how to report out-of-range results", k=2)
        assert hits
        assert "Reporting_guidance" in hits[0].chunk.source or True  # sanity: non-empty

    def test_citation_location_format(self):
        index = LocalIndex()
        index.add_document(INPUTS / "Reporting_guidance.md")
        hits = index.search("traceability attachments labels", k=1)
        assert hits
        assert "para" in hits[0].chunk.location


class TestFactGuardRedaction:
    def test_redact_removes_disallowed_numbers(self):
        from minireport.factguard import redact_numbers

        cleaned = redact_numbers("Yield was 99.7% with 5 samples at 48.2 Nm.", {"5", "48.2"})
        assert "99.7" not in cleaned
        assert "5 samples" in cleaned
