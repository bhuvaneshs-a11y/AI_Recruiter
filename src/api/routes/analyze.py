from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from main import run_zoho, run_zoho_for_job
from zoho_client import get_shared_client

router = APIRouter()


class AnalyzeRequest(BaseModel):
    limit: int = 5
    job_opening_id: Optional[str] = None


@router.post("/analyze")
def trigger_analysis(body: AnalyzeRequest):
    """Synchronous - blocks until all requested candidates are processed (each one
    involves LLM + GitHub/portfolio calls, so this can take anywhere from a few
    seconds to a minute or more per candidate). No background job/progress
    reporting in this first version.

    If job_opening_id is given, only that job's actual applicants are analyzed
    (best-first by job-fit score) - a job can have thousands of applicants, so
    `limit` controls how many are actually processed, not how many exist.
    Without it, falls back to the next N candidates in Zoho's default order
    (no job context, ranked by credibility only)."""
    client = get_shared_client()
    if body.job_opening_id:
        try:
            results = run_zoho_for_job(body.job_opening_id, limit=body.limit, client=client)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    else:
        results = run_zoho(limit=body.limit, client=client)
    return {"processed": len(results), "results": results}
