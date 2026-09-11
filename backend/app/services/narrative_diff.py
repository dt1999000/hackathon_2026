import json
import re
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from app.models import Company, Filing, NarrativeChange
from app.services.edgar import EdgarClient
from app.services.embeddings import EmbeddingClient
from app.services.filing_sections import extract_legal_proceedings, extract_risk_factors
from app.services.llm import LocalLLMClient
from app.services.materiality import assess_materiality
from app.tools.rag.chunking.default import DefaultChunker
from app.tools.rag.retrieval import _cosine_similarity

SectionType = Literal["risk_factors", "legal_proceedings"]
ChangeType = Literal["new", "removed", "modified"]

# Similarity is the cheap pre-filter that keeps this affordable: most
# paragraphs in a Risk Factors section are identical quarter to quarter, so
# skipping the LLM entirely above _UNCHANGED_SIMILARITY (and treating
# anything below _NO_MATCH_SIMILARITY as "no real match" rather than
# "modified") means only the genuinely ambiguous middle band ever reaches
# the LLM.
_UNCHANGED_SIMILARITY = 0.97
_NO_MATCH_SIMILARITY = 0.55

_SECTION_LABELS: dict[SectionType, str] = {"risk_factors": "Risk Factors", "legal_proceedings": "Legal Proceedings"}
_EXCERPT_LENGTH = 1000

# Larger chunks than a typical RAG setup: fewer, coarser chunks mean fewer
# LLM calls, which matters more than usual here because the shared local
# Ollama server processes one request at a time (confirmed via its -np 1
# launch flag) — most of the wall-clock cost of this pipeline is queueing
# behind our own prior calls, not per-call compute (measured ~2-4s of real
# GPU work per call vs. 30-60s wall time). Cutting call count is the
# highest-leverage lever available from application code.
_CHUNK_SIZE = 2500
_CHUNK_OVERLAP = 150

# Batching multiple chunk-pairs into one LLM call divides the queue-wait
# tax by roughly the batch size. Kept modest because the server's context
# window is only 4096 tokens (confirmed via /api/ps) and qwen3:4b's
# thinking-mode output can run long even for simple asks (a trivial
# one-line test prompt still produced 150-300 reasoning tokens) — a batch
# that's too large risks context overflow mid-generation.
_BATCH_SIZE = 4
_BATCH_ITEM_LENGTH = 800
_BATCH_PAIR_ITEM_LENGTH = 600


@dataclass
class _PendingChange:
    change_type: ChangeType
    new_text: str | None
    old_text: str | None
    score: float
    embedding: list[float]


def _extract_section(edgar: EdgarClient, cik: str, filing: Filing, section_type: SectionType) -> str | None:
    if filing.primary_document is None:
        return None
    html = edgar.get_filing_document(cik, filing.accession_number, filing.primary_document)
    if section_type == "risk_factors":
        return extract_risk_factors(html)
    return extract_legal_proceedings(html, filing.form_type)


def _best_match(embedding: list[float], candidates: list[str], candidate_embeddings: list[list[float]]) -> tuple[float, str]:
    best_score = -1.0
    best_text = ""
    for text, candidate_embedding in zip(candidates, candidate_embeddings, strict=True):
        score = _cosine_similarity(embedding, candidate_embedding)
        if score > best_score:
            best_score = score
            best_text = text
    return best_score, best_text


