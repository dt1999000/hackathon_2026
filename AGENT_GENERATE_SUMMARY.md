# `agent-generate` branch — implemented features

Snapshot of everything implemented on this branch as of the current working
tree (including uncommitted changes — see the note at the bottom).

## Backend

### Company Profile (`company_profile.py`, `models.py`)

- `CompanyProfile` table: basic typed fields (name, location, founded year,
  employees, revenue) plus free-text fields (`geographic_reach`,
  `contract_size`, `capabilities`, `exclusions`, `certifications`,
  `contractor_role`, `capacity`, `reference_projects`, `hardliners`,
  `self_description`) — one profile per user (`owner_id` unique FK).
- `GET /company-profile/me`, `POST /company-profile/me`.
- **Uncommitted:** `DELETE /company-profile/me` — lets a profile be replaced
  instead of being stuck behind the `POST` endpoint's 409.

### Bid-Fit agent (`agents/bid_fit.py`, `agents/bid_fit_scoring.py`, `api/routes/bid_fit.py`)

A LangGraph pipeline that flags how well a bid fits a company:

1. **Hardliners** derived straight from the profile's `hardliners`/
   `exclusions` text, one per line — no LLM call.
2. **Profile sections** — each free-text field split into independent
   retrieval queries (`capabilities`/`exclusions`/`reference_projects` are
   split one item per line).
3. **Retrieval** — bid loaded + chunked; each section's chunks ranked by
   cosine similarity to build a candidate pool, then an **LLM reranks** each
   section's pool to filter out same-domain-but-irrelevant boilerplate.
4. **Violation check** — LLM decides per hardliner whether the bid *actually*
   contradicts it (not just topically related), and whether a realistic
   solution exists.
5. **Scoring** — red (unsolvable violation) / yellow (workable violations) /
   green (no violations); `similarity_score` only breaks ties between bids
   sharing the same flag, never decides the flag itself.

Endpoints:

- `POST /bid-fit/analyze` — full pipeline against the caller's stored
  `CompanyProfile`.
- `POST /bid-fit/screen` — full pipeline with hardliners passed in directly
  (no stored profile needed).
- `POST /bid-fit/analyze-bids` — runs `/analyze` concurrently against every
  seeded bid, ranks best-first, returns the top N. This is what the
  dashboard's "Analyze" button calls.
- Per-stage endpoints for isolated testing: `GET /bid-fit/extract-hardliners`,
  `GET /bid-fit/profile-sections`, `POST /bid-fit/retrieve`,
  `POST /bid-fit/generate-violations`, `POST /bid-fit/score`,
  `POST /bid-fit/rank`.

### Bids table (uncommitted: `models.py::Bid`, `api/routes/bids.py`, `seed_bids.py`, new alembic migration)

A shared (non-owner-scoped) pool of tender notices, seeded idempotently from
`mock_data/bids/*.json`.

- `POST /bids/load` — seed/refresh the table (skips files already loaded,
  matched by filename).
- `GET /bids/` — list seeded bids.
- `raw_json` on each row is fed back into the bid-fit pipeline as
  `bid_content` (`bid_loader="json"`).

### Chat ("Aria") (`services/chat.py`, `services/chat_models.py`, `api/routes/chat.py`)

- `POST /chat/message` — general-purpose assistant.
- Silently task-detects one of: content generation, summarization,
  translation, classification, general chat — via one system prompt.
- `provider`: `claude` / `google` (Gemini) / `local` (Ollama).
- `language`: `en` / `de`.

### Embeddings (`services/embeddings.py`)

- Ollama-hosted models: `qwen3-embedding:0.6b` (default), `nomic-embed-text`,
  multilingual `bge-m3` / `jina-embeddings-v3`.
- Google's `gemini-embedding-2-preview` (no local Ollama server needed) as a
  multilingual alternative.
- Model selection is by name — `EmbeddingClient` routes to the right backend.

### RAG tooling (`tools/rag/*`, dev-only `api/routes/tools.py`)

- Loader registry: `json`, `jsonl`, `tabular`, `github`, `youtube_video`,
  `youtube_channel`, `pdf`.
- Chunker registry: `default`, `text`, `docx`, `mdx`, `web`, `csv`, `json`,
  `xml`.
