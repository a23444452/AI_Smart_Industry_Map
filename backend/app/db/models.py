from datetime import datetime

from sqlalchemy import BigInteger, ForeignKeyConstraint, UniqueConstraint
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
    # 產業鏈骨架（level → categories 的 name/desc/placeholder 順序）。公司歸屬仍
    # 正規化存於 topic_companies；但「無公司的 placeholder 分類」無法用關聯表表達，
    # 故將整個分類骨架（含 placeholder 與描述、排序）存於此 JSON 欄位。
    chain_meta: Mapped[list | None] = mapped_column(JSON, nullable=True)


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


class InstitutionalFlow(TimestampMixin, Base):
    __tablename__ = "institutional_flows"
    # 不加 FK 到 companies：與 quotes_daily 同策略，fetch_institutional job 於
    # 寫入前先過濾未知 ticker，DB 層不強制外鍵以免拖累批次匯入。

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str] = mapped_column(String, primary_key=True)  # ISO YYYY-MM-DD
    # 單位：股；來源缺欄時容忍 NULL。
    foreign_net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trust_net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dealer_net: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PipelineRun(TimestampMixin, Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String)  # success | failed | running
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IndexSnapshot(TimestampMixin, Base):
    __tablename__ = "index_snapshots"
    # 跑馬燈指數現值：以 symbol 為 PK，upsert 覆寫策略（只留現值，不留歷史）。

    symbol: Mapped[str] = mapped_column(String, primary_key=True)  # 如 "^TWII"
    name: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(nullable=True)


class MarketFlow(TimestampMixin, Base):
    __tablename__ = "market_flows"
    # 全市場三大法人買賣金額：date＋unit（foreign|trust|dealer）複合 PK。

    date: Mapped[str] = mapped_column(String, primary_key=True)  # ISO YYYY-MM-DD
    unit: Mapped[str] = mapped_column(String, primary_key=True)
    # 單位：元；來源缺欄時容忍 NULL。金額可達千億級，故用 BigInteger。
    buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class MarginBalance(TimestampMixin, Base):
    __tablename__ = "margin_balances"
    # 全市場信用交易餘額：date＋item（融資|融券）複合 PK。

    date: Mapped[str] = mapped_column(String, primary_key=True)  # ISO YYYY-MM-DD
    item: Mapped[str] = mapped_column(String, primary_key=True)
    # 單位：元／張，依 item 而定；來源缺欄時容忍 NULL。
    buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prev_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    today_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class MopsAnnouncement(TimestampMixin, Base):
    __tablename__ = "mops_announcements"
    __table_args__ = (
        UniqueConstraint("ticker", "title", "published_at"),
    )
    # 公開資訊觀測站重大訊息。category 慣例（僅約定，不建 enum）：
    # 澄清回應 / 自結 / 財務數據 / 公司治理 / 重大事件。

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column()
