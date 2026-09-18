"""
Standalone adapter: turns an already-produced agent_input.jsonl (from
CPV45_Eforms_Attachments_Pipeline.py) into contract_schema.json-shaped
instances -- one file per (notice, lot), matching ted_pipeline.py's output
exactly so both sources can be validated/imported with the same tools.

This is decoupled from the CSV/eForms download steps on purpose: you can
run it against any agent_input.jsonl you already have, right now, without
re-running the (slow, network-dependent) rest of the pipeline. The mapping
logic here is identical to the version embedded in
CPV45_Eforms_Attachments_Pipeline.py's own "8. Export common contract_schema
instances" section -- kept in sync by hand; if you change one, change both.

USAGE:
    python build_schema_from_agent_input.py <path-to-agent_input.jsonl> [output_dir]
"""

import json
import re
import sys
import os
from pathlib import Path
from typing import Any


def safe_component(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value)).strip("._")
    return cleaned[:120] or fallback


def to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def first_and_rest(values: list) -> tuple[str, list]:
    values = values or []
    return (values[0], values[1:]) if values else ("", [])


# Same company-profile filter as CPV45_Eforms_Attachments_Pipeline.py's own
# export step and ted_pipeline.py's QUERY -- kept here too so this fast path
# doesn't silently behave differently (export everything, unfiltered) from
# a full pipeline run. Keep all three in sync by hand if you change one.
PROFILE_VALUE_MIN = float(os.environ.get("CPV45_PROFILE_VALUE_MIN", "0"))
PROFILE_VALUE_MAX = float(os.environ.get("CPV45_PROFILE_VALUE_MAX", "inf"))
PROFILE_NUTS_PREFIXES = tuple(
    p.strip() for p in os.environ.get(
        "CPV45_PROFILE_NUTS_PREFIXES", ""
    ).split(",") if p.strip()
)


def matches_company_profile(record: dict[str, Any]) -> bool:
    discovery = record.get("discovery") or {}
    eforms = record.get("eforms") or {}

    value = to_float(discovery.get("estimatedValue") or eforms.get("estimatedValue"))
    if value is not None and not (PROFILE_VALUE_MIN <= value <= PROFILE_VALUE_MAX):
        return False

    if PROFILE_NUTS_PREFIXES:
        nuts_codes = [loc.get("nuts", "") for loc in eforms.get("locations", []) if loc.get("nuts")]
        if nuts_codes and not any(n.startswith(PROFILE_NUTS_PREFIXES) for n in nuts_codes):
            return False

    return True


