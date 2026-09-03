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
  → {generate_deep_analysis}          # credibility report: per-project verdict, red flags, score, recommendation
  → db/writer.save_analysis()         # candidates/resume_analyses/project_verifications tables
  → data/analysis/<id>.json           # same result also dumped to a file for quick inspection
```

`resume_text.extract_links()` exists because resumes commonly show a link as clickable text like "Live: Link" with no visible URL — plain-text regex would silently miss these; pdfplumber/python-docx expose them as hyperlink annotations separately from the page text.

### Three interchangeable backends, auto-selected

`main._select_backend()` picks `claude` > `gemini` > `rule_based` based on which API key is set in `.env` (first match wins). The two functions each backend must provide — `extract_candidate_profile(text, extra_links)` and `generate_deep_analysis(verified_profile)` — are looked up via the `EXTRACT_BY_BACKEND` / `ANALYZE_BY_BACKEND` dicts in `main.py`, not an if/elif chain. **When adding a backend, both dicts must get an entry, and the new module's function signatures must match exactly** (same positional args) since the dispatch is purely positional.

- `resume_analyzer.py` / `deep_analysis.generate_deep_analysis` — Claude (`claude-opus-5`), the intended long-term backend. Uses `output_config.format` with a JSON schema for guaranteed-shape structured output.
- `resume_analyzer_gemini.py` / `deep_analysis.generate_deep_analysis_gemini` — Google Gemini, added as a **temporary** stand-in while no Anthropic key is available. Uses the same JSON schemas as the Claude backend (imported and stripped of `additionalProperties`, which Gemini's schema subset doesn't support) via `response_json_schema`.
- `resume_parser_rule_based.py` / `deep_analysis.generate_deep_analysis_rule_based` — no LLM at all: regex/heuristic extraction and deterministic scoring. This is the last-resort fallback, not a demo — keep it working, since it's what runs when no API key is configured.

Gemini model IDs have proven **volatile in practice**: two model names 404'd outright ("no longer available to new users") within the same day, and the newest flagship-tier model returned persistent 503s on the free tier. If Gemini calls start failing with 404/503, don't guess a replacement model name — call `client.models.list()` to see what the key actually has access to, and prefer a `-lite` tier (better free-tier availability than flagship tiers).

### Zoho integration gotchas

`zoho_client.py` handles OAuth refresh-token exchange and the three Recruit calls used (`get_candidates`, `list_attachments`, `download_attachment`). Two non-obvious things baked into `config.py`'s defaults:

- **Data center matters for every URL, not just login.** `ZOHO_ACCOUNTS_URL` and `ZOHO_API_DOMAIN` must both match the Zoho account's actual data center (`.com`, `.in`, `.eu`, etc.) — a token issued against one data center's accounts server will not work against another's API domain.
- **The OAuth token response's `api_domain` field is misleading for Recruit.** It points at the generic `www.zohoapis.{tld}` gateway, which 404s for Recruit specifically — Recruit has its own dedicated domain, `recruit.zoho.{tld}`. Always use that, not the token response's `api_domain`.

`main._find_resume_attachment()` prefers Zoho's own `Category: {name: "Resume"}` field on an attachment over guessing by file extension, since a candidate record can have multiple attachments (cover letters, IDs, etc.).

### Database schema is ahead of the code

`db/models.py` already has `JobOpening` and `Application` tables and job-fit-scoring columns on `ResumeAnalysis` (`overall_fit_score`, `skills_matched`, `skills_missing`, `confidence`, etc.) — none of this is populated yet. The schema was designed up front for a planned job-fit-scoring feature (matching a candidate against a specific Zoho Job Opening) that hasn't been implemented. Don't assume every column is wired up just because it exists in the model.

Analysis results are stored in this local SQLite DB as the source of truth, **not written back to Zoho** — Zoho custom fields are flat types and can't hold structured data like per-project verification arrays, and the longer-term goal is a standalone app (shortlisting, interviews) that outgrows being a Zoho annotation layer.

### Testing philosophy

There's no automated test suite. The established pattern in this repo is: write the code, then actually run it against something real (a downloaded Zoho resume, a live GitHub API call, an actual Gemini/Zoho credential exchange) before considering it done — several bugs in this codebase (swapped company/title fields, a missed GitHub profile-only URL case, a stale deprecated Gemini model ID) were only caught this way, not by reading the code. Prefer this over trusting that a plausible-looking implementation is correct.
