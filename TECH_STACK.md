# AI Recruiter — Tech Stack

Technical reference doc covering the stack, deployment, and non-obvious
gotchas hit along the way. Update this whenever a new library, service, or
tool is added to the project.

## Language & Runtime

| Tech | Purpose |
|---|---|
| **Python 3.13** | Project language. Chosen for its ecosystem strength in PDF/DOCX parsing, HTTP clients, and LLM SDKs. |

## Core Libraries (`requirements.txt`)

| Library | Purpose | Used in |
|---|---|---|
| **requests** | HTTP client for all external API calls (Zoho, GitHub, portfolio link checks). | `zoho_client.py`, `link_verifier.py` |
| **python-dotenv** | Loads secrets/config from `.env` into environment variables. | `config.py` |
| **anthropic** | Official Claude API SDK. Powers structured resume-profile extraction and the deep-analysis credibility report when `ANTHROPIC_API_KEY` is set. | `resume_analyzer.py`, `deep_analysis.py` |
| **pdfplumber** | Extracts plain text *and* embedded hyperlink annotations from PDF resumes (the latter catches links shown as clickable text like "Live: Link" that don't appear as visible URLs). | `resume_text.py` |
| **python-docx** | Extracts plain text and hyperlink relationships from DOCX resumes. | `resume_text.py` |
| **sqlalchemy** | ORM for the local database — models, sessions, and schema migration. | `db/models.py`, `db/session.py`, `migrate_db.py` |
| **google-genai** | Google's Gemini SDK. **Temporary** free-tier stand-in for the Claude backend while `ANTHROPIC_API_KEY` isn't available — only used if `ANTHROPIC_API_KEY` is unset and `GEMINI_API_KEY` is set. | `resume_analyzer_gemini.py`, `deep_analysis.py` (`generate_deep_analysis_gemini`) |
| **fastapi** | Web API framework serving the frontend — job openings list, analysis trigger. | `src/api/app.py`, `src/api/routes/` |
| **uvicorn** | ASGI server that actually runs the FastAPI app. | run via `uvicorn api.app:app` from `src/` |
| **psycopg2-binary** | PostgreSQL driver — only actually connects when `DATABASE_URL` points at Postgres (e.g. Neon in production); local dev still defaults to SQLite. | `db/session.py` (via SQLAlchemy) |

## Storage

| Tech | Purpose |
|---|---|
| **SQLite** (local dev) / **PostgreSQL** (deployed) | `DATABASE_URL` picks the backend — defaults to a local SQLite file (`data/ai_recruiter.db`) if unset. Source of truth for candidates, job openings, applications, resume analyses, and per-project verification. Deployed on **Neon** (free-tier Postgres, no 30-day expiry unlike Render's own free Postgres) since the deployment host (Render free tier) has no persistent disk for a SQLite file to live on. `config.py` normalizes Render/Neon/Heroku-style `postgres://` URLs to the `postgresql://` SQLAlchemy 1.4+ requires. |

## External APIs / Services

| Service | Purpose | Auth |
|---|---|---|
| **Zoho Recruit API (v2)** | Source of candidate records and resume attachments. Web-based OAuth client ("Abstrabit Test"), India data center (`accounts.zoho.in` / `recruit.zoho.in`). | `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET` / `ZOHO_REFRESH_TOKEN` in `.env` |
| **GitHub REST API** | Verifies candidates' claimed projects — repo existence, fork status, contributor/commit activity, PR count. | `GITHUB_TOKEN` in `.env` (optional but recommended — unauthenticated is capped at 60 req/hr vs. 5,000 with a token) |
| **Anthropic (Claude) API** | Model: `claude-opus-5`. Structured extraction (`output_config.format` + JSON schema) for both the candidate-profile parser and the deep-analysis report generator. | `ANTHROPIC_API_KEY` in `.env` — not yet obtained |
| **Google Gemini API** | Model: `gemini-3.5-flash-lite`. **Temporary** stand-in for the two Claude calls above (same JSON-schema-constrained approach via `response_json_schema`), used only until an Anthropic key is available. **Verified working live** — tested end-to-end against a real resume, output quality is notably better than the rule-based fallback (correct project splitting, correct hyperlink-to-project attribution, both education entries captured). | `GEMINI_API_KEY` in `.env`, free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

**Note on Gemini model naming:** Google deprecates model IDs for new API keys fairly often (`gemini-2.5-flash` and `gemini-2.5-flash-lite` both 404'd immediately for this key, each pointing to a newer replacement in the error message itself). Also, the newer flagship-tier models (`gemini-3.6-flash`) hit persistent 503 "high demand" errors on the free tier, while the lighter `-flash-lite` tier worked immediately — if this breaks again, run `client.models.list()` to see what's actually available rather than guessing a name, and prefer a `-lite` tier for free-tier reliability.

**Note on Gemini free-tier rate limit (hard ceiling, confirmed live):** `gemini-3.5-flash-lite`'s free tier caps at **15 requests/minute** per project per model (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier` quota, returns `429 RESOURCE_EXHAUSTED` with a `retryDelay` when exceeded). Each candidate makes 2 Gemini calls (extract + report), so the real ceiling is ~7 candidates/minute *at best* — and since concurrent candidate processing (see below) bunches calls together in time rather than spacing them evenly, even `MAX_CONCURRENT_CANDIDATES=2` reliably breaches this (confirmed live: 2 of 10 candidates failed with 429 in one test run). **Fixed** — `gemini_rate_limiter.py` wraps every Gemini call site (extraction, report, search-prompt match-check) with a shared sliding-window limiter (14 calls/61s) plus retry-with-backoff for any 429 that still slips through. Verified live: 10 candidates at `MAX_CONCURRENT_CANDIDATES=6` (previously guaranteed to 429) completed with zero failures. Raising concurrency still won't make Gemini calls happen faster than 15/min allows — it only helps the non-Gemini parts of the pipeline (Zoho downloads, GitHub verification) now.

## Backend Auto-Selection

`main.py._select_backend()` picks the extraction/analysis backend automatically, in priority order:

1. **`claude`** — if `ANTHROPIC_API_KEY` is set
2. **`gemini`** — else if `GEMINI_API_KEY` is set (temporary bridge, see above)
3. **`rule_based`** — otherwise (`resume_parser_rule_based.py` + `deep_analysis.generate_deep_analysis_rule_based` — regex/heuristic extraction, deterministic non-LLM scoring)

## Web UI

| Tech | Purpose |
|---|---|
| **React (Vite scaffold)** | Frontend framework. `frontend/` — plain JS, not TypeScript. Two tabs: Active Job Openings (live from Zoho via the backend, each with an "Analyze Applicants" button), Run Analysis (job dropdown + candidate cap, trigger the pipeline, see scores, best-fit-first ranking with a "Best Match" badge). |
| **Vite** | Frontend dev server/bundler. Dev server on `localhost:5173`; backend on `localhost:8000`, CORS-allowed for that origin only. |

Run: `cd src && uvicorn api.app:app --port 8000` (backend) and `cd frontend && npm run dev` (frontend), separately. Prefer restarting the backend without `--reload` when debugging — it has silently missed reload events on live edits.

`POST /api/analyze` accepts an optional `job_opening_id`; when set, it analyzes that job's actual applicants (via `zoho_client.get_applications_for_job`, a title-based Applications-module search — see `CLAUDE.md` for why) instead of the next N candidates in Zoho's default order, and ranks results best-fit-first. Applicants with `Application_Status` `"Rejected"` or `"Junk candidate"` are excluded server-side (`zoho_client.EXCLUDED_APPLICATION_STATUSES`) so they don't get re-surfaced/re-analyzed on every pull. Results are explicitly sorted `sort_by=Created_Time&sort_order=desc` — the search endpoint's default order turned out not to be based on any timestamp field (confirmed live), so without an explicit sort, which candidates land in a limited pull's first N wasn't guaranteed stable across repeated searches. Both API routes share one `ZohoClient` (`get_shared_client()`) to avoid tripping Zoho's token-refresh rate limit under repeated requests.

A job's applicant list is a **frozen snapshot** (`job_openings.snapshot_applications`), not a live Zoho query every search — first search fetches + saves, every search after reuses it (skips the 30-40+s paginated Zoho fetch entirely, ~0.2s instead). Each reuse re-validates every candidate about to be touched via a cheap single-record status check (`ZohoClient.get_application_status()`, ~1.6s); anyone no longer `"Applied"` (rejected, moved to interview, etc.) is evicted from the persisted snapshot and skipped in favor of the next fresh candidate. `POST /api/analyze`'s `refresh_snapshot: bool` forces a full fresh pull. Verified live with a controlled 5-entry test snapshot (2 stale + 3 fresh): stale entries correctly evicted, snapshot shrank 5→3.

Already-analyzed candidates are also **cached** (`db.writer.get_latest_completed_analysis`) so re-running a job search with a higher limit only processes the *new* candidates, not the whole batch again — no-search-prompt path only (a cached report doesn't know about the *current* search prompt, so the filtering path always stays fresh). Verified live: `limit=4→5→6→9` on an already-covered job came back 100% cached each time (0 new DB rows); `limit=12` produced the real mixed case, 11 cache hits + exactly 1 freshly-analyzed candidate.

`_run_concurrent_until_target()`'s chunk size is capped at `min(MAX_CONCURRENT_CANDIDATES, target_count - len(results))` — not always the full concurrency limit — so overshoot past the requested count (both the final result list and the live "X of N" progress counter) is now mathematically impossible within a single call, not just "slight". Confirmed live: `limit=5` used to come back with 8; now comes back with exactly 5, and the progress counter never exceeds 5 either.

`POST /api/analyze` is now async: it starts the batch in a background thread and returns `{job_id}` immediately; the frontend polls `GET /api/analyze/{job_id}` every 2s for progress (`analysis_jobs.py` — a plain in-memory job store, process-lifetime only). Candidates within a batch are processed concurrently via a bounded thread pool (`config.MAX_CONCURRENT_CANDIDATES`, default 4, in `main._run_concurrent()`) instead of one at a time — required two thread-safety fixes: a lock around `ZohoClient`'s token-refresh check, and a SQLite busy-timeout (`connect_args={"timeout": 30}` in `db/session.py`) so concurrent writes retry instead of raising "database is locked".

Job cards also have persisted per-job overrides — an editable JD and an optional free-text "search prompt" — saved via `PUT /api/job-openings/{zoho_id}/override` into two new `job_openings` columns (`custom_description`, `custom_prompt`), added via an explicit `ALTER TABLE` in `migrate_db.py` since `create_all()` doesn't add columns to existing tables. Never written back to Zoho; picked up by `main.process_resume()` at analysis time and folded into the LLM prompt.

## Version Control / Hosting

| Tech | Purpose |
|---|---|
| **Git** | Version control. |
| **GitHub (private repo)** | `github.com/bhuvaneshs-a11y/AI_Recruiter` — remote hosting, pushed via `gh` CLI. |
| **Render** | Backend deployment host — a Web Service (Root Directory `src`, free tier). No persistent disk on free tier, hence Neon for the DB and ephemeral local storage for downloaded resumes/JSON dumps (acceptable since Zoho + the DB already hold everything that matters). Free tier spins down after ~15 min idle — an external uptime pinger hits `GET /api/health` (no DB/Zoho calls) every ~10 min to keep it warm. |
| **Vercel** | Frontend deployment host (Root Directory `frontend`, framework preset "Vite", build command `npm run build`, output `dist`) — moved here from an earlier Render Static Site attempt, since Vercel is purpose-built for this and doesn't have Render's build-command-detection quirks. |
| **Neon** | Free-tier PostgreSQL, used as the deployed `DATABASE_URL` (see Storage above) — chosen over Render's own free Postgres add-on because Render's expires/gets deleted after 30 days, Neon's doesn't (it autosuspends when idle instead, which just costs a brief cold-start delay, not data loss). |

Deployed env vars beyond the usual API keys: `CORS_ORIGINS` (Render backend — must list the frontend's actual **Vercel** URL, no trailing slash, comma-separated if more than one), `VITE_API_BASE` (Vercel frontend, backend's URL + `/api` — baked in at *build* time by Vite, so changing it requires a rebuild via Vercel's dashboard, not just a redeploy).

**Git workflow**: `master` is production — Render and Vercel both auto-deploy from it on push. `dev` is where ongoing work happens; nothing deploys from it. Merge `dev` → `master` (and push) only when something's been verified working, so deploys are a deliberate action, not a side effect of every commit.

---

## Not Yet Introduced (planned)

- Agentic/tool-use orchestration (Claude Tool Runner) — deferred until the deterministic pipeline is proven against more real data
- An Anthropic API key — would remove the Gemini rate-limit ceiling entirely, since Claude is the intended long-term backend anyway
