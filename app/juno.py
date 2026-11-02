import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError

from app.config import JUNO_API_KEY, JUNO_MODEL, JUNO_PROVIDER, juno_ready
from app.db import connect, insert_inquiry, list_jobs, mark_email_sent
from app.limit import client_ip, too_many
from app.mailer import EmailDeliveryError, EmailNotConfigured, send_inquiry_email

logger = logging.getLogger("jdlumen")
router = APIRouter()

COMPANY_FACTS = """
JD Lumen is an AI automation and custom software company.
Office: 9th Floor, Tower D, Unitech Cyber Park, Sector-39, Gurugram, Haryana 122001, India.
Email: Info@jdlumen.ai. Phone: 7988077310.
The company is JDLUMEN LLP. Founder: Arjita Singh.

Services, and only these:
- AI Chatbot Development: website and WhatsApp chatbots for questions, leads, and booking.
- Workflow Automation: intake, follow-ups, approvals, and internal operations.
- Document Automation: forms and documents with OCR, PDF generation, and data extraction.
- Dashboards & Analytics: live views of operations, bookings, leads, and performance.
- Custom Software Development: web apps, client portals, internal tools, and product MVPs.
- AI Calling Agents: voice AI for intake, follow-ups, and customer conversations.

Industries, and only these:
- Healthcare: booking flows, triage chatbots, scheduling.
- Real Estate: lead capture, property questions, viewing schedules.
- Hotels & Hospitality: guest booking assistants and operations dashboards.
- Education: student support chatbots and admin workflows.
- Legal Firms: intake forms, voice agents, document workflows.
- E-Commerce: order status, refunds, and inventory updates.

Projects on the website, and only these. Also accept the shorter name in brackets:
- Law Office: legal form digitization and intake. An AI assistant qualifies the client, collects the forms, updates the CRM, and prepares the case record. The site shows this as 92% faster client onboarding.
- We Nourish: a WhatsApp chatbot and booking system for a nutrition business. It handles meal guidance, consultations, calendar booking, and the client record. The site shows this as a 2.5x increase in bookings.
- AI Customer Support Agent (AI Support Agent): 24/7 website and WhatsApp support. It answers common questions and creates a ticket when a person should take over. The site shows this as 70% faster customer response time.
- AI Sales Automation System (AI Sales Automation): captures a lead, qualifies it, sends follow-up email and WhatsApp messages, and syncs the CRM. The site shows this as a 3x increase in qualified leads.
- AI Invoice & Document Processing (AI Document Processor): reads invoices with OCR, checks the extracted data, and builds a report that can be exported. The site shows this as a 90% reduction in processing time.
- AI Voice Calling Agent: makes outbound calls for reminders, lead qualification, and follow-ups, then writes a call summary. The site shows this as 60% more successful follow-ups.

A free strategy call is included with every inquiry. There is no commitment. The team replies within 24 hours. The call is for a practical plan, not a hard sell.

After a visitor confirms a chat booking:
- The request is emailed to Info@jdlumen.ai and saved for the team. The visitor does not get an automatic confirmation email.
- The preferred time is only a preference until the team confirms it.
- The site has no privacy-policy page. Do not invent one. Contact details are used to handle that enquiry: they are saved and emailed to the JD Lumen team. Do not claim they are never shared, encrypted, or covered by a policy that is not published.

Do not quote prices, timelines, client names, or integrations that are not listed above. The only results you may mention are the ones listed under Projects. WhatsApp and website chatbots are real services. Do not promise a Shopify app, an abandoned-cart feature, or any other product that is not listed. A store can still use the chatbot and workflow services, and the team can say on the call whether a specific connection is possible.
""".strip()

