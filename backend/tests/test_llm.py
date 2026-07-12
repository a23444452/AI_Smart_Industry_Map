"""LLM provider 層測試——全 mock httpx，絕不打真實 API。

涵蓋：兩真 provider 各（成功取文字／非 200 帶狀態碼／httpx 例外／回應缺欄）、
錯誤訊息不含 api_key、mock 確定性與 schema、factory 四路徑與 provider_label。
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.llm import (
    AnthropicProvider,
    LLMError,
    MockProvider,
    OpenAICompatProvider,
    get_provider,
    provider_label,
)

_SECRET_KEY = "sk-ant-super-secret-KEY-do-not-leak-42"


def _mock_post(monkeypatch, *, status_code=200, content=b"", raise_exc=None):
    """把 httpx.Client.post 換成回傳罐頭回應（或拋例外）的假函式。"""

    def fake_post(self, url, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return httpx.Response(
            status_code,
            content=content,
            headers={"Content-Type": "application/json"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)


def _json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# --- Anthropic -------------------------------------------------------------


def test_anthropic_success_returns_text(monkeypatch):
    _mock_post(
        monkeypatch,
        content=_json_bytes({"content": [{"type": "text", "text": "hello 世界"}]}),
    )
    provider = AnthropicProvider(_SECRET_KEY, "claude-sonnet-5")
    assert provider.complete("sys", "usr") == "hello 世界"


def test_anthropic_non_200_raises_with_status(monkeypatch):
    _mock_post(monkeypatch, status_code=429, content=b'{"error": "rate limited"}')
    provider = AnthropicProvider(_SECRET_KEY, "claude-sonnet-5")
    with pytest.raises(LLMError) as excinfo:
        provider.complete("sys", "usr")
    assert "429" in str(excinfo.value)


def test_anthropic_httpx_exception_wrapped(monkeypatch):
    _mock_post(monkeypatch, raise_exc=httpx.ConnectError("dns fail"))
    provider = AnthropicProvider(_SECRET_KEY, "claude-sonnet-5")
    with pytest.raises(LLMError):
        provider.complete("sys", "usr")


def test_anthropic_missing_field_raises(monkeypatch):
    _mock_post(monkeypatch, content=_json_bytes({"unexpected": "shape"}))
    provider = AnthropicProvider(_SECRET_KEY, "claude-sonnet-5")
    with pytest.raises(LLMError):
        provider.complete("sys", "usr")


# --- OpenAI 相容 -----------------------------------------------------------


def test_openai_success_returns_text(monkeypatch):
    _mock_post(
        monkeypatch,
        content=_json_bytes(
            {"choices": [{"message": {"role": "assistant", "content": "回覆內容"}}]}
        ),
    )
    provider = OpenAICompatProvider("https://api.x.test/v1/", _SECRET_KEY, "gpt-x")
    assert provider.complete("sys", "usr") == "回覆內容"


def test_openai_non_200_raises_with_status(monkeypatch):
    _mock_post(monkeypatch, status_code=500, content=b'{"error": "boom"}')
    provider = OpenAICompatProvider("https://api.x.test/v1", _SECRET_KEY, "gpt-x")
    with pytest.raises(LLMError) as excinfo:
        provider.complete("sys", "usr")
    assert "500" in str(excinfo.value)


def test_openai_httpx_exception_wrapped(monkeypatch):
    _mock_post(monkeypatch, raise_exc=httpx.ReadTimeout("slow"))
    provider = OpenAICompatProvider("https://api.x.test/v1", _SECRET_KEY, "gpt-x")
    with pytest.raises(LLMError):
        provider.complete("sys", "usr")


def test_openai_missing_field_raises(monkeypatch):
    _mock_post(monkeypatch, content=_json_bytes({"choices": []}))
    provider = OpenAICompatProvider("https://api.x.test/v1", _SECRET_KEY, "gpt-x")
    with pytest.raises(LLMError):
        provider.complete("sys", "usr")


# --- 錯誤訊息絕不含 api_key ------------------------------------------------


def test_anthropic_error_never_contains_key(monkeypatch):
    _mock_post(monkeypatch, raise_exc=httpx.ConnectError(_SECRET_KEY))
    provider = AnthropicProvider(_SECRET_KEY, "claude-sonnet-5")
    with pytest.raises(LLMError) as excinfo:
        provider.complete("sys", "usr")
    assert _SECRET_KEY not in str(excinfo.value)


def test_openai_error_never_contains_key(monkeypatch):
    _mock_post(monkeypatch, status_code=401, content=_SECRET_KEY.encode())
    provider = OpenAICompatProvider("https://api.x.test/v1", _SECRET_KEY, "gpt-x")
    with pytest.raises(LLMError) as excinfo:
        provider.complete("sys", "usr")
    assert _SECRET_KEY not in str(excinfo.value)


# --- Mock 確定性與 schema --------------------------------------------------


def test_mock_deterministic_same_user():
    p = MockProvider()
    assert p.complete("A", "同一輸入") == p.complete("不同 system", "同一輸入")


def test_mock_different_user_differs():
    p = MockProvider()
    assert p.complete("s", "輸入甲") != p.complete("s", "輸入乙")


def test_mock_schema_valid_json_five_keys():
    p = MockProvider()
    data = json.loads(p.complete("s", "台積電 2330"))
    assert set(data.keys()) == {"scores", "reasons", "summary"}
    assert len(data["scores"]) == 5
    assert len(data["reasons"]) == 5
    assert set(data["scores"]) == set(data["reasons"])
    for score in data["scores"].values():
        assert isinstance(score, int) and 60 <= score <= 95
    for reason in data["reasons"].values():
        assert "（模擬分析）" in reason
    assert isinstance(data["summary"], str) and data["summary"]


# --- factory 四路徑 + provider_label --------------------------------------


def _settings(**kw) -> SimpleNamespace:
    base = dict(
        llm_provider="mock",
        llm_model="claude-sonnet-5",
        llm_api_key="",
        llm_base_url="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_factory_mock():
    assert isinstance(get_provider(_settings(llm_provider="mock")), MockProvider)


def test_factory_anthropic_missing_key_raises():
    with pytest.raises(ValueError):
        get_provider(_settings(llm_provider="anthropic", llm_api_key=""))


def test_factory_anthropic_ok():
    provider = get_provider(_settings(llm_provider="anthropic", llm_api_key="k"))
    assert isinstance(provider, AnthropicProvider)


def test_factory_openai_missing_base_url_raises():
    with pytest.raises(ValueError):
        get_provider(
            _settings(llm_provider="openai_compat", llm_base_url="", llm_api_key="k")
        )


def test_factory_openai_missing_key_raises():
    with pytest.raises(ValueError):
        get_provider(
            _settings(
                llm_provider="openai_compat",
                llm_base_url="https://x.test",
                llm_api_key="",
            )
        )


def test_factory_openai_ok():
    provider = get_provider(
        _settings(
            llm_provider="openai_compat",
            llm_base_url="https://x.test",
            llm_api_key="k",
            llm_model="gpt-x",
        )
    )
    assert isinstance(provider, OpenAICompatProvider)


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_provider(_settings(llm_provider="nope"))


def test_provider_label_variants():
    assert provider_label(_settings(llm_provider="mock")) == "mock"
    assert (
        provider_label(_settings(llm_provider="anthropic", llm_model="claude-sonnet-5"))
        == "anthropic:claude-sonnet-5"
    )
    assert (
        provider_label(_settings(llm_provider="openai_compat", llm_model="gpt-x"))
        == "openai_compat:gpt-x"
    )
