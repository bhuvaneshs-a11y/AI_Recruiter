import json

from sqlalchemy.exc import IntegrityError

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
    """Upserts a JobOpening row using the caller's session, returns it.

    Candidates now process concurrently (see main._run_concurrent), so
    multiple candidates applied to the SAME job can reach this within
    moments of each other, each in its own save_analysis() call with its own
    session. If two of those sessions both see no existing row for a
    brand-new zoho_id and both try to insert, the second violates the unique
    constraint on zoho_id - confirmed live on the deployed Postgres backend
    (SQLite's single-writer-per-file lock had been masking this race
    locally; Postgres genuinely allows two sessions to race like this).

    The insert runs inside a SAVEPOINT (db.begin_nested()) so a failed
    attempt only rolls back this insert, not whatever else the caller's
    session already flushed earlier in the same transaction (e.g. the
    candidate row) - a plain db.rollback() would have discarded that too.
    A separate session/connection was tried first but self-deadlocks on
    SQLite (the caller's still-open transaction already holds the file's
    only write lock), so this stays on the caller's own session instead.
    """
    zoho_id = job_opening["id"]
    required_skills = [s.strip() for s in (job_opening.get("Required_Skills") or "").split(",") if s.strip()]
    row = db.query(JobOpening).filter_by(zoho_id=zoho_id).first()
    if row:
        row.title = job_opening.get("Posting_Title") or row.title
        row.description = job_opening.get("Job_Description") or row.description
        row.required_skills = json.dumps(required_skills, ensure_ascii=False)
        row.experience_level = job_opening.get("Work_Experience") or row.experience_level
        db.flush()
        return row

    try:
        with db.begin_nested():
            row = JobOpening(
                zoho_id=zoho_id,
                title=job_opening.get("Posting_Title"),
                description=job_opening.get("Job_Description"),
                required_skills=json.dumps(required_skills, ensure_ascii=False),
                experience_level=job_opening.get("Work_Experience"),
            )
            db.add(row)
            db.flush()
    except IntegrityError:
        # Lost the race - another session's insert for this zoho_id already
        # committed (that's the only way our unique constraint check could
        # have failed), so it's guaranteed visible now.
        row = db.query(JobOpening).filter_by(zoho_id=zoho_id).first()
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
            overall_fit_score=report.get("overall_fit_score"),
            confidence=report.get("confidence"),
            skills_matched=json.dumps(report.get("skills_matched", []), ensure_ascii=False)
                if "skills_matched" in report else None,
            skills_missing=json.dumps(report.get("skills_missing", []), ensure_ascii=False)
                if "skills_missing" in report else None,
            experience_assessment=report.get("experience_assessment"),
            career_trajectory_notes=report.get("career_trajectory_notes"),
            suggested_interview_questions=json.dumps(report.get("suggested_interview_questions", []), ensure_ascii=False)
                if "suggested_interview_questions" in report else None,
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


def get_job_opening_overrides(zoho_ids):
    """Bulk-fetch persisted JD/prompt overrides for a set of Zoho job opening ids.
    Returns {zoho_id: {"custom_description": ..., "custom_prompt": ...}} - job
    openings with no override row yet (or no override values set) are simply
    absent from the dict."""
    db = SessionLocal()
    try:
        rows = db.query(JobOpening).filter(JobOpening.zoho_id.in_(zoho_ids)).all()
        return {
            row.zoho_id: {"custom_description": row.custom_description, "custom_prompt": row.custom_prompt}
            for row in rows
            if row.custom_description or row.custom_prompt
        }
    finally:
        db.close()


def get_job_opening_override(zoho_id):
    overrides = get_job_opening_overrides([zoho_id])
    return overrides.get(zoho_id)


def save_job_opening_override(zoho_id, title, custom_description, custom_prompt):
    """Persist a recruiter's edited JD / extra search prompt for a job opening,
    upserting the JobOpening row by zoho_id since analysis may not have run for
    it yet (title is stored so the row is identifiable even before that)."""
    db = SessionLocal()
    try:
        row = db.query(JobOpening).filter_by(zoho_id=zoho_id).first()
        if row:
            row.custom_description = custom_description
            row.custom_prompt = custom_prompt
            row.title = row.title or title
        else:
            row = JobOpening(
                zoho_id=zoho_id,
                title=title,
                custom_description=custom_description,
                custom_prompt=custom_prompt,
            )
            db.add(row)
        db.commit()
        return {"custom_description": row.custom_description, "custom_prompt": row.custom_prompt}
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
