"""Alert dispatcher: Discord/Slack/generic webhooks and SMTP email."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AlertChannel, DriftEvent, Endpoint, severity_rank

log = logging.getLogger("driftwatch.alerts")

_EMOJI = {"benign": "🟢", "risky": "🟡", "breaking": "🔴", "error": "⚠️"}
_MAX_CHANGE_LINES = 15


def format_event(endpoint: Endpoint, event: DriftEvent) -> str:
    emoji = _EMOJI.get(event.severity, "❔")
    header = (
        f"{emoji} **DriftWatch: {event.severity.upper()}** on "
        f"`{endpoint.name}`\n{endpoint.method} {endpoint.url}"
    )
    lines = []
    for change in event.changes[:_MAX_CHANGE_LINES]:
        c_emoji = _EMOJI.get(change["severity"], "❔")
        lines.append(f"{c_emoji} `{change['path']}` — {change['detail']}")
    if len(event.changes) > _MAX_CHANGE_LINES:
        lines.append(f"… and {len(event.changes) - _MAX_CHANGE_LINES} more change(s)")
    return header + "\n" + "\n".join(lines)


def _payload_for(kind: str, text: str) -> dict:
    if kind == "discord":
        return {"content": text[:1990]}  # Discord hard limit: 2000 chars
    if kind == "slack":
        return {"text": text}
    return {"text": text, "source": "driftwatch"}  # generic webhook


def _send_email_sync(recipient: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def _send_email(recipient: str, subject: str, text: str) -> bool:
    if not settings.smtp_host:
        log.warning("email channel used but DRIFTWATCH_SMTP_HOST is not configured")
        return False
    try:
        await asyncio.to_thread(_send_email_sync, recipient, subject, text)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("email to %s failed: %s", recipient, exc)
        return False


async def dispatch_event(db: Session, endpoint: Endpoint, event: DriftEvent) -> int:
    """Send the event to every active channel that accepts its severity.

    Returns the number of channels notified. Delivery failures are logged,
    never raised — a dead webhook must not break probing.
    """
    channels = db.scalars(
        select(AlertChannel).where(AlertChannel.is_active.is_(True))
    ).all()
    eligible = [
        c for c in channels
        if severity_rank(event.severity) >= severity_rank(c.min_severity)
    ]
    if not eligible:
        return 0

    text = format_event(endpoint, event)
    sent = 0

    email_channels = [c for c in eligible if c.kind == "email"]
    webhook_channels = [c for c in eligible if c.kind != "email"]

    if email_channels:
        subject = f"[DriftWatch] {event.severity.upper()}: {endpoint.name}"
        plain = text.replace("**", "").replace("`", "")
        for channel in email_channels:
            # For email channels, webhook_url holds the recipient address.
            if await _send_email(channel.webhook_url, subject, plain):
                sent += 1

    if webhook_channels:
        async with httpx.AsyncClient(timeout=10) as client:
            for channel in webhook_channels:
                try:
                    resp = await client.post(
                        channel.webhook_url, json=_payload_for(channel.kind, text)
                    )
                    if resp.status_code >= 300:
                        log.warning(
                            "alert channel %s (%s) returned %s",
                            channel.id, channel.name, resp.status_code,
                        )
                    else:
                        sent += 1
                except httpx.HTTPError as exc:
                    log.warning("alert channel %s (%s) failed: %s", channel.id, channel.name, exc)
    return sent


async def send_test_message(channel: AlertChannel) -> bool:
    text = f"🛰️ DriftWatch test message for channel `{channel.name}` — delivery works."
    if channel.kind == "email":
        return await _send_email(
            channel.webhook_url, "[DriftWatch] test message", text.replace("`", "")
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(channel.webhook_url, json=_payload_for(channel.kind, text))
        return resp.status_code < 300
    except httpx.HTTPError:
        return False
