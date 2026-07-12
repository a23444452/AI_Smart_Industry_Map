"""OpenAI 相容 Chat Completions provider。

適用任何提供 /chat/completions 的相容端點（本地 llama.cpp、vLLM、OpenRouter…）。
POST {base_url}/chat/completions，Bearer auth，回應取 choices[0].message.content。
任何失敗包成 LLMError，訊息**絕不含 api_key**。
"""

from __future__ import annotations

import httpx

from app.llm.provider import LLMError

_MAX_TOKENS = 2048
_TIMEOUT_SECONDS = 60.0


class OpenAICompatProvider:
    """呼叫 OpenAI 相容 Chat Completions 端點的同步 provider。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def complete(self, system: str, user: str) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMError("AI 服務連線失敗，請稍後再試") from exc

        if resp.status_code != 200:
            raise LLMError(
                f"AI 服務回應異常（HTTP {resp.status_code}），請稍後再試"
            )

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("AI 服務回傳格式異常，請稍後再試") from exc

        if not isinstance(text, str):
            raise LLMError("AI 服務回傳格式異常，請稍後再試")
        return text
