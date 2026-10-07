# AI Tools & Assistance Note

Per the assignment's submission requirements:

**AI coding tools used**

- Codebuff (AI coding agent) was used as the primary coding assistant for this
  prototype: project scaffolding, module implementation, test generation and
  debugging iterations.

**What was human-directed**

- The overall architecture: a single deterministic evidence object as the only
  source of Pass/Fail truth; retrieval before generation; the fact-guard rule
  that any non-traceable number disqualifies an AI draft; stable attachment
  labels; the template-preserving DOCX strategy.
- Demo scenario design (complete / failing / incomplete) and the validation
  checklist mapping to the brief.

**Assistance from other developers**

- None; this submission is individual work as required.

**Verification performed**

- 19 automated tests (`python -m pytest`) covering the three mandatory demo
  cases, Pass/Fail boundary behaviour, the fact guard, retrieval citations and
  placeholder detection.
- End-to-end CLI runs of all three demo cases with artifact inspection
  (DOCX text, XLSX cells, PDF text extraction, ZIP contents).
- Streamlit UI exercised with Streamlit's AppTest framework: scenario
  switching, generation, summary editing and limit-edit regeneration.
