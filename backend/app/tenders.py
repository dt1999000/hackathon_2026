from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def first_nonempty(*values: Any) -> Any:
    for value in values:
        cleaned = blank_to_none(value)
        if cleaned is not None:
            return cleaned
    return None


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes)):
        items: list[str] = []
        for item in value:
            cleaned = blank_to_none(item)
            if cleaned is not None:
                items.append(str(cleaned))
        return items
    return [str(value)]


def parse_decimal(value: Any) -> Decimal | None:
    cleaned = blank_to_none(value)
    if cleaned is None:
        return None
    try:
        return Decimal(str(cleaned).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def combine_deadline(date_value: Any, time_value: Any) -> str | None:
    date_part = blank_to_none(date_value)
    time_part = blank_to_none(time_value)
    if date_part and time_part:
        return f"{date_part} {time_part}"
    if date_part:
        return str(date_part)
    return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


@dataclass(slots=True)
class Location:
    street: str | None = None
    additional_street: str | None = None
    postcode: str | None = None
    city: str | None = None
    nuts: str | None = None
    country: str | None = None


@dataclass(slots=True)
class CodedRequirement:
    code: str | None = None
    code_list: str | None = None
    description: str | None = None


@dataclass(slots=True)
class Guarantee:
    required: str | None = None
    description: str | None = None


@dataclass(slots=True)
class DocumentLink:
    url: str | None = None
    raw_url: str | None = None
    document_type: str | None = None
    document_reference_id: str | None = None
    scope: str | None = None
    description: str | None = None


@dataclass(slots=True)
class TenderDocument:
    local_path: str | None = None
    source_url: str | None = None
    content_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    filename: str | None = None


@dataclass(slots=True)
class TenderLot:
    """Flattened lot record ready to persist as JSON / JSONB columns."""

    id: str
    notice_identifier: str
    notice_version: str
    lot_identifier: str
    procedure_identifier: str | None = None
    internal_identifier: str | None = None
    title: str | None = None
    description: str | None = None
    buyer_names: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    nuts: str | None = None
    cpv_codes: list[str] = field(default_factory=list)
    matched_cpv_codes: list[str] = field(default_factory=list)
    matched_via: str | None = None
    contract_nature: str | None = None
    form_type: str | None = None
    notice_type: str | None = None
    notice_root_type: str | None = None
    procedure_type: str | None = None
    publication_date: str | None = None
    issue_date: str | None = None
    requested_publication_date: str | None = None
    submission_deadline: str | None = None
    submission_deadline_date: str | None = None
    submission_deadline_time: str | None = None
    question_deadline_date: str | None = None
    question_deadline_time: str | None = None
    duration_start_date: str | None = None
    duration_end_date: str | None = None
    estimated_value: Decimal | None = None
    estimated_value_currency: str | None = None
    submission_url: str | None = None
    submission_method: str | None = None
    award_criterion_types: list[str] = field(default_factory=list)
    selection_criteria: list[CodedRequirement] = field(default_factory=list)
    qualification_requirements: list[CodedRequirement] = field(default_factory=list)
    guarantees: list[Guarantee] = field(default_factory=list)
    execution_conditions: list[CodedRequirement] = field(default_factory=list)
    document_links: list[DocumentLink] = field(default_factory=list)
    documents: list[TenderDocument] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    xml_file: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def _location_from_raw(raw: dict[str, Any]) -> Location:
    return Location(
        street=blank_to_none(raw.get("street")),
        additional_street=blank_to_none(raw.get("additionalStreet")),
        postcode=blank_to_none(raw.get("postcode")),
        city=blank_to_none(raw.get("city")),
        nuts=blank_to_none(raw.get("nuts")),
        country=blank_to_none(raw.get("country")),
    )


def _coded_requirement_from_raw(raw: dict[str, Any]) -> CodedRequirement:
    return CodedRequirement(
        code=blank_to_none(raw.get("code")),
        code_list=blank_to_none(raw.get("codeList")),
        description=blank_to_none(raw.get("description")),
    )


def _document_link_from_raw(raw: dict[str, Any]) -> DocumentLink | None:
    url = first_nonempty(raw.get("url"), raw.get("rawUrl"))
    if url is None and blank_to_none(raw.get("documentReferenceId")) is None:
        return None
    return DocumentLink(
        url=blank_to_none(raw.get("url")) or url,
        raw_url=blank_to_none(raw.get("rawUrl")),
        document_type=blank_to_none(raw.get("documentType")),
        document_reference_id=blank_to_none(raw.get("documentReferenceId")),
        scope=blank_to_none(raw.get("scope")),
        description=blank_to_none(raw.get("description")),
    )


def _document_from_raw(raw: dict[str, Any]) -> TenderDocument:
    local_path = blank_to_none(raw.get("localPath"))
    return TenderDocument(
        local_path=local_path,
        source_url=first_nonempty(raw.get("sourceUrl"), raw.get("finalUrl")),
        content_type=blank_to_none(raw.get("contentType")),
        sha256=blank_to_none(raw.get("sha256")),
        size_bytes=raw.get("sizeBytes") if isinstance(raw.get("sizeBytes"), int) else None,
        filename=blank_to_none(raw.get("filename"))
        or (Path(local_path).name if local_path else None),
    )


def agent_record_to_tender(record: dict[str, Any]) -> TenderLot:
    """Map one agent_input.jsonl object onto the database-ready TenderLot schema."""
    discovery = record.get("discovery") or {}
    eforms = record.get("eforms") or {}
    locations = [_location_from_raw(item) for item in (eforms.get("locations") or [])]
    primary = locations[0] if locations else Location()

    document_links: list[DocumentLink] = []
    seen_urls: set[str] = set()
    for raw in (*(record.get("documentLinks") or []), *(eforms.get("documentLinks") or [])):
        link = _document_link_from_raw(raw)
        if link is None:
            continue
        key = link.url or link.raw_url or link.document_reference_id or ""
        if key in seen_urls:
            continue
        seen_urls.add(key)
        document_links.append(link)

    return TenderLot(
        id=str(record["candidateId"]),
        notice_identifier=str(record["noticeIdentifier"]),
        notice_version=str(record["noticeVersion"]),
        lot_identifier=str(record["lotIdentifier"]),
        procedure_identifier=first_nonempty(
            eforms.get("procedureIdentifier"), discovery.get("procedureIdentifier")
        ),
        internal_identifier=first_nonempty(
            eforms.get("internalIdentifier"), discovery.get("internalIdentifier")
        ),
        title=first_nonempty(eforms.get("title"), discovery.get("title")),
        description=first_nonempty(eforms.get("description"), discovery.get("description")),
        buyer_names=as_string_list(eforms.get("buyerNames")),
        locations=locations,
        city=primary.city,
        postcode=primary.postcode,
        country=primary.country,
        nuts=primary.nuts,
        cpv_codes=as_string_list(eforms.get("cpvCodes") or discovery.get("matchedCpvCodes")),
        matched_cpv_codes=as_string_list(discovery.get("matchedCpvCodes")),
        matched_via=blank_to_none(discovery.get("matchedVia")),
        contract_nature=first_nonempty(
            eforms.get("contractNature"), discovery.get("mainNature")
        ),
        form_type=blank_to_none(discovery.get("formType")),
        notice_type=first_nonempty(discovery.get("noticeType"), eforms.get("noticeTypeCode")),
        notice_root_type=blank_to_none(eforms.get("noticeRootType")),
        procedure_type=blank_to_none(eforms.get("procedureType")),
        publication_date=blank_to_none(discovery.get("publicationDate")),
        issue_date=blank_to_none(eforms.get("issueDate")),
        requested_publication_date=blank_to_none(eforms.get("requestedPublicationDate")),
        submission_deadline=combine_deadline(
            eforms.get("submissionDeadlineDate"), eforms.get("submissionDeadlineTime")
        ),
        submission_deadline_date=blank_to_none(eforms.get("submissionDeadlineDate")),
        submission_deadline_time=blank_to_none(eforms.get("submissionDeadlineTime")),
        question_deadline_date=blank_to_none(eforms.get("questionDeadlineDate")),
        question_deadline_time=blank_to_none(eforms.get("questionDeadlineTime")),
        duration_start_date=blank_to_none(eforms.get("durationStartDate")),
        duration_end_date=blank_to_none(eforms.get("durationEndDate")),
        estimated_value=parse_decimal(
            first_nonempty(eforms.get("estimatedValue"), discovery.get("estimatedValue"))
        ),
        estimated_value_currency=first_nonempty(
            eforms.get("estimatedValueCurrency"), discovery.get("estimatedValueCurrency")
        ),
        submission_url=blank_to_none(eforms.get("submissionUrl")),
        submission_method=blank_to_none(eforms.get("submissionMethod")),
        award_criterion_types=as_string_list(eforms.get("awardCriterionTypes")),
        selection_criteria=[
            _coded_requirement_from_raw(item) for item in (eforms.get("selectionCriteria") or [])
        ],
        qualification_requirements=[
            _coded_requirement_from_raw(item)
            for item in (eforms.get("qualificationRequirements") or [])
        ],
        guarantees=[
            Guarantee(
                required=blank_to_none(item.get("required")),
                description=blank_to_none(item.get("description")),
            )
            for item in (eforms.get("guarantees") or [])
        ],
        execution_conditions=[
            _coded_requirement_from_raw(item)
            for item in (eforms.get("executionConditions") or [])
        ],
        document_links=document_links,
        documents=[_document_from_raw(item) for item in (record.get("documents") or [])],
        missing_evidence=as_string_list(record.get("missingEvidence")),
        xml_file=blank_to_none(eforms.get("xmlFile")),
    )


def iter_tender_lots(jsonl_path: str | Path) -> Iterator[TenderLot]:
    path = Path(jsonl_path)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield agent_record_to_tender(json.loads(line))


def load_tender_lots(jsonl_path: str | Path) -> list[TenderLot]:
    return list(iter_tender_lots(jsonl_path))


def write_tender_lots_json(
    jsonl_path: str | Path,
    destination: str | Path | None = None,
) -> Path:
    """Convert agent_input.jsonl into a JSON array of TenderLot records."""
    source = Path(jsonl_path)
    output = Path(destination) if destination else source.with_name("tenders.json")
    lots = load_tender_lots(source)
    output.write_text(
        json.dumps([lot.to_json_dict() for lot in lots], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output
