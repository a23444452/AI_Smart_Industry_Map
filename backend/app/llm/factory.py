"""依 settings 建立 provider，並產生寫入 ai_analyses.model 的標籤字串。

get_provider 對缺設定（anthropic 缺金鑰、openai_compat 缺 base_url／金鑰、未知
provider）raise ValueError（清楚中文訊息），讓上層在啟動或請求時即早失敗。
"""

from __future__ import annotations

from app.llm.anthropic_ import AnthropicProvider
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.provider import LLMProvider


def get_provider(settings) -> LLMProvider:
    """依 settings.llm_provider 回傳對應 provider。

    Raises ValueError（中文）當 provider 未知，或所選 provider 缺必要設定。
    """
    provider = settings.llm_provider

    if provider == "mock":
        return MockProvider()

    if provider == "anthropic":
        if not settings.llm_api_key:
            raise ValueError(
                "使用 anthropic provider 需設定 AISM_LLM_API_KEY（API 金鑰）"
            )
        return AnthropicProvider(settings.llm_api_key, settings.llm_model)

    if provider == "openai_compat":
        if not settings.llm_base_url:
            raise ValueError(
                "使用 openai_compat provider 需設定 AISM_LLM_BASE_URL（端點網址）"
            )
        if not settings.llm_api_key:
            raise ValueError(
                "使用 openai_compat provider 需設定 AISM_LLM_API_KEY（API 金鑰）"
            )
        return OpenAICompatProvider(
            settings.llm_base_url, settings.llm_api_key, settings.llm_model
        )

    raise ValueError(f"未知的 LLM provider：{provider!r}")


def provider_label(settings) -> str:
    """回傳寫入 ai_analyses.model 的標籤，例：

    "mock"／"anthropic:claude-sonnet-5"／"openai_compat:<model>"。
    """
    provider = settings.llm_provider
    if provider == "mock":
        return "mock"
    return f"{provider}:{settings.llm_model}"
