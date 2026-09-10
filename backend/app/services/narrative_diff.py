import json
import re
from typing import Literal

from sqlmodel import Session

from app.models import Company, Filing, NarrativeChange
from app.services.edgar import EdgarClient
from app.services.embeddings import EmbeddingClient
from app.services.filing_sections import extract_legal_proceedings, extract_risk_factors
from app.services.llm import LocalLLMClient
from app.tools.rag.chunking.default import DefaultChunker
from app.tools.rag.retrieval import _cosine_similarity

SectionType = Literal["risk_factors", "legal_proceedings"]

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


def _ask_llm(llm: LocalLLMClient, prompt: str) -> str | None:
    try:
        raw = llm.complete([{"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 - a flaky local model must not break the whole diff
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    summary = parsed.get("summary")
    return str(summary) if summary else None


def _characterize_new_or_removed(
    llm: LocalLLMClient, text: str, change_type: Literal["new", "removed"], section_type: SectionType, score: float
) -> NarrativeChange:
    label = _SECTION_LABELS[section_type]
    verb = "added to" if change_type == "new" else "removed from"
    prompt = (
        f"This paragraph was {verb} a company's {label} section in a newer SEC filing "
        f"compared to the prior one.\n\nParagraph:\n{text[:2000]}\n\n"
        'Respond with JSON only: {"summary": "<one sentence describing what this paragraph is about>"}'
    )
    summary = _ask_llm(llm, prompt) or text[:200].strip()
    return NarrativeChange(
        section_type=section_type,
        change_type=change_type,
        summary=summary,
        similarity_score=score,
        new_excerpt=text[:_EXCERPT_LENGTH] if change_type == "new" else None,
        old_excerpt=text[:_EXCERPT_LENGTH] if change_type == "removed" else None,
    )


def _characterize_modified(
    llm: LocalLLMClient, new_text: str, old_text: str, section_type: SectionType, score: float
) -> NarrativeChange | None:
    label = _SECTION_LABELS[section_type]
    prompt = (
        f"Compare these two versions of a paragraph from a company's {label} section, from "
        f"consecutive SEC filings.\n\nOld version:\n{old_text[:1500]}\n\nNew version:\n{new_text[:1500]}\n\n"
        'Respond with JSON only: {"summary": "<one sentence describing what changed>"}'
    )
    summary = _ask_llm(llm, prompt)
    if not summary:
        return None
    return NarrativeChange(
        section_type=section_type,
        change_type="modified",
        summary=summary,
        similarity_score=score,
        new_excerpt=new_text[:_EXCERPT_LENGTH],
        old_excerpt=old_text[:_EXCERPT_LENGTH],
    )


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

    chunker = DefaultChunker(chunk_size=1200, chunk_overlap=100)
    current_chunks = chunker.chunk(current_text)
    previous_chunks = chunker.chunk(previous_text)
    if not current_chunks or not previous_chunks:
        return []

    embed = embedding_client or EmbeddingClient()
    current_embeddings = embed.embed(current_chunks)
    previous_embeddings = embed.embed(previous_chunks)

    llm = llm_client or LocalLLMClient()
    changes: list[NarrativeChange] = []

    for chunk, embedding in zip(current_chunks, current_embeddings, strict=True):
        score, matched_previous = _best_match(embedding, previous_chunks, previous_embeddings)
        if score >= _UNCHANGED_SIMILARITY:
            continue
        if score < _NO_MATCH_SIMILARITY:
            changes.append(_characterize_new_or_removed(llm, chunk, "new", section_type, score))
        else:
            modified = _characterize_modified(llm, chunk, matched_previous, section_type, score)
            if modified is not None:
                changes.append(modified)

    for chunk, embedding in zip(previous_chunks, previous_embeddings, strict=True):
        score, _ = _best_match(embedding, current_chunks, current_embeddings)
        if score < _NO_MATCH_SIMILARITY:
            changes.append(_characterize_new_or_removed(llm, chunk, "removed", section_type, score))

    for change in changes:
        change.filing_id = filing.id
        session.add(change)
    session.commit()
    for change in changes:
        session.refresh(change)
    return changes
