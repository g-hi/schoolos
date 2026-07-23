"""
messenger.py
────────────
Sends outbound messages to parents (and teachers) via WhatsApp or SMS.

Channel selection
─────────────────
Every User row has a preferred_channel field: 'whatsapp' | 'sms' | 'email'.
The send_to_user() function reads that field and routes accordingly:
  - whatsapp → Twilio WhatsApp API  (TWILIO_WHATSAPP_FROM)
  - sms       → Twilio SMS API      (TWILIO_SMS_FROM)
  - email     → delegated to notifier._send_via_sendgrid()

If Twilio credentials are placeholder / missing, messages are logged to
stdout instead — the system keeps running in dev without real keys.

Public interface
────────────────
  send_to_user(user, body, message_type, db, student_id=None)
      → sends via the user's preferred channel, saves a Message row, returns the row

  send_to_users(users, body, message_type, db, student_id=None)
      → fan-out: calls send_to_user for each user in the list
"""

import uuid
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.db.models import Message, User

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal channel senders
# ─────────────────────────────────────────────────────────────────────────────

def _twilio_send(to_phone: str, body: str, channel: str) -> tuple[bool, str | None]:
    """
    Sends via Twilio WhatsApp or SMS.
    Returns (success, error_string_or_None).
    """
    settings = get_settings()

    if (
        not settings.twilio_account_sid
        or settings.twilio_account_sid.startswith("ACxxx")
        or not settings.twilio_auth_token
        or settings.twilio_auth_token == "your_auth_token_here"
    ):
        logger.info("%s delivery skipped: Twilio not configured", channel.upper())
        return False, "TWILIO_NOT_CONFIGURED"

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        from_number = (
            settings.twilio_whatsapp_from
            if channel == "whatsapp"
            else settings.twilio_sms_from
        )
        to_number = f"whatsapp:{to_phone}" if channel == "whatsapp" else to_phone

        message = client.messages.create(body=body, from_=from_number, to=to_number)
        if message.sid:
            return True, None
        return False, "No SID returned"
    except Exception:
        logger.error("Twilio %s delivery failed", channel)
        return False, "TWILIO_ERROR"


def _email_send(to_email: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Sends via SendGrid. Returns (success, error_or_None)."""
    settings = get_settings()

    if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("SG.xxx"):
        logger.info("EMAIL delivery skipped: SendGrid not configured")
        return False, "SENDGRID_NOT_CONFIGURED"

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        msg = Mail(
            from_email=settings.email_from or "noreply@schoolos.app",
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
        )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(msg)
        if response.status_code in (200, 202):
            return True, None
        return False, f"SendGrid status {response.status_code}"
    except Exception:
        logger.error("SendGrid email delivery failed")
        return False, "SENDGRID_ERROR"


# ─────────────────────────────────────────────────────────────────────────────
# Public: send to one user
# ─────────────────────────────────────────────────────────────────────────────

async def send_to_user(
    user: User,
    body: str,
    message_type: str,
    db: AsyncSession,
    student_id: Optional[uuid.UUID] = None,
    notification_id: Optional[uuid.UUID] = None,
    email_subject: str = "[SchoolOS] School Notification",
) -> Message:
    """
    Sends a message to a single user via their preferred_channel.
    Saves a Message row with the result (sent / failed / skipped).
    Returns the saved Message object.
    """
    channel = user.preferred_channel or "sms"
    status = "sent"
    error = None

    if channel == "whatsapp":
        if user.phone:
            success, error = _twilio_send(user.phone, body, "whatsapp")
            if error == "TWILIO_NOT_CONFIGURED":
                status = "skipped"
            else:
                status = "sent" if success else "failed"
        else:
            status = "skipped"
            error = "NO_PHONE"

    elif channel == "sms":
        if user.phone:
            success, error = _twilio_send(user.phone, body, "sms")
            if error == "TWILIO_NOT_CONFIGURED":
                status = "skipped"
            else:
                status = "sent" if success else "failed"
        else:
            status = "skipped"
            error = "NO_PHONE"

    elif channel == "email":
        if user.email:
            success, error = _email_send(user.email, email_subject, body)
            if error == "SENDGRID_NOT_CONFIGURED":
                status = "skipped"
            else:
                status = "sent" if success else "failed"
        else:
            status = "skipped"
            error = "NO_EMAIL"

    else:
        status = "skipped"
        error = "UNKNOWN_CHANNEL"

    msg = Message(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        recipient_id=user.id,
        student_id=student_id,
        channel=channel,
        message_type=message_type,
        body=body,
        status=status,
        error=error,
        notification_id=notification_id,
    )
    db.add(msg)
    return msg


async def send_to_users(
    users: list[User],
    body: str,
    message_type: str,
    db: AsyncSession,
    student_id: Optional[uuid.UUID] = None,
    notification_id: Optional[uuid.UUID] = None,
    email_subject: str = "[SchoolOS] School Notification",
) -> list[Message]:
    """
    Fan-out: sends the same message to a list of users.
    Each user gets their own Message row.
    Returns list of Message objects (not yet committed — caller must commit).
    """
    results = []
    for user in users:
        msg = await send_to_user(
            user, body, message_type, db,
            student_id=student_id,
            notification_id=notification_id,
            email_subject=email_subject,
        )
        results.append(msg)
    return results
