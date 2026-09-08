# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands are run from `src/` (the entry scripts rely on flat sibling imports, e.g. `import config` — there is no top-level package, so `python` must be invoked with `src/` as the working directory, not the repo root).

```bash
cd src
pip install -r ../requirements.txt      # install deps
python migrate_db.py                    # create/update the SQLite schema (idempotent, safe to re-run)
python main.py --local <path-to-resume> # run the full pipeline on one local file (no Zoho, no side effects beyond local files/DB)
python main.py --zoho --limit N         # pull N candidates from Zoho Recruit and run the full pipeline on each
```

There is no test suite, linter, or build step in this project. Verification is done by running the actual pipeline against real downloaded resumes and real external APIs (Zoho, GitHub, Gemini) — see the "Testing philosophy" note below before assuming something works from reading the code alone.

## Architecture

### Pipeline shape

This is a **deterministic pipeline, not an agent** — `main.py` calls each stage in a fixed order; no LLM decides what to do next. One resume flows through:

```
resume file (Zoho attachment or local path)
  → resume_text.extract_text()        # plain text, PDF/DOCX/TXT
  → resume_text.extract_links()       # PDF/DOCX hyperlink *annotations* not visible as text
  → {extract_candidate_profile}       # structured profile: name, skills, experience, education, projects+links
  → deep_analysis.verify_profile_links()  # calls link_verifier per link — real GitHub API + HTTP checks, no LLM
  → {generate_deep_analysis}          # report: per-project verdict/credibility score, + job-fit score if a job_opening was passed in
  → db/writer.save_analysis()         # candidates/resume_analyses/project_verifications (+ job_openings/applications) tables
  → data/analysis/<id>.json           # same result also dumped to a file for quick inspection
```

In `--zoho` mode, `run_zoho()` also calls `ZohoClient.get_associated_job_openings()` per candidate before `process_resume()`, so the job the candidate applied for (if any) flows into both the analysis prompt and the JSON output.

`resume_text.extract_links()` exists because resumes commonly show a link as clickable text like "Live: Link" with no visible URL — plain-text regex would silently miss these; pdfplumber/python-docx expose them as hyperlink annotations separately from the page text. `link_verifier.verify_link()` filters out non-`http(s)` URLs (`mailto:`, `tel:`) before attempting verification — hyperlink annotations aren't always web links.

### Two scores, deliberately kept separate

Every report has `overall_credibility_score` (are the claims verifiable — always present) and, only when a job opening is attached, `overall_fit_score` + `confidence` + `skills_matched`/`skills_missing` + `experience_assessment` + `career_trajectory_notes` (does this candidate fit *this* role). These are **not** meant to be merged into one number — a candidate can score high on one and low on the other (e.g. verified, real project history, but the wrong tech stack for the role applied to), and collapsing them loses that signal. `suggested_interview_questions` was deliberately dropped from scope (DB column still exists, unpopulated) — don't reintroduce it without being asked.

### Raw vs. cleaned `job_opening` shapes — don't mix them up

`ZohoClient.get_associated_job_openings()` returns Zoho's raw field names (`Posting_Title`, `Job_Description`, `Required_Skills`, `Work_Experience`, `$application_id`, `id`, ...). `main.process_resume()` converts this to a small cleaned dict (`job_applied_for`, `job_description`, `required_skills`, `experience_level`) for the JSON output and for every `deep_analysis` function's prompt/heuristic. `db.writer.save_analysis()`, however, takes the **raw** dict (it needs `id`, `$application_id`, etc. to write `JobOpening`/`Application` rows). If you add a new consumer of `job_opening`, check which shape it actually needs — mixing them up silently produces `None`s, not an error, since both are plain dicts with `.get()`.

### Three interchangeable backends, auto-selected

`main._select_backend()` picks `claude` > `gemini` > `rule_based` based on which API key is set in `.env` (first match wins). Each backend must provide two functions with matching signatures — `extract_candidate_profile(text, extra_links)` and `generate_deep_analysis(verified_profile, job_opening=None)` — looked up via the `EXTRACT_BY_BACKEND` / `ANALYZE_BY_BACKEND` dicts in `main.py`, not an if/elif chain. **When adding a backend, both dicts must get an entry, and the new module's function signatures must match exactly** (same positional args) since the dispatch is purely positional.