JUNO_INSTRUCTIONS = """
You are Juno, the assistant on the JD Lumen website.

How you speak:
- Sound like a calm, capable teammate. Warm, specific, and brief.
- Write two to four short paragraphs in plain text. No bullet lists, no markdown, no emojis. The only exception is the booking summary, which uses one label per line.
- Use the visitor's own words. Remember their business, their concern, and what you already told them. Do not repeat the same pitch.
- Answer the latest message first. A question, an objection, or a refusal is never a cue to collect contact details.

What you are trying to do:
- Help a business visitor understand whether JD Lumen fits their work.
- When their need is clear, connect it to one real service and explain a practical workflow in plain language.
- Offer a free call only when it helps, and not after every message. Do not open with a sales pitch. If they hesitate, answer the concern and stop there.
- If they are looking for a job, answer from the open roles below and set action to "careers". Do not steer a candidate into a sales call.
- If they ask about projects, explain only the projects in the company facts. For a list, name them briefly and ask which one they want. Set action to "none".

Rules:
- Use only the company facts and the open roles in this prompt. If a role is not listed, it is not open.
- Never invent prices, discounts, deadlines, guarantees, client names, team members, response steps, confirmation emails, privacy policies, or results.
- If you do not know something, say you cannot confirm it and that the team can explain it. The team replies within 24 hours after a submitted request. Do not invent any other timing.
- Never pretend a person has already reviewed their project.
- Never use fake urgency, fake scarcity, guilt, or pressure.
- On price, say the team scopes the work on the free call. Do not compare with a made-up product. Custom work means the system follows their process. Ready-made tools are general. Do not claim JD Lumen is always cheaper or faster.
- Stay on JD Lumen. For an unrelated topic, give one short line and offer help with their business or a role.

Booking a call:
- Do not ask for a name, email, phone, or time until they clearly agree to schedule. Interest in a service is not agreement. "Yes, I would like to schedule" is agreement. A question about what happens next is not.
- If they do not want to book, say that is fine and keep helping. Do not ask again unless they bring it up.
- After they agree, ask once for all four details in one message: name, email, phone, and preferred date and time. Then wait.
- If they ask something else before sending those details, answer that question only. Do not repeat the four-field request in the same reply.
- Copy details only from words the visitor typed. Never guess a name, email, phone, company, or time.
- If the email or phone is not usable, ask them to correct that one item. An email needs a name, an @ sign, and a domain. A phone number needs at least 8 digits.
- When all four are present and their latest message is not a question, show this summary and wait. Do not say it has been submitted:
  Here is what I will send to the team:
  Name: ...
  Email: ...
  Phone: ...
  Preferred date and time: ...
  Reply yes to submit this, or tell me what to change. I have not sent it yet.
- Set booking to those details on that turn, and set confirmed to false.
- Set confirmed to true only when they accept a summary you already showed, with a clear yes or confirm, and they are not asking a question or changing a detail.
- You do not send the email. The website sends it only after confirmed is true. Never say the request was submitted unless confirmed is true.
- If they would rather use the website form, set action to "book". Otherwise use "none" or "careers".

Reply with JSON only, in one of these shapes:
{"reply":"your message","action":"none","booking":null,"confirmed":false}
{"reply":"your message","action":"none","booking":{"name":"","email":"","phone":"","company":"","preferred_time":"","need":""},"confirmed":false}
{"reply":"your message","action":"none","booking":{"name":"","email":"","phone":"","company":"","preferred_time":"","need":""},"confirmed":true}
action must be "book", "careers", or "none".
""".strip()


class ChatMessage(BaseModel):
    role: str
    text: str = Field(max_length=2000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=24)
    already_booked: bool = False


_EMAIL = TypeAdapter(EmailStr)
_CONFIRMATION = re.compile(
    r"^(yes|yeah|yep|yup|confirm|confirmed|correct|go ahead|please submit|submit|looks good|all good|that(?:'s| is) (?:right|correct))[.!]*$",
    re.IGNORECASE,
)
_CONFIRMATION_PHRASE = re.compile(
    r"\b(i confirm|yes,? confirm|please (?:submit|go ahead|send it)|that(?:'s| is) correct|looks good)\b",
    re.IGNORECASE,
)
_CHANGE = re.compile(r"\b(change|instead|actually|make it|switch|update|wrong)\b", re.IGNORECASE)
_REFUSAL = re.compile(
    r"\b(don'?t want|do not want|not ready|no thanks|not interested|maybe later|not now)\b",
    re.IGNORECASE,
)
_FALSE_SENT = re.compile(
    r"\b(i have sent|i've sent|has been submitted|successfully submitted|request was sent|emailed the team)\b",
    re.IGNORECASE,
)
_PRIVACY_LIE = re.compile(
    r"not shared with|never shared|won'?t be shared|will not be shared|no third part",
    re.IGNORECASE,
)


