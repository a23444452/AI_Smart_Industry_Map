"""全站搜尋 API 測試——GET /api/search.

回傳 ``{companies:[{ticker,name,market}], topics:[{slug,title}]}``。
公司：ticker 前綴 OR name 包含；題材：title 包含 OR slug 前綴。各 limit 10、
依 ticker/slug 升冪。q 必填、strip 後空→422、長度 >50→422。
"""

from sqlalchemy.orm import Session

from app.db import models


def _engine(client):
    return client.app.state.engine


def _add(client, rows: list) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(r)
        s.commit()


def _company(ticker, name, market="TW"):
    return models.Company(ticker=ticker, name=name, market=market)


def _topic(slug, title, market_tab="tw"):
    return models.Topic(slug=slug, title=title, market_tab=market_tab)


def test_search_empty_db(client):
    resp = client.get("/api/search", params={"q": "台積"})
    assert resp.status_code == 200
    assert resp.json() == {"companies": [], "topics": []}


def test_search_company_by_name_contains(client):
    _add(client, [_company("2330", "台積電"), _company("2317", "鴻海")])
    body = client.get("/api/search", params={"q": "台積"}).json()
    assert [c["ticker"] for c in body["companies"]] == ["2330"]
    assert body["companies"][0] == {"ticker": "2330", "name": "台積電", "market": "TW"}


def test_search_company_by_ticker_prefix(client):
    _add(client, [_company("2330", "台積電"), _company("2317", "鴻海")])
    body = client.get("/api/search", params={"q": "233"}).json()
    assert [c["ticker"] for c in body["companies"]] == ["2330"]


def test_search_company_ticker_prefix_not_infix(client):
    # ticker 為前綴比對——"330" 不應命中 "2330"。
    _add(client, [_company("2330", "台積電")])
    body = client.get("/api/search", params={"q": "330"}).json()
    assert body["companies"] == []


def test_search_topic_by_title_contains(client):
    _add(client, [_topic("silicon-photonics", "矽光子"), _topic("cpo", "CPO")])
    body = client.get("/api/search", params={"q": "矽光"}).json()
    assert [t["slug"] for t in body["topics"]] == ["silicon-photonics"]
    assert body["topics"][0] == {"slug": "silicon-photonics", "title": "矽光子"}


def test_search_topic_by_slug_prefix(client):
    _add(client, [_topic("silicon-photonics", "矽光子"), _topic("cpo", "CPO")])
    body = client.get("/api/search", params={"q": "silicon"}).json()
    assert [t["slug"] for t in body["topics"]] == ["silicon-photonics"]


def test_search_returns_both_companies_and_topics(client):
    _add(client, [_company("2330", "台積電")])
    _add(client, [_topic("tsmc-chain", "台積電供應鏈")])
    body = client.get("/api/search", params={"q": "台積"}).json()
    assert [c["ticker"] for c in body["companies"]] == ["2330"]
    assert [t["slug"] for t in body["topics"]] == ["tsmc-chain"]


def test_search_companies_sorted_by_ticker_asc(client):
    _add(
        client,
        [
            _company("2454", "聯發科A"),
            _company("2330", "聯發科B"),
            _company("3034", "聯發科C"),
        ],
    )
    body = client.get("/api/search", params={"q": "聯發科"}).json()
    assert [c["ticker"] for c in body["companies"]] == ["2330", "2454", "3034"]


def test_search_topics_sorted_by_slug_asc(client):
    _add(
        client,
        [
            _topic("z-topic", "共同題材"),
            _topic("a-topic", "共同題材"),
            _topic("m-topic", "共同題材"),
        ],
    )
    body = client.get("/api/search", params={"q": "共同題材"}).json()
    assert [t["slug"] for t in body["topics"]] == ["a-topic", "m-topic", "z-topic"]


def test_search_companies_limit_10(client):
    _add(client, [_company(f"{2000 + i}", "半導體") for i in range(15)])
    body = client.get("/api/search", params={"q": "半導體"}).json()
    assert len(body["companies"]) == 10
    # 升冪取前 10（ticker 2000..2009）。
    assert [c["ticker"] for c in body["companies"]] == [
        str(2000 + i) for i in range(10)
    ]


def test_search_topics_limit_10(client):
    _add(client, [_topic(f"t{i:02d}", "熱門") for i in range(15)])
    body = client.get("/api/search", params={"q": "熱門"}).json()
    assert len(body["topics"]) == 10
    assert [t["slug"] for t in body["topics"]] == [f"t{i:02d}" for i in range(10)]


def test_search_strips_query(client):
    _add(client, [_company("2330", "台積電")])
    body = client.get("/api/search", params={"q": "  台積  "}).json()
    assert [c["ticker"] for c in body["companies"]] == ["2330"]


def test_search_missing_q_422(client):
    resp = client.get("/api/search")
    assert resp.status_code == 422


def test_search_blank_q_422(client):
    resp = client.get("/api/search", params={"q": "   "})
    assert resp.status_code == 422


def test_search_too_long_q_422(client):
    resp = client.get("/api/search", params={"q": "台" * 51})
    assert resp.status_code == 422
