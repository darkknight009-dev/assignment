"""Shared text utilities."""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, numbers kept (limits like 9.5 matter)."""
    return TOKEN_RE.findall(text.lower())


# Words too common to be useful for retrieval scoring.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to",
    "was", "were", "will", "with", "this", "these", "those", "shall", "may",
    "must", "can", "not", "any", "all", "each", "which", "when", "where",
}


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS]
