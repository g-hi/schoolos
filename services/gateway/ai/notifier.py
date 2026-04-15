"""
notifier.py
───────────
Sends notifications for teacher substitution assignments and reminders.

Supports two channels simultaneously:
  - Email via SendGrid  (requires SENDGRID_API_KEY + EMAIL_FROM)
  - SMS   via Twilio    (requires TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_SMS_FROM)

If credentials for a channel are missing / placeholder, that channel is
logged to stdout and gracefully skipped — the other channel still fires.

Public interface
────────────────
  send_substitution_notification(to_email, to_phone, ...)
      → returns (email_sent: bool, sms_sent: bool)

  schedule_reminder(to_email, to_phone, ...)
      → schedules a background task to fire both channels 5 min before the period

HOW THE REMINDER WORKS (MVP APPROACH)
──────────────────────────────────────
asyncio.create_task() keeps it lightweight with no extra dependencies.
Caveat: reminders are lost if the server restarts before they fire.
For production, use Celery + Redis or APScheduler.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from shared.config import get_settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal: SendGrid email sender
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_sendgrid(to_email: str, subject: str, body: str) -> bool:
    """Returns True on success, False if key not configured or send fails."""
    settings = get_settings()
    if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("SG.xxx"):
        logger.info(
            "[EMAIL - not sent, no SendGrid key]\n"
            f"  To:      {to_email}\n"
            f"  Subject: {subject}\n"
            f"  Body:    {body}"
        )
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=settings.email_from or "noreply@schoolos.app",
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
        )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        success = response.status_code in (200, 202)
        if not success:
            logger.warning(f"SendGrid returned status {response.status_code} for {to_email}")
        return success
    except Exception as exc:
        logger.error(f"SendGrid error sending to {to_email}: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Internal: Twilio SMS sender
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_twilio(to_phone: str, body: str) -> bool:
    """Returns True on success, False if credentials not configured or send fails."""
    settings = get_settings()
    if (
        not settings.twilio_account_sid
        or settings.twilio_account_sid.startswith("ACxxx")
        or not settings.twilio_auth_token
        or settings.twilio_auth_token == "your_auth_token_here"
    ):
        logger.info(
            "[SMS - not sent, Twilio not configured]\n"
            f"  To:   {to_phone}\n"
            f"  Body: {body}"
        )
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        message = client.messages.create(
            body=body,
            from_=settings.twilio_sms_from,
            to=to_phone,
        )
        success = message.sid is not None
        if not success:
            logger.warning(f"Twilio message to {to_phone} returned no SID")
        return success
    except Exception as exc:
        logger.error(f"Twilio error sending to {to_phone}: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public: immediate assignment notification (email + SMS)
# ─────────────────────────────────────────────────────────────────────────────

def send_substitution_notification(
    to_email: str | None,
    to_phone: str | None,
    to_name: str,
    absent_teacher_name: str,
    grade: str,
    section: str,
    subject_name: str,
    period_name: str,
    period_start_time: str,
    date_str: str,
) -> tuple[bool, bool]:
    """
    Sends the substitution assignment notification via both email and SMS.

    Returns (email_sent, sms_sent).
    Each channel is attempted independently — one failing does not block the other.
    Called synchronously from run_in_executor to keep the async handler non-blocking.
    """
    email_sent = False
    sms_sent = False

    if to_email:
        subject = f"[SchoolOS] Substitution Assignment - {date_str} {period_name}"
        email_body = (
            f"Dear {to_name},\n\n"
            f"You have been assigned to cover a class on {date_str}.\n\n"
            f"  Covering:  {absent_teacher_name} (absent)\n"
            f"  Class:     {grade} {section}\n"
            f"  Subject:   {subject_name}\n"
            f"  Period:    {period_name} (starts {period_start_time})\n\n"
            f"Please be in the classroom on time.\n\n"
            f"- SchoolOS Auto-Scheduler"
        )
        email_sent = _send_via_sendgrid(to_email, subject, email_body)

    if to_phone:
        sms_body = (
            f"[SchoolOS] Hi {to_name}, you are covering {absent_teacher_name}'s class on {date_str}. "
            f"Class: {grade} {section}, Subject: {subject_name}, "
            f"{period_name} at {period_start_time}. Please be on time."
        )
        sms_sent = _send_via_twilio(to_phone, sms_body)

    return email_sent, sms_sent


# ─────────────────────────────────────────────────────────────────────────────
# Public: 5-minute reminder (background asyncio task)
# ─────────────────────────────────────────────────────────────────────────────

async def _reminder_task(
    to_email: str | None,
    to_phone: str | None,
    to_name: str,
    subject_name: str,
    period_name: str,
    period_start_time: str,
    date_str: str,
    delay_seconds: float,
):
    """Waits then sends reminder via both channels. Runs as a background asyncio task."""
    await asyncio.sleep(delay_seconds)

    if to_email:
        email_subject = f"[SchoolOS] Reminder - {period_name} starts in 5 minutes"
        email_body = (
            f"Dear {to_name},\n\n"
            f"Reminder: your substitution class starts in 5 minutes.\n\n"
            f"  Subject: {subject_name}\n"
            f"  Period:  {period_name} (starts {period_start_time})\n"
            f"  Date:    {date_str}\n\n"
            f"- SchoolOS Auto-Scheduler"
        )
        _send_via_sendgrid(to_email, email_subject, email_body)

    if to_phone:
        sms_body = (
            f"[SchoolOS] Reminder {to_name}: your substitute class ({subject_name}) "
            f"starts in 5 minutes. {period_name} at {period_start_time} on {date_str}."
        )
        _send_via_twilio(to_phone, sms_body)

    logger.info(f"Reminders fired for {to_name} ({period_name} on {date_str})")


def schedule_reminder(
    to_email: str | None,
    to_phone: str | None,
    to_name: str,
    subject_name: str,
    period_name: str,
    period_start_time: str,   # "HH:MM"
    date_str: str,            # "YYYY-MM-DD"
) -> bool:
    """
    Schedules reminder notifications (email + SMS) to fire 5 minutes before the period.
    Returns True if scheduled, False if the period is already too soon.
    The task runs in the background — the HTTP response is not delayed.
    """
    try:
        period_dt = datetime.strptime(f"{date_str} {period_start_time}", "%Y-%m-%d %H:%M")
        reminder_dt = period_dt - timedelta(minutes=5)
        delay = (reminder_dt - datetime.now()).total_seconds()

        if delay <= 0:
            logger.info(f"Reminder skipped for {to_name} — period {period_name} already too soon.")
            return False

        asyncio.create_task(
            _reminder_task(
                to_email, to_phone, to_name, subject_name,
                period_name, period_start_time, date_str, delay
            )
        )
        logger.info(f"Reminder scheduled for {to_name} in {delay:.0f}s ({period_name} on {date_str})")
        return True
    except Exception as exc:
        logger.error(f"Failed to schedule reminder for {to_name}: {exc}")
        return False
