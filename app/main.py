import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.admin import router as admin_router
from app.careers import router as careers_router
from app.config import (
    ADMIN_EMAIL,
    ADMIN_NAME,
    ADMIN_PASSWORD,
    ALLOWED_ORIGINS,
    INQUIRY_TO_EMAIL,
    juno_ready,
    smtp_ready,
)
from app.db import admin_exists, init_db, insert_admin, insert_inquiry, mark_email_sent
from app.juno import router as juno_router
from app.security import hash_password
from app.limit import client_ip, too_many
from app.mailer import EmailDeliveryError, EmailNotConfigured, send_inquiry_email

logger = logging.getLogger("jdlumen")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if ADMIN_EMAIL and ADMIN_PASSWORD and not admin_exists(ADMIN_EMAIL):
        insert_admin(ADMIN_NAME or "JD Lumen Team", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD))
        logger.info("Created the team admin %s", ADMIN_EMAIL)
    elif not ADMIN_EMAIL or not ADMIN_PASSWORD:
        logger.warning("Team admin is not configured. Set ADMIN_EMAIL and ADMIN_PASSWORD in backend/.env")
    if smtp_ready():
        logger.info("Inquiry email is configured for %s", INQUIRY_TO_EMAIL)
    else:
        logger.warning(
            "Inquiry email is not configured. Set SMTP_HOST and SMTP_PASSWORD in backend/.env"
        )
    yield


app = FastAPI(title="JD Lumen API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(careers_router)
app.include_router(admin_router)
app.include_router(juno_router)


class InquiryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    company: str = Field(min_length=1, max_length=160)
    service: str = Field(min_length=1, max_length=150)
    industry: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=4000)
    source: Literal["free-call", "project"] = "free-call"

    @field_validator("name", "company", "service", "industry", "source")
    @classmethod
    def single_line(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("This field is required")
        return cleaned

    @field_validator("message")
    @classmethod
    def keep_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field is required")
        return cleaned


class InquiryOut(BaseModel):
    id: int
    email_sent: bool


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "inbox": INQUIRY_TO_EMAIL,
        "email_configured": smtp_ready(),
        "juno_ready": juno_ready(),
    }


@app.post("/api/inquiries", response_model=InquiryOut, status_code=201)
def create_inquiry(payload: InquiryIn, request: Request):
    if too_many(client_ip(request), "inquiries"):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a few minutes and try again.",
        )

    inquiry = payload.model_dump()
    inquiry["email"] = str(payload.email)
    inquiry_id = insert_inquiry(inquiry)

    try:
        send_inquiry_email(inquiry)
    except EmailNotConfigured as error:
        logger.warning("Inquiry %s saved without email: SMTP is not configured", inquiry_id)
        raise HTTPException(status_code=503, detail=str(error)) from error
    except EmailDeliveryError as error:
        logger.exception("Inquiry %s saved but email delivery failed", inquiry_id)
        raise HTTPException(status_code=502, detail=str(error)) from error

    mark_email_sent(inquiry_id)
    return InquiryOut(id=inquiry_id, email_sent=True)
