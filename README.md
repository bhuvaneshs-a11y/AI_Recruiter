# AI Recruiter

A pipeline that pulls candidate resumes from Zoho Recruit (or a local file), extracts a structured
candidate profile, **fact-checks the claimed projects against real evidence** (GitHub commit/contributor
activity, live portfolio reachability), scores overall credibility, **scores how well the candidate fits
the specific job they applied for**, and stores everything in a local database — so a recruiter gets more
than a raw resume: a verified, structured profile with an honest assessment of what actually checks out
and how well it matches the role.

This is an early-stage personal/internal project, not a packaged product. It's built step by step, with
each piece tested against real data (real Zoho candidates, real GitHub repos, real API calls) before
moving to the next.

## What it does

1. **Pulls a resume** — either from a Zoho Recruit candidate record (via the Recruit API) or a local file
2. **Extracts a structured profile** — name, contact info, skills, experience, education, and every
   project mentioned along with its links
3. **Verifies every project link independently** — is the GitHub repo real, is the candidate actually a
   contributor with real commit/PR activity, is the portfolio link actually reachable — no LLM guessing,
   real API calls
4. **Retrieves the job the candidate applied for** (Zoho mode only) — title, full job description,
   required skills, experience level
5. **Generates a report** with two independent scores:
   - **Credibility** — per-project verdict (`verified` / `partially_verified` / `unverified` /
     `suspicious`), red flags, a 0-100 credibility score, and a hiring recommendation
   - **Job fit** (only when a job opening is attached) — a 0-100 fit score, confidence level, matched vs.
     missing required skills, an experience assessment, and career-trajectory notes
6. **Stores the result** — in a local SQLite database (source of truth) and as a JSON file per candidate
   for quick inspection

## Why two separate scores?

Credibility and job fit answer different questions and can genuinely disagree: a candidate can have
perfectly verified project claims (high credibility) while being a poor match for a specific role's tech
stack (low fit), or vice versa. Collapsing them into one number would hide which problem you're actually
looking at — "should I trust this resume" vs. "does this person fit this role."

## Setup

### Prerequisites

