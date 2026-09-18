import json

import pytest

from app.agents.bid_fit import (
    FitAnalysis,
    HardlinerExtraction,
    derive_hardliners_from_profile,
    generate_violations,
    merge_hardliners_with_notes,
    retrieve_bid_context,
)
from app.agents.bid_fit_scoring import HardlinerViolation
from app.models import CompanyProfileBase


class _FakeEmbeddingClient:
    """Maps known strings to hand-picked vectors so similarity is
    deterministic, instead of calling out to a real embedding model."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]


class _FakeStructuredLLM:
    def __init__(self, response: object) -> None:
        self._response = response

    def invoke(self, prompt: str) -> object:
        return self._response


class _FakeChatModel:
    """Stands in for a LangChain chat model: `.with_structured_output(schema)`
    returns a fake that always yields the canned response, regardless of
    prompt — enough to test the calling code without a real LLM call."""

    def __init__(self, response: object) -> None:
        self._response = response

    def with_structured_output(self, schema: type) -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self._response)


def test_retrieve_bid_context_counts_a_matched_section(tmp_path) -> None:
    bid_file = tmp_path / "bid.json"
    bid_file.write_text(json.dumps({"title": "Road resurfacing contract"}), encoding="utf-8")

    section = "Capabilities: road construction"
    chunk_text = 'title: "Road resurfacing contract"'

    client = _FakeEmbeddingClient({section: [1.0, 0.0], chunk_text: [0.8, 0.2]})

    metadata, context_chunks, similarity_score = retrieve_bid_context(
        bid_source=str(bid_file),
        bid_loader="json",
        bid_chunker="default",
        profile_sections=[section],
        embedding_client=client,
        top_k=1,
    )

    assert metadata["format"] == "json"
    assert context_chunks == [chunk_text]
    assert similarity_score == 1.0  # 1 of 1 sections matched


def test_retrieve_bid_context_scores_zero_when_nothing_clears_the_threshold(tmp_path) -> None:
    bid_file = tmp_path / "bid.json"
    bid_file.write_text(json.dumps({"title": "Road resurfacing contract"}), encoding="utf-8")

    section = "Certifications held: explosion-protection"
    chunk_text = 'title: "Road resurfacing contract"'

    client = _FakeEmbeddingClient({section: [1.0, 0.0], chunk_text: [0.0, 1.0]})

    metadata, context_chunks, similarity_score = retrieve_bid_context(
        bid_source=str(bid_file),
        bid_loader="json",
        bid_chunker="default",
        profile_sections=[section],
        embedding_client=client,
        top_k=1,
    )

    assert context_chunks == []
    assert similarity_score == 0.0


def test_retrieve_bid_context_score_is_the_fraction_of_sections_matched(tmp_path) -> None:
    bid_file = tmp_path / "bid.json"
    bid_file.write_text(json.dumps({"title": "Road resurfacing contract"}), encoding="utf-8")

    matching_section = "Capabilities: road construction"
    unmatching_section = "Certifications held: explosion-protection"
    chunk_text = 'title: "Road resurfacing contract"'

    client = _FakeEmbeddingClient(
        {
            matching_section: [1.0, 0.0],
            unmatching_section: [0.0, 1.0],
            chunk_text: [0.9, 0.1],
        }
    )

    _, context_chunks, similarity_score = retrieve_bid_context(
        bid_source=str(bid_file),
        bid_loader="json",
        bid_chunker="default",
        profile_sections=[matching_section, unmatching_section],
        embedding_client=client,
        top_k=1,
    )

    assert context_chunks == [chunk_text]
    assert similarity_score == 0.5  # 1 of 2 sections matched


def test_retrieve_bid_context_accepts_inline_bid_content() -> None:
    section = "Capabilities: road construction"
    chunk_text = 'title: "Road resurfacing contract"'

    client = _FakeEmbeddingClient({section: [1.0, 0.0], chunk_text: [0.8, 0.2]})

    metadata, context_chunks, similarity_score = retrieve_bid_context(
        bid_source=None,
        bid_loader="json",
        bid_chunker="default",
        profile_sections=[section],
        embedding_client=client,
        top_k=1,
        bid_content=json.dumps({"title": "Road resurfacing contract"}),
    )

    assert metadata == {"format": "json", "type": "dict"}
    assert context_chunks == [chunk_text]
    assert similarity_score == 1.0


def test_retrieve_bid_context_requires_source_or_content() -> None:
    with pytest.raises(ValueError, match="bid_source or bid_content"):
        retrieve_bid_context(
            bid_source=None,
            bid_loader="json",
            bid_chunker="default",
            profile_sections=["x"],
            embedding_client=_FakeEmbeddingClient({}),
            top_k=1,
        )


def test_derive_hardliners_from_profile_needs_no_llm_call() -> None:
    profile = CompanyProfileBase(
        company_name="Test Co",
        base_location="Augsburg",
        max_radius_km=150,
        served_regions=["Bavaria"],
        excluded_regions=["Saxony"],
        min_contract_value_eur=400_000,
        max_contract_value_eur=4_000_000,
        explicit_exclusions=["rail-side work"],
        max_self_perform_pct=40,
        guarantee_limit_total_eur=1_500_000,
        guarantee_currently_committed_eur=200_000,
        custom_hardliners=["No bridges"],
    )

    hardliners = derive_hardliners_from_profile(profile)

    # custom_hardliners come through verbatim — no paraphrasing.
    assert "No bridges" in hardliners
    assert "Must not involve: rail-side work" in hardliners
    assert "Must be within 150 km of Augsburg" in hardliners
    assert "Must be in one of these regions: Bavaria" in hardliners
    assert "Must not be in: Saxony" in hardliners
    assert any("400000" in h and "4000000" in h for h in hardliners)
    assert "Self-performed work share must not exceed 40%" in hardliners
    assert any("1300000" in h for h in hardliners)  # 1.5M limit - 200k committed


def test_derive_hardliners_from_profile_is_empty_for_a_minimal_profile() -> None:
    profile = CompanyProfileBase(company_name="Minimal Co")
    assert derive_hardliners_from_profile(profile) == []


def test_merge_hardliners_with_notes_returns_llm_output() -> None:
    expected = HardlinerExtraction(hardliners=["No bridges", "No work on Sundays"])
    llm = _FakeChatModel(expected)

    hardliners = merge_hardliners_with_notes(
        llm, base_hardliners=["No bridges"], user_notes="also no Sunday work"
    )
    assert hardliners == expected.hardliners


def test_generate_violations_returns_llm_output_unmodified() -> None:
    expected = FitAnalysis(
        violations=[
            HardlinerViolation(
                hardliner="No bridges",
                violated=True,
                reason="The bid explicitly requires bridge construction.",
                solution=None,
                solution_is_realistic=False,
            )
        ]
    )
    llm = _FakeChatModel(expected)

    violations = generate_violations(
        llm=llm,
        hardliners=["No bridges"],
        profile_text="",
        context_chunks=["This lot includes bridge construction."],
        bid_source="test",
    )
    assert violations == expected.violations
