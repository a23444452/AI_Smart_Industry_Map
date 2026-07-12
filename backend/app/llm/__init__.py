"""LLM provider 層。

三個 provider（anthropic／openai_compat／mock）共用同一契約：同步
``complete(system, user) -> str``，回傳原始文字（JSON 解析由 service 層負責）。
此層獨立，不 import pipeline 的任何東西。錯誤一律包成 LLMError，且訊息絕不
含 api_key 等機密。
"""

from app.llm.anthropic_ import AnthropicProvider
from app.llm.factory import get_provider, provider_label
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.provider import LLMError, LLMProvider

__all__ = [
    "AnthropicProvider",
    "LLMError",
    "LLMProvider",
    "MockProvider",
    "OpenAICompatProvider",
    "get_provider",
    "provider_label",
]
