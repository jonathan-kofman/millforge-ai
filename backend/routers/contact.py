"""
/api/contact endpoint – pilot interest capture form.

Email notifications are sent via Gmail SMTP using smtplib.
Set SMTP_EMAIL and SMTP_PASSWORD in your environment.

IMPORTANT – SMTP_PASSWORD must be a Gmail App Password, NOT your regular Gmail
password. To generate one:
  Google Account → Security → 2-Step Verification → App Passwords
  → select "Mail" → Generate → paste the 16-character code as SMTP_PASSWORD.
Regular Gmail passwords will be rejected; App Passwords bypass Google's
"less secure app" block without weakening your account security.

If SMTP is not configured, submissions are still saved to the database and a
warning is logged. The form always returns success — we never lose a submission.
"""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from db_models import ContactSubmission
from models.schemas import ContactRequest, ContactResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Contact"])

NOTIFY_TO = "kofman.j@northeastern.edu"


def _send_notification(req: ContactRequest, submitted_at: datetime) -> None:
    """
    Send a notification email via Gmail SMTP.

    Reads SMTP_EMAIL and SMTP_PASSWORD from environment at call time so that
    tests can monkeypatch os.environ without restarting the process.

    Raises on any SMTP failure — caller is responsible for catching.
    """
    smtp_email = os.getenv("SMTP_EMAIL", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()

    if not smtp_email or not smtp_password:
        raise ValueError("SMTP_EMAIL or SMTP_PASSWORD not configured")

    company_str = req.company or "—"
    timestamp_str = submitted_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"New MillForge AI Contact — {req.name} from {company_str}"
    body = (
        f"Name: {req.name}\n"
        f"Email: {req.email}\n"
        f"Company: {company_str}\n"
        f"Message: {req.message}\n"
        f"Submitted: {timestamp_str}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = NOTIFY_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, [NOTIFY_TO], msg.as_string())


@router.post("/contact", response_model=ContactResponse, summary="Submit pilot interest")
async def submit_contact(req: ContactRequest, db: Session = Depends(get_db)) -> ContactResponse:
    """
    Accept contact / pilot interest form submissions.

    Always saves to the database first, then attempts SMTP notification.
    If SMTP fails for any reason the submission is not lost and the user
    still sees the success message.
    """
    submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── 1. Save to database (always) ──────────────────────────────────────────
    record = ContactSubmission(
        name=req.name,
        email=req.email,
        company=req.company,
        message=req.message,
        pilot_interest=req.pilot_interest,
        submitted_at=submitted_at,
    )
    db.add(record)
    db.commit()
    logger.info(
        "Contact submission saved: name=%s email=%s company=%s pilot=%s",
        req.name, req.email, req.company, req.pilot_interest,
    )

    # ── 2. Send email notification (best-effort) ──────────────────────────────
    try:
        _send_notification(req, submitted_at)
        logger.info("Notification email sent for contact submission from %s", req.email)
    except ValueError:
        logger.warning(
            "SMTP not configured — skipping email notification for %s. "
            "Set SMTP_EMAIL and SMTP_PASSWORD to enable.",
            req.email,
        )
    except Exception as exc:
        logger.warning(
            "Failed to send notification email for %s: %s", req.email, exc
        )

    return ContactResponse(
        success=True,
        message=(
            f"Thanks {req.name}! We've received your message"
            + (" and will reach out about our pilot program." if req.pilot_interest else ".")
        ),
    )
