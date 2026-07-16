"""Pydantic request/response schemas for the REST API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings

VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
VALID_SEVERITIES = {"benign", "risky", "breaking", "error"}
VALID_CHANNEL_KINDS = {"discord", "slack", "webhook"}


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    method: str = "GET"
    headers: dict[str, str] = {}
    body: str | None = None
    interval_seconds: int = 300
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("method")
    @classmethod
    def method_valid(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_METHODS:
            raise ValueError(f"method must be one of {sorted(VALID_METHODS)}")
        return v

    @field_validator("interval_seconds")
    @classmethod
    def interval_floor(cls, v: int) -> int:
        return max(v, settings.min_interval_seconds)


class EndpointUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    method: str | None = None
    headers: dict[str, str] | None = None
    body: str | None = None
    interval_seconds: int | None = None
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("method")
    @classmethod
    def method_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in VALID_METHODS:
            raise ValueError(f"method must be one of {sorted(VALID_METHODS)}")
        return v


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    method: str
    headers: dict
    body: str | None
    interval_seconds: int
    is_active: bool
    created_at: datetime
    last_probed_at: datetime | None
    last_status: str
    last_error: str | None
    last_response_ms: float | None
    open_events: int = 0  # unacknowledged drift events


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    shape: dict
    status_code: int | None
    response_ms: float | None
    is_baseline: bool
    created_at: datetime


class ChangeOut(BaseModel):
    path: str
    kind: str
    severity: str
    detail: str


class DriftEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    endpoint_name: str = ""
    snapshot_id: int | None
    severity: str
    changes: list[ChangeOut]
    acknowledged: bool
    created_at: datetime


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    webhook_url: str = Field(min_length=1)
    min_severity: str = "risky"
    is_active: bool = True

    @field_validator("kind")
    @classmethod
    def kind_valid(cls, v: str) -> str:
        if v not in VALID_CHANNEL_KINDS:
            raise ValueError(f"kind must be one of {sorted(VALID_CHANNEL_KINDS)}")
        return v

    @field_validator("min_severity")
    @classmethod
    def severity_valid(cls, v: str) -> str:
        if v not in VALID_SEVERITIES:
            raise ValueError(f"min_severity must be one of {sorted(VALID_SEVERITIES)}")
        return v

    @field_validator("webhook_url")
    @classmethod
    def webhook_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("webhook_url must start with http:// or https://")
        return v


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    webhook_url: str
    min_severity: str
    is_active: bool
    created_at: datetime


class StatsOut(BaseModel):
    endpoints: int
    active_endpoints: int
    open_events: int
    open_breaking: int
    probes_ok: int
    probes_error: int
