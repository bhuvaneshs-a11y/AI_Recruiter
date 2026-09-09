import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
from db.writer import get_job_opening_override, save_analysis, save_failed_analysis
from deep_analysis import (
    generate_deep_analysis,
    generate_deep_analysis_gemini,
    generate_deep_analysis_rule_based,
    verify_profile_links,
)
from resume_analyzer import extract_candidate_profile as extract_candidate_profile_claude
from resume_analyzer_gemini import extract_candidate_profile as extract_candidate_profile_gemini
from resume_parser_rule_based import extract_candidate_profile as extract_candidate_profile_rule_based
from resume_text import extract_links, extract_text
from zoho_client import ZohoClient


def _select_backend():
    if config.ANTHROPIC_API_KEY:
        return "claude"
    if config.GEMINI_API_KEY:
        return "gemini"
    return "rule_based"


EXTRACT_BY_BACKEND = {
    "claude": extract_candidate_profile_claude,
    "gemini": extract_candidate_profile_gemini,
    "rule_based": extract_candidate_profile_rule_based,
}

ANALYZE_BY_BACKEND = {
    "claude": generate_deep_analysis,
    "gemini": generate_deep_analysis_gemini,
    "rule_based": generate_deep_analysis_rule_based,
}


def process_resume(resume_path, zoho_id, full_name=None, email=None, phone=None, job_opening=None):
    """job_opening: raw dict from ZohoClient.get_associated_job_openings() data[0] - kept
    in Zoho's own field names here since save_analysis()/db.writer need those, but
    converted to a clean shape below for the LLM prompt and JSON output."""
    backend = _select_backend()

    job_opening_clean = None
    if job_opening:
        # A recruiter-edited JD/prompt (see save_job_opening_override) takes
        # precedence over Zoho's own Job_Description for the LLM prompt - it's
        # a local-only override, never written back to Zoho.
        override = get_job_opening_override(job_opening.get("id")) if job_opening.get("id") else None
        job_opening_clean = {
            "job_applied_for": job_opening.get("Posting_Title"),
            "job_description": (override and override.get("custom_description"))
                or job_opening.get("Job_Description"),
            "required_skills": job_opening.get("Required_Skills"),
            "experience_level": job_opening.get("Work_Experience"),
        }
        if override and override.get("custom_prompt"):
            job_opening_clean["additional_instructions"] = override["custom_prompt"]

    try:
        text = extract_text(resume_path)
        extra_links = extract_links(resume_path)

        profile = EXTRACT_BY_BACKEND[backend](text, extra_links)
        verified_profile = verify_profile_links(profile)
        report = ANALYZE_BY_BACKEND[backend](verified_profile, job_opening_clean)
    except Exception as e:
        save_failed_analysis(
            zoho_id=zoho_id,
            full_name=full_name,
            email=email,
            phone=phone,
            resume_file_path=resume_path,
            backend=backend,
            error_message=str(e),
        )
        print(f"[{zoho_id}] FAILED: {e}")
        return None

    output = {"profile": verified_profile, "report": report}
    if job_opening_clean:
        output["job_opening"] = job_opening_clean

    out_path = config.ANALYSIS_DIR / f"{str(zoho_id).replace(':', '_')}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    analysis_id = save_analysis(
        zoho_id=zoho_id,
        full_name=full_name or profile.get("full_name"),
        email=email or profile.get("email"),
        phone=phone or profile.get("phone"),
        resume_file_path=resume_path,
        backend=backend,
        verified_profile=verified_profile,
        report=report,
        job_opening=job_opening,
    )

    print(f"[{zoho_id}] credibility={report['overall_credibility_score']} "
          f"db_analysis_id={analysis_id} -> {out_path}")
    return report


def run_local(resume_path):
    path = Path(resume_path)
    process_resume(path, f"local:{path.stem}")


def _find_resume_attachment(attachments):
    # Prefer Zoho's own categorization; fall back to file extension if uncategorized.
    for a in attachments:
        category = a.get("Category") or a.get("$attach_type") or {}
        if category.get("name") == "Resume":
            return a
    return next(
        (a for a in attachments if a.get("File_Name", "").lower().endswith(
            (".pdf", ".docx", ".doc"))),
        None,
    )


def _run_concurrent(items, process_one, on_result=None):
    """Runs process_one(item) for every item using a bounded thread pool
    (config.MAX_CONCURRENT_CANDIDATES workers) instead of one at a time -
    each candidate's pipeline is almost entirely spent waiting on external
    APIs (Zoho, GitHub, the LLM), so running several concurrently cuts total
    wall-clock time roughly proportionally to the worker count.

    on_result(result), if given, is called from this (the calling) thread as
    each result becomes available - as_completed() yields sequentially here,
    so this never runs concurrently with itself and needs no locking of its
    own. process_one returning None means "skip this item, no result".
    """
    results = []
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_CANDIDATES) as executor:
        futures = [executor.submit(process_one, item) for item in items]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            results.append(result)
            if on_result:
                on_result(result)
    return results


