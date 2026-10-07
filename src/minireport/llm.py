"""AI narrative via the OpenRouter API with a free-model fallback chain.

Activated with ``--ai openrouter`` (CLI) or the AI toggle (UI).  Requires an
``OPENROUTER_API_KEY``, read from the environment or auto-loaded from a
``.env`` file (see :func:`load_env_file`); every other path uses the
deterministic fallback summary, so the app never depends on the API.

The fallback chain tries the listed free models in order.  Free endpoints can
be busy or rate-limited at any moment, so the first model gets a short
timeout and each attempted model's error is recorded; the first successful
draft wins and the outcome of each attempt is surfaced to the review UI.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Six free models, capability-first, each verified against the live API with a
# real call on 2026-10-07 (see test_fallback_models_all_free_and_live and the
# candidate scan): 1 & 2 answered instantly with clean output, 3 & 5 are proven
# performers whose free-tier 429s rotate, 4 is the largest free model (its
# reasoning prose is rejected by _post, see below), 6 is OpenRouter's wildcard
# router over whatever free model is currently available.  Empty-response and
# harness-restricted models (dots-3-note, ling-3.0-sante, apodex, inkling)
# were measured and deliberately excluded.
FALLBACK_MODELS: list[str] = [
    "nvidia/nemotron-3-super-120b-a12b:free",  # 120B MoE: instant, clean (main)
    "inclusionai/ling-3.1-flash",              # fast, clean output (free by default)
    "google/gemma-4-31b-it:free",              # 31B dense; transient 429s at peak
    "nvidia/nemotron-3-ultra-550b-a55b:free",  # biggest free model; reasoning-rejected
    "poolside/laguna-s-2.1:free",              # answered in two earlier live runs
    "openrouter/free",                         # wildcard: any currently free model
]

PROMPT_TEMPLATE = """You are drafting the "Summary and observations" section of a draft
inspection report. Use ONLY the FACTS and the cited REFERENCE EXCERPTS below.

Hard rules:
- Never invent or alter numbers; the only numbers allowed are those in FACTS
  or in the reference excerpts. Any other number makes your draft invalid.
- Do not restate failures as successes and never invent causes or explanations.
- Mention missing measurements and missing attachments explicitly if present.
- 120-180 words, plain professional tone, no headings, no bullet lists.
- Output ONLY the finished paragraph text. Do NOT include any analysis,
  thinking process, notes about the task, or commentary of any kind.

FACTS:
{facts}

REFERENCE EXCERPTS:
{context}
"""


def load_env_file(start_dir: str | Path | None = None, max_up: int = 6) -> bool:
    """Load KEY=VALUE pairs from the nearest ``.env`` file.

    Searches ``start_dir`` (default: cwd) and upward, so both ``streamlit``
    and repo-rooted CLI runs pick up the same file.  Existing environment
    variables always win (``setdefault``); comments, blank lines and quotes
    are handled.  The key itself is never logged.
    """
    start = Path(start_dir or os.getcwd()).resolve()
    for candidate in [start, *list(start.parents)[:max_up]]:
        env_file = candidate / ".env"
        if env_file.is_file():
            try:
                lines = env_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                return False
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, value)
            return True
    return False


STRIP_PATTERNS = (
    re.compile(r"^Here'?s (?:a|the) thinking process[^:]*:\s*", re.IGNORECASE),
    re.compile(r"^Let me (?:analyze|analyse|think)[^:]*:\s*", re.IGNORECASE),
    re.compile(r"^\s*\*{0,2}(?:ANALYSIS|ANALYZE|PLAN|REASONING|THINKING)\s*:?\s*\*{0,2}$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Okay,? .{0,80}?\.") ,
)


def strip_reasoning(text: str) -> str:
    """Remove chain-of-thought / task-analysis preamble some free models emit."""
    out = text.strip()
    for pattern in STRIP_PATTERNS:
        out = pattern.sub("", out)
    # Numbered thinking blocks: leading run of lines like "1. ..." where the
    # FIRST numbered line looks like reasoning (e.g. "Analyze the request");
    # the whole block including its sub-bullets is then dropped.  A plain
    # numbered list (first line is real content) is preserved untouched.
    lines = out.splitlines()
    i = 0
    reasoning_first = None
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            if reasoning_first is None:
                looks_reasoning = re.match(
                    r"\*{0,2}(?:Analyze|Review|Understand|Identify|Draft|Compose|"
                    r"Structure|Format|Check|Verify|Ensure|Note|Key|Task|Goal)\b",
                    m.group(2), re.IGNORECASE)
                if looks_reasoning:
                    reasoning_first = i
                    i += 1
                    continue
                else:
                    break  # real numbered content starts here
            i += 1
            continue
        if reasoning_first is not None and (line.startswith(("-", "*")) or line.startswith("   ")):
            i += 1  # sub-bullet of the reasoning block
            continue
        break
    if reasoning_first is not None:
        out = "\n".join(lines[i:])
        # drop a leaked section title like "**Summary and observations:**"
        out = re.sub(r"^\s*\**\s*(?:#{1,3}\s+|Summary (?:and|&) observations:?\s*)\**\s*",
                     "", out.strip(), count=1, flags=re.IGNORECASE)
    return out.strip()


class OpenRouterLLM:
    """Tries each model in FALLBACK_MODELS until one returns a draft."""

    # short timeout for the first model so a dead primary endpoint does not
    # hang the demo; later models get the same, keeping worst-case bounded
    TIMEOUT = 45.0

    def __init__(self) -> None:
        load_env_file()
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set; run with --ai off or add it to "
                ".env (see .env.example)"
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
        """One chat completion request; returns the text or raises.

        ``reasoning.enabled=False`` is sent for every model: reasoning-mode
        models (Nemotron etc.) otherwise put the answer into a separate
        ``message.reasoning`` field and leave ``content`` empty.  Non-reasoning
        models simply ignore the parameter.  If a model still returns only a
        reasoning field, the attempt fails rather than leaking thinking text
        into a report.
        """
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 400,
            "reasoning": {"enabled": False},
        }
        with httpx.Client(timeout=self.TIMEOUT) as client:
            resp = client.post(BASE_URL, headers=self._headers, json=body)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", "") or resp.text[:120]
            except Exception:
                detail = resp.text[:120]
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        message = (resp.json().get("choices") or [{}])[0].get("message", {})
        content = (message.get("content") or "").strip()
        if not content and (message.get("reasoning") or "").strip():
            raise RuntimeError("model returned reasoning-only output")
        text = strip_reasoning(content)
        if not text:
            raise RuntimeError("empty response body")
        # Last guard: some large free models narrate their reasoning ("The user
        # wants ...", "Key data points: ...") before answering.  If that prose
        # survives the stripper, reject the attempt so no meta-text can ever
        # reach a report; the chain simply tries the next model.
        head = text[:120].lower()
        if head.startswith(("the user ", "key data points", "as an ai")) or \
                "user wants" in head or "user is asking" in head or "here's a thinking" in head:
            raise RuntimeError("reasoning preamble could not be stripped")
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
