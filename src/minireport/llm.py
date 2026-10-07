"""Optional AI narrative via the OpenAI API.

Activated with ``--ai openai`` (CLI) or the AI toggle (UI).  Requires
``OPENAI_API_KEY`` in the environment; every other path uses the
deterministic fallback, so the app never depends on the API being available.
"""

from __future__ import annotations

import os


class OpenAILLM:
    """Thin wrapper used by ``build_summary_section``."""

    MODEL = "gpt-4o-mini"

    def __init__(self) -> None:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set; run with --ai off or export the key")
        self._client = OpenAI(api_key=api_key)

    def summarise(self, facts: str, retrieved_context: str) -> str:
        prompt = f"""You are drafting the "Summary and observations" section of a draft
inspection report. Use ONLY the FACTS and the cited REFERENCE EXCERPTS below.

Hard rules:
- Never invent or alter numbers; the only numbers allowed are those in FACTS
  or in the reference excerpts. Any other number makes your draft invalid.
- Do not restate failures as successes and never invent causes or explanations.
- Mention missing measurements and missing attachments explicitly if present.
- 120-180 words, plain professional tone, no headings, no bullet lists.

FACTS:
{facts}

REFERENCE EXCERPTS:
{retrieved_context}
"""
        resp = self._client.chat.completions.create(
            model=self.MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=400,
        )
        return (resp.choices[0].message.content or "").strip()
