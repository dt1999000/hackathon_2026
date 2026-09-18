"""
End-to-end pipeline: query the TED Search API -> download the English PDF for
each matching notice -> extract its text with the hackathon repo's PDFLoader
-> write one contract_schema-shaped instance PER LOT (not per notice), with
the extracted text added under "documentContents" (see contract_schema.json).

FIX vs. an earlier version: a notice can contain multiple lots (value,
duration, submission, classification are all lot-scoped, single-object
fields in the schema). TED's search API returns lot-scoped fields as
parallel arrays -- one entry per lot, aligned by position -- on a single
notice-level response object. An older version silently assumed array
index 0 == "the" lot and wrote one output file per notice, so a 5-lot
notice would produce 5 near-identical files that just describe lot 1,
or overwrite each other if keyed by publication-number alone. This
version explodes each notice into one instance per lot, zipping the
"-lot" arrays by position, and keys every output file on
(publication-number, lotIdentifier).

DEFAULT SCOPE: everything German-flagged construction work (CPV prefix 45)
published on ONE calendar day, no company/price/region filtering -- for
scraping as broadly as possible rather than screening for one company. This
mirrors CPV45_Eforms_Attachments_Pipeline.py's own default scope (CPV prefix
45, one day at a time). Set the TED_PROFILE_* env vars below to narrow this
back down to a specific company's bid/no-bid profile when you need that
instead (mirrors CPV45_PROFILE_* on the oeffentlichevergabe.de side).

USAGE:
    python ted_pipeline.py <backend_path>
"""

import os
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
PDFS_DIR = Path("pdfs")
OUTPUT_DIR = Path("output")

# TED's PDF host rate-limits fast sequential downloads (429 Too Many Requests)
# once you're pulling ~100+ notices in one run. A small delay between
# successful downloads, exponential backoff + retry on a 429, and a final
# retry sweep over whatever still failed cut most of these down to zero in
# practice; tune via env vars if you still see a lot of failures.
PDF_DOWNLOAD_DELAY_SECONDS = float(os.getenv("TED_PDF_DOWNLOAD_DELAY_SECONDS", "0.5"))
PDF_MAX_RETRIES = int(os.getenv("TED_PDF_MAX_RETRIES", "4"))
PDF_RETRY_SWEEP_DELAY_SECONDS = float(os.getenv("TED_PDF_RETRY_SWEEP_DELAY_SECONDS", "10"))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Same calendar day as the oeffentlichevergabe.de pipeline. run_contract_
# pipelines.py sets PIPELINE_TARGET_DATE for both subprocesses so they always
# agree; running this file alone falls back to today's date. Caveat: TED's
# own API doesn't always have the current day's notices published yet, so a
# same-day run can legitimately come back with 0 results on some days --
# pass PIPELINE_TARGET_DATE=<yesterday's date> explicitly if you hit that
# and want yesterday's (already-published) notices instead.
TARGET_DATE_ISO = os.getenv("PIPELINE_TARGET_DATE") or date.today().isoformat()
TARGET_DATE = TARGET_DATE_ISO.replace("-", "")  # TED wants YYYYMMDD

# Scope: what counts as "construction" and "in Germany". CPV_PREFIX="45"
# matches CPV45_PREFIX on the other pipeline (all construction work, not one
# company's specific trade); COUNTRY="DEU" is needed for a fair comparison
# since oeffentlichevergabe.de only ever covers Germany.
CPV_PREFIX = os.getenv("TED_CPV_PREFIX", "45")
COUNTRY = os.getenv("TED_COUNTRY", "DEU")

# Off by default = no company/price/region filtering, i.e. "scrape everything
# findable that day". Set these to narrow back down to one company's profile:
#   TED_PROFILE_VALUE_MIN=5000000
#   TED_PROFILE_VALUE_MAX=90000000
#   TED_PROFILE_NUTS_PREFIXES=DE5,DE6,DE9,DEF,DE8
VALUE_MIN = os.getenv("TED_PROFILE_VALUE_MIN")
VALUE_MAX = os.getenv("TED_PROFILE_VALUE_MAX")
NUTS_PREFIXES = [p.strip() for p in os.getenv("TED_PROFILE_NUTS_PREFIXES", "").split(",") if p.strip()]

