from fastapi import APIRouter

from zoho_client import get_shared_client

router = APIRouter()

ACTIVE_STATUS = "In-progress"


@router.get("/job-openings")
def list_active_job_openings():
    client = get_shared_client()
    jobs = client.get_all_job_openings()
    active = [j for j in jobs if j.get("Job_Opening_Status") == ACTIVE_STATUS]
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
        }
        for j in active
    ]
