"""Application configuration, sourced from environment variables."""
import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DRIFTWATCH_DB", "sqlite:///./driftwatch.db")
    )
    scheduler_enabled: bool = field(
        default_factory=lambda: _env_bool("DRIFTWATCH_SCHEDULER_ENABLED", True)
    )
    # Optional bearer token protecting /api routes. Empty string disables auth.
    api_token: str = field(default_factory=lambda: os.getenv("DRIFTWATCH_API_TOKEN", ""))
    probe_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("DRIFTWATCH_PROBE_TIMEOUT", "15"))
    )
    # Extra attempts after a network failure or 5xx (0 disables retries).
    probe_retries: int = field(
        default_factory=lambda: int(os.getenv("DRIFTWATCH_PROBE_RETRIES", "2"))
    )
    probe_backoff_seconds: float = field(
        default_factory=lambda: float(os.getenv("DRIFTWATCH_PROBE_BACKOFF", "0.5"))
    )
    # Number of successful probes merged into a new endpoint's baseline before
    # drift detection arms. >1 teaches the baseline about optional fields.
    baseline_probes: int = field(
        default_factory=lambda: max(1, int(os.getenv("DRIFTWATCH_BASELINE_PROBES", "3")))
    )
    # Days to keep acknowledged events and orphaned snapshots (0 = keep forever).
    retention_days: int = field(
        default_factory=lambda: int(os.getenv("DRIFTWATCH_RETENTION_DAYS", "30"))
    )
    # SMTP settings for 'email' alert channels (host empty = email disabled).
    smtp_host: str = field(default_factory=lambda: os.getenv("DRIFTWATCH_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("DRIFTWATCH_SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("DRIFTWATCH_SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("DRIFTWATCH_SMTP_PASSWORD", ""))
    smtp_from: str = field(
        default_factory=lambda: os.getenv("DRIFTWATCH_SMTP_FROM", "driftwatch@localhost")
    )
    smtp_starttls: bool = field(
        default_factory=lambda: _env_bool("DRIFTWATCH_SMTP_STARTTLS", True)
    )
    min_interval_seconds: int = 10


settings = Settings()
