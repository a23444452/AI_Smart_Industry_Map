from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    # 本專案 datetime 一律儲存 naive UTC：SQLite 不保留 tzinfo，讀回的值
    # 必為 naive；統一寫入 naive UTC 可避免 aware 與 naive 相減的 TypeError。
    return datetime.now(UTC).replace(tzinfo=None)


# 相容別名：既有模組（runner.py、meta.py 等）以舊名 ``_utcnow`` import，保留不動。
_utcnow = utcnow


class TimestampMixin:
    """Adds created_at/updated_at columns, maintained by the app layer."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


def make_engine(path: str) -> Engine:
    """Create a SQLite engine for ``path`` with WAL journaling and FK enforcement.

    Both pragmas are set per-connection via a connect event so every pooled
    connection (and every fresh file) gets them applied.
    """
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine
