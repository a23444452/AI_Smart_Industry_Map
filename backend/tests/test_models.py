import time
from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine


def _make_db(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    return eng


def test_create_all_and_wal(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    names = set(inspect(eng).get_table_names())
    assert {
        "companies",
        "topics",
        "topic_companies",
        "quotes_daily",
        "pipeline_runs",
        "institutional_flows",
        "index_snapshots",
        "market_flows",
        "margin_balances",
        "mops_announcements",
        "fundamentals",
        "per_daily",
        "major_holders",
    } <= names
    with eng.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_quote_roundtrip(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(models.Company(ticker="2330", name="台積電", market="TW"))
        s.add(
            models.QuoteDaily(
                ticker="2330",
                date="2026-07-11",
                open=1080,
                high=1095,
                low=1075,
                close=1090,
                volume=33169039,
                change_pct=1.40,
            )
        )
        s.commit()
        assert s.get(models.QuoteDaily, ("2330", "2026-07-11")).close == 1090


def test_institutional_flow_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.InstitutionalFlow(
                ticker="2330",
                date="2026-07-10",
                foreign_net=1200000,
                trust_net=-50000,
                dealer_net=None,
            )
        )
        s.commit()
        row = s.get(models.InstitutionalFlow, ("2330", "2026-07-10"))
        assert row.foreign_net == 1200000
        assert row.trust_net == -50000
        assert row.dealer_net is None


def test_index_snapshot_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    fetched = datetime(2026, 7, 11, 13, 30, 0)
    with Session(eng) as s:
        s.add(
            models.IndexSnapshot(
                symbol="^TWII",
                name="加權指數",
                price=23150.5,
                change=105.3,
                change_pct=0.46,
                fetched_at=fetched,
            )
        )
        s.commit()
        row = s.get(models.IndexSnapshot, "^TWII")
        assert row.name == "加權指數"
        assert row.price == 23150.5
        assert row.change == 105.3
        assert row.change_pct == 0.46
        assert row.fetched_at == fetched


def test_index_snapshot_overwrite_current_value(tmp_path):
    # 跑馬燈只留現值：同一 symbol 以 merge 覆寫，不累積歷史。
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.IndexSnapshot(
                symbol="^TWII", name="加權指數", price=23000.0
            )
        )
        s.commit()
    with Session(eng) as s:
        s.merge(
            models.IndexSnapshot(
                symbol="^TWII", name="加權指數", price=23200.0
            )
        )
        s.commit()
    with Session(eng) as s:
        assert s.query(models.IndexSnapshot).count() == 1
        assert s.get(models.IndexSnapshot, "^TWII").price == 23200.0


def test_index_snapshot_nullable_change(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.IndexSnapshot(symbol="^DJI", name="道瓊", price=39000.0)
        )
        s.commit()
        row = s.get(models.IndexSnapshot, "^DJI")
        assert row.change is None
        assert row.change_pct is None


def test_market_flow_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.MarketFlow(
                date="2026-07-11",
                unit="foreign",
                buy=120_000_000_000,
                sell=100_000_000_000,
                net=20_000_000_000,
            )
        )
        s.commit()
        row = s.get(models.MarketFlow, ("2026-07-11", "foreign"))
        assert row.buy == 120_000_000_000
        assert row.sell == 100_000_000_000
        assert row.net == 20_000_000_000


def test_market_flow_composite_pk_and_nullable(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(models.MarketFlow(date="2026-07-11", unit="foreign", net=1))
        s.add(models.MarketFlow(date="2026-07-11", unit="trust", buy=None))
        s.commit()
        assert s.query(models.MarketFlow).count() == 2
        assert s.get(models.MarketFlow, ("2026-07-11", "trust")).buy is None


def test_margin_balance_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.MarginBalance(
                date="2026-07-11",
                item="融資",
                buy=50000,
                sell=48000,
                prev_balance=6_500_000,
                today_balance=6_502_000,
            )
        )
        s.commit()
        row = s.get(models.MarginBalance, ("2026-07-11", "融資"))
        assert row.buy == 50000
        assert row.prev_balance == 6_500_000
        assert row.today_balance == 6_502_000


