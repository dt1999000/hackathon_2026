"""
Cross-source deduplication for contract_schema_*.json files.

Above-EU-threshold German notices get sent through both sources (the
national eSender-Hub converts and forwards them to TED), so the same real
tender can legitimately show up once from ted_pipeline.py and once from
CPV45_Eforms_Attachments_Pipeline.py, with two different, unrelated IDs.
Neither source exposes a shared key linking the two, so this can only be a
FUZZY match -- it will have some false positives and false negatives.
Because of that, this script never deletes or merges anything; it only
ANNOTATES each file's provenance with a duplicate-group id and a role
("primary"/"secondary"), and writes a human-readable report so you can
check its judgement before trusting it (e.g. in import_contracts.py).

Matching approach:
  - Block by (normalized buyer name, exact submission deadlineDate). Both
    need to be non-empty and equal -- an exact deadline collision between
    two DIFFERENT genuine tenders from the same buyer is rare enough to be
    a strong signal, and this also keeps the search space small (no need
    to compare every record against every other record).
  - Within a block, cluster by title similarity (difflib ratio over
    normalized text) -- catches the case of one buyer posting two
    unrelated notices with the same deadline.
  - Only clusters that span MORE THAN ONE sourceSystem are reported --
    same-source "duplicates" aren't this script's concern.
  - Within a cluster, the record with more populated data (documentContents
    text length + count of non-empty top-level fields) is marked "primary";
    the rest "secondary".

USAGE:
    python dedupe_contracts.py <output_dir> [--title-threshold 0.55]
"""

import argparse
import difflib
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def normalize_text(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def buyer_key(instance: dict[str, Any]) -> str:
    names = (instance.get("buyer") or {}).get("names") or []
    return normalize_text(names[0]) if names else ""


def deadline_key(instance: dict[str, Any]) -> str:
    return ((instance.get("submission") or {}).get("deadlineDate") or "").strip()


def title_text(instance: dict[str, Any]) -> str:
    return (instance.get("procedure") or {}).get("title") or ""


def richness_score(instance: dict[str, Any]) -> int:
    """Rough proxy for "which copy has more useful data" -- not exact, just
    enough to consistently prefer the fuller record as primary."""
    score = 0
    doc_text_len = sum(len(d.get("text", "")) for d in instance.get("documentContents", []))
    score += min(doc_text_len, 50_000) // 100  # cap so one huge doc doesn't dominate everything else
    for section in ("buyer", "procedure", "classification", "value", "duration", "submission"):
        block = instance.get(section) or {}
        score += sum(1 for v in block.values() if v not in (None, "", [], {}))
    score += len(instance.get("selectionCriteria") or [])
    score += len(instance.get("qualificationRequirementCodes") or [])
    return score


def load_instances(output_dir: Path) -> list[tuple[Path, dict]]:
    instances = []
    for path in sorted(output_dir.glob("contract_schema_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skipping {path.name}: could not parse ({type(e).__name__}: {e})")
            continue
        instances.append((path, data))
    return instances


def find_duplicate_groups(
    instances: list[tuple[Path, dict]], title_threshold: float
) -> list[list[tuple[Path, dict]]]:
    blocks: dict[tuple[str, str], list[tuple[Path, dict]]] = defaultdict(list)
    for path, data in instances:
        b, d = buyer_key(data), deadline_key(data)
        if not b or not d:
            continue  # can't trust a match without both a real buyer name and a real deadline
        blocks[(b, d)].append((path, data))

    groups = []
    for (b, d), members in blocks.items():
        if len(members) < 2:
            continue
        used = [False] * len(members)
        for i in range(len(members)):
            if used[i]:
                continue
            cluster = [members[i]]
            used[i] = True
            title_i = normalize_text(title_text(members[i][1]))
            for j in range(i + 1, len(members)):
                if used[j]:
                    continue
                title_j = normalize_text(title_text(members[j][1]))
                ratio = difflib.SequenceMatcher(None, title_i, title_j).ratio()
                if ratio >= title_threshold:
                    cluster.append(members[j])
                    used[j] = True
            sources = {data.get("provenance", {}).get("sourceSystem") for _, data in cluster}
            if len(cluster) > 1 and len(sources) > 1:
                groups.append(cluster)
    return groups


def annotate_and_report(groups: list[list[tuple[Path, dict]]]) -> list[dict]:
    report = []
    for cluster in groups:
        ranked = sorted(cluster, key=lambda pd: richness_score(pd[1]), reverse=True)
        group_id = hashlib.sha256(
            "|".join(sorted(str(p) for p, _ in cluster)).encode("utf-8")
        ).hexdigest()[:12]

        group_report = {"duplicateGroupId": group_id, "members": []}
        for rank, (path, data) in enumerate(ranked):
            role = "primary" if rank == 0 else "secondary"
            data.setdefault("provenance", {})["duplicateGroupId"] = group_id
            data["provenance"]["duplicateRole"] = role
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            group_report["members"].append({
                "file": path.name,
                "role": role,
                "sourceSystem": data.get("provenance", {}).get("sourceSystem"),
                "title": title_text(data),
                "buyer": (data.get("buyer") or {}).get("names"),
                "deadline": deadline_key(data),
            })
        report.append(group_report)
    return report


def clear_previous_annotations(instances: list[tuple[Path, dict]]) -> None:
    """Rerunning this script should reflect the CURRENT file set, not carry
    forward stale annotations from a previous run (e.g. a group that no
    longer has a cross-source match after files changed)."""
    for path, data in instances:
        provenance = data.get("provenance") or {}
        if "duplicateGroupId" in provenance or "duplicateRole" in provenance:
            provenance.pop("duplicateGroupId", None)
            provenance.pop("duplicateRole", None)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(output_dir: str, title_threshold: float) -> None:
    out_dir = Path(output_dir)
    instances = load_instances(out_dir)
    print(f"loaded {len(instances)} contract_schema files")

    clear_previous_annotations(instances)
    # Re-load: clear_previous_annotations already rewrote files in place,
    # but the in-memory `data` dicts are already updated too, so this just
    # keeps the rest of the function working off the same objects.

    groups = find_duplicate_groups(instances, title_threshold)
    report = annotate_and_report(groups)

    report_path = out_dir / "duplicates_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    total_secondary = sum(1 for g in report for m in g["members"] if m["role"] == "secondary")
    print(f"duplicate groups found: {len(report)} ({total_secondary} record(s) marked 'secondary')")
    print(f"report written to: {report_path}")
    for g in report[:5]:
        primary = next(m for m in g["members"] if m["role"] == "primary")
        others = [m["sourceSystem"] for m in g["members"] if m["role"] == "secondary"]
        print(f"  [{g['duplicateGroupId']}] \"{primary['title'][:60]}\" "
              f"-- primary: {primary['sourceSystem']}, also seen in: {others}")
    if len(report) > 5:
        print(f"  ... and {len(report) - 5} more (see {report_path.name})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_dir")
    parser.add_argument("--title-threshold", type=float, default=0.55,
                         help="Minimum title similarity (0-1) to cluster two same-buyer, "
                              "same-deadline records together. Default 0.55.")
    args = parser.parse_args()
    main(args.output_dir, args.title_threshold)