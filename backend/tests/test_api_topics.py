"""Tests for GET /api/topics.

The `client` fixture runs the real lifespan against a per-test tmp DB and mounts
the engine on `app.state.engine`; these tests seed through that same engine
(real seeds via load_seeds + hand-inserted fake quotes) so the API reads exactly
what the test wrote.
"""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.seed import load_seeds


def _engine(client):
    return client.app.state.engine


def _seed_real(client) -> None:
    with Session(_engine(client)) as s:
        load_seeds(settings.seeds_dir, s)
        s.commit()


def _add_quotes(client, rows: list[dict]) -> None:
    """Insert QuoteDaily rows; each dict needs ticker/date/change_pct at least."""
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(models.QuoteDaily(**r))
        s.commit()


def _find(topics: list[dict], slug: str) -> dict:
    return next(t for t in topics if t["slug"] == slug)


def test_topics_card_shape_and_distinct_company_count(client):
    _seed_real(client)
    r = client.get("/api/topics?market=tw")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"topics", "rank"}

    sp = _find(body["topics"], "silicon-photonics")
    assert set(sp.keys()) == {
        "slug",
        "title",
        "description",
        "market_tab",
        "company_count",
        "verified_at",
        "change_pct_avg",
    }
    assert sp["title"] == "光通訊｜矽光子與 CPO"
    assert sp["market_tab"] == "tw"
    # 20 topic_companies rows but 3711/3363/3450 repeat across categories → 17 distinct
    assert sp["company_count"] == 17


def test_change_pct_avg_is_latest_day_mean_skipping_null(client):
    _seed_real(client)
    # Give three members known change_pct on their latest day. Include an older
    # date to prove only the newest day counts, one NULL change_pct (skipped),
    # and leave the other 14 members without any quotes (also skipped).
    _add_quotes(
        client,
        [
            # 2330: older day should be ignored; latest is 2026-07-11 → 2.0
            {"ticker": "2330", "date": "2026-07-10", "change_pct": 99.0},
            {"ticker": "2330", "date": "2026-07-11", "change_pct": 2.0},
            # 3443: latest 4.0
            {"ticker": "3443", "date": "2026-07-11", "change_pct": 4.0},
            # 3081: latest 6.0
            {"ticker": "3081", "date": "2026-07-11", "change_pct": 6.0},
            # 3450: latest day change_pct NULL → skipped by AVG
            {"ticker": "3450", "date": "2026-07-11", "change_pct": None},
        ],
    )
    r = client.get("/api/topics?market=tw")
    assert r.status_code == 200
    sp = _find(r.json()["topics"], "silicon-photonics")
    # mean of {2.0, 4.0, 6.0} = 4.0 (NULL + no-quote members skipped)
    assert sp["change_pct_avg"] == 4.0
    # distinct company count unchanged by quote insertion
    assert sp["company_count"] == 17


def _seed_three_topics_with_avgs(client) -> None:
    """Three tw topics whose single member fixes a known change_pct_avg."""
    with Session(_engine(client)) as s:
        for slug, title, ticker, pct in [
            ("topic-hi", "高", "AAA", 5.0),
            ("topic-mid", "中", "BBB", 1.0),
            ("topic-lo", "低", "CCC", -3.0),
        ]:
            s.add(models.Topic(slug=slug, title=title, market_tab="tw"))
            s.add(models.Company(ticker=ticker, name=ticker, market="TW"))
            s.add(
                models.TopicCompany(
                    topic_slug=slug, ticker=ticker, category="x"
                )
            )
            s.add(
                models.QuoteDaily(
                    ticker=ticker, date="2026-07-11", change_pct=pct
                )
            )
        s.commit()


def test_rank_up_is_top3_by_change_pct_desc(client):
    _seed_three_topics_with_avgs(client)
    r = client.get("/api/topics?market=tw")  # direction defaults to up
    assert r.status_code == 200
    rank = r.json()["rank"]
    assert [t["slug"] for t in rank] == ["topic-hi", "topic-mid", "topic-lo"]


def test_rank_down_is_ascending_top3(client):
    _seed_three_topics_with_avgs(client)
    r = client.get("/api/topics?market=tw&direction=down")
    assert r.status_code == 200
    rank = r.json()["rank"]
    assert [t["slug"] for t in rank] == ["topic-lo", "topic-mid", "topic-hi"]


def test_rank_caps_at_three(client):
    with Session(_engine(client)) as s:
        for i in range(5):
            slug = f"t{i}"
            s.add(models.Topic(slug=slug, title=slug, market_tab="tw"))
            s.add(models.Company(ticker=f"T{i}", name=slug, market="TW"))
            s.add(models.TopicCompany(topic_slug=slug, ticker=f"T{i}", category="x"))
            s.add(
                models.QuoteDaily(
                    ticker=f"T{i}", date="2026-07-11", change_pct=float(i)
                )
            )
        s.commit()
    rank = client.get("/api/topics?market=tw").json()["rank"]
    assert len(rank) == 3
    assert [t["slug"] for t in rank] == ["t4", "t3", "t2"]


def test_market_etf_returns_empty_topics(client):
    _seed_real(client)  # only seeds a tw topic
    r = client.get("/api/topics?market=etf")
    assert r.status_code == 200
    body = r.json()
    assert body["topics"] == []
    assert body["rank"] == []


def test_market_invalid_returns_422(client):
    r = client.get("/api/topics?market=xx")
    assert r.status_code == 422


def test_change_pct_avg_null_when_no_quotes(client):
    _seed_real(client)
    r = client.get("/api/topics?market=tw")
    assert r.status_code == 200
    sp = _find(r.json()["topics"], "silicon-photonics")
    assert sp["change_pct_avg"] is None
    assert sp["company_count"] == 17
    # rank still resolves without a crash — no non-null avgs → empty
    assert r.json()["rank"] == []
