"""Retrieval-Augmented Generation support: a small local TF-IDF index.

No hosted vector DB is needed for this scale (a handful of short documents).
Chunks are paragraphs; every chunk keeps its source filename and a human
readable location (page/paragraph) so generated sections can cite exactly
where each sentence came from.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .docreader import read_any
from .textutils import content_tokens


@dataclass
class Chunk:
    source: str  # file name (not full path, safe to show in reports)
    location: str  # e.g. "p1 para3" or "para5"
    text: str
    tokens: list[str] = field(default_factory=list)
    tf: dict[str, int] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    chunk: Chunk
    score: float


class LocalIndex:
    """Tiny TF-IDF index with cosine scoring. Deterministic and offline."""

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._idf: dict[str, float] = {}

    # ------------------------------------------------------------- indexing
    def add_document(self, path: str | Path) -> int:
        """Extract text from ``path`` and index it paragraph by paragraph."""
        name = Path(path).name
        pages = read_any(path)  # list[(page_number_or_None, text)]
        added = 0
        para_counter = 0
        for page_no, page_text in pages:
            for para in _split_paragraphs(page_text):
                tokens = content_tokens(para)
                if len(tokens) < 4:
                    continue  # skip headings-only / trivial fragments
                para_counter += 1
                location = f"p{page_no} para{para_counter}" if page_no else f"para{para_counter}"
                tf: dict[str, int] = {}
                for t in tokens:
                    tf[t] = tf.get(t, 0) + 1
                self.chunks.append(
                    Chunk(source=name, location=location, text=para, tokens=tokens, tf=tf)
                )
                added += 1
        self._recompute_idf()
        return added

    def _recompute_idf(self) -> None:
        n = max(1, len(self.chunks))
        df: dict[str, int] = {}
        for c in self.chunks:
            for t in set(c.tokens):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(n / d) + 1.0 for t, d in df.items()}

    # -------------------------------------------------------------- queries
    def search(self, query: str, k: int = 4) -> list[RetrievalResult]:
        q_tokens = content_tokens(query)
        if not q_tokens or not self.chunks:
            return []
        q_tf: dict[str, int] = {}
        for t in q_tokens:
            q_tf[t] = q_tf.get(t, 0) + 1

        scored: list[RetrievalResult] = []
        for chunk in self.chunks:
            score = _cosine(q_tf, chunk.tf, self._idf)
            if score > 0:
                scored.append(RetrievalResult(chunk=chunk, score=score))
        scored.sort(key=lambda r: (-r.score, r.chunk.source, r.chunk.location))
        return scored[:k]

    def search_per_topic(self, topics: list[str], k_per_topic: int = 3) -> list[RetrievalResult]:
        """Union of per-topic searches, deduped by chunk, best score kept."""
        best: dict[int, RetrievalResult] = {}
        for topic in topics:
            for res in self.search(topic, k=k_per_topic):
                key = id(res.chunk)
                if key not in best or res.score > best[key].score:
                    best[key] = res
        ranked = sorted(best.values(), key=lambda r: -r.score)
        return ranked


def _cosine(q_tf: dict[str, int], d_tf: dict[str, int], idf: dict[str, float]) -> float:
    dot = 0.0
    for t, q_count in q_tf.items():
        w_q = q_count * idf.get(t, 1.0)
        w_d = d_tf.get(t, 0) * idf.get(t, 1.0)
        dot += w_q * w_d
    if dot == 0.0:
        return 0.0
    q_norm = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in q_tf.items()))
    d_norm = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in d_tf.items()))
    if q_norm == 0 or d_norm == 0:
        return 0.0
    return dot / (q_norm * d_norm)


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]
