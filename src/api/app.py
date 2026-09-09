from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes import analyze, job_openings

app = FastAPI(title="AI Recruiter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(job_openings.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")


@app.get("/api/health")
def health():
    """No DB/Zoho calls - just proves the process is alive and responding.
    Meant for an external uptime pinger to hit every ~10 min on free-tier
    hosts (e.g. Render) that spin the service down after 15 min idle, so it
    never goes idle long enough to spin down in the first place."""
    return {"status": "ok"}
