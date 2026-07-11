"""Tests for app.api.serializers.to_utc_iso.

時間戳一律輸出 ``YYYY-MM-DDTHH:MM:SSZ``（秒以下截斷、明示 UTC）；``None`` 原樣回傳。
"""

from datetime import UTC, datetime, timedelta, timezone

from app.api.serializers import to_utc_iso


def test_naive_datetime_formats_with_z_suffix():
    assert to_utc_iso(datetime(2026, 7, 11, 9, 2, 29)) == "2026-07-11T09:02:29Z"


def test_none_passes_through():
    assert to_utc_iso(None) is None


def test_microseconds_are_truncated():
    assert to_utc_iso(datetime(2026, 7, 11, 9, 2, 29, 987654)) == "2026-07-11T09:02:29Z"


def test_aware_datetime_is_converted_to_utc():
    # +08:00 local → subtract 8h to reach UTC wall clock.
    aware = datetime(2026, 7, 11, 17, 2, 29, tzinfo=timezone(timedelta(hours=8)))
    assert to_utc_iso(aware) == "2026-07-11T09:02:29Z"


def test_utc_aware_datetime_keeps_wall_clock():
    assert to_utc_iso(datetime(2026, 7, 11, 9, 2, 29, tzinfo=UTC)) == "2026-07-11T09:02:29Z"