- `resume_analyzer.py` / `deep_analysis.generate_deep_analysis` — Claude (`claude-opus-5`), the intended long-term backend. Uses `output_config.format` with a JSON schema for guaranteed-shape structured output. Schema is `REPORT_SCHEMA` normally, or `JOB_FIT_REPORT_SCHEMA` (extends it, doesn't replace it) when a `job_opening` is passed in.
- `resume_analyzer_gemini.py` / `deep_analysis.generate_deep_analysis_gemini` — Google Gemini, added as a **temporary** stand-in while no Anthropic key is available. Uses the same schemas as the Claude backend (imported and stripped of `additionalProperties`, which Gemini's schema subset doesn't support) via `response_json_schema`.
- `resume_parser_rule_based.py` / `deep_analysis.generate_deep_analysis_rule_based` — no LLM at all: regex/heuristic extraction, deterministic credibility scoring, and a loose keyword-substring job-fit match. This is the last-resort fallback, not a demo — keep it working, since it's what runs when no API key is configured.

Gemini model IDs have proven **volatile in practice**: two model names 404'd outright ("no longer available to new users") within the same day, and the newest flagship-tier model returned persistent 503s on the free tier. Current default (`config.GEMINI_MODEL`) is `gemini-3.5-flash-lite`. If Gemini calls start failing with 404/503, don't guess a replacement model name — call `client.models.list()` to see what the key actually has access to, and prefer a `-lite` tier (better free-tier availability than flagship tiers).

### Zoho integration gotchas

`zoho_client.py` handles OAuth refresh-token exchange and the Recruit calls used: `get_candidates`, `list_attachments`, `download_attachment`, `get_associated_job_openings` (a candidate's applied-to Job Openings, via `Candidates/{id}/associate` — candidate→job direction), `get_job_opening` (fetch one by ID directly), `get_all_job_openings` (auto-paginated full list), `get_applications_for_job` (job→candidates direction, see below). Gotchas baked into `config.py`'s defaults and worth knowing before touching any of these:

- **Data center matters for every URL, not just login.** `ZOHO_ACCOUNTS_URL` and `ZOHO_API_DOMAIN` must both match the Zoho account's actual data center (`.com`, `.in`, `.eu`, etc.) — a token issued against one data center's accounts server will not work against another's API domain.
- **The OAuth token response's `api_domain` field is misleading for Recruit.** It points at the generic `www.zohoapis.{tld}` gateway, which 404s for Recruit specifically — Recruit has its own dedicated domain, `recruit.zoho.{tld}`. Always use that, not the token response's `api_domain`.
- **`Job_Description` differs by endpoint.** Via `get_associated_job_openings` (the `associate` endpoint) it comes back as clean plain text. Via `get_job_opening` (fetching the same Job Opening directly by ID) it comes back as raw HTML (`<span>`/`<div>` with inline styles) — strip tags before using that path in a prompt.
- **A candidate can have multiple associated job openings**; `run_zoho()` currently only takes `job_openings[0]` — not handled beyond that.
- **`/JobOpenings/{id}/associate` does not work in the job→candidates direction**, despite docs implying symmetry with the candidate-side endpoint — confirmed live to return 400 ("the relation name given seems to be invalid", then "EXTRA_PARAM_FOUND" after trying the docs-suggested `candidate_statuses` param). `get_applications_for_job()` instead searches the `Applications` module directly, filtering server-side by `Job_Opening_Name` (a candidate's applied-to job title) — **not** by `$Job_Opening_Id`, a computed reference field that Zoho's search API silently ignores as a criterion (returns 200 with unfiltered results across all jobs, not an error). Since two job openings could share a title, results are then double-checked against the exact `job_opening_id` client-side on the smaller returned set. Total Applications volume seen live: 16,543 records — fetch-all-then-filter is not viable, hence the server-side title search.
- **`get_applications_for_job()` excludes `Application_Status` in `EXCLUDED_APPLICATION_STATUSES`** (`"Rejected"`, `"Junk candidate"`) client-side — neither a previously-rejected candidate nor a junk/spam/irrelevant application should be re-surfaced and re-analyzed every time a job's applicants are pulled. Confirmed live on one job's 4,899 applications: 258 `"Rejected"` + 323 `"Junk candidate"` correctly excluded, 4,318 remained (`"Applied"`, `"In Review"`, `"Call"`, `"Qualified"`, `"Technical Round - 1"`, `"Interview-Scheduled"`).
#### Resolved: "You have made too many requests continuously" (token-refresh rate limit)

- **Error**: Zoho's OAuth token endpoint (`/oauth/v2/token`) returns `"You have made too many requests continuously"` instead of a new access token.
- **Root cause**: Zoho rate-limits the *token-refresh* endpoint itself, separately and much more strictly than normal Recruit API call limits. `ZohoClient()` used to refresh its access token on construction whenever the cached one was missing/expired — fine for a single CLI run, but the FastAPI server was constructing a **fresh `ZohoClient()` on every incoming HTTP request** (e.g. every page load of "Active Job Openings", every "Run Analysis" click), so every request triggered its own token refresh. A handful of clicks was enough to trip the limit.
- **Fix**: `zoho_client.get_shared_client()` — a process-lifetime singleton — is used everywhere a client is needed outside a single script run, instead of `ZohoClient()`. Both `/api/job-openings` and `/api/analyze` use it, and `run_zoho()` / `run_zoho_for_job()` both accept an optional `client=` param so callers pass the shared instance through rather than each constructing their own. Confirmed holding up under repeated `/api/job-openings` loads and multiple `/api/analyze` runs without recurring. If you add a new route or script that talks to Zoho, use `get_shared_client()` — constructing `ZohoClient()` directly outside a one-off script reintroduces this.

`main._find_resume_attachment()` prefers Zoho's own `Category: {name: "Resume"}` field on an attachment over guessing by file extension, since a candidate record can have multiple attachments (cover letters, IDs, etc.).

### GitHub verification depth depends on link type

`link_verifier.verify_github()` behaves differently depending on whether the resume links a specific repo (`github.com/{owner}/{repo}`) or just a profile (`github.com/{owner}`):
- **Repo link**: fork status, star count, whether the owner is a contributor, approximate commit count, PR count, plus owner-level stats.
- **Profile-only link**: only owner-level stats — `owner_public_repos`, `owner_followers`, `owner_account_created_at` (all pulled from the same `/users/{owner}` call already made for name-matching, via the shared `_check_owner_profile()` helper). It does **not** enumerate or score the user's actual repositories. `repo`/`is_fork`/`stars`/`owner_is_contributor`/etc. staying `null` for a profile-only link is expected, not a bug.

### Database schema

`db/models.py` has `candidates`, `job_openings`, `applications`, `resume_analyses` (credibility + job-fit columns), and `project_verifications` — all of it is now populated by the pipeline (job-fit columns went live once job-fit scoring was implemented; don't assume they're still dead schema from an earlier state of this project).

Analysis results are stored in this local SQLite DB as the source of truth, **not written back to Zoho** — Zoho custom fields are flat types and can't hold structured data like per-project verification arrays, and the longer-term goal is a standalone app (shortlisting, interviews) that outgrows being a Zoho annotation layer.

### Web UI

`src/api/` (FastAPI) + `frontend/` (React/Vite, plain JS) — a thin layer over the same pipeline, not a second implementation. Two tabs: **Active Job Openings** (live from Zoho, via `GET /api/job-openings`) and **Run Analysis** (`POST /api/analyze`, body `{limit, job_opening_id}`). Clicking "Analyze Applicants" on a job card jumps to Run Analysis with that job pre-selected (lifted state in `App.jsx`).

- With `job_opening_id`: `analyze.py` calls `main.run_zoho_for_job()`, which fetches that job's *actual* applicants via `get_applications_for_job()` (not just the next N candidates in Zoho's default order), runs the full pipeline on each, and returns them **best-first** by `overall_fit_score` (falls back to credibility if fit is absent) — the UI shows a "Best Match" badge on the top result.
- Without it: falls back to `main.run_zoho()` — the next N candidates in Zoho's default order, no job context, ranked by credibility only.
- Both routes use `zoho_client.get_shared_client()` (see rate-limit gotcha above) — this matters more here than in the CLI, since a web server fields repeated requests instead of running once and exiting.

Run backend and frontend separately: `cd src && uvicorn api.app:app --port 8000` and `cd frontend && npm run dev` (port 5173, CORS-allowed for that origin only). **`uvicorn --reload` has been observed to silently miss reload events** on some edits (confirmed live: editing `main.py` kept serving stale logic, evidenced by a job-scoped query returning the wrong job's candidates, while a fresh debug script using the same function returned correctly) — if a code change doesn't seem to take effect, don't trust `--reload`; kill the process fully and restart without it.

### Recruiter-editable JD / search prompt overrides

Each job card in **Active Job Openings** has an "Edit description & prompt" toggle exposing two persisted free-text fields: an editable **job description** (defaults to Zoho's `Job_Description`) and an optional **search prompt** (extra ad-hoc criteria, e.g. "must know Kubernetes, prioritize RAG experience"). Saved via `PUT /api/job-openings/{zoho_id}/override`, stored in two new `job_openings` columns — `custom_description`, `custom_prompt` — added via an explicit `ALTER TABLE` in `migrate_db.py` (`Base.metadata.create_all()` alone doesn't add columns to a table that already exists).

These are **local-only overrides, never written back to Zoho** (consistent with the rest of this app's Zoho-is-read-only stance). `main.process_resume()` looks up any saved override (`db.writer.get_job_opening_override()`) by the job's `zoho_id` and, if present, substitutes `custom_description` for `job_description` and adds `custom_prompt` as `additional_instructions` in the `job_opening_clean` dict passed to the LLM backends. `deep_analysis._job_fit_prompt_section()` appends `additional_instructions` to the job-fit prompt, telling the model to weigh it heavily — this only affects the Claude/Gemini backends (the rule-based backend's `_match_skills()` is pure keyword substring matching and has no mechanism to interpret free-text instructions; it silently ignores `additional_instructions` via `.get()`).

The override row can exist before any analysis has ever run for that job (the JD/prompt fields need to be editable the first time you open a job card), so `save_job_opening_override()` upserts by `zoho_id` directly rather than relying on `_get_or_create_job_opening()` (which only ever gets called from `save_analysis()`, i.e. after a candidate has actually been analyzed).

### Concurrent candidate processing + background analysis jobs

`main._run_concurrent()` runs each candidate's pipeline (resume download → LLM extraction → link verification → LLM report) in a bounded thread pool (`config.MAX_CONCURRENT_CANDIDATES`, default 4) instead of one at a time — nearly all of a candidate's processing time is spent waiting on external APIs (Zoho, GitHub, the LLM), so several run concurrently with minimal added risk, capped to avoid bursting past those providers' rate limits. Both `run_zoho()` and `run_zoho_for_job()` take optional `on_result`/`on_total` callbacks fired as each candidate completes / once the candidate count is known — the CLI passes neither (unchanged behavior), the API layer uses them to report live progress.

`POST /api/analyze` no longer blocks until every candidate is done — it starts the batch in a background thread (`analysis_jobs.start_job()`) and returns `{job_id}` immediately. Poll `GET /api/analyze/{job_id}` for `{status: "running"|"done"|"error", total, results, error}`; `results` fills in as candidates complete (completion order while running, best-fit-sorted once `status` is `"done"`). The job store (`analysis_jobs.py`) is a plain in-memory dict guarded by one `threading.Lock` — process-lifetime only, not persisted, which is fine since the DB remains the source of truth for completed analyses and this is just live-progress bookkeeping for one session. **A bad `job_opening_id` no longer produces an immediate 404** — that lookup now happens inside the background job, so it surfaces as `status: "error"` on the first poll instead.

Two thread-safety fixes were needed to make this safe:
- `ZohoClient._headers()`'s check-and-refresh-token logic is now guarded by a `threading.Lock` — without it, multiple concurrent candidate threads could all see an expired token at the same instant and every one of them would call the refresh endpoint simultaneously, retriggering the exact rate-limit error `get_shared_client()` was introduced to fix, just from a new angle.
- `db/session.py`'s SQLite engine now sets `connect_args={"timeout": 30}` (a busy-timeout) — SQLite serializes writes at the file level, so two threads finishing at nearly the same moment could otherwise hit "database is locked" instead of one simply waiting briefly for the other.

### Testing philosophy

There's no automated test suite. The established pattern in this repo is: write the code, then actually run it against something real (a downloaded Zoho resume, a live GitHub API call, an actual Gemini/Zoho credential exchange, the actual browser UI) before considering it done — several bugs in this codebase (swapped company/title fields, a missed GitHub profile-only URL case, a stale deprecated Gemini model ID, a GitHub profile check silently discarding `public_repos` that was already in the API response, a `job_opening` dict shape mismatch between raw Zoho fields and the cleaned output shape, a stale `--reload` process serving old job-scoping logic) were only caught this way, not by reading the code. Prefer this over trusting that a plausible-looking implementation is correct.
