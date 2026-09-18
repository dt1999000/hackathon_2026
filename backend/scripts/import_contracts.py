"""
Upsert every exported contract_schema_<publication-number>_<lot>.json file
into the Contract table. Idempotent: rerunning on the same files updates
existing rows instead of duplicating them, keyed on
(notice_identifier, notice_version, lot_identifier) -- see the note on
Contract in app/models.py for why version/lot are normalized to "" instead
of left as None.

By default, records dedupe_contracts.py marked as "secondary" (the same
real tender already represented by a "primary" record from the other
source) are skipped, so the same contract isn't inserted twice. Pass
--include-duplicates to import every record regardless.

USAGE (from the backend/ directory):
    uv run python scripts/import_contracts.py <path-to-output-folder>
    uv run python scripts/import_contracts.py <path-to-output-folder> --include-duplicates
"""

import argparse
import json
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Contract


def upsert_contract(session: Session, instance: dict) -> str:
    notice = instance.get("notice", {})
    key = dict(
        notice_identifier=notice.get("identifier") or "",
        notice_version=notice.get("version") or "",
        lot_identifier=notice.get("lotIdentifier") or "",
    )

    existing = session.exec(
        select(Contract).where(
            Contract.notice_identifier == key["notice_identifier"],
            Contract.notice_version == key["notice_version"],
            Contract.lot_identifier == key["lot_identifier"],
        )
    ).first()

    value = instance.get("value", {})
    submission = instance.get("submission", {})
    classification = instance.get("classification", {})
    provenance = instance.get("provenance", {})
    document_contents = instance.get("documentContents", []) or []
    document_contents_text = "\n\n".join(
        d.get("text", "") for d in document_contents if d.get("text")
    ) or None

    fields = dict(
        source_system=provenance.get("sourceSystem", ""),
        source_record_id=provenance.get("sourceRecordId", ""),
        publication_date=notice.get("publicationDate"),
        buyer_names=instance.get("buyer", {}).get("names", []),
        procedure_title=instance.get("procedure", {}).get("title"),
        main_nature=classification.get("mainNature"),
        main_cpv_code=classification.get("mainCpvCode"),
        additional_cpv_codes=classification.get("additionalCpvCodes", []),
        place_of_performance=instance.get("placeOfPerformance", []),
        estimated_value=value.get("estimatedValue"),
        currency=value.get("currency"),
        deadline_date=submission.get("deadlineDate"),
        deadline_time=submission.get("deadlineTime"),
        procurement_document_links=instance.get("procurementDocuments", {}).get("links", []),
        document_contents=document_contents,
        document_contents_text=document_contents_text,
        duplicate_group_id=provenance.get("duplicateGroupId"),
        duplicate_role=provenance.get("duplicateRole"),
        raw_json=instance,
    )

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        session.add(existing)
        action = "updated"
    else:
        row = Contract(**key, **fields)
        session.add(row)
        action = "inserted"

    session.commit()
    return action


def main(folder: str, include_duplicates: bool) -> None:
    files = sorted(Path(folder).glob("contract_schema_*.json"))
    if not files:
        print(f"no contract_schema_*.json files found in {folder}")
        return

    skipped_duplicates = 0
    with Session(engine) as session:
        for path in files:
            instance = json.loads(path.read_text(encoding="utf-8"))

            if not include_duplicates:
                role = (instance.get("provenance") or {}).get("duplicateRole")
                if role == "secondary":
                    skipped_duplicates += 1
                    print(f"skipped (duplicate, already have the primary copy): {path.name}")
                    continue

            action = upsert_contract(session, instance)
            print(f"{action}: {path.name}")

    if skipped_duplicates:
        print(f"\n{skipped_duplicates} duplicate record(s) skipped "
              f"(pass --include-duplicates to import them anyway)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_dir")
    parser.add_argument("--include-duplicates", action="store_true",
                         help="Import 'secondary' duplicate records too, instead of skipping them")
    args = parser.parse_args()
    main(args.output_dir, args.include_duplicates)