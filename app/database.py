"""Database engine/session setup (SQLite by default, zero-config)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    # The scheduler probes from a background thread/loop, so allow cross-thread use.
    connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Lightweight in-place migrations for SQLite (create_all never ALTERs)."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        _ensure_column(conn, "snapshots", "samples", "samples INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "drift_events", "baseline_snapshot_id", "baseline_snapshot_id INTEGER")


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    columns = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
