from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import analyze, job_openings

app = FastAPI(title="AI Recruiter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(job_openings.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