# Also off by default now (real "no filters" means Result/award notices can
# come back too). This was added earlier specifically to keep already-awarded
# contracts out of a bid/no-bid shortlist -- turn it back on with
# TED_EXCLUDE_RESULT_NOTICES=true if you want that safeguard without giving
# up the rest of the "no filters" scope.
EXCLUDE_RESULT_NOTICES = env_bool("TED_EXCLUDE_RESULT_NOTICES", False)

_query_parts = [
    f"(classification-cpv IN ({CPV_PREFIX}*))",
    f"(buyer-country IN ({COUNTRY}))",
    f"(publication-date >= {TARGET_DATE})",
    f"(publication-date <= {TARGET_DATE})",
]
if VALUE_MIN:
    _query_parts.append(f"(estimated-value-lot >= {VALUE_MIN})")
if VALUE_MAX:
    _query_parts.append(f"(estimated-value-lot <= {VALUE_MAX})")
if NUTS_PREFIXES:
    _query_parts.append(
        "(place-of-performance-subdiv-lot IN (" + " ".join(f"{p}*" for p in NUTS_PREFIXES) + "))"
    )
if EXCLUDE_RESULT_NOTICES:
    _query_parts.append(
        "(notice-type IN (cn-standard cn-social cn-desg qu-sy pin-cfc-standard pin-cfc-social))"
    )

QUERY = " AND ".join(_query_parts)

# "identifier-lot" is the field this whole fix hinges on: it's what lets us
# tell lots apart and zip the other "-lot" arrays together correctly.
FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-country",
    "identifier-lot",
    "place-of-performance-subdiv-lot",
    "main-classification-lot",
    "additional-classification-lot",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "deadline-receipt-request",
    "publication-date",
    "procurement-document-id-lot",
    "links",
]


# --- Step 1: search -----------------------------------------------------

def query_hash(query: str, length: int = 10) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:length]


