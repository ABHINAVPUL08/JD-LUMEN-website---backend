import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, TypeAdapter, ValidationError

from app.config import RESUME_DIR
from app.db import (
    create_session,
    delete_session,
    get_candidate_by_email,
    get_candidate_by_token,
    get_candidate_record,
    get_job,
    insert_application,
    insert_candidate,
    list_applications,
    list_jobs,
    set_candidate_resume,
)
from app.limit import client_ip, too_many
from app.security import DUMMY_PASSWORD_HASH, hash_password, new_token, verify_password

router = APIRouter()
MAX_RESUME_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".doc", ".docx"}
_email = TypeAdapter(EmailStr)


class LoginIn(BaseModel):
    email: str
    password: str


def _guard(request: Request) -> None:
    if too_many(client_ip(request), "auth"):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a few minutes and try again.",
        )


def _email_address(value: str) -> str:
    try:
        parsed = _email.validate_python(value.strip())
    except ValidationError as error:
        raise HTTPException(status_code=400, detail="Enter a valid email address.") from error
    return str(parsed).lower()


def _required_line(value: str, limit: int, label: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"Enter your {label}.")
    if len(cleaned) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"{label.capitalize()} must be {limit} characters or fewer.",
        )
    return cleaned


def _optional_line(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _password(value: str) -> str:
    if len(value) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters.",
        )
    if len(value) > 128:
        raise HTTPException(
            status_code=400,
            detail="Password must be 128 characters or fewer.",
        )
    return value


def _read_resume(upload: UploadFile | None) -> tuple[str, bytes] | None:
    if upload is None or not (upload.filename or "").strip():
        return None
    original = Path(upload.filename).name
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Resume must be a PDF, DOC, or DOCX file.",
        )
    content = upload.file.read(MAX_RESUME_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The resume file is empty.")
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="Resume must be 5 MB or smaller.")
    if len(original) > 180:
        original = f"{original[:170]}{suffix}"
    return original, content


def _store_resume(candidate_id: int, original: str, content: bytes) -> str:
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(original).suffix.lower()
    stored = f"{candidate_id}-{secrets.token_hex(8)}{suffix}"
    (RESUME_DIR / stored).write_bytes(content)
    return stored


def _token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in again.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return token


def require_candidate(authorization: str | None = Header(default=None)) -> dict:
    candidate = get_candidate_by_token(_token_from_header(authorization))
    if candidate is None:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return candidate


def _session(candidate: dict) -> dict:
    token = new_token()
    create_session(candidate["id"], token)
    return {"token": token, "candidate": candidate}


@router.get("/api/jobs")
def jobs():
    return list_jobs()


@router.post("/api/auth/register", status_code=201)
def register(
    request: Request,
    name: str = Form(),
    email: str = Form(),
    password: str = Form(),
    phone: str = Form(default=""),
    experience: str = Form(default=""),
    skills: str = Form(default=""),
    resume: UploadFile | None = File(default=None),
):
    _guard(request)
    resume_data = _read_resume(resume)
    address = _email_address(email)
    if get_candidate_by_email(address) is not None:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Log in instead.",
        )

    try:
        candidate = insert_candidate(
            {
                "name": _required_line(name, 120, "name"),
                "email": address,
                "phone": _optional_line(phone, 30),
                "experience": _optional_line(experience, 80),
                "skills": _optional_line(skills, 300),
                "password_hash": hash_password(_password(password)),
            }
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Log in instead.",
        ) from error

    if resume_data is not None:
        original, content = resume_data
        stored = _store_resume(candidate["id"], original, content)
        set_candidate_resume(candidate["id"], original, stored)
        candidate["resumeName"] = original

    return _session(candidate)


@router.post("/api/auth/login")
def login(payload: LoginIn, request: Request):
    _guard(request)
    address = _email_address(payload.email)
    record = get_candidate_by_email(address)
    password_ok = record is not None and verify_password(payload.password, record["password_hash"])
    if record is None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
    if not password_ok or record is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    candidate = {
        "id": record["id"],
        "name": record["name"],
        "email": record["email"],
        "phone": record["phone"],
        "experience": record["experience"],
        "skills": record["skills"],
        "resumeName": record["resume_original"] or "",
    }
    return _session(candidate)


@router.post("/api/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        delete_session(authorization.split(" ", 1)[1].strip())
    return Response(status_code=204)


@router.get("/api/auth/me")
def me(candidate: dict = Depends(require_candidate)):
    return {
        "candidate": candidate,
        "applications": list_applications(candidate["id"]),
    }


@router.post("/api/applications", status_code=201)
def apply(
    request: Request,
    job_id: str = Form(),
    resume: UploadFile | None = File(default=None),
    candidate: dict = Depends(require_candidate),
):
    _guard(request)
    role = get_job(job_id.strip())
    if role is None:
        raise HTTPException(status_code=404, detail="That role is no longer open.")

    record = get_candidate_record(candidate["id"])
    if record is None:
        raise HTTPException(status_code=401, detail="Please log in again.")

    resume_original = record["resume_original"]
    resume_stored = record["resume_stored"]
    uploaded = _read_resume(resume)
    if uploaded is not None:
        resume_original, content = uploaded
        resume_stored = _store_resume(candidate["id"], resume_original, content)
        set_candidate_resume(candidate["id"], resume_original, resume_stored)

    try:
        return insert_application(
            candidate["id"],
            role["id"],
            resume_original,
            resume_stored,
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="You have already applied for this role.",
        ) from error
