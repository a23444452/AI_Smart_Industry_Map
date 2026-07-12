"""AI 分析 service 測試——脈絡建構、prompt 產生、回應解析、背景執行。

provider 一律以 fake 注入（monkeypatch app.services.analysis.get_provider），
絕不打真實 API。DB 為每測獨立 tmp SQLite。
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, make_engine, utcnow
from app.db.models import (
    AiAnalysis,
    Company,
    Fundamental,
    InstitutionalFlow,
    MajorHolder,
    MopsAnnouncement,
    PerDaily,
    QuoteDaily,
    Topic,
    TopicCompany,
)
from app.llm import ASPECTS, LLMError
from app.services import analysis as svc


# ── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    return eng


def _d(days_ago: int) -> str:
    return (utcnow().date() - timedelta(days=days_ago)).isoformat()


def _seed_full(engine, ticker="2330"):
    """一檔資料齊全的標的（含各段落）。"""
    with Session(engine) as s:
        s.add(Company(ticker=ticker, name="台積電", market="TW", has_futures=True))
        # 近 5 個交易日 quotes（date 由新到舊會被查詢排序）
        closes = [1050, 1060, 1070, 1080, 1090]  # 對應 days_ago 8..0（越近越後）
        for i, close in enumerate(closes):
            s.add(
                QuoteDaily(
                    ticker=ticker,
                    date=_d(8 - i * 2),
                    close=close,
                    change_pct=1.0 + i,
                )
            )
        # 法人三筆
        for i in range(3):
            s.add(
                InstitutionalFlow(
                    ticker=ticker,
                    date=_d(i),
                    foreign_net=100 * (i + 1),
                    trust_net=10 * (i + 1),
                    dealer_net=-5 * (i + 1),
                )
            )
        # 大戶兩週
        s.add(MajorHolder(ticker=ticker, week=_d(7), ratio_400up=70.0))
        s.add(MajorHolder(ticker=ticker, week=_d(0), ratio_400up=72.5))
        # 基本面
        this_month = utcnow().date().strftime("%Y-%m")
        s.add(Fundamental(ticker=ticker, month=this_month, revenue=250_000_000, yoy=18.5))
        # 評價
        s.add(PerDaily(ticker=ticker, date=_d(0), per=22.0, pbr=6.5, dividend_yield=1.8))
        # 題材
        s.add(Topic(slug="silicon-photonics", title="矽光子", market_tab="tw"))
        s.add(
            TopicCompany(
                topic_slug="silicon-photonics",
                ticker=ticker,
                category="晶圓代工",
                role="龍頭",
            )
        )
        # 公告五筆以上（取近 5）
        for i in range(6):
            s.add(
                MopsAnnouncement(
                    ticker=ticker,
                    name="台積電",
                    category="財務數據",
                    title=f"公告標題 {i}",
                    published_at=utcnow() - timedelta(days=i),
                )
            )
        s.commit()


# ── 常數一致性 ──────────────────────────────────────────────────────────────
def test_modes_and_aspects_constants():
    assert svc.MODES == ("近期觀察", "中期展望", "全面檢視")
    # 單一來源：service 的 ASPECTS 即 app.llm 的 ASPECTS。
    assert svc.ASPECTS is ASPECTS
    assert set(svc.ASPECTS) == {"題材面", "基本面", "技術面", "籌碼面", "新聞面"}


# ── build_context ───────────────────────────────────────────────────────────
def test_build_context_full(engine):
    _seed_full(engine)
    with Session(engine) as s:
        ctx = svc.build_context(s, "2330")

    assert ctx["ticker"] == "2330"
    assert ctx["name"] == "台積電"

    q = ctx["quote"]
    assert q["count"] == 5
    assert q["latest_close"] == 1090
    assert q["high"] == 1090 and q["low"] == 1050
    # 近 5 日序列為時序（舊→新），最後一筆即最新收盤。
    assert q["recent_closes"][-1] == 1090
    assert len(q["recent_closes"]) == 5

    f = ctx["flows"]
    assert f["count"] == 3
    assert f["foreign_net_sum"] == 100 + 200 + 300
    assert f["trust_net_sum"] == 10 + 20 + 30
    assert f["dealer_net_sum"] == -(5 + 10 + 15)

    h = ctx["major_holder"]
    assert h["ratio_400up"] == 72.5
    assert h["prev_week_diff"] == 2.5

    assert ctx["fundamental"]["yoy"] == 18.5
    assert ctx["valuation"]["per"] == 22.0

    assert ctx["topics"] == [{"title": "矽光子", "roles": ["龍頭"]}]

    assert ctx["announcements"] == [f"公告標題 {i}" for i in range(5)]


def test_build_context_no_data(engine):
    # 公司存在但無任何市場資料——各段為 None／空 list，不炸。
    with Session(engine) as s:
        s.add(Company(ticker="9999", name="無資料公司", market="TW"))
        s.commit()
    with Session(engine) as s:
        ctx = svc.build_context(s, "9999")

    assert ctx["name"] == "無資料公司"
    assert ctx["quote"] is None
    assert ctx["flows"] is None
    assert ctx["major_holder"] is None
    assert ctx["fundamental"] is None
    assert ctx["valuation"] is None
    assert ctx["topics"] == []
    assert ctx["announcements"] == []


def test_build_context_unknown_ticker(engine):
    # 連 company 都不存在也不炸，name 為 None。
    with Session(engine) as s:
        ctx = svc.build_context(s, "0000")
    assert ctx["name"] is None
    assert ctx["quote"] is None
    assert ctx["topics"] == []


def test_build_context_flows_cover_20_trading_days(engine):
    # 25 筆日頻 flows 落在近 5–29 日曆日——其中 22–29 日已超出 queries.flows_by_ticker
    # 的 21 日曆日窗。合計須取「最新 20 筆」（含 21 日外的資料），證明籌碼段
    # 真的覆蓋近 20 個交易日，而非只有 ~5 筆。
    with Session(engine) as s:
        s.add(Company(ticker="3008", name="大立光", market="TW"))
        for i in range(5, 30):
            s.add(
                InstitutionalFlow(
                    ticker="3008", date=_d(i), foreign_net=1, trust_net=0, dealer_net=0
                )
            )
        s.commit()
    with Session(engine) as s:
        ctx = svc.build_context(s, "3008")
    assert ctx["flows"]["count"] == 20
    assert ctx["flows"]["foreign_net_sum"] == 20


def test_build_context_flows_cutoff_excludes_stale(engine):
    # 超出 40 日曆日下界的 flows 不入合計。
    with Session(engine) as s:
        s.add(Company(ticker="2317", name="鴻海", market="TW"))
        s.add(InstitutionalFlow(ticker="2317", date=_d(0), foreign_net=10))
        s.add(InstitutionalFlow(ticker="2317", date=_d(1), foreign_net=20))
        s.add(InstitutionalFlow(ticker="2317", date=_d(45), foreign_net=999))
        s.commit()
    with Session(engine) as s:
        ctx = svc.build_context(s, "2317")
    assert ctx["flows"]["count"] == 2
    assert ctx["flows"]["foreign_net_sum"] == 30


def test_build_context_recent_closes_filters_none(engine):
    # 近 5 日內有缺值 close → recent_closes 過濾（與 closes 口徑一致）。
    with Session(engine) as s:
        s.add(Company(ticker="2454", name="聯發科", market="TW"))
        s.add(QuoteDaily(ticker="2454", date=_d(2), close=1400, change_pct=1.0))
        s.add(QuoteDaily(ticker="2454", date=_d(1), close=None, change_pct=None))
        s.add(QuoteDaily(ticker="2454", date=_d(0), close=1450, change_pct=2.0))
        s.commit()
    with Session(engine) as s:
        ctx = svc.build_context(s, "2454")
    assert ctx["quote"]["recent_closes"] == [1400, 1450]


def test_build_context_single_holder_no_diff(engine):
    with Session(engine) as s:
        s.add(Company(ticker="1111", name="單週大戶", market="TW"))
        s.add(MajorHolder(ticker="1111", week=_d(0), ratio_400up=55.0))
        s.commit()
    with Session(engine) as s:
        ctx = svc.build_context(s, "1111")
    assert ctx["major_holder"]["ratio_400up"] == 55.0
    assert ctx["major_holder"]["prev_week_diff"] is None


# ── build_prompt ────────────────────────────────────────────────────────────
def _ctx(engine, ticker="2330"):
    with Session(engine) as s:
        return svc.build_context(s, ticker)


def test_build_prompt_system_lists_keys_and_no_fence():
    system, _ = svc.build_prompt(
        {
            "ticker": "2330",
            "name": "台積電",
            "quote": None,
            "flows": None,
            "major_holder": None,
            "fundamental": None,
            "valuation": None,
            "topics": [],
            "announcements": [],
        },
        "全面檢視",
    )
    for aspect in ASPECTS:
        assert aspect in system
    assert "scores" in system and "reasons" in system and "summary" in system
    # 明確要求不要 markdown fence。
    assert "```" in system  # 指令中提及 ``` 是為了說「不要」


def test_build_prompt_modes_differ(engine):
    _seed_full(engine)
    ctx = _ctx(engine)
    users = {mode: svc.build_prompt(ctx, mode)[1] for mode in svc.MODES}
    # 三 mode 的 user 內容彼此相異。
    assert len(set(users.values())) == 3
    assert "技術" in users["近期觀察"] and "籌碼" in users["近期觀察"]
    assert "基本" in users["中期展望"] and "題材" in users["中期展望"]
    assert "均衡" in users["全面檢視"]


def test_build_prompt_only_lists_sections_with_data(engine):
    # 無資料標的：user 不應出現各資料段標題。
    with Session(engine) as s:
        s.add(Company(ticker="9999", name="無資料公司", market="TW"))
        s.commit()
    ctx = _ctx(engine, "9999")
    _, user = svc.build_prompt(ctx, "全面檢視")
    assert "【近期行情】" not in user
    assert "【法人籌碼】" not in user
    assert "9999" in user  # 標的識別仍在


def test_build_prompt_full_has_sections(engine):
    _seed_full(engine)
    ctx = _ctx(engine)
    _, user = svc.build_prompt(ctx, "全面檢視")
    for header in ["【近期行情】", "【法人籌碼】", "【大戶持股】", "【基本面】",
                   "【評價】", "【所屬題材】", "【近期重大訊息】"]:
        assert header in user


def test_build_prompt_unknown_mode_raises():
    with pytest.raises(ValueError):
        svc.build_prompt({"ticker": "x", "name": None, "quote": None,
                          "flows": None, "major_holder": None, "fundamental": None,
                          "valuation": None, "topics": [], "announcements": []},
                         "不存在的模式")


# ── parse_llm_response ──────────────────────────────────────────────────────
def _valid_payload() -> dict:
    return {
        "scores": {a: 80 for a in ASPECTS},
        "reasons": {a: ["理由一。", "理由二。"] for a in ASPECTS},
        "summary": "綜合結論一句話。",
    }


def test_parse_success():
    text = json.dumps(_valid_payload(), ensure_ascii=False)
    out = svc.parse_llm_response(text)
    assert set(out["scores"]) == set(ASPECTS)
    assert out["summary"] == "綜合結論一句話。"


def test_parse_strips_json_fence():
    text = "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    out = svc.parse_llm_response(text)
    assert set(out["scores"]) == set(ASPECTS)


def test_parse_strips_bare_fence():
    text = "```\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    out = svc.parse_llm_response(text)
    assert set(out["reasons"]) == set(ASPECTS)


def test_parse_invalid_json_raises():
    with pytest.raises(LLMError):
        svc.parse_llm_response("這不是 JSON")


def test_parse_missing_score_key_raises():
    payload = _valid_payload()
    del payload["scores"]["新聞面"]
    with pytest.raises(LLMError):
        svc.parse_llm_response(json.dumps(payload, ensure_ascii=False))


def test_parse_score_out_of_range_raises():
    payload = _valid_payload()
    payload["scores"]["技術面"] = 150
    with pytest.raises(LLMError):
        svc.parse_llm_response(json.dumps(payload, ensure_ascii=False))


def test_parse_score_not_int_raises():
    payload = _valid_payload()
    payload["scores"]["技術面"] = 80.5
    with pytest.raises(LLMError):
        svc.parse_llm_response(json.dumps(payload, ensure_ascii=False))


def test_parse_empty_reasons_raises():
    payload = _valid_payload()
    payload["reasons"]["籌碼面"] = []
    with pytest.raises(LLMError):
        svc.parse_llm_response(json.dumps(payload, ensure_ascii=False))


def test_parse_summary_missing_raises():
    payload = _valid_payload()
    payload["summary"] = ""
    with pytest.raises(LLMError):
        svc.parse_llm_response(json.dumps(payload, ensure_ascii=False))


def test_parse_error_message_excludes_full_text():
    huge = "x" * 5000
    with pytest.raises(LLMError) as ei:
        svc.parse_llm_response(huge)
    assert huge not in str(ei.value)


# ── run_analysis ────────────────────────────────────────────────────────────
class _FakeProvider:
    """依序回傳／拋錯的假 provider；記錄呼叫次數。"""

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        item = self._behaviors.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # 重試 sleep 不拖慢測試。
    monkeypatch.setattr(svc.time, "sleep", lambda *_a, **_k: None)


def _new_analysis(engine, ticker="2330", mode="全面檢視") -> int:
    with Session(engine) as s:
        row = AiAnalysis(ticker=ticker, mode=mode, status="pending")
        s.add(row)
        s.commit()
        return row.id


def _inject(monkeypatch, provider):
    monkeypatch.setattr(svc, "get_provider", lambda _settings: provider)


def test_run_analysis_success(engine, monkeypatch):
    _seed_full(engine)
    aid = _new_analysis(engine)
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    _inject(monkeypatch, _FakeProvider([payload]))

    svc.run_analysis(engine, aid)

    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
    assert row.status == "done"
    assert set(row.scores) == set(ASPECTS)
    assert row.reasons["題材面"] == ["理由一。", "理由二。"]
    assert row.summary == "綜合結論一句話。"
    assert row.total == 80.0  # 五個 80 等權平均
    assert row.model == "mock"
    assert row.error is None


def test_run_analysis_retries_once_then_succeeds(engine, monkeypatch):
    _seed_full(engine)
    aid = _new_analysis(engine)
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = _FakeProvider([LLMError("暫時失敗"), payload])
    _inject(monkeypatch, provider)

    svc.run_analysis(engine, aid)

    assert provider.calls == 2
    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
    assert row.status == "done"
    assert row.error is None


def test_run_analysis_parse_failure_counts_as_attempt(engine, monkeypatch):
    # 第一次回傳壞 JSON（parse 失敗＝一次失敗），第二次成功。
    _seed_full(engine)
    aid = _new_analysis(engine)
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = _FakeProvider(["不是 JSON", payload])
    _inject(monkeypatch, provider)

    svc.run_analysis(engine, aid)

    assert provider.calls == 2
    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
    assert row.status == "done"


def test_run_analysis_two_failures(engine, monkeypatch):
    _seed_full(engine)
    aid = _new_analysis(engine)
    provider = _FakeProvider([LLMError("失敗一"), LLMError("失敗二")])
    _inject(monkeypatch, provider)

    svc.run_analysis(engine, aid)

    assert provider.calls == 2
    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
    assert row.status == "failed"
    assert row.error
    assert row.scores is None


def test_run_analysis_missing_row_no_raise(engine, monkeypatch):
    # 列不存在——log error 後 return，絕不 raise。
    called = _FakeProvider([json.dumps(_valid_payload())])
    _inject(monkeypatch, called)
    svc.run_analysis(engine, 999_999)  # 不存在的 id
    assert called.calls == 0  # 未進入分析流程


def test_run_analysis_skips_non_pending(engine, monkeypatch):
    # 非 pending（已被處理過）→ 不呼叫 provider、狀態不變——防背景任務重複執行。
    _seed_full(engine)
    aid = _new_analysis(engine)
    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
        row.status = "done"
        s.commit()
    provider = _FakeProvider([json.dumps(_valid_payload())])
    _inject(monkeypatch, provider)

    svc.run_analysis(engine, aid)

    assert provider.calls == 0
    with Session(engine) as s:
        assert s.get(AiAnalysis, aid).status == "done"


def test_run_analysis_never_raises_on_provider_config_error(engine, monkeypatch):
    _seed_full(engine)
    aid = _new_analysis(engine)

    def _boom(_settings):
        raise ValueError("provider 設定錯誤")

    monkeypatch.setattr(svc, "get_provider", _boom)
    # 不得 raise。
    svc.run_analysis(engine, aid)
    with Session(engine) as s:
        row = s.get(AiAnalysis, aid)
    assert row.status == "failed"
    assert row.error
