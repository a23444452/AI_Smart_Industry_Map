from datetime import datetime

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Boolean, Float, Integer, String, Text

from app.db.base import Base, TimestampMixin


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)  # TW | US | JP
    industry_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    has_futures: Mapped[bool] = mapped_column(Boolean, default=False)


class Topic(TimestampMixin, Base):
    __tablename__ = "topics"

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_tab: Mapped[str] = mapped_column(String)  # tw | us | jp | chain | etf
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[str | None] = mapped_column(String, nullable=True)  # ISO date


class TopicCompany(TimestampMixin, Base):
    __tablename__ = "topic_companies"
    __table_args__ = (
        ForeignKeyConstraint(["topic_slug"], ["topics.slug"]),
        ForeignKeyConstraint(["ticker"], ["companies.ticker"]),
    )

    topic_slug: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    chain_level: Mapped[str | None] = mapped_column(String, nullable=True)  # 上游|中游|下游
    category_desc: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)  # 龍頭|利基|新興|挑戰
    relevance: Mapped[str | None] = mapped_column(String, nullable=True)  # 高|中|低


class QuoteDaily(TimestampMixin, Base):
    __tablename__ = "quotes_daily"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str] = mapped_column(String, primary_key=True)  # ISO YYYY-MM-DD
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class PipelineRun(TimestampMixin, Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String)  # success | failed | running
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