- Dev-only endpoints (enabled only when `FASTAPI_ENV=development`):
  `/tools/rag/load`, `/tools/rag/chunk`, `/tools/rag/ingest`,
  `/tools/rag/generate` (RAG generation with/without retrieval),
  `/tools/llm/complete`, plus Firecrawl `/tools/firecrawl/{crawl,scrape,search,extract}`.

### Uncommitted bug fixes in RAG tooling

- **`RecursiveCharacterTextSplitter`** (`tools/rag/chunking/base.py`) — fixed
  double-counted overlap/separator text. The old code merged at every
  recursion level, so a child call's already-merged, already-overlapping
  chunks got fed back into the parent's merge as if they were fresh splits,
  duplicating shared overlap text and doubling separators (e.g. `"\n"` →
  `"\n\n"`). Now splits recursively into a flat list of atomic pieces first,
  then merges exactly once, globally.
- **`DefaultChunker`** (`tools/rag/chunking/default.py`) — shrunk from
  `chunk_size=2000/overlap=20` to `75/10`, with a sentence-aware separator
  hierarchy (`\n\n`, `\n`, `. `, `! `, `? `, `; `, `, `, ` `, ``). A large
  chunk size collapsed distinct bid requirements into one chunk, so every
  profile section's best match converged on the same keyword-dense chunk and
  `similarity_score` saturated at 1.0 regardless of actual relevance.
- **`JSONLoader` / `flatten_json_to_text`** (`tools/rag/loader/json.py`) —
  added `ensure_ascii=False` (was silently mangling German characters like
  `ü`/`ß` into `\uXXXX` escapes before embedding, with no error). Added
  `load_json_data()` helper so the bid-fit agent can get the parsed JSON
  object directly instead of only flattened text.

## Frontend

- **Dashboard** (`routes/_layout/index.tsx`,
  `components/Bids/BidsAnalysisPanel.tsx`, `components/Bids/BidMatchCard.tsx`)
  — "Load data" button seeds bids (`POST /bids/load`); "Analyze" button runs
  `POST /bid-fit/analyze-bids` and renders results as red/yellow/green cards
  showing hard blockers, workable mitigations, and satisfied hardliners.
- **Onboarding form** (`routes/onboarding.tsx`) — react-hook-form + zod form
  for entering the company profile.
- Generated API client (`client/*.gen.ts`) regenerated for the new
  endpoints/types.

## ⚠️ Known issue

`onboarding.tsx` was **not updated** after the `CompanyProfile` schema was
simplified (commit `777ffa64`). It still posts fields that no longer exist on
`CompanyProfileCreate` (`max_radius_km`, `served_regions`,
`excluded_regions`, `min_contract_value_eur`, `max_contract_value_eur`,
`partner_threshold_eur`, `explicit_exclusions`, `max_self_perform_pct`,
`guarantee_limit_total_eur`, `guarantee_currently_committed_eur`,
`available_from`, `capacity_note`, `custom_hardliners`). It will fail to
typecheck/build as-is. It needs to be rewritten against the current
free-text schema: `geographic_reach`, `contract_size`, `capabilities`,
`exclusions`, `certifications`, `contractor_role`, `capacity`,
`reference_projects`, `hardliners`, `self_description`.

## Working tree state at time of writing

The following were **uncommitted** on top of `origin/agent-generate`:

- `backend/app/agents/bid_fit.py`, `backend/app/api/main.py`,
  `backend/app/api/routes/bid_fit.py`, `backend/app/api/routes/company_profile.py`,
  `backend/app/models.py`, `backend/app/tools/rag/chunking/base.py`,
  `backend/app/tools/rag/chunking/default.py`,
  `backend/app/tools/rag/loader/json.py` (modified)
- `backend/app/alembic/versions/760a95845d2f_add_bids_table.py`,
  `backend/app/api/routes/bids.py`, `backend/app/seed_bids.py`,
  `frontend/src/components/Bids/` (untracked/new)
- Generated client files, `bun.lock`, `frontend/package.json`,
  `frontend/src/routeTree.gen.ts`, `frontend/src/routes/_layout/index.tsx`
  (regenerated/modified)
- Scratch files not part of the feature work: `_tmp_screenshot*.mjs`,
  `package-lock.json` — worth cleaning up or `.gitignore`-ing before
  committing.

None of this was staged. Commit (or discard the scratch files) before
continuing further work on this branch.