- Python 3.13
- A Zoho Recruit account with API access (see [Zoho credentials](#zoho-credentials) below)

### Install

```bash
pip install -r requirements.txt
```

### Configure

Copy `.env.example` to `.env` and fill in credentials:

```bash
cp .env.example .env
```

| Variable | Required? | Purpose |
|---|---|---|
| `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` | Yes, for `--zoho` mode | Zoho Recruit OAuth credentials — see below |
| `ZOHO_ACCOUNTS_URL`, `ZOHO_API_DOMAIN` | Yes, for `--zoho` mode | Must match your Zoho account's data center — see [gotcha](#zoho-data-center-gotcha) below |
| `GITHUB_TOKEN` | Recommended | A GitHub personal access token (no scopes needed) — bumps the GitHub API rate limit from 60/hr to 5,000/hr. Verification makes several GitHub calls per link, so this matters even for a handful of candidates. |
| `ANTHROPIC_API_KEY` | No (yet) | Enables the Claude-powered extraction/analysis backend (highest quality). Falls back automatically if unset. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | No | Temporary free-tier backend, used only if `ANTHROPIC_API_KEY` is unset. Default model is `gemini-3.5-flash-lite` — see [Backends](#three-backends-auto-selected) and the model-naming caveat below. |
| `DATABASE_URL` | No | Defaults to a local SQLite file at `data/ai_recruiter.db` if unset. |

### Zoho credentials

Zoho Recruit's OAuth flow depends on which client type your org's admin registers:

- **Self Client** (simplest, if you're a provisioned user in the Recruit org yourself): generate a grant
  code directly in the [Zoho API Console](https://api-console.zoho.com/), then exchange it for tokens.
- **Web-based client** (if you're *not* a provisioned Recruit user, but someone who is can authorize on
  your behalf): register a client with any redirect URI, have that person open the authorization URL and
  accept, then exchange the resulting `code` for tokens.

Either way, the token exchange looks like:

```bash
curl -X POST https://accounts.zoho.<tld>/oauth/v2/token \
  -d "grant_type=authorization_code" \
  -d "client_id=<CLIENT_ID>" \
  -d "client_secret=<CLIENT_SECRET>" \
  -d "redirect_uri=<REDIRECT_URI>" \
  -d "code=<GRANT_CODE>"
```

This returns `access_token`, `refresh_token`, and `expires_in`. Only `refresh_token` (plus the client
id/secret) needs to go in `.env` — the app refreshes its own access token automatically.

#### Zoho data center gotcha

Zoho splits accounts across regional data centers (`.com`, `.in`, `.eu`, `.com.au`, etc.). Both
`ZOHO_ACCOUNTS_URL` and `ZOHO_API_DOMAIN` must match the data center of the account that authorized the
app, or every API call fails even with valid credentials. The redirect after authorization includes an
`accounts-server` query parameter that tells you the correct one — use that, not a guess. Also note:
**Zoho Recruit uses its own dedicated API domain** (`recruit.zoho.<tld>`), not the generic
`www.zohoapis.<tld>` gateway some OAuth responses point at — the generic gateway 404s for Recruit calls.

#### Gemini model-naming gotcha

Google deprecates Gemini model IDs for new API keys often, and the newest flagship-tier models can hit
persistent 503 "high demand" errors on the free tier. If Gemini calls start failing, don't guess a
replacement model name — call `client.models.list()` to see what your key actually has access to, and
prefer a `-lite` tier for better free-tier reliability.

### Run the database migration

```bash
cd src
python migrate_db.py
```

Safe to re-run any time the schema changes.

## Usage

All commands run from `src/`:

```bash
cd src

# Analyze a single local resume file (no Zoho, no external side effects beyond local files/DB)
python main.py --local /path/to/resume.pdf

# Pull candidates from Zoho Recruit and analyze each (capped to N candidates)
python main.py --zoho --limit 5

# Pull and analyze every candidate (no cap — use with care against a real API rate limit)
python main.py --zoho
```

Each run prints a one-line summary per candidate (credibility score, DB row id, output file path) and
writes:
- A full JSON result to `data/analysis/<id>.json` — `profile`, `report`, and (Zoho mode, if the candidate
  has an application) a `job_opening` block with the job title/description/required skills
- Rows in `data/ai_recruiter.db`: `candidates`, `resume_analyses`, `project_verifications`, and (Zoho mode)
  `job_openings` + `applications`
- The downloaded resume file itself to `data/resumes/` (Zoho mode only)

## Web UI

A FastAPI backend (`src/api/`) + React frontend (`frontend/`) sit on top of the same pipeline — no separate
logic, just a thin trigger/display layer. Two tabs:

- **Active Job Openings** — every active Job Opening pulled live from Zoho, with an **Analyze Applicants**
  button per job.
- **Run Analysis** — pick a job opening (or none, for job-agnostic analysis of the next N candidates) and a
  candidate cap, then run the pipeline from the browser. Clicking **Analyze Applicants** on a job jumps here
  with that job pre-selected. When a job is selected, only candidates who *actually applied to that job* are
  fetched from Zoho and analyzed (a single job opening can have thousands of applicants, so the cap matters),
  and results are ranked best-first by job-fit score, with the top result flagged **Best Match**.

Run both servers separately:

```bash
cd src && uvicorn api.app:app --port 8000       # backend, localhost:8000
cd frontend && npm run dev                       # frontend, localhost:5173
```

## Three backends, auto-selected

The extraction and report-generation steps run through one of three interchangeable backends, picked
automatically based on which API key is configured in `.env` (first match wins):

1. **Claude** (`ANTHROPIC_API_KEY` set) — the intended long-term backend, highest quality
2. **Gemini** (`GEMINI_API_KEY` set, no Anthropic key) — a temporary free-tier stand-in, verified to work
   well but explicitly meant to be replaced once an Anthropic key is available
3. **Rule-based** (neither key set) — a dependency-free regex/heuristic fallback with deterministic
   (non-LLM) scoring, including a loose keyword-overlap job-fit match; noticeably lower quality on messy
   real-world resume formatting, but requires zero API keys to run

You don't need to choose — just set whichever key(s) you have, and the pipeline picks the best available
option automatically on every run.

## Project structure

```
src/
  config.py                    # loads .env, exposes all settings
  main.py                      # entry point: --local / --zoho, backend auto-selection, job-opening lookup
  zoho_client.py                # Zoho Recruit OAuth + API calls (candidates, attachments, job openings)
  resume_text.py                # PDF/DOCX/TXT text + hyperlink-annotation extraction
  resume_analyzer.py            # Claude-powered profile extraction
  resume_analyzer_gemini.py     # Gemini-powered profile extraction (temporary)
  resume_parser_rule_based.py   # regex/heuristic profile extraction (no API key needed)
  link_verifier.py              # real GitHub API + HTTP checks (no LLM)
  deep_analysis.py              # report generation (credibility + job-fit) + link verification orchestration
  migrate_db.py                 # create/update the SQLite schema
  db/
    models.py                   # SQLAlchemy models
    session.py                   # engine/session setup
    writer.py                    # save_analysis / save_failed_analysis
  api/
    app.py                       # FastAPI app + CORS setup
    routes/                      # job_openings.py, analyze.py
frontend/                       # React (Vite) web UI — Active Job Openings / Run Analysis tabs
data/
  resumes/                      # downloaded resume files (gitignored)
  analysis/                     # per-candidate JSON results (gitignored)
  ai_recruiter.db                # SQLite database (gitignored)
```

## Known limitations

- **Not an agent** — this is a fixed, deterministic pipeline. Each stage runs in the same order every
  time; the LLM backends only perform isolated extraction/generation calls, they don't decide what to do.
- **Rule-based backend has real gaps** on messy real-world PDFs — e.g. multiple jobs with no blank line
  between them in the extracted text can merge into one experience entry. Its job-fit matching is a loose
  keyword substring match, not semantic understanding. The LLM backends don't have these problems.
- **LinkedIn can only be checked for reachability**, not content — there's no public API for verifying
  profile claims.
- **A bare GitHub profile link** (no specific repo) only surfaces account-level stats (public repos,
  followers, account age) — it doesn't enumerate or score the candidate's actual repositories.
- **If a candidate applied to multiple job openings**, only the first one returned by Zoho is retrieved
  and scored against.
- **Suggested interview questions were deliberately left out** of the job-fit report for now — the DB
  column exists but is unpopulated; easy to add back later.

## Roadmap (not yet built)

- Writing a lightweight summary back into Zoho for recruiters who work primarily there (full data stays in
  the local DB regardless)
- Converting the fixed pipeline into a tool-using agent that decides its own investigation depth per
  candidate — deferred until the deterministic version is proven against more real data
- Shortlisting and interview features, as part of the longer-term goal of a standalone AI recruiting app
- Suggested interview questions (removed from scope for now, straightforward to reintroduce)
- Handling candidates with multiple job applications instead of only the first
