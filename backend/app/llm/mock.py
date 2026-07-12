"""確定性 Mock provider——零設定、不打網路。

輸出 schema 是三個 provider 的**契約基準**（真 provider 的 system prompt 會要求
模型輸出同一結構）：

    {
      "scores":  {<五面向>: int 60-95, ...},
      "reasons": {<五面向>: list[str]（每面向 2 句、含「（模擬分析）」）, ...},
      "summary": str（一句）
    }

分數純由 ``sha256(user)`` 派生，故同一 user 恆得同一輸出、不同 user 得不同輸出——
方便前端與 service 層在無金鑰環境下穩定測試。
"""

from __future__ import annotations

import hashlib
import json

# 計畫 Task 1（AiAnalysis 註解）明定的五面向鍵名——與原站的分析框架一致。
# 此順序即 seed byte 的取用順序。
_ASPECTS = ("題材面", "基本面", "技術面", "籌碼面", "新聞面")

# 分數落點 60-95（含），共 36 個可能值。
_SCORE_MIN = 60
_SCORE_SPAN = 36


def _level(score: int) -> str:
    if score >= 85:
        return "偏強"
    if score >= 75:
        return "中性偏強"
    return "中性"


class MockProvider:
    """確定性模擬 provider——不需任何金鑰、不打真實 API。"""

    def complete(self, system: str, user: str) -> str:
        seed = hashlib.sha256(user.encode()).digest()

        scores: dict[str, int] = {}
        reasons: dict[str, list[str]] = {}
        for i, aspect in enumerate(_ASPECTS):
            score = _SCORE_MIN + seed[i] % _SCORE_SPAN
            scores[aspect] = score
            reasons[aspect] = [
                f"{aspect}評分為 {score}，屬於{_level(score)}區間（模擬分析）。",
                "此為依輸入內容雜湊派生的確定性結果，非真實 AI 判斷。",
            ]

        avg = round(sum(scores.values()) / len(scores))
        summary = (
            f"綜合五面向平均 {avg} 分，本結果為模擬分析輸出，"
            "僅供介面串接與測試使用。"
        )

        return json.dumps(
            {"scores": scores, "reasons": reasons, "summary": summary},
            ensure_ascii=False,
        )
