import json

import anthropic

import config
from link_verifier import verify_link

MODEL = "claude-opus-5"

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_name": {"type": "string"},
        "summary": {"type": "string"},
        "skills_assessment": {"type": "string"},
        "project_verification": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"},
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["verified", "partially_verified", "unverified", "suspicious"],
                    },
                },
                "required": ["project_name", "claim", "evidence", "verdict"],
                "additionalProperties": False,
            },
        },
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "overall_credibility_score": {"type": "integer"},
        "recommendation": {"type": "string"},
    },
    "required": [
        "candidate_name", "summary", "skills_assessment",
        "project_verification", "red_flags",
        "overall_credibility_score", "recommendation",
    ],
    "additionalProperties": False,
}


def verify_profile_links(profile):
    candidate_name = profile.get("full_name", "")
    verified_projects = []
    for project in profile.get("projects", []):
        links = [verify_link(link, candidate_name) for link in project.get("links", [])]
        verified_projects.append({**project, "link_verification": links})

    other_link_verification = [
        verify_link(link, candidate_name) for link in profile.get("other_links", [])
    ]

    return {
        **profile,
        "projects": verified_projects,
        "other_link_verification": other_link_verification,
    }


def generate_deep_analysis(verified_profile):
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": REPORT_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": (
                "You are reviewing a candidate profile extracted from a resume, where "
                "every project link has already been independently verified against "
                "GitHub/portfolio/LinkedIn (see link_verification data per project). "
                "Cross-check each project's claimed description against the verification "
                "evidence (e.g. does the GitHub repo actually exist, is the candidate a "
                "real contributor with meaningful commit/PR activity, or is it an empty "
                "fork with no real work). Flag any claim not supported by evidence as "
                "unverified or suspicious. Give an overall credibility score 0-100 and a "
                "hiring recommendation.\n\nCandidate profile with verification data:\n\n"
                + json.dumps(verified_profile, indent=2)
            ),
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _project_verdict(project):
    verifications = project.get("link_verification", [])
    if not verifications:
        return "unverified", "No links provided for this project."

    notes = []
    for v in verifications:
        if v.get("type") == "github":
            if not v.get("exists"):
                notes.append(f"GitHub link {v['url']} does not exist or is unreachable.")
            elif v.get("owner_is_contributor") and (v.get("owner_commit_count_approx") or 0) > 0 and not v.get("is_fork"):
                notes.append(
                    f"GitHub repo {v['url']} exists, candidate is a contributor with "
                    f"~{v.get('owner_commit_count_approx')} commits and {v.get('owner_pr_count') or 0} PRs."
                )
                return "verified", " ".join(notes)
            elif v.get("is_fork"):
                notes.append(f"GitHub repo {v['url']} is a fork, not original work.")
            elif v.get("owner_is_contributor") is False:
                notes.append(f"Candidate does not appear as a contributor on {v['url']}.")
            else:
                notes.append(f"GitHub repo {v['url']} exists but activity could not be confirmed.")
        elif v.get("type") == "portfolio":
            if v.get("reachable"):
                notes.append(f"Portfolio link {v['url']} is reachable (status {v.get('status_code')}).")
            else:
                notes.append(f"Portfolio link {v['url']} is unreachable.")
        elif v.get("type") == "linkedin":
            notes.append(f"LinkedIn link {v['url']}: reachability only, no content verification available.")

    if any("does not exist" in n or "unreachable" in n for n in notes):
        return "suspicious", " ".join(notes)
    if any("reachable" in n or "exists but activity" in n for n in notes):
        return "partially_verified", " ".join(notes)
    return "unverified", " ".join(notes)


def generate_deep_analysis_rule_based(verified_profile):
    """Deterministic, non-LLM report generator — used when no ANTHROPIC_API_KEY is configured."""
    project_verification = []
    score = 50
    red_flags = []

    for project in verified_profile.get("projects", []):
        verdict, evidence = _project_verdict(project)
        project_verification.append({
            "project_name": project.get("name", ""),
            "claim": project.get("description", ""),
            "evidence": evidence,
            "verdict": verdict,
        })
        if verdict == "verified":
            score += 10
        elif verdict == "partially_verified":
            score += 3
        elif verdict == "suspicious":
            score -= 15
            red_flags.append(f"Project '{project.get('name', '')}' looks suspicious: {evidence}")
        elif verdict == "unverified":
            score -= 5

    for link in verified_profile.get("other_link_verification", []):
        if link.get("type") in ("portfolio", "github") and link.get("reachable") is False:
            red_flags.append(f"Unreachable link: {link.get('url')}")
        if link.get("type") == "github" and link.get("exists") is False:
            red_flags.append(f"GitHub profile/repo does not exist: {link.get('url')}")

    score = max(0, min(100, score))

    if score >= 75:
        recommendation = "Claims are well-supported by verified evidence. Proceed with confidence."
    elif score >= 50:
        recommendation = "Some claims verified, others could not be confirmed. Ask candidate to clarify unverified projects in interview."
    else:
        recommendation = "Multiple claims are unverified or suspicious. Recommend closer scrutiny before proceeding."

    return {
        "candidate_name": verified_profile.get("full_name", ""),
        "summary": "Auto-generated summary (rule-based mode, no ANTHROPIC_API_KEY configured). "
                    "Set ANTHROPIC_API_KEY in .env for a full narrative analysis.",
        "skills_assessment": (
            "Skills listed: " + ", ".join(verified_profile.get("skills", []))
            if verified_profile.get("skills")
            else "No skills section detected."
        ),
        "project_verification": project_verification,
        "red_flags": red_flags,
        "overall_credibility_score": score,
        "recommendation": recommendation,
    }
