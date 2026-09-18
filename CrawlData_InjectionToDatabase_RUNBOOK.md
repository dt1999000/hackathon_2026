# Contract Pipeline Runbook

End-to-end: scrape German construction tenders from **TED** and
**oeffentlichevergabe.de** for one calendar day → deduplicate contracts that
appear in both sources → import into the `contract` table in Postgres.

## Files, and where they live

All in `backend/app/` unless noted:

| File | Role |
|---|---|
| `contract_schema.json` | The shared schema both sources map onto. Reference only, not run. |
| `ted_pipeline.py` | Scrapes TED: search → download notice PDFs → extract text → write `contract_schema_*.json`. |
| `CPV45_Eforms_Attachments_Pipeline.py` | Scrapes oeffentlichevergabe.de: download CSV/eForms exports → filter CPV-45 → download attachments → extract text → write `agent_input.jsonl` **and** `contract_schema_*.json`. |
| `build_schema_from_agent_input.py` | Fast path: re-map an existing `agent_input.jsonl` into `contract_schema_*.json` without rerunning the slow download. |
| `dedupe_contracts.py` | Finds the same real tender appearing in both sources (fuzzy match on buyer + deadline + title), annotates `primary`/`secondary`, writes `duplicates_report.json`. |
| `run_contract_pipelines.py` | Orchestrates all of the above, in order, into one shared `backend/app/output/` folder. |
| `models.py` | Adds the `Contract` SQLModel table. |
| `backend/scripts/import_contracts.py` | Upserts `contract_schema_*.json` into the `contract` table; skips `secondary` duplicates by default. |
| `backend/scripts/check_db.py` | Quick row counts / breakdown by source, without opening Adminer. |

## One-time setup

From the **repo root** (`hackathon_2026/`):
```bash
docker compose up -d db
```

From **`backend/`** (every command below assumes you're standing here):
```bash
uv sync
uv add pandas certifi          # CPV45 pipeline needs these; not in the template by default
```

Make sure `app/models.py` has the `Contract` class (copy it in if it's still just the template's `User`/`Item`), then create and apply the migration:
```bash
uv run alembic revision --autogenerate -m "add contract table"
uv run alembic upgrade head
```
Check the generated file under `app/alembic/versions/` actually has `op.create_table("contract", ...)` before upgrading — autogenerate occasionally misses things.

## Running everything, one command

From `backend/`:
```bash
uv run python app/run_contract_pipelines.py --import-db
```

This runs, in order: TED scrape → oeffentlichevergabe.de scrape → cross-source dedup → DB import — all pinned to the **same calendar day** (defaults to yesterday, since neither source publishes same-day data yet).

### Useful flags
| Flag | Effect |
|---|---|
| `--skip-ted` | Only run the oeffentlichevergabe.de side |
| `--skip-oeffentlichevergabe` | Only run TED |
| `--agent-input PATH` | Skip the slow oeffentlichevergabe.de download; re-map an `agent_input.jsonl` you already have |
| `--skip-dedupe` | Don't run cross-source deduplication |
| `--import-db` | Chain into `import_contracts.py` at the end (omit to just generate files and inspect them first) |

### Env vars worth knowing
| Var | Default | Effect |
|---|---|---|
| `PIPELINE_TARGET_DATE` | yesterday | Force both pipelines onto a specific `YYYY-MM-DD` |
| `TED_CPV_PREFIX` / `TED_COUNTRY` | `45` / `DEU` | What "construction, in Germany" means for TED's query |
| `TED_PROFILE_VALUE_MIN` / `_MAX`, `TED_PROFILE_NUTS_PREFIXES` | unset (no filter) | Narrow TED to one company's value/region profile |
| `TED_EXCLUDE_RESULT_NOTICES` | `false` | Set `true` to drop already-awarded ("Result") notices |
| `TED_PDF_DOWNLOAD_DELAY_SECONDS` / `_MAX_RETRIES` / `_RETRY_SWEEP_DELAY_SECONDS` | `0.5` / `4` / `10` | Rate-limit handling for TED's PDF host (429s) |
| `CPV45_DOWNLOAD_ATTACHMENTS` | `true` | Actually fetch tender-document attachments (needed for `documentContents` to have real text) |
| `CPV45_FOLLOW_STATIC_LINKS` | `false` | Extra hop: try file links found on a landing page |
| `CPV45_MAX_ATTACHMENT_URLS` | `1000` | Cap on attachment downloads per run |
| `CPV45_PROFILE_VALUE_MIN` / `_MAX`, `CPV45_PROFILE_NUTS_PREFIXES` | unset (no filter) | Same idea as `TED_PROFILE_*`, other source |
| `CPV45_VERBOSE` | `false` | Set `true` to get the full DataFrame dumps back (debugging) |

## Doing it in separate steps instead

```bash
uv run python app/run_contract_pipelines.py          # scrape + dedup, no DB write
# ...inspect backend/app/output/*.json, duplicates_report.json...
uv run python scripts/import_contracts.py app/output
```

## Verifying the result

**Without any UI:**
```bash
uv run python scripts/check_db.py
```

**With Adminer** (from the **repo root**, backend does *not* need to be running — Adminer talks to `db` directly):
```bash
docker compose up -d adminer
```
Login: System `PostgreSQL`, Server `db`, Username `postgres`, Password = your `.env`'s `POSTGRES_PASSWORD`, Database `app`.

**Matching a DB row back to its file on disk:** filenames follow `contract_schema_<notice_identifier>_<lotIdentifier-or-"nolot">.json`, in `backend/app/output/`. Or skip the file entirely — each row's `raw_json` column already holds the full original JSON.

## Known issues and fixes already baked in

- **TED 429 Too Many Requests** — handled: per-download delay, exponential-backoff retry, and a final retry sweep over anything still failing.
- **CPV45 crash on a malformed document URL** — downgraded to a warning; doesn't stop the run (everything else was already written to disk by that point anyway).
- **`documentContents` empty** — check `CPV45_DOWNLOAD_ATTACHMENTS=true` (now the default); some links are JS-rendered dashboards that can't be auto-downloaded regardless of this setting.
- **`ModuleNotFoundError: pandas`** — `uv add pandas certifi` (see setup above).
- **Pydantic `Settings` "Field required" errors** — you're running a command from the wrong directory. `.env` is resolved via a relative path, so always run `uv run python ...` from `backend/`, never from `backend/app/`.
- **Output folder is cumulative** — `backend/app/output/` isn't cleared between runs; if you want a clean single-day view, delete its contents first.
- **Windows PowerShell + inline `python -c "..."` or `curl`** — fragile with quoting/escaping. Prefer a real script file run via `uv run python scripts/x.py`, as done throughout this pipeline.

## Worth knowing before running attachment downloads at scale

`CPV45_DOWNLOAD_ATTACHMENTS` now defaults to `true`, which fetches real files from whichever platform each tender's documents are hosted on (RIB, DTVP, deutsche-evergabe.de, subreport, DB's Bieterportal, etc.) — confirm that's acceptable for your use case before running this against a large volume. `oeffentlichevergabe.de`'s own site is not crawlable directly (`robots.txt` disallows it) — only its documented `Datenservice` export API is used here, which is the sanctioned path.
