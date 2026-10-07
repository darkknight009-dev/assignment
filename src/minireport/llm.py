"""AI narrative via the OpenRouter API with a free-model fallback chain.

Activated with ``--ai openrouter`` (CLI) or the AI toggle (UI).  Requires
``OPENROUTER_API_KEY`` in the environment; every other path uses the
deterministic fallback summary, so the app never depends on the API.

The fallback chain tries the listed free models in order.  Free endpoints can
be busy or rate-limited at any moment, so the first model gets a short
timeout and each attempted model's error is recorded; the first successful
draft wins and the outcome of each attempt is surfaced to the review UI.
"""

from __future__ import annotations

import os

import httpx

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Six free models, provider-diverse, instruction-following quality first.
# Verified free (0/0 pricing) against https://openrouter.ai/api/v1/models
# on 2026-10-07; refresh from that endpoint before relying on it.
FALLBACK_MODELS: list[str] = [
    "google/gemma-4-31b-it:free",          # newest Gemma IT, strong instruction following (main)
    "thinkingmachines/inkling-small:free",  # 1M-context general model
    "nvidia/nemotron-3-super-120b-a12b:free",  # large nvidia MoE, strong quality
    "inclusionai/ling-3.1-flash",           # fast recent flash model (free by default)
    "poolside/laguna-s-2.1:free",           # diverse provider fallback
    "liquid/lfm-2.5-2.6b:free",             # small/light, best last-resort for quota
]

PROMPT_TEMPLATE = """You are drafting the "Summary and observations" section of a draft
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
{context}
"""


class OpenRouterLLM:
    """Tries each model in FALLBACK_MODELS until one returns a draft."""

    # short timeout for the first model so a dead primary endpoint does not
    # hang the demo; later models get the same, keeping worst-case bounded
    TIMEOUT = 45.0

    def __init__(self) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set; run with --ai off or export the key"
            )
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (optional but recommended)
            "HTTP-Referer": "https://localhost/minireport",
            "X-Title": "Mini Report Generator",
        }
        self.model_used: str | None = None
        self.attempt_log: list[tuple[str, str]] = []  # (model, "ok"|"error: ...")

    def summarise(self, facts: str, retrieved_context: str) -> str:
        """Return the draft from the first model that answers.

        Raises RuntimeError only if every model fails, so the section builder
        can fall back to the deterministic summary.
        """
        prompt = PROMPT_TEMPLATE.format(facts=facts, context=retrieved_context)
        errors: list[str] = []

        for model in FALLBACK_MODELS:
            try:
                text = self._post(model, prompt)
                self.model_used = model
                self.attempt_log.append((model, "ok"))
                return text
            except Exception as exc:
                self.attempt_log.append((model, f"error: {exc}"))
                errors.append(f"{model}: {exc}")

        raise RuntimeError("all OpenRouter fallback models failed -> " + " | ".join(errors[:3]))

    def _post(self, model: str, prompt: str) -> str:
        """One chat completion request; returns the text or raises."""
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 400,
        }
        with httpx.Client(timeout=self.TIMEOUT) as client:
            resp = client.post(BASE_URL, headers=self._headers, json=body)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", "") or resp.text[:120]
            except Exception:
                detail = resp.text[:120]
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        text = (content or "").strip()
        if not text:
            raise RuntimeError("empty response body")
        return text


def free_model_list() -> list[str]:
    """Fetch the current free text models from OpenRouter, newest first.

    Used operationally to keep FALLBACK_MODELS up to date; not called during
    generation so the report flow never depends on network availability.
    """
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("https://openrouter.ai/api/v1/models")
        resp.raise_for_status()
        data = resp.json()["data"]
    free = [
        m for m in data
        if str(m.get("pricing", {}).get("prompt", "1")) == "0"
        and str(m.get("pricing", {}).get("completion", "1")) == "0"
        and m["architecture"]["output_modalities"] == ["text"]
        and "text" in m["architecture"]["input_modalities"]
    ]
    free.sort(key=lambda m: -m["created"])
    return [m["id"] for m in free]
