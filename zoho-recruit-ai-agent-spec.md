# Zoho Recruit AI Analysis Agent — Architecture & Spec

## 1. Purpose

An autonomous agent that watches Zoho Recruit for candidates, performs deep AI-driven
resume/profile analysis against the job they applied for, and writes structured results
(score, summary, flags, suggested questions) back into Zoho — so recruiters see a
ready-made performance profile instead of a raw resume.

---

## 2. High-Level Architecture

```
┌─────────────────┐       ┌──────────────────────────────────────┐       ┌─────────────────┐
│  Zoho Recruit    │       │           YOUR AGENT SERVICE          │       │   Claude API     │
│                  │       │                                        │       │  (analysis brain)│
│ - Candidates     │──(1)─▶│  A. Trigger Listener (webhook/cron)   │       │                  │
│ - Job Openings   │       │  B. Zoho Client (OAuth + REST calls)  │──(3)─▶│  Structured JSON │
│ - Attachments     │◀─(6)─│  C. Resume Parser (PDF/DOCX → text)   │◀──────│  analysis output │
│ - Custom Fields   │       │  D. Prompt Builder                   │       │                  │
│ - Webhooks        │       │  E. Result Writer (write-back)        │       └─────────────────┘
└─────────────────┘       │  F. State Store (DB - job status,     │
                          │     dedup, audit log)                  │
                          │  G. Notifier (optional: email/Slack)   │
                          └──────────────────────────────────────┘
```

**Flow in words:**
1. Candidate applies / is updated in Zoho → webhook fires (or agent polls on a schedule)
2. Agent fetches the candidate record, resume attachment, and matching Job Opening
3. Agent extracts resume text, builds a structured prompt, sends to Claude
4. Claude returns structured JSON: score, rationale, extracted skills, flags, questions
5. Agent validates/parses that JSON
6. Agent writes results back into custom fields on the Candidate record in Zoho
7. (Optional) Agent notifies the recruiter if score crosses a threshold

---

## 3. Core Components

### A. Trigger Listener
Two options, not mutually exclusive:

| Method | How it works | Pros | Cons |
|---|---|---|---|
| **Webhook** | Zoho Recruit workflow rule fires an "Outgoing Webhook" to your endpoint when a Candidate is created/updated | Near real-time, low API usage | Requires a publicly reachable HTTPS endpoint |
| **Polling** | Agent runs on a schedule (e.g. every 5–15 min), queries `Candidates` with a `modified_time` filter since last run | Simple, no public endpoint needed | Slight delay, uses more API credits |

**Recommendation:** Start with polling (simpler to build/debug), move to webhooks once stable.

### B. Zoho Client
Wraps OAuth token lifecycle + REST calls:
- Handles access token refresh (hourly expiry) using the stored refresh token
- Methods: `get_candidate(id)`, `get_job_opening(id)`, `download_attachment(module, record_id, attachment_id)`, `update_candidate_fields(id, fields)`, `list_modified_candidates(since)`
- Respects rate limits — batches requests, backs off on 429s

### C. Resume Parser
- Input: raw resume file (PDF/DOCX/DOC) downloaded from Zoho attachment API
- Output: clean plain text
- Libraries: `pdfplumber`/`PyMuPDF` for PDF, `python-docx`/`mammoth` for DOCX
- Fallback: if Zoho's own parsed fields (skills, experience) are already populated, use those as a supplement/cross-check rather than re-parsing from scratch

### D. Prompt Builder
Constructs a single structured prompt per candidate containing:
- Job Opening details (title, required skills, experience level, description)
- Candidate resume text (cleaned)
- Candidate's existing Zoho fields (current title, total experience, etc.)
- Explicit instruction: **respond only in JSON**, matching a fixed schema (see §5)