def fetch_all_notices(page_size=50, max_pages=20) -> list[dict]:
    all_notices = []
    page = 1
    while page <= max_pages:
        body = {
            "query": QUERY,
            "fields": FIELDS,
            "page": page,
            "limit": page_size,
            "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        }
        resp = requests.post(SEARCH_URL, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()

        notices = data.get("notices", []) or data.get("results", [])
        if not notices:
            break
        print(f"[search] page {page}: got {len(notices)} notices")
        all_notices.extend(notices)
        if len(notices) < page_size:
            break
        page += 1
    return all_notices


def save_search_results(notices: list[dict]) -> Path:
    path = Path(f"ted_search_{query_hash(QUERY)}_{len(notices)}results.json")
    path.write_text(json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[search] wrote {len(notices)} notices to {path}")
    return path


# --- Step 2: download English PDFs (once per notice; the PDF is notice-  --
# --- level, not per-lot, so lots of the same notice share one PDF file) --

def get_english_pdf_url(notice: dict) -> str | None:
    return notice.get("links", {}).get("pdf", {}).get("ENG")


def download_pdf(url: str, dest_path: Path, timeout: int = 30) -> bool:
    if dest_path.exists():
        print(f"  already have {dest_path.name}, skipping")
        return True

    for attempt in range(1, PDF_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as e:
            print(f"  FAILED to download {url}: {e}")
            return False

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait_seconds = float(retry_after) if retry_after else min(2 ** attempt, 30)
            print(f"  rate-limited (429) on attempt {attempt}/{PDF_MAX_RETRIES}, "
                  f"waiting {wait_seconds:.0f}s before retrying")
            time.sleep(wait_seconds)
            continue

        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  FAILED to download {url}: {e}")
            return False

        dest_path.write_bytes(resp.content)
        print(f"  saved {dest_path.name} ({len(resp.content)} bytes)")
        return True

    print(f"  FAILED to download {url}: still rate-limited after {PDF_MAX_RETRIES} attempts")
    return False


def download_all_pdfs(notices: list[dict]) -> None:
    PDFS_DIR.mkdir(exist_ok=True)
    failed: list[tuple[str, str]] = []  # (pub_number, url), for a retry sweep at the end

    for notice in notices:
        pub_number = notice.get("publication-number")
        if not pub_number:
            continue
        print(f"[{pub_number}]")
        url = get_english_pdf_url(notice)
        if not url:
            print("  no English PDF link available, skipping")
            continue

        dest = PDFS_DIR / f"{pub_number}.pdf"
        if dest.exists():
            download_pdf(url, dest)  # just prints "already have", no delay needed
            continue

        if download_pdf(url, dest):
            time.sleep(PDF_DOWNLOAD_DELAY_SECONDS)  # be polite between requests to the same host
        else:
            failed.append((pub_number, url))

    if failed:
        print(f"\n[retry sweep] {len(failed)} PDF(s) failed on the first pass "
              f"(mostly rate-limiting with ~250 sequential downloads) -- "
              f"waiting {PDF_RETRY_SWEEP_DELAY_SECONDS:.0f}s then trying them again once")
        time.sleep(PDF_RETRY_SWEEP_DELAY_SECONDS)
        still_failed = []
        for pub_number, url in failed:
            print(f"[{pub_number}] (retry)")
            if download_pdf(url, PDFS_DIR / f"{pub_number}.pdf"):
                time.sleep(PDF_DOWNLOAD_DELAY_SECONDS)
            else:
                still_failed.append(pub_number)
        if still_failed:
            print(f"[retry sweep] still failed after retry: {still_failed}")


# --- Step 3: explode each notice into per-lot instances ------------------

def pick_lang(multilingual: dict, preferred=("eng", "en")):
    if not isinstance(multilingual, dict) or not multilingual:
        return None
    for lang in preferred:
        if lang in multilingual:
            return multilingual[lang]
    return next(iter(multilingual.values()))


def lot_count_of(notice: dict) -> int:
    """Number of lots in this notice, from the length of identifier-lot.
    Falls back to other '-lot' arrays if identifier-lot wasn't returned,
    and finally to 1 (single, unsplit lot) if no lot arrays are present."""
    for field in ("identifier-lot", "estimated-value-lot", "place-of-performance-subdiv-lot"):
        values = notice.get(field)
        if values:
            return len(values)
    return 1


def at_lot(values, lot_index: int):
    """Read the value for lot `lot_index` out of a TED '-lot' array.
    If the array has only one entry, treat it as shared across all lots
    (a notice-wide value TED didn't repeat per lot) rather than lot-specific."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values[lot_index] if lot_index < len(values) else None


def cpv_list_at_lot(values, lot_index: int) -> list:
    """CPV '-lot' fields can hold either one code or several per lot
    (a lot may have multiple additional CPV codes); normalize to a list."""
    v = at_lot(values, lot_index)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def build_instance(notice: dict, lot_index: int, n_lots: int, pdf_text: str, pdf_url: str | None) -> dict:
    pub_number = notice.get("publication-number")

    lot_id = at_lot(notice.get("identifier-lot"), lot_index)
    if lot_id is None and n_lots > 1:
        # We know (from another '-lot' array's length) that this notice has
        # multiple lots, but TED didn't give us identifier-lot for it (e.g.
        # it wasn't in FIELDS at fetch time, or TED omitted it). Falling
        # back to None here would collide every lot onto the same
        # "..._nolot.json" filename -- exactly the silent-overwrite bug
        # this fix exists to prevent. Synthesize a positional id instead,
        # clearly marked as non-authoritative so it's never confused with
        # a real TED lot identifier.
        lot_id = f"pos{lot_index + 1}"
    main_cpv = at_lot(notice.get("main-classification-lot"), lot_index)
    additional_cpv = cpv_list_at_lot(notice.get("additional-classification-lot"), lot_index)

    deadline = at_lot(notice.get("deadline-receipt-request"), lot_index)
    deadline_date, deadline_time = (deadline.split("T") if deadline else (None, None))

    est_value = at_lot(notice.get("estimated-value-lot"), lot_index)
    est_currency = at_lot(notice.get("estimated-value-cur-lot"), lot_index)

    nuts = at_lot(notice.get("place-of-performance-subdiv-lot"), lot_index)

    return {
        "schemaVersion": "1.0",
        "provenance": {"sourceSystem": "TED", "sourceRecordId": pub_number},
        "notice": {
            "identifier": pub_number,
            "lotIdentifier": lot_id,  # null only if this notice genuinely has a single, unsplit lot
            "publicationDate": (notice.get("publication-date") or "").rstrip("Z") or None,
        },
        "buyer": {"names": pick_lang(notice.get("buyer-name", {})) or []},
        "procedure": {"title": pick_lang(notice.get("notice-title", {}))},
        "classification": {
            "mainNature": "",
            "mainCpvCode": main_cpv or "",
            "additionalCpvCodes": additional_cpv,
        },
        "placeOfPerformance": [{"nuts": nuts}] if nuts else [],
        "value": {
            "estimatedValue": float(est_value) if est_value else None,
            "currency": est_currency,
        },
        "submission": {"deadlineDate": deadline_date, "deadlineTime": deadline_time},
        "procurementDocuments": {
            "links": [
                {"url": url, "documentType": lang}
                for lang, url in notice.get("links", {}).get("pdf", {}).items()
            ],
        },
        # TED gives exactly one document -- its own rendered notice PDF, in
        # whatever language we chose to download (English here). It never
        # hosts the actual Vergabeunterlagen attachments, unlike the
        # oeffentlichevergabe.de pipeline (see documentContents in
        # contract_schema.json for why this list can hold many entries there).
        "documentContents": [
            {
                "sourceUrl": pdf_url,
                "fileName": f"{pub_number}.pdf",
                "documentType": "ENG",
                "text": pdf_text,
                "needsOcr": None,
            }
        ] if pdf_text else [],
    }


def output_filename(pub_number: str, lot_id: str | None) -> Path:
    lot_part = lot_id if lot_id else "nolot"
    return OUTPUT_DIR / f"contract_schema_{pub_number}_{lot_part}.json"


def build_all_schemas(notices: list[dict], backend_path: str) -> None:
    sys.path.insert(0, backend_path)
    from app.tools.rag.loader.base import SourceContent  # noqa: E402
    from app.tools.rag.loader.pdf import PDFLoader  # noqa: E402

    loader = PDFLoader()
    OUTPUT_DIR.mkdir(exist_ok=True)

    for notice in notices:
        pub_number = notice.get("publication-number")
        pdf_path = PDFS_DIR / f"{pub_number}.pdf"

        print(f"[{pub_number}]")
        if not pdf_path.exists():
            print("  no local PDF found, skipping")
            continue

        result = loader.load(SourceContent(source=str(pdf_path)))
        n_lots = lot_count_of(notice)
        pdf_url = get_english_pdf_url(notice)
        print(f"  extracted {result.metadata['num_pages']} pages, {len(result.content)} chars"
              f" -- {n_lots} lot(s) in this notice")

        for lot_index in range(n_lots):
            instance = build_instance(notice, lot_index, n_lots, result.content, pdf_url)
            out_path = output_filename(pub_number, instance["notice"]["lotIdentifier"])
            out_path.write_text(json.dumps(instance, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    lot {lot_index}: wrote {out_path}")


# --- main -----------------------------------------------------------------

def main(backend_path: str):
    notices = fetch_all_notices()
    save_search_results(notices)
    download_all_pdfs(notices)
    build_all_schemas(notices, backend_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python ted_pipeline.py <backend_path>")
        sys.exit(1)
    main(sys.argv[1])