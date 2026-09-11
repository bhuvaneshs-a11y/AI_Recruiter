from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from analysis_jobs import get_job, report_result, report_total, set_results, start_job
from main import run_zoho, run_zoho_for_job
from zoho_client import get_shared_client

router = APIRouter()


class AnalyzeRequest(BaseModel):
    limit: int = 5
    job_opening_id: Optional[str] = None
    refresh_snapshot: bool = False


@router.post("/analyze")
def trigger_analysis(body: AnalyzeRequest):
    """Starts analysis in a background thread and returns immediately with a
    job_id - poll GET /analyze/{job_id} for progress and results instead of
    waiting on this request. Candidates are processed concurrently, not one
    at a time (see main._run_concurrent), but each one still involves real
    LLM + GitHub/portfolio calls, so the batch as a whole can still take a
    while.

    If job_opening_id is given, only that job's actual applicants are
    analyzed (best-first by job-fit score once done) - a job can have
    thousands of applicants, so `limit` controls how many are actually
    processed, not how many exist. Without it, falls back to the next N
    candidates in Zoho's default order (no job context, ranked by
    credibility only).

    The applicant list for a job is a frozen snapshot after the first search
    (see main.run_zoho_for_job) - repeated searches return the same
    candidates instead of shifting as new applications arrive, and are much
    faster since they skip re-querying Zoho. Pass refresh_snapshot=true to
    explicitly discard the old snapshot and pull a fresh one from Zoho.

    Note: a bad job_opening_id no longer raises synchronously here - that
    lookup now happens inside the background job, so it surfaces as
    status="error" on the first poll instead of an immediate 404.
    """
    client = get_shared_client()

    def target(job_id):
        on_result = lambda r: report_result(job_id, r)
        on_total = lambda t: report_total(job_id, t)
        if body.job_opening_id:
            final_results = run_zoho_for_job(
                body.job_opening_id, limit=body.limit, client=client,
                on_result=on_result, on_total=on_total,
                refresh_snapshot=body.refresh_snapshot,
            )
        else:
            final_results = run_zoho(limit=body.limit, client=client, on_result=on_result, on_total=on_total)
        # run_zoho()/run_zoho_for_job() sort their return value best-first, but
        # on_result() above only ever appended in completion order - overwrite
        # with the final sorted order now that the whole batch is done.
        set_results(job_id, final_results)

    job_id = start_job(target)
    return {"job_id": job_id}


@router.get("/analyze/{job_id}")
def get_analysis_status(job_id: str):
    """Poll target for the job started by POST /analyze. status is "running"
    (results filled in so far, in completion order), "done" (results final
    and best-fit-sorted), or "error" (error holds the message)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
