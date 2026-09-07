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

`zoho_client.py` handles OAuth refresh-token exchange and the Recruit calls used: `get_candidates`, `list_attachments`, `download_attachment`, `get_associated_job_openings` (a candidate's applied-to Job Openings, via `Candidates/{id}/associate`), `get_job_opening` (fetch one by ID directly). Gotchas baked into `config.py`'s defaults and worth knowing before touching any of these:

- **Data center matters for every URL, not just login.** `ZOHO_ACCOUNTS_URL` and `ZOHO_API_DOMAIN` must both match the Zoho account's actual data center (`.com`, `.in`, `.eu`, etc.) — a token issued against one data center's accounts server will not work against another's API domain.
- **The OAuth token response's `api_domain` field is misleading for Recruit.** It points at the generic `www.zohoapis.{tld}` gateway, which 404s for Recruit specifically — Recruit has its own dedicated domain, `recruit.zoho.{tld}`. Always use that, not the token response's `api_domain`.
- **`Job_Description` differs by endpoint.** Via `get_associated_job_openings` (the `associate` endpoint) it comes back as clean plain text. Via `get_job_opening` (fetching the same Job Opening directly by ID) it comes back as raw HTML (`<span>`/`<div>` with inline styles) — strip tags before using that path in a prompt.
- **A candidate can have multiple associated job openings**; `run_zoho()` currently only takes `job_openings[0]` — not handled beyond that.

`main._find_resume_attachment()` prefers Zoho's own `Category: {name: "Resume"}` field on an attachment over guessing by file extension, since a candidate record can have multiple attachments (cover letters, IDs, etc.).

### GitHub verification depth depends on link type

`link_verifier.verify_github()` behaves differently depending on whether the resume links a specific repo (`github.com/{owner}/{repo}`) or just a profile (`github.com/{owner}`):
- **Repo link**: fork status, star count, whether the owner is a contributor, approximate commit count, PR count, plus owner-level stats.
- **Profile-only link**: only owner-level stats — `owner_public_repos`, `owner_followers`, `owner_account_created_at` (all pulled from the same `/users/{owner}` call already made for name-matching, via the shared `_check_owner_profile()` helper). It does **not** enumerate or score the user's actual repositories. `repo`/`is_fork`/`stars`/`owner_is_contributor`/etc. staying `null` for a profile-only link is expected, not a bug.

### Database schema

`db/models.py` has `candidates`, `job_openings`, `applications`, `resume_analyses` (credibility + job-fit columns), and `project_verifications` — all of it is now populated by the pipeline (job-fit columns went live once job-fit scoring was implemented; don't assume they're still dead schema from an earlier state of this project).

Analysis results are stored in this local SQLite DB as the source of truth, **not written back to Zoho** — Zoho custom fields are flat types and can't hold structured data like per-project verification arrays, and the longer-term goal is a standalone app (shortlisting, interviews) that outgrows being a Zoho annotation layer.

### Testing philosophy

There's no automated test suite. The established pattern in this repo is: write the code, then actually run it against something real (a downloaded Zoho resume, a live GitHub API call, an actual Gemini/Zoho credential exchange) before considering it done — several bugs in this codebase (swapped company/title fields, a missed GitHub profile-only URL case, a stale deprecated Gemini model ID, a GitHub profile check silently discarding `public_repos` that was already in the API response, a `job_opening` dict shape mismatch between raw Zoho fields and the cleaned output shape) were only caught this way, not by reading the code. Prefer this over trusting that a plausible-looking implementation is correct.
