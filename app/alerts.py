"""Alert dispatcher: pushes drift events to Discord/Slack/generic webhooks."""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    async with httpx.AsyncClient(timeout=10) as client:
        for channel in eligible:
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
    text = f"🛰️ DriftWatch test message for channel `{channel.name}` — webhook works."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(channel.webhook_url, json=_payload_for(channel.kind, text))
        return resp.status_code < 300
    except httpx.HTTPError:
        return False
