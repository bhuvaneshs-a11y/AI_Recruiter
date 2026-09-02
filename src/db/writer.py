import json

from db.models import Candidate, ProjectVerification, ResumeAnalysis
from db.session import SessionLocal


def _get_or_create_candidate(db, zoho_id, full_name, email, phone, resume_file_path):
    candidate = db.query(Candidate).filter_by(zoho_id=zoho_id).first()
    if candidate:
        candidate.full_name = full_name or candidate.full_name
        candidate.email = email or candidate.email
        candidate.phone = phone or candidate.phone
        candidate.resume_file_path = str(resume_file_path)
    else:
        candidate = Candidate(
            zoho_id=zoho_id,
            full_name=full_name,
            email=email,
            phone=phone,
            resume_file_path=str(resume_file_path),
        )
        db.add(candidate)
    db.flush()
    return candidate


def save_analysis(zoho_id, full_name, email, phone, resume_file_path, backend, verified_profile, report):
    """Persist one analysis run to the DB. Returns the new ResumeAnalysis id."""
    db = SessionLocal()
    try:
        candidate = _get_or_create_candidate(db, zoho_id, full_name, email, phone, resume_file_path)

        links_by_project = {
            p.get("name"): p.get("links", []) for p in verified_profile.get("projects", [])
        }

        analysis = ResumeAnalysis(
            candidate_id=candidate.id,
            backend=backend,
            status="completed",
            summary=report.get("summary"),
            credibility_score=report.get("overall_credibility_score"),
            red_flags=json.dumps(report.get("red_flags", [])),
            raw_llm_response=json.dumps({"profile": verified_profile, "report": report}),
        )
        db.add(analysis)
        db.flush()

        for pv in report.get("project_verification", []):
            db.add(ProjectVerification(
                resume_analysis_id=analysis.id,
                project_name=pv.get("project_name"),
                claim=pv.get("claim"),
                links=json.dumps(links_by_project.get(pv.get("project_name"), [])),
                verdict=pv.get("verdict"),
                evidence=pv.get("evidence"),
            ))

        db.commit()
        return analysis.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_failed_analysis(zoho_id, full_name, email, phone, resume_file_path, backend, error_message):
    """Persist a failed analysis attempt so it shows up in history instead of silently vanishing."""
    db = SessionLocal()
    try:
        candidate = _get_or_create_candidate(db, zoho_id, full_name, email, phone, resume_file_path)
        analysis = ResumeAnalysis(
            candidate_id=candidate.id,
            backend=backend,
            status="failed",
            error_message=error_message,
        )
        db.add(analysis)
        db.commit()
        return analysis.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
