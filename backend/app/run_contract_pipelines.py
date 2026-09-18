"""
Orchestrates both source pipelines and collects every generated
contract_schema_*.json into one shared folder, ready for import_contracts.py.

Expects, alongside this file (backend/app/):
    ted_pipeline.py
    CPV45_Eforms_Attachments_Pipeline.py
    build_schema_from_agent_input.py
    contract_schema.json
And, in backend/scripts/ (from the earlier DB-import setup):
    import_contracts.py

USAGE (from the backend/ directory):
    uv run python app/run_contract_pipelines.py
    uv run python app/run_contract_pipelines.py --skip-ted
    uv run python app/run_contract_pipelines.py --skip-oeffentlichevergabe
    uv run python app/run_contract_pipelines.py --agent-input path/to/agent_input.jsonl
    uv run python app/run_contract_pipelines.py --import-db

Each pipeline is run as its own subprocess (not imported) because both are
written as top-to-bottom scripts with side effects at import time (network
calls, file downloads) -- importing them directly would run the whole
pipeline the moment Python parsed the `import` statement, with no chance to
sequence or handle failures cleanly.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = APP_DIR.parent                        # backend
SCRIPTS_DIR = BACKEND_DIR / "scripts"

TED_PIPELINE = APP_DIR / "ted_pipeline.py"
CPV45_PIPELINE = APP_DIR / "CPV45_Eforms_Attachments_Pipeline.py"
AGENT_INPUT_ADAPTER = APP_DIR / "build_schema_from_agent_input.py"
DEDUPE_SCRIPT = APP_DIR / "dedupe_contracts.py"
IMPORT_SCRIPT = SCRIPTS_DIR / "import_contracts.py"

# Both pipelines default to a folder named "output" resolved relative to
# wherever they think their own working directory is. ted_pipeline.py uses
# whatever cwd we launch it with (set to APP_DIR below); the CPV45 pipeline
# calls os.chdir() to its own file's directory the moment it's imported
# (also APP_DIR, since it lives right here) -- so both land in the same
# place either way.
SHARED_OUTPUT_DIR = APP_DIR / "output"


def resolve_target_date() -> str:
    """The one calendar day both pipelines scrape. Respects an explicit
    PIPELINE_TARGET_DATE if the caller already set one; otherwise defaults to
    yesterday, matching CPV45_Eforms_Attachments_Pipeline.py's own default
    (its API doesn't publish the current day yet)."""
    explicit = os.environ.get("PIPELINE_TARGET_DATE")
    if explicit:
        return explicit
    return (date.today() - timedelta(days=1)).isoformat()


def run(cmd: list[str], cwd: Path, label: str, extra_env: dict[str, str] | None = None) -> bool:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    env = {**os.environ, **(extra_env or {})}
    result = subprocess.run(cmd, cwd=cwd, env=env)
    ok = result.returncode == 0
    print(f"[{label}] {'completed successfully' if ok else f'FAILED (exit code {result.returncode})'}")
    return ok


def run_ted_pipeline(target_date: str) -> bool:
    if not TED_PIPELINE.exists():
        print(f"ted_pipeline.py not found at {TED_PIPELINE}")
        return False
    # ted_pipeline.py needs the backend/ directory to import PDFLoader from
    # app.tools.rag.loader.pdf -- that's BACKEND_DIR here, not APP_DIR.
    return run(
        [sys.executable, str(TED_PIPELINE), str(BACKEND_DIR)],
        cwd=APP_DIR,
        label=f"TED pipeline (ted.europa.eu) -- {target_date}",
        extra_env={"PIPELINE_TARGET_DATE": target_date},
    )


def run_oeffentlichevergabe_pipeline(target_date: str) -> bool:
    if not CPV45_PIPELINE.exists():
        print(f"CPV45_Eforms_Attachments_Pipeline.py not found at {CPV45_PIPELINE}")
        return False
    return run(
        [sys.executable, str(CPV45_PIPELINE)],
        cwd=APP_DIR,
        label=f"oeffentlichevergabe.de pipeline (full run: download + extract + export) -- {target_date}",
        # CPV45_Eforms_Attachments_Pipeline.py reads these two directly --
        # setting them here is what actually forces the same day as TED,
        # regardless of what its own default would have picked.
        extra_env={"PIPELINE_TARGET_DATE": target_date, "CPV45_PERIOD_TYPE": "day", "CPV45_PERIOD_VALUE": target_date},
    )


def run_from_existing_agent_input(agent_input_path: str) -> bool:
    """Fast path: skip the slow CSV/eForms download + attachment extraction
    entirely and just re-map an agent_input.jsonl you already have."""
    if not AGENT_INPUT_ADAPTER.exists():
        print(f"build_schema_from_agent_input.py not found at {AGENT_INPUT_ADAPTER}")
        return False
    return run(
        [sys.executable, str(AGENT_INPUT_ADAPTER), agent_input_path, str(SHARED_OUTPUT_DIR)],
        cwd=APP_DIR,
        label=f"oeffentlichevergabe.de pipeline (fast path: from {agent_input_path})",
    )


def run_dedupe() -> bool:
    if not DEDUPE_SCRIPT.exists():
        print(f"dedupe_contracts.py not found at {DEDUPE_SCRIPT} -- skipping dedup")
        return False
    return run(
        [sys.executable, str(DEDUPE_SCRIPT), str(SHARED_OUTPUT_DIR)],
        cwd=APP_DIR,
        label="Cross-source deduplication (TED vs oeffentlichevergabe.de)",
    )


def run_db_import() -> bool:
    if not IMPORT_SCRIPT.exists():
        print(f"import_contracts.py not found at {IMPORT_SCRIPT} -- skipping DB import")
        return False
    return run(
        [sys.executable, str(IMPORT_SCRIPT), str(SHARED_OUTPUT_DIR)],
        cwd=BACKEND_DIR,
        label="Import contract_schema files into the database",
    )


def count_contract_files(directory: Path) -> int:
    return len(list(directory.glob("contract_schema_*.json"))) if directory.exists() else 0


def summarize_output(directory: Path) -> dict[str, dict]:
    """Per-source counts, read straight from each file's own provenance --
    not a before/after delta -- so it stays correct across reruns where a
    pipeline just overwrites files it already produced rather than adding
    new ones (TED and CPV45 both key filenames by notice/lot identifier,
    not by run)."""
    stats: dict[str, dict] = defaultdict(lambda: {"lots": 0, "notices": set()})
    if not directory.exists():
        return stats
    for path in directory.glob("contract_schema_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source = (data.get("provenance") or {}).get("sourceSystem") or "unknown"
        notice_id = (data.get("notice") or {}).get("identifier")
        stats[source]["lots"] += 1
        if notice_id:
            stats[source]["notices"].add(notice_id)
    return stats


def print_summary(target_date: str, ok_ted: bool, ok_oev: bool, before: int, after: int) -> None:
    print(f"\n{'=' * 70}\nSummary\n{'=' * 70}")
    print(f"TED pipeline:                    {'OK' if ok_ted else 'FAILED'}")
    print(f"oeffentlichevergabe.de pipeline: {'OK' if ok_oev else 'FAILED'}")
    print(f"contract_schema files in {SHARED_OUTPUT_DIR}: {before} -> {after}")

    stats = summarize_output(SHARED_OUTPUT_DIR)
    print(f"\nContracts found for {target_date}:")
    known_sources = ["TED", "oeffentlichevergabe.de"]
    total_notices = total_lots = 0
    for source in known_sources + [s for s in stats if s not in known_sources]:
        s = stats.get(source, {"lots": 0, "notices": set()})
        n_notices, n_lots = len(s["notices"]), s["lots"]
        total_notices += n_notices
        total_lots += n_lots
        print(f"  {source:<25} {n_notices:>4} notices  {n_lots:>4} lots")
    print(f"  {'TOTAL':<25} {total_notices:>4} notices  {total_lots:>4} lots")

    report_path = SHARED_OUTPUT_DIR / "duplicates_report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            n_secondary = sum(1 for g in report for m in g["members"] if m["role"] == "secondary")
            print(f"\nCross-source duplicates: {len(report)} group(s) found, "
                  f"{n_secondary} record(s) flagged 'secondary' "
                  f"(same contract counted once instead of twice; see {report_path.name})")
        except Exception:
            pass

    print(f"\n(Note: {SHARED_OUTPUT_DIR} is cumulative across runs -- this counts "
          f"everything currently in that folder, not just files this run added.)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-ted", action="store_true", help="Skip the TED pipeline")
    parser.add_argument("--skip-oeffentlichevergabe", action="store_true", help="Skip the oeffentlichevergabe.de pipeline")
    parser.add_argument(
        "--agent-input",
        metavar="PATH",
        help="Use an existing agent_input.jsonl instead of running the full "
             "oeffentlichevergabe.de pipeline (skips its slow download step, "
             "but still produces contract_schema files from it)",
    )
    parser.add_argument("--skip-dedupe", action="store_true", help="Skip cross-source deduplication")
    parser.add_argument("--import-db", action="store_true", help="Run import_contracts.py on the combined output after both pipelines finish")
    args = parser.parse_args()

    if args.agent_input:
        # Resolve BEFORE any subprocess changes cwd -- otherwise a relative
        # path here (typed relative to wherever the user ran this from)
        # would be looked up relative to APP_DIR inside the child process
        # instead, and silently fail with a wrong-looking FileNotFoundError.
        args.agent_input = str(Path(args.agent_input).resolve())

    before = count_contract_files(SHARED_OUTPUT_DIR)
    target_date = resolve_target_date()
    print(f"Target date for both pipelines: {target_date}")

    ok_ted = True
    if args.skip_ted:
        print("Skipping TED pipeline (--skip-ted)")
    else:
        ok_ted = run_ted_pipeline(target_date)

    ok_oev = True
    if args.agent_input:
        ok_oev = run_from_existing_agent_input(args.agent_input)
    elif args.skip_oeffentlichevergabe:
        print("Skipping oeffentlichevergabe.de pipeline (--skip-oeffentlichevergabe)")
    else:
        ok_oev = run_oeffentlichevergabe_pipeline(target_date)

    after = count_contract_files(SHARED_OUTPUT_DIR)

    if ok_ted and ok_oev and not args.skip_dedupe:
        run_dedupe()
    elif args.skip_dedupe:
        print("Skipping cross-source deduplication (--skip-dedupe)")
    else:
        print("Skipping cross-source deduplication: at least one pipeline above failed")

    print_summary(target_date, ok_ted, ok_oev, before, after)

    if args.import_db:
        if ok_ted and ok_oev:
            run_db_import()
        else:
            print("\nNot running DB import: at least one pipeline above failed.")

    if not (ok_ted and ok_oev):
        sys.exit(1)


if __name__ == "__main__":
    main()