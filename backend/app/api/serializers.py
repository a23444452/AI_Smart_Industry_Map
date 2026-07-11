"""API 序列化輔助：時間戳一律輸出 UTC ISO8601 帶 ``Z`` 尾碼。

本專案 datetime 一律存 naive UTC（見 ``app.db.base._utcnow``），Pydantic 對
naive datetime 自動序列化不會帶時區標記，前端無從得知是 UTC。此 helper 統一把
datetime 轉為 ``YYYY-MM-DDTHH:MM:SSZ``（秒以下截斷），讓 API 契約明確標示 UTC。
"""

from datetime import UTC, datetime


def to_utc_iso(dt: datetime | None) -> str | None:
    """把 datetime 轉為 ``YYYY-MM-DDTHH:MM:SSZ``；``None`` 原樣回傳。

    naive datetime 視為 UTC（本專案慣例）；aware datetime 先轉 UTC 再輸出。
    秒以下（microsecond）一律截斷，確保格式穩定。
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