### E. Result Writer
- Parses the JSON response
- Maps each field to a corresponding **custom field** in Zoho (must be created in Zoho's module settings first — see §6)
- Writes via `PUT`/`PATCH` to the Candidate record
- Logs success/failure to the state store

### F. State Store (small DB)
Even a lightweight SQLite/Postgres table is enough. Tracks:
- Which candidates have already been analyzed (avoid duplicate LLM calls / API waste)
- Last poll timestamp
- Audit log: candidate ID, timestamp, score, raw LLM response, any errors
- Useful for debugging and for later refining prompts based on real outcomes

### G. Notifier (optional, later phase)
- If AI score ≥ threshold → create a Zoho Task assigned to the recruiter, or send a Slack/email ping
- Keeps humans in the loop rather than fully automating decisions

---

## 4. Data Flow — Single Candidate Walkthrough

1. `GET /recruit/v2/Candidates/{id}` → candidate JSON (name, email, resume attachment ID, applied Job Opening ID, existing parsed fields)
2. `GET /recruit/v2/Candidates/{id}/Attachments` → resume file
3. `GET /recruit/v2/JobOpenings/{job_id}` → job requirements/description
4. Parse resume file → plain text
5. Build prompt → send to Claude API
6. Receive structured JSON response
7. `PUT /recruit/v2/Candidates/{id}` with custom fields populated
8. Log to state store; optionally notify

---

## 5. Analysis Output Schema (what Claude returns)

Keeping this as a strict, fixed schema makes write-back reliable and avoids fragile text-parsing.

```json
{
  "overall_fit_score": 0-100,
  "confidence": "high | medium | low",
  "summary": "2-3 sentence recruiter-facing summary",
  "skills_matched": ["skill1", "skill2"],
  "skills_missing": ["skill3"],
  "experience_assessment": "short paragraph on depth/seniority fit",
  "career_trajectory_notes": "short paragraph, growth pattern, job-hopping, relevance",
  "red_flags": ["short bullet", "short bullet"],
  "suggested_interview_questions": ["question 1", "question 2", "question 3"],
  "disclaimer": "AI-generated assessment; recruiter judgment required"
}
```

This maps cleanly to Zoho custom fields:
- `AI_Fit_Score` (number)
- `AI_Confidence` (picklist)
- `AI_Summary` (text area)
- `AI_Skills_Matched` (multi-line text or tags)
- `AI_Skills_Missing` (multi-line text)
- `AI_Red_Flags` (text area)
- `AI_Suggested_Questions` (text area)

---

## 6. Zoho-Side Setup Checklist

- [ ] Register OAuth client in Zoho Developer Console (Self Client for testing → Server-based for production)
- [ ] Scopes needed: `ZohoRecruit.modules.candidates.ALL`, `ZohoRecruit.modules.jobopenings.READ`, `ZohoRecruit.modules.attachments.ALL`
- [ ] Create custom fields on the **Candidates** module (listed in §5)
- [ ] (If using webhooks) Create a Workflow Rule: Trigger = "Candidate Created/Edited" → Action = "Outgoing Webhook" → point at your agent's endpoint
- [ ] Confirm your Zoho data center domain (.com / .eu / .in / .com.au) — must match everywhere in API calls

---

## 7. Tech Stack Recommendation

| Layer | Suggested choice | Why |
|---|---|---|
| Language | Python | Best ecosystem for PDF parsing, LLM SDKs, quick iteration |
| Web framework (if webhook) | FastAPI | Lightweight, async, good for a webhook receiver |
| Scheduler (if polling) | APScheduler or a cron job | Simple periodic execution |
| State store | SQLite (prototype) → Postgres (production) | Easy start, easy upgrade path |
| Hosting | A small VM, Render/Railway, or serverless (AWS Lambda + API Gateway) | Needs to be persistent enough to hold refresh tokens & run on schedule/webhook |
| Secrets | Environment variables / a secrets manager | Client ID/secret, refresh token, Claude API key must never be hardcoded |

---

## 8. Security & Compliance Notes

- Resumes = PII. Store the minimum necessary; don't persist raw resume text longer than needed for analysis.
- Encrypt secrets at rest (refresh token, API keys).
- Log access, not content — avoid storing full resume text in plaintext logs.
- Be mindful of regional data laws (GDPR etc.) if candidates are in the EU/UK — check where your hosting and the Claude API processing occurs.
- This system should **assist**, not replace, recruiter judgment — the schema includes an explicit disclaimer field for this reason, and Zoho UI should visibly label these as AI-generated fields.

---

## 9. Rollout Plan (Phased)

**Phase 1 — Manual trigger prototype**
- Script that takes a candidate ID as input, runs the full pipeline, prints the result (no write-back yet)
- Validates: OAuth works, resume parsing works, prompt produces good output

**Phase 2 — Write-back**
- Add custom fields in Zoho
- Add the write-back step
- Test on a handful of real (or test) candidates

**Phase 3 — Automation**
- Add polling or webhook trigger
- Add state store for dedup/audit
- Run continuously on a small handful of job openings

**Phase 4 — Refinement**
- Track actual hiring outcomes vs. AI scores
- Tune the prompt/rubric based on real signal
- Add notifications for high-fit candidates

**Phase 5 (optional) — Multi-tool agent**
- Give the agent the ability to also check a candidate's portfolio/LinkedIn link, cross-reference multiple job openings, or ask clarifying questions before scoring — a more genuinely agentic step beyond a fixed pipeline

---

## 10. Open Design Questions (worth deciding before coding)

- **Trigger method first**: polling (simpler) or webhook (real-time) for v1?
- **Scope**: analyze every candidate automatically, or only on-demand per job opening?
- **Where does it run**: do you have existing hosting (a server, cloud account), or starting from scratch?
- **Volume**: roughly how many candidates/month — affects LLM cost and API credit planning
- **Field visibility**: should AI fields be visible to all recruiters, or restricted by role?
