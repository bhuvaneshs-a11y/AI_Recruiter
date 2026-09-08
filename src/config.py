import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Overridable so a deployment can point this at a mounted persistent disk
# (e.g. Render) instead of the app's own ephemeral filesystem, which gets
# wiped on every redeploy/restart.
DATA_DIR = Path(os.getenv("DATA_DIR") or (ROOT_DIR / "data"))
RESUMES_DIR = DATA_DIR / "resumes"
ANALYSIS_DIR = DATA_DIR / "analysis"
RESUMES_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# Origins allowed to call the API (CORSMiddleware in api/app.py). Comma-separated
# for multiple, e.g. "https://myapp.onrender.com,http://localhost:5173".
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://recruit.zoho.com")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'ai_recruiter.db').as_posix()}"
# Render (and Heroku-style hosts before it) hand out connection strings as
# postgres://, a scheme SQLAlchemy 1.4+ rejects outright - it wants
# postgresql:// instead. Normalizing here means the env var can be pasted in
# verbatim from the host's dashboard with no manual editing.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# How many candidates' pipelines (resume download -> LLM extraction -> link
# verification -> LLM report) run at once in --zoho/API analysis. Each is
# mostly spent waiting on external APIs (Zoho, GitHub, the LLM provider), so
# running several concurrently cuts total wall-clock time substantially -
# capped rather than unbounded to avoid bursting past those providers' own
# rate limits.
MAX_CONCURRENT_CANDIDATES = int(os.getenv("MAX_CONCURRENT_CANDIDATES", "4"))
