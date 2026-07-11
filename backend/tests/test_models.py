from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine


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
