import smtplib
from email.message import EmailMessage

from app.config import (
    INQUIRY_TO_EMAIL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USERNAME,
    smtp_ready,
)


class EmailNotConfigured(Exception):
    pass


class EmailDeliveryError(Exception):
    pass


def _header(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def send_inquiry_email(inquiry: dict) -> None:
    if not smtp_ready():
        raise EmailNotConfigured(
            "Email is not configured yet. Your request was saved. "
            "Please also write to Info@jdlumen.ai."
        )

    message = EmailMessage()
    message["Subject"] = _header(
        f"JD Lumen website: call request from {inquiry['name']}"
    )
    message["From"] = _header(SMTP_FROM)
    message["To"] = _header(INQUIRY_TO_EMAIL)
    message["Reply-To"] = _header(inquiry["email"])
    message.set_content(
        "\n".join(
            [
                "A new call request was submitted on the JD Lumen website.",
                "",
                f"Name: {inquiry['name']}",
                f"Email: {inquiry['email']}",
                f"Company: {inquiry['company']}",
                f"Service: {inquiry['service']}",
                f"Industry: {inquiry['industry']}",
                f"Form: {inquiry['source']}",
                "",
                "Project:",
                inquiry["message"],
                "",
                "Reply to this email to respond to the visitor.",
            ]
        )
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.ehlo()
            if SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError(
            "Your request was saved, but the email could not be sent. "
            "Please write to Info@jdlumen.ai."
        ) from error