def run_zoho(limit=None, client=None, on_result=None, on_total=None):
    """Returns a list of {"zoho_id", "full_name", "report"} - report is None on failure.
    CLI usage ignores the return value; the API layer uses it to show results.
    Pass an existing client (e.g. zoho_client.get_shared_client()) to reuse a
    cached access token instead of refreshing one per call - Zoho separately
    rate-limits the token-refresh endpoint itself.

    on_result(result), if given, is called as each candidate finishes (not in
    Zoho's listing order - completion order) so a caller can report live
    progress instead of waiting for the whole batch. on_total(count), if
    given, is called once candidates are known, before processing starts.
    """
    client = client or ZohoClient()
    candidates = []
    page = 1
    while limit is None or len(candidates) < limit:
        result = client.get_candidates(page=page, fields="id,Full_Name,Email,Phone")
        page_candidates = result.get("data", [])
        if not page_candidates:
            break
        candidates.extend(page_candidates)
        if not result.get("info", {}).get("more_records"):
            break
        page += 1
    if limit is not None:
        candidates = candidates[:limit]

    if on_total:
        on_total(len(candidates))

    def process_one(candidate):
        record_id = candidate["id"]
        attachments = client.list_attachments(record_id).get("data", [])
        resume_attachment = _find_resume_attachment(attachments)
        if not resume_attachment:
            print(f"[{record_id}] no resume attachment found, skipping")
            return None

        job_openings = client.get_associated_job_openings(record_id).get("data", [])
        job_opening = job_openings[0] if job_openings else None

        file_name = resume_attachment["File_Name"]
        save_path = config.RESUMES_DIR / f"{record_id}_{file_name}"
        client.download_attachment(record_id, resume_attachment["id"], save_path)
        report = process_resume(
            save_path,
            record_id,
            full_name=candidate.get("Full_Name"),
            email=candidate.get("Email"),
            phone=candidate.get("Phone"),
            job_opening=job_opening,
        )
        result = {"zoho_id": record_id, "full_name": candidate.get("Full_Name"), "report": report}
        if report is None:
            # process_resume() already logged/saved the real error - this is a
            # genuinely different failure than "no resume attachment" above
            # (e.g. a corrupted file, or an LLM/rate-limit error), and the UI
            # must not conflate the two.
            result["failure_reason"] = "processing_error"
        return result

    results = _run_concurrent(candidates, process_one, on_result)
    results.sort(key=_rank_key, reverse=True)
    return results


def _rank_key(result):
    """Best-first: prefer job-fit score when available (job-scoped analysis),
    fall back to credibility. Failed analyses always sort last."""
    report = result.get("report")
    if not report:
        return -1
    fit = report.get("overall_fit_score")
    return fit if fit is not None else report.get("overall_credibility_score", 0)


def run_zoho_for_job(job_opening_id, limit=None, client=None, on_result=None, on_total=None):
    """Analyze candidates who applied to a specific Job Opening, returned best-first.

    A job opening can have thousands of applicants (seen live: 6,424 for one
    role) - `limit` caps how many are actually processed by the pipeline, not
    how many total applicants exist. The most recent applications are
    processed first (Zoho's default Applications ordering).

    on_result / on_total: see run_zoho() - same live-progress callbacks.
    """
    client = client or ZohoClient()

    job_openings = client.get_all_job_openings()
    job_opening = next((j for j in job_openings if j.get("id") == job_opening_id), None)
    if not job_opening:
        raise ValueError(f"Job opening {job_opening_id} not found")

    applications = client.get_applications_for_job(job_opening_id, job_opening.get("Posting_Title"))
    if limit is not None:
        applications = applications[:limit]

    if on_total:
        on_total(len(applications))

    def process_one(app):
        record_id = app.get("$Candidate_Id")
        if not record_id:
            return None

        full_name = app.get("Full_Name")
        email = app.get("Email")
        phone = app.get("Mobile") or app.get("Phone")

        attachments = client.list_attachments(record_id).get("data", [])
        resume_attachment = _find_resume_attachment(attachments)
        if not resume_attachment:
            return {"zoho_id": record_id, "full_name": full_name, "report": None,
                     "failure_reason": "no_resume_attachment"}

        file_name = resume_attachment["File_Name"]
        save_path = config.RESUMES_DIR / f"{record_id}_{file_name}"
        client.download_attachment(record_id, resume_attachment["id"], save_path)
        report = process_resume(
            save_path, record_id,
            full_name=full_name, email=email, phone=phone,
            job_opening=job_opening,
        )
        result = {"zoho_id": record_id, "full_name": full_name, "report": report}
        if report is None:
            # process_resume() already logged/saved the real error - this is a
            # genuinely different failure than "no resume attachment" above
            # (e.g. a corrupted file, or an LLM/rate-limit error), and the UI
            # must not conflate the two.
            result["failure_reason"] = "processing_error"
        return result

    results = _run_concurrent(applications, process_one, on_result)
    results.sort(key=_rank_key, reverse=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume extraction and deep analysis pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--local", metavar="RESUME_PATH", help="Analyze a single local resume file")
    group.add_argument("--zoho", action="store_true", help="Pull resumes from Zoho Recruit and analyze all")
    parser.add_argument("--limit", type=int, default=None,
                         help="Max number of candidates to process in --zoho mode (default: no limit)")
    args = parser.parse_args()

    if args.local:
        run_local(args.local)
    else:
        run_zoho(limit=args.limit)
