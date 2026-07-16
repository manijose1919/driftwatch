"""Optional bearer-token auth for /api routes.

If DRIFTWATCH_API_TOKEN is unset, the API is open (self-hosted, LAN use).
If set, requests must send: Authorization: Bearer <token>.
"""
import secrets

from fastapi import Header, HTTPException

from .config import settings


async def require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API token")