def build_contract_schema_instance(record: dict[str, Any]) -> dict[str, Any]:
    """Map one agent_input.jsonl record (one lot) onto contract_schema.json.

    See contract_schema.json's own per-field "description" for the matching
    TED-side mapping and why each design choice was made (verified against
    real notices, not guessed).
    """
    discovery = record.get("discovery") or {}
    eforms = record.get("eforms") or {}

    cpv_codes = eforms.get("cpvCodes") or discovery.get("matchedCpvCodes") or []
    main_cpv, additional_cpv = first_and_rest(cpv_codes)

    return {
        "schemaVersion": "1.0",
        "provenance": {
            "sourceSystem": "oeffentlichevergabe.de",
            "sourceRecordId": record["candidateId"],
            "candidateId": record["candidateId"],
            "matchedVia": discovery.get("matchedVia"),
            "matchedCpvCodes": discovery.get("matchedCpvCodes", []),
            "missingEvidence": record.get("missingEvidence", []),
        },
        "notice": {
            "identifier": record["noticeIdentifier"],
            "version": record["noticeVersion"],
            "lotIdentifier": record["lotIdentifier"] or None,
            "procedureIdentifier": discovery.get("procedureIdentifier") or eforms.get("procedureIdentifier"),
            "internalIdentifier": eforms.get("internalIdentifier") or discovery.get("internalIdentifier"),
            "formType": discovery.get("formType"),
            "noticeTypeCode": eforms.get("noticeTypeCode") or discovery.get("noticeType"),
            "noticeRootType": eforms.get("noticeRootType"),
            "publicationDate": discovery.get("publicationDate"),
            "issueDate": eforms.get("issueDate"),
        },
        "buyer": {
            "names": eforms.get("buyerNames", []),
        },
        "procedure": {
            "title": discovery.get("title") or eforms.get("title"),
            "description": discovery.get("description") or eforms.get("description"),
            "type": eforms.get("procedureType"),
            "typeRaw": eforms.get("procedureType"),
        },
        "classification": {
            "mainNature": discovery.get("mainNature") or eforms.get("contractNature") or "",
            "mainCpvCode": main_cpv,
            "additionalCpvCodes": additional_cpv,
        },
        "placeOfPerformance": eforms.get("locations", []),
        "value": {
            "estimatedValue": to_float(discovery.get("estimatedValue") or eforms.get("estimatedValue")),
            "currency": discovery.get("estimatedValueCurrency") or eforms.get("estimatedValueCurrency"),
        },
        "duration": {
            "startDate": eforms.get("durationStartDate"),
            "endDate": eforms.get("durationEndDate"),
            "measure": eforms.get("durationMeasure"),
        },
        "submission": {
            "deadlineDate": eforms.get("submissionDeadlineDate"),
            "deadlineTime": eforms.get("submissionDeadlineTime"),
            "method": eforms.get("submissionMethod"),
            "url": eforms.get("submissionUrl"),
            "questionDeadlineDate": eforms.get("questionDeadlineDate"),
        },
        "selectionCriteria": [
            {"code": item.get("code"), "label": None, "description": item.get("description", "")}
            for item in eforms.get("selectionCriteria", [])
        ],
        "awardCriteria": {
            "types": eforms.get("awardCriterionTypes", []),
        },
        "qualificationRequirementCodes": eforms.get("qualificationRequirements", []),
        "procurementDocuments": {
            "links": [
                {
                    "url": link.get("url"),
                    "description": link.get("description"),
                    "documentType": link.get("documentType"),
                }
                for link in record.get("documentLinks", [])
            ],
        },
        # Full extracted text of the real downloaded tender-document
        # attachments -- not truncated further here; whatever length cap
        # agent_input.jsonl itself already applied (MAX_TEXT_CHARS_PER_LOT
        # in CPV45_Eforms_Attachments_Pipeline.py) is preserved as-is.
        "documentContents": [
            {
                "sourceUrl": document.get("sourceUrl") or None,
                "fileName": document.get("fileName"),
                "documentType": document.get("extension"),
                "text": document.get("text", ""),
                "needsOcr": document.get("needsOcr"),
            }
            for document in record.get("documents", [])
        ],
    }


def main(agent_input_path: str, output_dir: str = "output") -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_by_profile = 0
    with open(agent_input_path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception as e:
                print(f"  line {line_number}: FAILED to parse JSON ({type(e).__name__}: {e}), skipping")
                continue

            if not matches_company_profile(record):
                skipped_by_profile += 1
                continue

            try:
                instance = build_contract_schema_instance(record)
            except Exception as e:
                print(f"  line {line_number}: FAILED to map ({type(e).__name__}: {e}), skipping")
                continue

            lot_id = record.get("lotIdentifier") or ""
            lot_part = safe_component(lot_id) if lot_id else "nolot"
            out_path = out_dir / f"contract_schema_{safe_component(record['noticeIdentifier'])}_{lot_part}.json"
            out_path.write_text(json.dumps(instance, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
            print(f"  wrote {out_path}")

    print(
        f"\ncontract_schema instances written: {written} "
        f"(skipped by company-profile filter: {skipped_by_profile}; "
        f"value {PROFILE_VALUE_MIN:,.0f}-{PROFILE_VALUE_MAX:,.0f} EUR, "
        f"NUTS prefixes {PROFILE_NUTS_PREFIXES or '(any)'})"
    )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("usage: python build_schema_from_agent_input.py <agent_input.jsonl> [output_dir]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "output")