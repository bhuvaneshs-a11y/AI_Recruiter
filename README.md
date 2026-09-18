# AI Recruiter

A pipeline that pulls candidate resumes from Zoho Recruit (or a local file), extracts a structured
candidate profile, **fact-checks the claimed projects against real evidence** (GitHub commit/contributor
activity, live portfolio reachability), scores overall credibility, **scores how well the candidate fits
the specific job they applied for**, and stores everything in a local database — so a recruiter gets more
than a raw resume: a verified, structured profile with an honest assessment of what actually checks out
and how well it matches the role.

This is an early-stage internal project, not a packaged product. It's built step by step, with each piece
tested against real data (real Zoho candidates, real GitHub repos, real API calls) before moving to the
next — see `CLAUDE.md` for architecture details and known gotchas, and `TECH_STACK.md` for the full
library/service list with the reasoning behind each choice.

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
6. **Stores the result** — in a database (SQLite locally, PostgreSQL/Neon when deployed — source of truth)
   and as a JSON file per candidate for quick inspection

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
| `GEMINI_API_KEY`, `GEMINI_MODEL` | No | Temporary free-tier backend, used only if `ANTHROPIC_API_KEY` is unset. Default model is `gemini-3.5-flash-lite` — see [Backends](#three-backends-auto-selected) and the model-naming caveat below. Free tier hard-caps at 15 requests/min — see the rate-limit note below. |
| `DATABASE_URL` | No | Defaults to a local SQLite file at `data/ai_recruiter.db` if unset. Point this at a PostgreSQL connection string (e.g. Neon) for deployment — see [Deployment](#deployment) below. |
| `DATA_DIR` | No | Overrides where downloaded resumes/analysis JSON dumps live — defaults to `<repo>/data`. Only matters on hosts with ephemeral local disk; leave unset locally. |
| `CORS_ORIGINS` | No (Yes for the deployed Web UI) | Comma-separated list of origins the backend's CORS policy allows — defaults to `http://localhost:5173`. Must list the deployed frontend's exact URL (no trailing slash) in production. |

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

#### Gemini free-tier rate limit

`gemini-3.5-flash-lite`'s free tier hard-caps at **15 requests/minute** per project — each candidate makes
2-3 Gemini calls, so the real ceiling is around 7 candidates/minute at best. `src/gemini_rate_limiter.py`
throttles every Gemini call site to stay under this automatically (with retry-with-backoff as a safety
net), so you won't see `429` errors — but analysis will still only go as fast as that ceiling allows, no
matter how high `MAX_CONCURRENT_CANDIDATES` is set. Getting an `ANTHROPIC_API_KEY` removes this ceiling
entirely, since Claude doesn't share the same free-tier constraint.

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
  button per job. Each card can also be expanded to edit the job description and add an optional free-text
  search prompt (extra criteria like "must know Kubernetes, prioritize RAG experience") — both are saved
  locally (never written back to Zoho) and used the next time that job's applicants are analyzed.
- **Run Analysis** — pick a job opening (or none, for job-agnostic analysis of the next N candidates) and a
  candidate cap, then run the pipeline from the browser. Clicking **Analyze Applicants** on a job jumps here
  with that job pre-selected. When a job is selected, only candidates who *actually applied to that job* are
  fetched from Zoho and analyzed (a single job opening can have thousands of applicants, so the cap matters).
  Candidates are processed several at a time (not one-by-one), results appear in a table as each candidate
  finishes rather than all at once at the end, and once complete they're ranked best-first by job-fit score
  (ties broken by credibility) with the top result flagged **Best Match**.

### How a job-scoped search behaves under the hood

A few things worth knowing if you're wondering why a search returns what it does:

- **The applicant list is a frozen snapshot, not a live query every time.** The first search for a job
  fetches live from Zoho (can take 30+ seconds for a job with thousands of applicants) and saves the
  result; every search after that reuses the saved list instead (near-instant), so repeated searches
  return the *same* candidates instead of shifting as new applications trickle in. Send
  `refresh_snapshot: true` to `POST /api/analyze` to force a fresh pull.
- **Every reuse re-checks each candidate's live status first.** Only candidates still marked `"Applied"`
  in Zoho count as fresh — anyone a recruiter has already rejected, called, interviewed, or otherwise
  moved past the initial stage is automatically dropped from the snapshot and skipped, so you don't keep
  getting re-shown candidates someone's already handled elsewhere. If a job's applicant pool has mostly
  moved on, you can legitimately get *fewer* candidates than you asked for — the UI explains this when it
  happens ("Only 2 of 5 requested — the rest of this job's applicant pool has already moved past the
  initial application stage").
- **A job's optional search prompt is a hard filter, not just a scoring hint.** If you've set one (e.g.
  "must have graduated in 2025"), candidates are checked against it *before* the expensive part of the
  pipeline runs, and non-matches are skipped entirely (not shown, not counted) — the search keeps going
  deeper into the applicant pool until it finds enough genuine matches or exhausts the pool.
- **Already-analyzed candidates are cached.** Bumping a search's candidate cap up (e.g. 4 → 5) only
  processes the newly-needed candidates, not the whole batch again — as long as no search prompt is active
  (a cached result can't account for a prompt that didn't exist, or was different, when it was created).

Run both servers separately:

```bash
cd src && uvicorn api.app:app --port 8000       # backend, localhost:8000
cd frontend && npm run dev                       # frontend, localhost:5173
```

## Deployment

The app is deployed with the backend and frontend on separate hosts, and a managed Postgres database —
none of this is required for local development (SQLite + `localhost` is the default and needs no setup).

**Live**: frontend at `https://ai-recruiter-xi-two.vercel.app`, backend at `https://ai-recruiter-xmsh.onrender.com`
(both dashboards are on the org's Render/Vercel accounts — ask for access if you don't have it).

| Piece | Host | Notes |
|---|---|---|
| Backend | [Render](https://render.com) — Web Service | Root Directory `src`, build `pip install -r ../requirements.txt`, start `python migrate_db.py && uvicorn api.app:app --host 0.0.0.0 --port $PORT`. Free tier has **no persistent disk** and **spins down after ~15 min idle**. |
| Frontend | [Vercel](https://vercel.com) — Static Site | Root Directory `frontend`, framework preset "Vite", build `npm run build`, output `dist`. |
| Database | [Neon](https://neon.tech) — Postgres | Free tier, no 30-day expiry (unlike Render's own free Postgres add-on) — just autosuspends when idle, costing a brief cold-start delay on the next query, not data loss. |

### Deployment-specific environment variables

Set these on top of the usual `.env` keys, as environment variables on each host's dashboard:

- **Render (backend)**: `DATABASE_URL` (the Neon connection string), `CORS_ORIGINS` (the frontend's exact Vercel URL, no trailing slash), plus all the API keys from the table above.
- **Vercel (frontend)**: `VITE_API_BASE` = the backend's Render URL + `/api`. This is baked in at **build time** by Vite — changing it requires triggering a new build, not just a redeploy.

### Keeping the backend warm

Render's free tier spins the backend down after ~15 minutes of no traffic, making the next request slow
(30-60s) while it wakes back up. `GET /api/health` is a zero-dependency endpoint (no DB/Zoho calls) built
for an external uptime pinger — e.g. [cron-job.org](https://cron-job.org) or UptimeRobot's free tier,
hitting it every ~10 minutes — to keep the service from ever going idle long enough to spin down.

### Git workflow

`master` is production — Render and Vercel both auto-deploy from it on every push. Do **not** push directly
to `master` for anything still being worked on. Instead:

1. Do all work on the `dev` branch (`git checkout dev`) — pushing here doesn't trigger any deploy.
2. Once something's built and verified working, merge `dev` into `master` and push — that's the one
   deliberate moment a deploy happens.

```bash
git checkout dev
# ... make changes, commit, push to dev as normal ...

# when ready to ship:
git checkout master
git merge dev
git push origin master   # <- this triggers the actual Render + Vercel deploy
git checkout dev          # back to dev for the next round of work
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
  main.py                      # entry point: --local / --zoho, backend auto-selection, concurrency, snapshots
  zoho_client.py                # Zoho Recruit OAuth + API calls (candidates, attachments, job openings, applications)
  gemini_rate_limiter.py        # sliding-window limiter + retry-with-backoff for every Gemini call site
  resume_text.py                # PDF/DOCX/TXT text + hyperlink-annotation extraction
  resume_analyzer.py            # Claude-powered profile extraction
  resume_analyzer_gemini.py     # Gemini-powered profile extraction (temporary)
  resume_parser_rule_based.py   # regex/heuristic profile extraction (no API key needed)
  link_verifier.py              # real GitHub API + HTTP checks (no LLM)
  deep_analysis.py              # report generation (credibility + job-fit) + link verification orchestration
  migrate_db.py                 # create/update the schema (SQLite or Postgres)
  analysis_jobs.py              # in-memory background-job store backing POST/GET /api/analyze
  db/
    models.py                   # SQLAlchemy models
    session.py                   # engine/session setup (pool_pre_ping for Neon, busy-timeout for SQLite)
    writer.py                    # save_analysis, job-opening overrides, applicant snapshots, analysis cache
  api/
    app.py                       # FastAPI app + CORS setup + /api/health
    routes/                      # job_openings.py, analyze.py
frontend/                       # React (Vite) web UI — Active Job Openings / Run Analysis tabs
data/
  resumes/                      # downloaded resume files (gitignored)
  analysis/                     # per-candidate JSON results (gitignored)
  ai_recruiter.db                # SQLite database (gitignored, local dev only)
```

## Known limitations

- **Not an agent** — this is a fixed, deterministic pipeline. Each stage runs in the same order every
  time; the LLM backends only perform isolated extraction/generation calls, they don't decide what to do.
- **No automated test suite** — verification is done by running the actual pipeline against real data (see
  `CLAUDE.md`'s "Testing philosophy"). Treat any change as unverified until it's actually been run.
- **Rule-based backend has real gaps** on messy real-world PDFs — e.g. multiple jobs with no blank line
  between them in the extracted text can merge into one experience entry. Its job-fit matching is a loose
  keyword substring match, not semantic understanding, and it can't interpret a free-text search prompt at
  all (every candidate passes through unfiltered). The LLM backends don't have these problems.
- **Gemini's free tier caps at 15 requests/minute** — `gemini_rate_limiter.py` keeps this from causing
  errors, but analysis speed is still bounded by it (~7 candidates/minute at best) until an
  `ANTHROPIC_API_KEY` is added.
- **LinkedIn can only be checked for reachability**, not content — there's no public API for verifying
  profile claims.
- **A bare GitHub profile link** (no specific repo) only surfaces account-level stats (public repos,
  followers, account age) — it doesn't enumerate or score the candidate's actual repositories.
- **If a candidate applied to multiple job openings**, the job-agnostic `run_zoho()` path (no job selected
  in Run Analysis) only retrieves and scores against the first one Zoho returns. Not an issue for the
  job-scoped path (`run_zoho_for_job()`, i.e. picking a specific job in the UI) — that already searches by
  the exact job you selected.
- **Suggested interview questions were deliberately left out** of the job-fit report for now — the DB
  column exists but is unpopulated; easy to add back later.
- **The deployed backend (Render free tier) has no persistent disk** — downloaded resumes and the
  per-candidate JSON dumps in `data/` don't survive a redeploy or restart there. This is fine because the
  database (source of truth) is unaffected and Zoho still has the original resume files.

## Roadmap (not yet built)

- Writing a lightweight summary back into Zoho for recruiters who work primarily there (full data stays in
  the local DB regardless)
- Converting the fixed pipeline into a tool-using agent that decides its own investigation depth per
  candidate — deferred until the deterministic version is proven against more real data
- Shortlisting and interview features, as part of the longer-term goal of a standalone AI recruiting app
- Suggested interview questions (removed from scope for now, straightforward to reintroduce)
- Handling candidates with multiple job applications in the job-agnostic path (already handled in the
  job-scoped path)
- Getting an `ANTHROPIC_API_KEY` to remove the Gemini rate-limit ceiling and switch to the intended
  long-term backend
