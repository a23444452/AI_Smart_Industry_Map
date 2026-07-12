"""Anthropic Messages API provider。

POST https://api.anthropic.com/v1/messages，回應取 content[0].text。任何失敗
（非 200／httpx 例外／回應缺欄）包成 LLMError，訊息**絕不含 api_key**。
"""

from __future__ import annotations

import httpx

from app.llm.provider import LLMError

_ENDPOINT = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 2048
_TIMEOUT_SECONDS = 60.0


class AnthropicProvider:
    """呼叫 Anthropic Messages API 的同步 provider。"""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def complete(self, system: str, user: str) -> str:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.post(_ENDPOINT, headers=headers, json=body)
        except httpx.HTTPError as exc:
            # 只帶例外型別名稱，不帶字串內容——避免任何機密外洩到訊息。
            raise LLMError("AI 服務連線失敗，請稍後再試") from exc

        if resp.status_code != 200:
            raise LLMError(
                f"AI 服務回應異常（HTTP {resp.status_code}），請稍後再試"
            )

        try:
            data = resp.json()
            text = data["content"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("AI 服務回傳格式異常，請稍後再試") from exc

        if not isinstance(text, str):
            raise LLMError("AI 服務回傳格式異常，請稍後再試")
        return text
