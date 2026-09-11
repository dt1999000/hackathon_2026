"""Cheap, deterministic materiality triage for narrative-diff changes.

The problem this solves: the narrative-diff pipeline flags every chunk that
isn't near-identical to its prior-filing counterpart, but most of those are
routine — a reworded sentence, a boilerplate cross-reference restated with
a new note number. Only a minority are genuinely new risk exposure worth a
reader's attention. Asking the LLM to characterize (and rate) every single
one is both slow (each LLM call pays a real queue-wait cost on the shared,
single-slot Ollama server — see narrative_diff.py) and noisy in the output.

This module decides, for each candidate chunk, whether it's plausibly
"big potato" material BEFORE any LLM call — using two layers that reuse
data we already have, so the filter itself costs no additional LLM or
embedding calls at request time:

1. Lexical — the Loughran-McDonald Master Dictionary (resources/), a
   financial-text word list built and validated for exactly this kind of
   textual analysis (not something we invented). We use only its
   "Litigious" category: legal/regulatory vocabulary specific enough not
   to fire on ordinary risk-factor negativity (unlike "Negative", which
   would match almost every sentence in a Risk Factors section and be
   useless as a discriminator). Paired with a small hand-curated list of
   multi-word trigger phrases ("material weakness", "going concern",
   "data breach"...) that a single-word frequency list can't represent.
2. Semantic — cosine similarity between the chunk's ALREADY-COMPUTED
   embedding (from the bidirectional match step in narrative_diff.py) and
   a small set of reference-example embeddings, one per material-event
   category modeled on SEC Form 8-K's own item categories (the closest
   thing to an authoritative "what counts as material" list). The
   reference embeddings are computed once per process and cached — not
   recomputed per chunk, per filing, or per request.

A chunk is HIGH materiality if either layer fires; otherwise LOW. HIGH
chunks go to the LLM for real characterization. LOW chunks get a free,
instant, truncated-excerpt summary and never reach the model at all.
"""

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.services.embeddings import EmbeddingClient
from app.tools.rag.retrieval import _cosine_similarity

MaterialityTier = Literal["high", "low"]

_DICTIONARY_PATH = Path(__file__).resolve().parents[3] / "resources" / "Loughran-McDonald_MasterDictionary_1993-2025.csv"

# Only "Litigious" — L-M's "Negative" category is common enough in ordinary
# risk-factor prose (full of words like "adverse", "risk", "harm") that
# using it here would flag nearly everything, defeating the point of a
# filter. Litigious vocabulary (lawsuit, subpoena, indemnify, settlement...)
# is specific enough to be a real discriminator.
_LM_CATEGORY = "Litigious"
_MIN_LITIGIOUS_WORD_HITS = 2

# Multi-word phrases the word-frequency approach above can't represent —
# modeled on SEC Form 8-K's own item categories (bankruptcy, non-reliance
# on financials, executive changes, cybersecurity incidents) plus SAB 99's
# enumerated qualitative materiality factors (internal-control weaknesses,
# concealment of unlawful transactions).
_PHRASE_TRIGGERS = [
    "class action",
    "material weakness",
    "going concern",
    "data breach",
    "unauthorized access",
    "consent order",
    "sec investigation",
    "doj investigation",
    "subpoena",
    "restated",
    "restatement",
    "bankruptcy",
    "default under",
    "covenant breach",
    "cybersecurity incident",
    "ransomware",
    "product recall",
    "delisting",
    "delisted",
    "ceased operations",
    "impairment charge",
    "non-reliance",
    "internal control",
    "whistleblower",
    "indictment",
    "settlement agreement",
    "government investigation",
    "regulatory action",
    "substantial doubt",
]

# One embedding-similarity match against any of these beats an LLM call for
# deciding "is this plausibly material" — categories mirror 8-K item types.
_REFERENCE_EXAMPLES: dict[str, list[str]] = {
    "litigation": [
        "The Company received a subpoena from the SEC.",
        "We are a defendant in a class action lawsuit.",
        "A court entered a judgment against us.",
    ],
    "cybersecurity": [
        "An unauthorized third party gained access to our systems.",
        "We experienced a data breach affecting customer information.",
        "We discovered a cybersecurity incident affecting our operations.",
    ],
    "going_concern_liquidity": [
        "There is substantial doubt about our ability to continue as a going concern.",
        "We may be unable to meet our debt obligations as they come due.",
        "We are in default under our credit agreement.",
    ],
    "regulatory_action": [
        "We received a consent order from a regulator.",
        "We are subject to a government investigation.",
        "Regulators imposed a significant fine on the Company.",
    ],
    "restatement_controls": [
        "We restated our previously issued financial statements.",
        "We identified a material weakness in our internal controls.",
    ],
    "executive_departure": [
        "Our Chief Executive Officer resigned unexpectedly.",
        "We terminated our Chief Financial Officer.",
    ],
}

_EMBEDDING_SIMILARITY_THRESHOLD = 0.75

_reference_embeddings_cache: dict[str, list[list[float]]] | None = None


@lru_cache(maxsize=1)
def _load_litigious_words() -> frozenset[str]:
    words: set[str] = set()
    with open(_DICTIONARY_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = row.get(_LM_CATEGORY, "0")
            if value and value != "0":
                words.add(row["Word"].upper())
    return frozenset(words)


def _lexical_signal(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _PHRASE_TRIGGERS):
        return True
    words = re.findall(r"[A-Za-z']+", text.upper())
    litigious = _load_litigious_words()
    hits = sum(1 for word in words if word in litigious)
    return hits >= _MIN_LITIGIOUS_WORD_HITS


def _get_reference_embeddings(embedding_client: EmbeddingClient) -> dict[str, list[list[float]]]:
    global _reference_embeddings_cache
    if _reference_embeddings_cache is None:
        _reference_embeddings_cache = {
            category: embedding_client.embed(examples) for category, examples in _REFERENCE_EXAMPLES.items()
        }
    return _reference_embeddings_cache


def _semantic_signal(chunk_embedding: list[float], embedding_client: EmbeddingClient) -> str | None:
    for category, reference_embeddings in _get_reference_embeddings(embedding_client).items():
        for reference_embedding in reference_embeddings:
            if _cosine_similarity(chunk_embedding, reference_embedding) >= _EMBEDDING_SIMILARITY_THRESHOLD:
                return category
    return None


def assess_materiality(
    text: str, embedding: list[float], embedding_client: EmbeddingClient
) -> tuple[MaterialityTier, str | None]:
    """Returns (tier, matched_category). `matched_category` is only set for
    a semantic match — a lexical match doesn't map cleanly to one category."""
    if _lexical_signal(text):
        return "high", None
    category = _semantic_signal(embedding, embedding_client)
    if category is not None:
        return "high", category
    return "low", None