def test_margin_balance_composite_pk_and_nullable(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(models.MarginBalance(date="2026-07-11", item="融資"))
        s.add(models.MarginBalance(date="2026-07-11", item="融券"))
        s.commit()
        assert s.query(models.MarginBalance).count() == 2
        row = s.get(models.MarginBalance, ("2026-07-11", "融資"))
        assert row.buy is None
        assert row.today_balance is None


def test_mops_announcement_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    published = datetime(2026, 7, 11, 8, 5, 0)
    with Session(eng) as s:
        ann = models.MopsAnnouncement(
            ticker="2330",
            name="台積電",
            category="財務數據",
            title="本公司公告第二季合併營收",
            published_at=published,
        )
        s.add(ann)
        s.commit()
        got = s.get(models.MopsAnnouncement, ann.id)
        assert got.id is not None
        assert got.ticker == "2330"
        assert got.category == "財務數據"
        assert got.title == "本公司公告第二季合併營收"
        assert got.published_at == published


def test_mops_announcement_unique_constraint(tmp_path):
    eng = _make_db(tmp_path)
    published = datetime(2026, 7, 11, 8, 5, 0)
    with Session(eng) as s:
        s.add(
            models.MopsAnnouncement(
                ticker="2330",
                name="台積電",
                category="重大事件",
                title="重訊說明",
                published_at=published,
            )
        )
        s.add(
            models.MopsAnnouncement(
                ticker="2330",
                name="台積電",
                category="重大事件",
                title="重訊說明",
                published_at=published,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_fundamental_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.Fundamental(
                ticker="2330",
                month="2026-06",
                revenue=250_000_000,  # 千元
                yoy=18.5,
            )
        )
        s.add(models.Fundamental(ticker="2330", month="2026-05", revenue=240_000_000))
        s.commit()
        row = s.get(models.Fundamental, ("2330", "2026-06"))
        assert row.revenue == 250_000_000
        assert row.yoy == 18.5
        assert s.get(models.Fundamental, ("2330", "2026-05")).yoy is None
        assert s.query(models.Fundamental).count() == 2


def test_per_daily_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.PerDaily(
                ticker="2330",
                date="2026-07-11",
                per=22.4,
                pbr=6.1,
                dividend_yield=1.85,
            )
        )
        s.add(models.PerDaily(ticker="2330", date="2026-07-10"))
        s.commit()
        row = s.get(models.PerDaily, ("2330", "2026-07-11"))
        assert row.per == 22.4
        assert row.pbr == 6.1
        assert row.dividend_yield == 1.85
        empty = s.get(models.PerDaily, ("2330", "2026-07-10"))
        assert empty.per is None
        assert empty.pbr is None
        assert empty.dividend_yield is None


def test_major_holder_roundtrip(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.MajorHolder(
                ticker="2330",
                week="2026-07-04",
                ratio_400up=62.3,
                holder_count=1_050_000,
            )
        )
        s.add(models.MajorHolder(ticker="2330", week="2026-06-27", ratio_400up=61.9))
        s.commit()
        row = s.get(models.MajorHolder, ("2330", "2026-07-04"))
        assert row.ratio_400up == 62.3
        assert row.holder_count == 1_050_000
        assert s.get(models.MajorHolder, ("2330", "2026-06-27")).holder_count is None
        assert s.query(models.MajorHolder).count() == 2


def test_orphan_topic_company_rejected(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(
            models.TopicCompany(
                topic_slug="no-such-topic",
                ticker="0000",
                category="上游",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_updated_at_changes_on_update(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(models.Company(ticker="2330", name="台積電", market="TW"))
        s.commit()
        first = s.get(models.Company, "2330").updated_at
        time.sleep(0.01)
        s.get(models.Company, "2330").name = "台積電（更名）"
        s.commit()
        assert s.get(models.Company, "2330").updated_at > first


def test_topic_company_same_ticker_multiple_categories(tmp_path):
    eng = _make_db(tmp_path)
    with Session(eng) as s:
        s.add(models.Company(ticker="2330", name="台積電", market="TW"))
        s.add(models.Topic(slug="ai-chips", title="AI 晶片", market_tab="tw"))
        s.commit()
        s.add(
            models.TopicCompany(
                topic_slug="ai-chips", ticker="2330", category="晶圓代工"
            )
        )
        s.add(
            models.TopicCompany(
                topic_slug="ai-chips", ticker="2330", category="先進封裝"
            )
        )
        s.commit()
        rows = s.query(models.TopicCompany).filter_by(
            topic_slug="ai-chips", ticker="2330"
        )
        assert {r.category for r in rows} == {"晶圓代工", "先進封裝"}
