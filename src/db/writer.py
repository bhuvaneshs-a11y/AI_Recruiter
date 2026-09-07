import json

from db.models import Application, Candidate, JobOpening, ProjectVerification, ResumeAnalysis
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


def _get_or_create_job_opening(db, job_opening):
    zoho_id = job_opening["id"]
    row = db.query(JobOpening).filter_by(zoho_id=zoho_id).first()
    required_skills = [s.strip() for s in (job_opening.get("Required_Skills") or "").split(",") if s.strip()]
    if row:
        row.title = job_opening.get("Posting_Title") or row.title
        row.description = job_opening.get("Job_Description") or row.description
        row.required_skills = json.dumps(required_skills, ensure_ascii=False)
        row.experience_level = job_opening.get("Work_Experience") or row.experience_level
    else:
        row = JobOpening(
            zoho_id=zoho_id,
            title=job_opening.get("Posting_Title"),
            description=job_opening.get("Job_Description"),
            required_skills=json.dumps(required_skills, ensure_ascii=False),
            experience_level=job_opening.get("Work_Experience"),
        )
        db.add(row)
    db.flush()
    return row


def _get_or_create_application(db, candidate_id, job_opening_id, application_zoho_id):
    application = None
    if application_zoho_id:
        application = db.query(Application).filter_by(zoho_id=application_zoho_id).first()
    if not application:
        application = db.query(Application).filter_by(
            candidate_id=candidate_id, job_opening_id=job_opening_id
        ).first()
    if not application:
        application = Application(
            zoho_id=application_zoho_id,
            candidate_id=candidate_id,
            job_opening_id=job_opening_id,
        )
        db.add(application)
    db.flush()
    return application


def save_analysis(zoho_id, full_name, email, phone, resume_file_path, backend,
                   verified_profile, report, job_opening=None):
    """Persist one analysis run to the DB. Returns the new ResumeAnalysis id.

    job_opening: raw dict from ZohoClient.get_associated_job_openings() data[0],
    or None if the candidate has no associated job opening (or this isn't a Zoho
    candidate at all, e.g. --local mode).
    """
    db = SessionLocal()
    try:
        candidate = _get_or_create_candidate(db, zoho_id, full_name, email, phone, resume_file_path)

        application_id = None
        if job_opening:
            job_row = _get_or_create_job_opening(db, job_opening)
            application = _get_or_create_application(
                db, candidate.id, job_row.id, job_opening.get("$application_id")
            )
            application_id = application.id

        links_by_project = {
            p.get("name"): p.get("links", []) for p in verified_profile.get("projects", [])
        }

        analysis = ResumeAnalysis(
            candidate_id=candidate.id,
            application_id=application_id,
            backend=backend,
            status="completed",
            summary=report.get("summary"),
            credibility_score=report.get("overall_credibility_score"),
            red_flags=json.dumps(report.get("red_flags", []), ensure_ascii=False),
            raw_llm_response=json.dumps({"profile": verified_profile, "report": report}, ensure_ascii=False),
        )
        db.add(analysis)
        db.flush()

        for pv in report.get("project_verification", []):
            db.add(ProjectVerification(
                resume_analysis_id=analysis.id,
                project_name=pv.get("project_name"),
                claim=pv.get("claim"),
                links=json.dumps(links_by_project.get(pv.get("project_name"), []), ensure_ascii=False),
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
