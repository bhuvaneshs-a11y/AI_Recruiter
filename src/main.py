import argparse
import json
from pathlib import Path

import config
from db.writer import save_analysis, save_failed_analysis
from deep_analysis import (
    generate_deep_analysis,
    generate_deep_analysis_rule_based,
    verify_profile_links,
)
from resume_analyzer import extract_candidate_profile as extract_candidate_profile_claude
from resume_parser_rule_based import extract_candidate_profile as extract_candidate_profile_rule_based
from resume_text import extract_links, extract_text
from zoho_client import ZohoClient


def process_resume(resume_path, zoho_id, full_name=None, email=None, phone=None):
    backend = "claude" if config.ANTHROPIC_API_KEY else "rule_based"

    try:
        text = extract_text(resume_path)
        extra_links = extract_links(resume_path)

        if backend == "claude":
            profile = extract_candidate_profile_claude(text, extra_links)
        else:
            profile = extract_candidate_profile_rule_based(text, extra_links)

        verified_profile = verify_profile_links(profile)

        if backend == "claude":
            report = generate_deep_analysis(verified_profile)
        else:
            report = generate_deep_analysis_rule_based(verified_profile)
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

    out_path = config.ANALYSIS_DIR / f"{str(zoho_id).replace(':', '_')}.json"
    out_path.write_text(json.dumps({
        "profile": verified_profile,
        "report": report,
    }, indent=2), encoding="utf-8")

    analysis_id = save_analysis(
        zoho_id=zoho_id,
        full_name=full_name or profile.get("full_name"),
        email=email or profile.get("email"),
        phone=phone or profile.get("phone"),
        resume_file_path=resume_path,
        backend=backend,
        verified_profile=verified_profile,
        report=report,
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


def run_zoho(limit=None):
    client = ZohoClient()
    page = 1
    processed = 0
    while limit is None or processed < limit:
        result = client.get_candidates(page=page, fields="id,Full_Name,Email,Phone")
        candidates = result.get("data", [])
        if not candidates:
            break

        for candidate in candidates:
            if limit is not None and processed >= limit:
                break

            record_id = candidate["id"]
            attachments = client.list_attachments(record_id).get("data", [])
            resume_attachment = _find_resume_attachment(attachments)
            if not resume_attachment:
                print(f"[{record_id}] no resume attachment found, skipping")
                continue

            file_name = resume_attachment["File_Name"]
            save_path = config.RESUMES_DIR / f"{record_id}_{file_name}"
            client.download_attachment(record_id, resume_attachment["id"], save_path)
            process_resume(
                save_path,
                record_id,
                full_name=candidate.get("Full_Name"),
                email=candidate.get("Email"),
                phone=candidate.get("Phone"),
            )
            processed += 1

        if not result.get("info", {}).get("more_records"):
            break
        page += 1


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