def _ask_llm_batch(llm: LocalLLMClient, prompt: str, expected_count: int) -> list[str | None]:
    try:
        raw = llm.complete([{"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 - a flaky local model must not break the whole diff
        return [None] * expected_count
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return [None] * expected_count
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [None] * expected_count
    if not isinstance(parsed, list):
        return [None] * expected_count

    summaries: list[str | None] = []
    for i in range(expected_count):
        item = parsed[i] if i < len(parsed) else None
        summary = item.get("summary") if isinstance(item, dict) else None
        summaries.append(str(summary) if summary else None)
    return summaries


def _describe_item(index: int, item: _PendingChange, label: str) -> str:
    if item.change_type == "new":
        assert item.new_text is not None
        return f"{index}. [ADDED paragraph in the {label} section]\n{item.new_text[:_BATCH_ITEM_LENGTH]}"
    if item.change_type == "removed":
        assert item.old_text is not None
        return f"{index}. [REMOVED paragraph from the {label} section]\n{item.old_text[:_BATCH_ITEM_LENGTH]}"
    assert item.new_text is not None and item.old_text is not None
    return (
        f"{index}. [MODIFIED paragraph in the {label} section]\n"
        f"Old version:\n{item.old_text[:_BATCH_PAIR_ITEM_LENGTH]}\n"
        f"New version:\n{item.new_text[:_BATCH_PAIR_ITEM_LENGTH]}"
    )


def _characterize_batch(llm: LocalLLMClient, section_type: SectionType, batch: list[_PendingChange]) -> list[NarrativeChange]:
    label = _SECTION_LABELS[section_type]
    items_text = "\n\n".join(_describe_item(i, item, label) for i, item in enumerate(batch, start=1))
    prompt = (
        f"Below are {len(batch)} numbered changes between two versions of a company's {label} section, "
        f"from consecutive SEC filings. For ADDED/REMOVED paragraphs, describe in one sentence what the "
        f"paragraph is about. For MODIFIED paragraphs, describe in one sentence what changed.\n\n"
        f"{items_text}\n\n"
        f'Respond with JSON only: an array of exactly {len(batch)} objects in order, each '
        '{"summary": "<one sentence>"}. Example: [{"summary": "..."}, {"summary": "..."}]'
    )
    summaries = _ask_llm_batch(llm, prompt, len(batch))

    changes: list[NarrativeChange] = []
    for item, summary in zip(batch, summaries, strict=True):
        if item.change_type == "modified" and not summary:
            continue  # no fallback for modified — an unclear diff isn't worth a vague row
        fallback = (item.new_text or item.old_text or "")[:200].strip()
        changes.append(
            NarrativeChange(
                section_type=section_type,
                change_type=item.change_type,
                summary=summary or fallback,
                similarity_score=item.score,
                new_excerpt=item.new_text[:_EXCERPT_LENGTH] if item.new_text else None,
                old_excerpt=item.old_text[:_EXCERPT_LENGTH] if item.old_text else None,
            )
        )
    return changes


def diff_narrative_section(
    session: Session,
    filing: Filing,
    section_type: SectionType,
    edgar_client: EdgarClient | None = None,
    llm_client: LocalLLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> list[NarrativeChange]:
    """Compare a filing's narrative section against the prior filing of the
    same form_type and persist the changes found. Empty list if there's no
    previous filing, either side fails to extract, or nothing changed."""
    if filing.previous_filing_id is None:
        return []
    previous_filing = session.get(Filing, filing.previous_filing_id)
    if previous_filing is None:
        return []
    company = session.get(Company, filing.company_id)
    if company is None:
        return []

    edgar = edgar_client or EdgarClient()
    current_text = _extract_section(edgar, company.cik, filing, section_type)
    previous_text = _extract_section(edgar, company.cik, previous_filing, section_type)
    if not current_text or not previous_text:
        return []

    chunker = DefaultChunker(chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP)
    current_chunks = chunker.chunk(current_text)
    previous_chunks = chunker.chunk(previous_text)
    if not current_chunks or not previous_chunks:
        return []

    embed = embedding_client or EmbeddingClient()
    current_embeddings = embed.embed(current_chunks)
    previous_embeddings = embed.embed(previous_chunks)

    pending: list[_PendingChange] = []

    for chunk, embedding in zip(current_chunks, current_embeddings, strict=True):
        score, matched_previous = _best_match(embedding, previous_chunks, previous_embeddings)
        if score >= _UNCHANGED_SIMILARITY:
            continue
        if score < _NO_MATCH_SIMILARITY:
            pending.append(_PendingChange("new", new_text=chunk, old_text=None, score=score, embedding=embedding))
        else:
            pending.append(
                _PendingChange("modified", new_text=chunk, old_text=matched_previous, score=score, embedding=embedding)
            )

    for chunk, embedding in zip(previous_chunks, previous_embeddings, strict=True):
        score, _ = _best_match(embedding, current_chunks, current_embeddings)
        if score < _NO_MATCH_SIMILARITY:
            pending.append(_PendingChange("removed", new_text=None, old_text=chunk, score=score, embedding=embedding))

    # Materiality triage: decide which chunks are worth an LLM call BEFORE
    # making one. Neither layer inside assess_materiality costs anything
    # extra here — the chunk embedding already exists, and the reference
    # embeddings it's compared against are computed once and cached.
    llm = llm_client or LocalLLMClient()
    changes: list[NarrativeChange] = []
    needs_llm: list[_PendingChange] = []
    for item in pending:
        text = item.new_text or item.old_text or ""
        tier, _category = assess_materiality(text, item.embedding, embed)
        if tier == "high":
            needs_llm.append(item)
        else:
            changes.append(
                NarrativeChange(
                    section_type=section_type,
                    change_type=item.change_type,
                    summary=text[:200].strip(),
                    similarity_score=item.score,
                    new_excerpt=item.new_text[:_EXCERPT_LENGTH] if item.new_text else None,
                    old_excerpt=item.old_text[:_EXCERPT_LENGTH] if item.old_text else None,
                )
            )

    for i in range(0, len(needs_llm), _BATCH_SIZE):
        changes.extend(_characterize_batch(llm, section_type, needs_llm[i : i + _BATCH_SIZE]))

    for change in changes:
        change.filing_id = filing.id
        session.add(change)
    session.commit()
    for change in changes:
        session.refresh(change)
    return changes