def _visitor_text(history: list[dict]) -> str:
    return "\n".join(item["text"] for item in history if item["role"] == "user")


def _time_was_said(preferred_time: str, visitor: str) -> bool:
    if preferred_time.lower() in visitor.lower():
        return True
    words = [
        word
        for word in re.findall(r"[a-z0-9:]+", preferred_time.lower())
        if word not in {"at", "on", "the", "a", "pm", "am"}
    ]
    if not words:
        return False
    visitor_text = visitor.lower()
    hits = sum(1 for word in words if word in visitor_text)
    return hits >= max(1, (len(words) + 1) // 2)


def _verified_booking(raw: object, history: list[dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    visitor = _visitor_text(history)
    visitor_digits = re.sub(r"\D", "", visitor)
    name = " ".join(str(raw.get("name", "")).split())
    email = str(raw.get("email", "")).strip()
    phone = " ".join(str(raw.get("phone", "")).split())
    preferred_time = " ".join(str(raw.get("preferred_time", "")).split())
    company = " ".join(str(raw.get("company", "")).split())
    need = " ".join(str(raw.get("need", "")).split())
    phone_digits = re.sub(r"\D", "", phone)
    try:
        email = str(_EMAIL.validate_python(email))
    except ValidationError:
        return None
    if (
        len(name) < 2
        or name.lower() not in visitor.lower()
        or email.lower() not in visitor.lower()
        or len(phone_digits) < 8
        or phone_digits not in visitor_digits
        or len(preferred_time) < 3
        or not _time_was_said(preferred_time, visitor)
    ):
        return None
    if company.lower() not in visitor.lower():
        company = ""
    if len(need) < 8:
        need = " ".join(visitor.split())[:1000]
    return {
        "name": name,
        "email": email,
        "phone": phone,
        "company": company,
        "preferred_time": preferred_time,
        "need": need,
    }


def _latest_text(history: list[dict]) -> str:
    return history[-1]["text"]


def _prior_user_text(history: list[dict]) -> str:
    users = [item["text"] for item in history if item["role"] == "user"]
    return "\n".join(users[:-1])


def _is_question(text: str) -> bool:
    return "?" in text


def _is_confirmation(text: str) -> bool:
    cleaned = " ".join(text.split())
    if "?" in cleaned or "@" in cleaned or _CHANGE.search(cleaned):
        return False
    if _CONFIRMATION.match(cleaned):
        return True
    return len(cleaned) < 80 and bool(_CONFIRMATION_PHRASE.search(cleaned))


def _details_were_shared_earlier(booking: dict, history: list[dict]) -> bool:
    prior = _prior_user_text(history)
    prior_digits = re.sub(r"\D", "", prior)
    phone_digits = re.sub(r"\D", "", booking["phone"])
    return (
        booking["name"].lower() in prior.lower()
        and booking["email"].lower() in prior.lower()
        and phone_digits in prior_digits
        and _time_was_said(booking["preferred_time"], prior)
    )


def _just_shared_contact(text: str) -> bool:
    return "@" in text or len(re.sub(r"\D", "", text)) >= 8


def _summary(booking: dict) -> str:
    return (
        "Here is what I will send to the team:\n\n"
        f"Name: {booking['name']}\n"
        f"Email: {booking['email']}\n"
        f"Phone: {booking['phone']}\n"
        f"Preferred date and time: {booking['preferred_time']}\n\n"
        "Reply yes to submit this, or tell me what to change. I have not sent it yet."
    )


def _is_form_reply(reply: str) -> bool:
    return all(label in reply for label in ("Name:", "Email:", "Phone:", "Preferred date"))


def _turn_hint(latest: str) -> str:
    if _REFUSAL.search(latest):
        return (
            "The visitor does not want to book right now. Respect that and answer them. "
            "Do not ask for contact details."
        )
    if _is_question(latest):
        extra = " Answer each question they asked."
        if re.search(r"third part|privacy|stored|share", latest, re.IGNORECASE):
            extra += (
                " Do not say the details are never shared or are not shared with third parties. "
                "Say they are saved and emailed to Info@jdlumen.ai for this enquiry, and that you cannot confirm any wider sharing."
            )
        if re.search(r"confirmation email|email confirmation", latest, re.IGNORECASE):
            extra += " There is no automatic confirmation email. The team replies within 24 hours."
        return (
            "The latest message is a question. Answer it from the company facts. "
            "Do not ask for a name, email, phone, or time, do not include a contact form, "
            "and do not ask them to book or schedule in this reply."
            + extra
        )
    if _is_confirmation(latest):
        return (
            "The visitor is confirming a summary already shown. "
            "Set confirmed to true only if their name, email, phone, and time are already in earlier messages. "
            "Do not say the request was submitted."
        )
    return ""


def _recent_inquiry(email: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM inquiries
            WHERE lower(email) = lower(?) AND created_at >= ? AND email_sent = 1
            """,
            (email, cutoff),
        ).fetchone()
    return row is not None


def _send_booking(booking: dict, request: Request) -> tuple[bool, str]:
    if _recent_inquiry(booking["email"]):
        return True, (
            f"This request was already submitted. The team will reply to {booking['email']} within 24 hours."
        )
    if too_many(client_ip(request), "inquiries"):
        return False, (
            "Your details are still here, but I could not send another request just now. "
            "Reply yes to try again in a few minutes, or write to Info@jdlumen.ai."
        )

    inquiry = {
        "name": booking["name"],
        "email": booking["email"],
        "company": booking["company"] or "Not given in chat",
        "service": "Free strategy call",
        "industry": "Not given in chat",
        "source": "free-call",
        "message": "\n".join(
            [
                "This request was collected by Juno in the website chat.",
                "",
                f"Preferred time: {booking['preferred_time']}",
                f"Phone: {booking['phone']}",
                "",
                "What they need:",
                booking["need"],
            ]
        ),
    }
    inquiry_id = insert_inquiry(inquiry)
    try:
        send_inquiry_email(inquiry)
    except EmailNotConfigured:
        logger.warning("Juno booking %s saved without email: SMTP is not configured", inquiry_id)
        return False, (
            "Your details are still here, but the email to the team is not set up, so nothing was submitted. "
            "Reply yes to try again, or write to Info@jdlumen.ai."
        )
    except EmailDeliveryError:
        logger.exception("Juno booking %s saved but email delivery failed", inquiry_id)
        return False, (
            "Your details are still here, but the email to the team could not be sent, so nothing was submitted. "
            "Reply yes to try again, or write to Info@jdlumen.ai."
        )

    mark_email_sent(inquiry_id)
    first_name = booking["name"].split()[0]
    return True, (
        f"Thank you, {first_name}. Your consultation request has been submitted. "
        f"The team will review it and reply to {booking['email']} within 24 hours. "
        f"{booking['preferred_time']} stays a preference until they confirm it."
    )


def _facts() -> str:
    jobs = list_jobs()
    if jobs:
        lines = [
            f"- {job['title']} ({job['type']}, {job['location']}, {job['experience']}): {job['description']}"
            for job in jobs
        ]
        openings = "Open roles right now:\n" + "\n".join(lines)
    else:
        openings = "There are no open roles listed right now. Invite interested people to check the careers page later."
    return f"{JUNO_INSTRUCTIONS}\n\nCompany facts:\n{COMPANY_FACTS}\n\n{openings}"


def _clean_history(messages: list[ChatMessage]) -> list[dict]:
    history = []
    for message in messages:
        role = "assistant" if message.role == "assistant" else "user"
        text = message.text.strip()
        if text:
            history.append({"role": role, "text": text})
    if not history or history[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="Send the visitor's latest message.")
    return history


def _parse_model_text(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("The model did not return JSON.") from error
    reply = str(parsed.get("reply", "")).strip()
    action = str(parsed.get("action", "none")).strip().lower()
    if action not in {"book", "careers", "none"}:
        action = "none"
    if not reply:
        raise ValueError("The model returned an empty reply.")
    return {
        "ready": True,
        "reply": reply,
        "action": action,
        "booking": parsed.get("booking"),
        "confirmed": parsed.get("confirmed") is True,
    }


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:500]
        logger.warning("Juno provider returned %s: %s", error.code, detail)
        raise
    except OSError:
        logger.exception("Juno provider could not be reached")
        raise


def _ask_openai(history: list[dict], system: str) -> str:
    model = JUNO_MODEL or "gpt-4o-mini"
    payload = {
        "model": model,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            *[
                {"role": item["role"], "content": item["text"]}
                for item in history
            ],
        ],
    }
    body = _post_json(
        "https://api.openai.com/v1/chat/completions",
        payload,
        {
            "Authorization": f"Bearer {JUNO_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    return body["choices"][0]["message"]["content"]


def _ask_gemini(history: list[dict], system: str) -> str:
    model = JUNO_MODEL or "gemini-2.0-flash"
    contents = [
        {
            "role": "user" if item["role"] == "user" else "model",
            "parts": [{"text": item["text"]}],
        }
        for item in history
    ]
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
        },
    }
    body = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        payload,
        {
            "x-goog-api-key": JUNO_API_KEY,
            "Content-Type": "application/json",
        },
    )
    return body["candidates"][0]["content"]["parts"][0]["text"]


@router.post("/api/juno/chat")
def chat(payload: ChatIn, request: Request):
    if too_many(client_ip(request), "juno", limit=30):
        raise HTTPException(
            status_code=429,
            detail="Too many messages. Please wait a few minutes and try again.",
        )
    if not juno_ready():
        return {"ready": False}

    history = _clean_history(payload.messages)
    latest = _latest_text(history)
    system = _facts()
    hint = _turn_hint(latest)
    if hint:
        system += f"\n\nThis turn:\n{hint}"
    if payload.already_booked:
        system += (
            "\n\nThis visitor's call request was already emailed to the team. "
            "Do not ask for their contact details again and set booking to null."
        )
    try:
        parsed = _model_reply(history, system)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        logger.exception("Juno could not answer, so the site will use the saved replies")
        return {"ready": False}

    if _is_question(latest) and (_is_form_reply(parsed["reply"]) or _PRIVACY_LIE.search(parsed["reply"])):
        try:
            parsed = _model_reply(
                history,
                system + "\n\nYour previous draft was wrong. Answer the question. "
                "Do not include Name:, Email:, or Phone: labels. "
                "Do not say contact details are not shared with third parties. "
                "Say they are saved and emailed to Info@jdlumen.ai for this enquiry, "
                "and that you cannot confirm any wider sharing.",
            )
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            logger.exception("Juno could not retry the question")

    raw_booking = parsed.pop("booking", None)
    parsed.pop("confirmed", None)
    booking = None if payload.already_booked else _verified_booking(raw_booking, history)
    ready_to_send = (
        booking is not None
        and _details_were_shared_earlier(booking, history)
        and _is_confirmation(latest)
    )
    if ready_to_send:
        sent, reply = _send_booking(booking, request)
        return {
            "ready": True,
            "reply": reply,
            "action": "none" if sent else "book",
            "booked": sent,
        }

    if (
        booking is not None
        and not _is_question(latest)
        and (_just_shared_contact(latest) or _FALSE_SENT.search(parsed["reply"]))
    ):
        parsed["reply"] = _summary(booking)
        parsed["action"] = "none"

    parsed["booked"] = False
    return parsed


def _model_reply(history: list[dict], system: str) -> dict:
    if JUNO_PROVIDER == "openai":
        raw = _ask_openai(history, system)
    else:
        raw = _ask_gemini(history, system)
    return _parse_model_text(raw)
