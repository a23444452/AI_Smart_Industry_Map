"""Provider 契約：LLMError 與 LLMProvider Protocol。

全後端 sync，故 complete 是同步方法（不用 async）。回傳原始文字；把文字解析成
結構化結果（JSON）是 service 層的責任，不在此層。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """LLM 呼叫失敗。

    訊息對使用者友善（中文），且**絕不含 api_key 或其他機密**——上層可直接把
    str(err) 顯示給使用者或寫進 log。
    """


@runtime_checkable
class LLMProvider(Protocol):
    """同步文字補全介面。實作者：Anthropic／OpenAI 相容／Mock。"""

    def complete(self, system: str, user: str) -> str:
        """送出 system＋user 提示，回傳模型的原始文字回覆。

        失敗（連線錯誤、非 200、回應缺欄）一律 raise LLMError。
        """
        ...
