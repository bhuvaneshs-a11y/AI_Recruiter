from fastapi import APIRouter
from pydantic import BaseModel

from db.writer import get_job_opening_overrides, save_job_opening_override
from zoho_client import get_shared_client

router = APIRouter()

ACTIVE_STATUS = "In-progress"


class JobOpeningOverride(BaseModel):
    title: str = ""
    custom_description: str = ""
    custom_prompt: str = ""


@router.get("/job-openings")
def list_active_job_openings():
    client = get_shared_client()
    jobs = client.get_all_job_openings()
    active = [j for j in jobs if j.get("Job_Opening_Status") == ACTIVE_STATUS]
    overrides = get_job_opening_overrides([j.get("id") for j in active])
    return [
        {
            "id": j.get("id"),
            "title": j.get("Posting_Title") or j.get("Job_Opening_Name"),
            "status": j.get("Job_Opening_Status"),
            "number_of_positions": j.get("Number_of_Positions"),
            "job_type": j.get("Job_Type"),
            "remote": j.get("Remote_Job"),
            "industry": j.get("Industry"),
            "target_date": j.get("Target_Date"),
            "required_skills": j.get("Required_Skills"),
            "description": j.get("Job_Description"),
            "custom_description": overrides.get(j.get("id"), {}).get("custom_description") or "",
            "custom_prompt": overrides.get(j.get("id"), {}).get("custom_prompt") or "",
        }
        for j in active
    ]


@router.put("/job-openings/{zoho_id}/override")
def update_job_opening_override(zoho_id: str, body: JobOpeningOverride):
    """Persist a recruiter-edited JD and/or extra search prompt for a job opening.
    Local-only - never written back to Zoho. Used as an override on top of Zoho's
    Job_Description the next time this job's applicants are analyzed."""
    return save_job_opening_override(
        zoho_id=zoho_id,
        title=body.title or None,
        custom_description=body.custom_description or None,
        custom_prompt=body.custom_prompt or None,
    )
