import time

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
