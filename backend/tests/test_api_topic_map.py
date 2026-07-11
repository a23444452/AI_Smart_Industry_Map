"""Tests for GET /api/topics/{slug}/map — 產業鏈地圖（上中下游 × 分類 × 公司卡片）.

`client` fixture 跑真實 lifespan 對 per-test tmp DB，並把 engine 掛在
`app.state.engine`；測試以真實 seeds（load_seeds）建骨架，再手插已知
quotes / institutional_flows，API 讀到的就是測試寫入的。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.base import _utcnow
from app.db.seed import load_seeds

SLUG = "silicon-photonics"


def _d(days_ago: int) -> str:
    """今日（UTC）往回 ``days_ago`` 日曆日的 ISO 日期。

    flows 查詢有時間下界（21 日曆日），固定日期會隨真實時間掉出視窗，
    以「今日」為基準避免測試變定時炸彈。
    """
    return (_utcnow().date() - timedelta(days=days_ago)).isoformat()


def _engine(client):
    return client.app.state.engine


def _seed_real(client) -> None:
    with Session(_engine(client)) as s:
        load_seeds(settings.seeds_dir, s)
        s.commit()


def _add_quotes(client, rows: list[dict]) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(models.QuoteDaily(**r))
        s.commit()


def _add_flows(client, rows: list[dict]) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(models.InstitutionalFlow(**r))
        s.commit()


def _map(client) -> dict:
    r = client.get(f"/api/topics/{SLUG}/map")
    assert r.status_code == 200
    return r.json()


def _level(body: dict, name: str) -> dict:
    return next(lvl for lvl in body["levels"] if lvl["level"] == name)


def _category(level: dict, name: str) -> dict:
    return next(c for c in level["categories"] if c["name"] == name)


def _company(category: dict, ticker: str) -> dict:
    return next(co for co in category["companies"] if co["ticker"] == ticker)


# ── case 1: 頂層結構與 levels 順序 ────────────────────────────────────────
def test_map_top_level_structure(client):
    _seed_real(client)
    body = _map(client)
    assert set(body.keys()) == {"slug", "title", "levels"}
    assert body["slug"] == SLUG
    assert body["title"] == "光通訊｜矽光子與 CPO"
    assert [lvl["level"] for lvl in body["levels"]] == ["上游", "中游", "下游"]


# ── case 2: 分類順序照 chain_meta 骨架 ────────────────────────────────────
def test_category_order_follows_chain_meta(client):
    _seed_real(client)
    body = _map(client)
    up = _level(body, "上游")
    assert [c["name"] for c in up["categories"]] == [
        "矽光子製程代工平台",
        "外部光源與雷射引擎",
        "高密度光纖套件與被動元件",
    ]
    mid = _level(body, "中游")
    assert [c["name"] for c in mid["categories"]] == [
        "CPO 共同封裝與異質整合",
        "高密度光纖陣列 (FAU)",
        "矽光子測試介面與檢測",
    ]


# ── case 2b: 下游 2 個 placeholder 分類 → companies:[]、placeholder:true ───
def test_downstream_placeholders_are_empty(client):
    _seed_real(client)
    down = _level(_map(client), "下游")
    assert [c["name"] for c in down["categories"]] == [
        "CPO 整合交換器系統",
        "AI 算力單元與高效能運算",
    ]
    assert len(down["categories"]) == 2
    for cat in down["categories"]:
        assert cat["placeholder"] is True
        assert cat["companies"] == []
        assert cat["desc"]  # 描述仍帶出


# ── case 2c: 非 placeholder 分類 flag=false 且有公司 ──────────────────────
def test_non_placeholder_category_flag_false(client):
    _seed_real(client)
    plat = _category(_level(_map(client), "上游"), "矽光子製程代工平台")
    assert plat["placeholder"] is False
    assert plat["desc"]
    assert {c["ticker"] for c in plat["companies"]} == {"2330", "3443"}


# ── case 3: 同 ticker 跨分類各自出現 ──────────────────────────────────────
def test_same_ticker_appears_in_multiple_categories(client):
    _seed_real(client)
    body = _map(client)
    mid = _level(body, "中游")
    cpo = _category(mid, "CPO 共同封裝與異質整合")
    test_iface = _category(mid, "矽光子測試介面與檢測")
    # 3711 同時在中游兩個分類
    assert _company(cpo, "3711")["ticker"] == "3711"
    assert _company(test_iface, "3711")["ticker"] == "3711"
    # 3450 跨上游（外部光源）＋中游（CPO）
    els = _category(_level(body, "上游"), "外部光源與雷射引擎")
    assert _company(els, "3450")["ticker"] == "3450"
    assert _company(cpo, "3450")["ticker"] == "3450"


# ── case 3b: 公司卡片欄位齊全且與 seed 一致 ───────────────────────────────
def test_company_card_keys_and_seed_fields(client):
    _seed_real(client)
    plat = _category(_level(_map(client), "上游"), "矽光子製程代工平台")
    c = _company(plat, "2330")
    assert set(c.keys()) == {
        "ticker",
        "name",
        "role",
        "relevance",
        "close",
        "change_pct",
        "badges",
    }
    assert c["name"] == "台積電"
    assert c["role"] == "龍頭"
    assert c["relevance"] == "高"


# ── case 4: 有股票期貨徽章（正反例）──────────────────────────────────────
def test_futures_badge_positive_and_negative(client):
    _seed_real(client)
    body = _map(client)
    up = _level(body, "上游")
    # 2330 has_futures=true → 有徽章
    c2330 = _company(_category(up, "矽光子製程代工平台"), "2330")
    assert "有股票期貨" in c2330["badges"]
    # 3450 無 has_futures → 無徽章
    c3450 = _company(_category(up, "外部光源與雷射引擎"), "3450")
    assert "有股票期貨" not in c3450["badges"]


# ── case 4b: 法人徽章取「依 date 降冪第一筆」net>0（正反例）───────────────
def test_flow_badges_use_latest_record_only(client):
    _seed_real(client)
    _add_flows(
        client,
        [
            # 2330：較舊一筆外資大買（若誤取則會誤判），最新一筆外資賣、投信買
            {"ticker": "2330", "date": _d(5), "foreign_net": 999999, "trust_net": -9},
            {"ticker": "2330", "date": _d(0), "foreign_net": -100, "trust_net": 50},
            # 3081（has_futures）：最新一筆外資、投信皆買超
            {"ticker": "3081", "date": _d(0), "foreign_net": 100, "trust_net": 100},
            # 4979（無 futures）：最新一筆皆 ≤0 → 無法人徽章
            {"ticker": "4979", "date": _d(0), "foreign_net": 0, "trust_net": -5},
        ],
    )
    body = _map(client)
    up = _level(body, "上游")
    plat = _category(up, "矽光子製程代工平台")
    els = _category(up, "外部光源與雷射引擎")

    # 2330：最新一筆 foreign_net=-100（無外資買超）、trust_net=50（投信買超）＋期貨
    assert _company(plat, "2330")["badges"] == ["有股票期貨", "投信買超"]
    # 3081：期貨＋外資買超＋投信買超（徽章順序固定）
    assert _company(els, "3081")["badges"] == [
        "有股票期貨",
        "外資買超",
        "投信買超",
    ]
    # 4979：無徽章
    assert _company(els, "4979")["badges"] == []


# ── case 4c: 無 flows → 無法人徽章（僅可能保留期貨徽章）────────────────────
def test_no_flows_means_no_flow_badges(client):
    _seed_real(client)
    body = _map(client)
    up = _level(body, "上游")
    # 2330 期貨徽章仍在，但無外資/投信徽章
    assert _company(_category(up, "矽光子製程代工平台"), "2330")["badges"] == [
        "有股票期貨"
    ]
    # 3450 無期貨、無 flows → 空
    assert _company(_category(up, "外部光源與雷射引擎"), "3450")["badges"] == []


# ── case 5: close/change_pct 取最新日、change_pct round 2 ─────────────────
def test_close_and_change_pct_from_latest_quote_rounded(client):
    _seed_real(client)
    _add_quotes(
        client,
        [
            # 舊日應被忽略
            {"ticker": "2330", "date": _d(1), "close": 100.0, "change_pct": 9.0},
            {
                "ticker": "2330",
                "date": _d(0),
                "close": 2415.0,
                "change_pct": -2.028397565922921,
            },
        ],
    )
    c2330 = _company(
        _category(_level(_map(client), "上游"), "矽光子製程代工平台"), "2330"
    )
    assert c2330["close"] == 2415.0
    assert c2330["change_pct"] == -2.03


def test_no_quotes_close_and_change_pct_null(client):
    _seed_real(client)
    c2330 = _company(
        _category(_level(_map(client), "上游"), "矽光子製程代工平台"), "2330"
    )
    assert c2330["close"] is None
    assert c2330["change_pct"] is None


# ── case 6: 未知 slug → 404 統一錯誤格式 ──────────────────────────────────
def test_unknown_slug_returns_404(client):
    _seed_real(client)
    r = client.get("/api/topics/does-not-exist/map")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "找不到此題材"}}


# ── case 6b: chain_meta 為 null 的 topic → levels: [] 不炸 ─────────────────
def test_null_chain_meta_yields_empty_levels(client):
    with Session(_engine(client)) as s:
        s.add(
            models.Topic(
                slug="bare",
                title="裸題材",
                market_tab="tw",
                chain_meta=None,
            )
        )
        s.commit()
    r = client.get("/api/topics/bare/map")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "bare"
    assert body["title"] == "裸題材"
    assert body["levels"] == []
