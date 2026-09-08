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
