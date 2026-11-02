import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.careers import _email_address, _guard, _password, _required_line
from app.config import RESUME_DIR
from app.db import (
    create_admin_session,
    delete_admin_session,
    get_admin_by_email,
    get_admin_by_token,
    get_application_resume,
    insert_job,
    job_id_taken,
    list_admin_applications,
    list_all_jobs,
    list_inquiries,
    update_application_status,
    update_job,
)
from app.security import DUMMY_PASSWORD_HASH, new_token, verify_password

router = APIRouter()
STATUSES = ("Applied", "In review", "Interview", "Rejected", "Hired")
RESUME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class LoginIn(BaseModel):
    email: str
    password: str


class StatusIn(BaseModel):
    status: Literal["Applied", "In review", "Interview", "Rejected", "Hired"]


class JobIn(BaseModel):
    title: str
    department: str
    type: str
    location: str
    experience: str
    description: str
    requirements: list[str] = Field(default_factory=list)
    is_open: bool = True


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in again.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return token


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    admin = get_admin_by_token(_token(authorization))
    if admin is None:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return admin


def _clean_job(payload: JobIn) -> dict:
    requirements = [" ".join(item.split()) for item in payload.requirements]
    requirements = [item for item in requirements if item]
    if not requirements:
        raise HTTPException(status_code=400, detail="Add at least one requirement.")
    return {
        "title": _required_line(payload.title, 120, "job title"),
        "department": _required_line(payload.department, 80, "department"),
        "type": _required_line(payload.type, 40, "job type"),
        "location": _required_line(payload.location, 80, "location"),
        "experience": _required_line(payload.experience, 80, "experience"),
        "description": _required_line(payload.description, 500, "description"),
        "requirements": requirements[:12],
        "is_open": payload.is_open,
    }


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return slug or "role"


def _session(admin: dict) -> dict:
    token = new_token()
    create_admin_session(admin["id"], token)
    return {
        "token": token,
        "admin": {"id": admin["id"], "name": admin["name"], "email": admin["email"]},
    }


@router.post("/api/admin/login")
def login(payload: LoginIn, request: Request):
    _guard(request)
    address = _email_address(payload.email)
    _password(payload.password)
    record = get_admin_by_email(address)
    password_ok = record is not None and verify_password(payload.password, record["password_hash"])
    if record is None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
    if not password_ok or record is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return _session(record)


@router.post("/api/admin/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        delete_admin_session(authorization.split(" ", 1)[1].strip())
    return Response(status_code=204)


@router.get("/api/admin/me")
def me(admin: dict = Depends(require_admin)):
    return {"admin": admin}


@router.get("/api/admin/applications")
def applications(_admin: dict = Depends(require_admin)):
    return list_admin_applications()


@router.patch("/api/admin/applications/{application_id}")
def set_status(
    application_id: int,
    payload: StatusIn,
    _admin: dict = Depends(require_admin),
):
    if not update_application_status(application_id, payload.status):
        raise HTTPException(status_code=404, detail="That application was not found.")
    return {"id": application_id, "status": payload.status}


@router.get("/api/admin/applications/{application_id}/resume")
def resume(application_id: int, _admin: dict = Depends(require_admin)):
    record = get_application_resume(application_id)
    if record is None:
        raise HTTPException(status_code=404, detail="This application has no resume.")
    path = (RESUME_DIR / record["stored"]).resolve()
    if not path.is_relative_to(RESUME_DIR.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="This application has no resume.")
    return FileResponse(
        path,
        media_type=RESUME_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=record["name"],
        content_disposition_type="inline",
    )


@router.get("/api/admin/jobs")
def jobs(_admin: dict = Depends(require_admin)):
    return list_all_jobs()


@router.post("/api/admin/jobs", status_code=201)
def create_job(payload: JobIn, _admin: dict = Depends(require_admin)):
    job = _clean_job(payload)
    base = _slug(job["title"])
    job_id = base
    suffix = 2
    while job_id_taken(job_id):
        job_id = f"{base[:36]}-{suffix}"
        suffix += 1
    job["id"] = job_id
    insert_job(job)
    return {"id": job_id}


@router.patch("/api/admin/jobs/{job_id}")
def edit_job(job_id: str, payload: JobIn, _admin: dict = Depends(require_admin)):
    if not job_id_taken(job_id):
        raise HTTPException(status_code=404, detail="That role was not found.")
    job = _clean_job(payload)
    update_job(job_id, job)
    return {"id": job_id}


@router.get("/api/admin/inquiries")
def inquiries(_admin: dict = Depends(require_admin)):
    rows = list_inquiries()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "company": row["company"],
            "service": row["service"],
            "industry": row["industry"],
            "message": row["message"],
            "source": row["source"],
            "createdAt": row["created_at"],
            "emailSent": bool(row["email_sent"]),
        }
        for row in rows
    ]
