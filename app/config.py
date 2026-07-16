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
    min_interval_seconds: int = 10


settings = Settings()
