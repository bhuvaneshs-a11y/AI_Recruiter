from fastapi import APIRouter
from pydantic import BaseModel

from main import run_zoho

router = APIRouter()


class AnalyzeRequest(BaseModel):
    limit: int = 1


@router.post("/analyze")
def trigger_analysis(body: AnalyzeRequest):
    """Synchronous - blocks until all requested candidates are processed (each one
    involves LLM + GitHub/portfolio calls, so this can take anywhere from a few
    seconds to a minute or more per candidate). No background job/progress
    reporting in this first version."""
    results = run_zoho(limit=body.limit)
    return {"processed": len(results), "results": results}
