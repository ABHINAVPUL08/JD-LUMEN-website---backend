import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "inquiries.db"
RESUME_DIR = DATA_DIR / "resumes"

load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


INQUIRY_TO_EMAIL = _env("INQUIRY_TO_EMAIL", "Info@jdlumen.ai")
SMTP_FROM = _env("SMTP_FROM", INQUIRY_TO_EMAIL)
SMTP_USERNAME = _env("SMTP_USERNAME", SMTP_FROM)
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587") or "587")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_USE_TLS = _env("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}

ADMIN_EMAIL = _env("ADMIN_EMAIL").lower()
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
ADMIN_NAME = _env("ADMIN_NAME", "JD Lumen Team")

JUNO_PROVIDER = _env("JUNO_PROVIDER").lower()
JUNO_API_KEY = _env("JUNO_API_KEY")
JUNO_MODEL = _env("JUNO_MODEL")

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def smtp_ready() -> bool:
    return bool(SMTP_HOST and SMTP_PASSWORD and INQUIRY_TO_EMAIL and SMTP_FROM)


def juno_ready() -> bool:
    return JUNO_PROVIDER in {"openai", "gemini"} and bool(JUNO_API_KEY)
