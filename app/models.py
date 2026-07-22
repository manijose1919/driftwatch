"""ORM models: Endpoint, Snapshot, DriftEvent, AlertChannel."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Endpoint.last_status values
STATUS_PENDING = "pending"    # never probed yet
STATUS_LEARNING = "learning"  # merging first N probes into the baseline
STATUS_OK = "ok"              # matches baseline
STATUS_DRIFT = "drift"        # shape differs from baseline
STATUS_ERROR = "error"        # unreachable / non-2xx / non-JSON

# DriftEvent.severity values, ordered weakest -> strongest
SEVERITY_ORDER = ["benign", "risky", "breaking", "error"]


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10), default="GET")
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )
    events: Mapped[list["DriftEvent"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )
    probe_results: Mapped[list["ProbeResult"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id"))
    shape: Mapped[dict] = mapped_column(JSON)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    # How many probes were merged into this shape (baselines learn from the
    # first N probes so intermittent/optional fields are captured).
    samples: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    endpoint: Mapped[Endpoint] = relationship(back_populates="snapshots")


class DriftEvent(Base):
    __tablename__ = "drift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"), nullable=True)
    # The baseline this event was diffed against (for the shape viewer).
    baseline_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(20))  # benign | risky | breaking | error
    # list of {"path": str, "kind": str, "severity": str, "detail": str}
    changes: Mapped[list] = mapped_column(JSON, default=list)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    endpoint: Mapped[Endpoint] = relationship(back_populates="events")
    snapshot: Mapped[Snapshot | None] = relationship(foreign_keys=[snapshot_id])


class ProbeResult(Base):
    """One lightweight metrics row per probe (latency + outcome status).

    Unlike Snapshot — which stores a full JSON type-shape only for baselines
    and drift events — a ProbeResult is written on *every* probe. It carries no
    shape blob, just a few numbers, so it's cheap to keep a per-endpoint time
    series for latency sparklines and status timelines. Retention-pruned.
    """
    __tablename__ = "probe_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # learning | ok | drift | error
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    endpoint: Mapped[Endpoint] = relationship(back_populates="probe_results")


class AlertChannel(Base):
    __tablename__ = "alert_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # discord | slack | webhook
    webhook_url: Mapped[str] = mapped_column(Text)
    min_severity: Mapped[str] = mapped_column(String(20), default="risky")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
