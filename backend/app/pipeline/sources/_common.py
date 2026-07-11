"""Shared helpers for TWSE/TPEx source clients.

Scope (Task 4): fetch + parse into a neutral dict only. No DB, no filtering,
no persistence — the job layer (Task 6) owns those.
"""

from __future__ import annotations

import ssl
from datetime import date

import httpx

TIMEOUT_SECONDS = 30.0
_USER_AGENT = "aism/1.0 (+industry-map)"

# Values the exchanges use for "no trade / suspended" in a numeric column.
_EMPTY_TOKENS = {"", "--", "-", "null", "none"}


class SourceFetchError(RuntimeError):
    """A source endpoint was unreachable or returned a non-200 response.

    Carries a user-friendly (Chinese) message and, when available, the HTTP
    status code. The message deliberately avoids leaking internal detail.
    """

    def __init__(self, source: str, message: str, *, status_code: int | None = None):
        self.source = source
        self.status_code = status_code
        super().__init__(message)


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context tolerant of the TPEx cert's missing SKI extension.

    tpex.org.tw serves a chain that violates the strict RFC 5280 checks that
    Python 3.12+ enables by default (``VERIFY_X509_STRICT``), which surfaces as
    "Missing Subject Key Identifier". Clearing only that strict flag keeps full
    CA-chain, hostname and expiry verification intact — unlike ``verify=False``,
    it does NOT disable certificate verification.
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def get_json(url: str, *, source: str) -> list[dict]:
    """GET an OpenAPI endpoint and return the decoded JSON array.

    Raises SourceFetchError (friendly message + status code) on any non-200
    response, connection/timeout failure, or a 200 whose body is not a valid
    JSON list — so the job layer only ever needs to catch SourceFetchError.
    """
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, verify=_ssl_context()
        ) as client:
            resp = client.get(url, headers={"User-Agent": _USER_AGENT})
    except httpx.HTTPError as exc:
        raise SourceFetchError(
            source, f"{source} 資料來源連線失敗，請稍後再試"
        ) from exc

    if resp.status_code != 200:
        raise SourceFetchError(
            source,
            f"{source} 資料來源回應異常（HTTP {resp.status_code}），請稍後再試",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(
            source,
            f"{source} 資料來源回傳內容無法解析，請稍後再試",
            status_code=resp.status_code,
        ) from exc

    if not isinstance(data, list):
        raise SourceFetchError(
            source,
            f"{source} 資料來源回傳格式異常，請稍後再試",
            status_code=resp.status_code,
        )
    return data


def get_json_dict(url: str, *, source: str) -> dict:
    """GET a table-shaped endpoint and return the decoded JSON object.

    The TWSE ``rwd`` (T86) and TPEx ``dailyTrade`` endpoints wrap their rows in
    a ``{stat, fields, data}`` / ``{stat, tables:[...]}`` object rather than the
    bare array that OpenAPI serves, so ``get_json`` (list-only) cannot be used.
    Same friendly-error contract: raises SourceFetchError on any non-200,
    connection/timeout failure, unparseable body, or a 200 that is not a dict.
    """
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, verify=_ssl_context()
        ) as client:
            resp = client.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise SourceFetchError(
            source, f"{source} 資料來源連線失敗，請稍後再試"
        ) from exc

    if resp.status_code != 200:
        raise SourceFetchError(
            source,
            f"{source} 資料來源回應異常（HTTP {resp.status_code}），請稍後再試",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(
            source,
            f"{source} 資料來源回傳內容無法解析，請稍後再試",
            status_code=resp.status_code,
        ) from exc

    if not isinstance(data, dict):
        raise SourceFetchError(
            source,
            f"{source} 資料來源回傳格式異常，請稍後再試",
            status_code=resp.status_code,
        )
    return data


def iso_to_yyyymmdd(iso: str) -> str:
    """'2026-07-09' -> '20260709' (the TWSE ``rwd`` date parameter format)."""
    return date.fromisoformat(iso).strftime("%Y%m%d")


def iso_to_roc_slash(iso: str) -> str:
    """'2026-07-09' -> '115/07/09' (the TPEx ``dailyTrade`` date parameter format)."""
    d = date.fromisoformat(iso)
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def resolve_field_index(
    fields: list,
    required: tuple[str, ...],
    *,
    source: str,
    normalize=str.strip,
) -> dict[str, int]:
    """Map header labels to column indices, guarding against structural drift.

    Returns ``{normalized_label: index}`` for every header in ``fields``.
    Raises SourceFetchError when any ``required`` label is missing — a table
    endpoint dropping/renaming an expected column needs human attention, not a
    silent empty parse. ``normalize`` is applied to each header before matching
    (default strip(); pass a whitespace-collapsing fn for headers like '日 期').
    """
    idx = {normalize(str(name)): i for i, name in enumerate(fields)}
    if any(col not in idx for col in required):
        raise SourceFetchError(
            source, f"{source} 資料來源欄位結構變動，請人工確認"
        )
    return idx


def roc_slash_to_iso(raw: object) -> str | None:
    """Convert a slash Minguo (ROC) date like '115/06/03' to ISO '2026-06-03'.

    The per-stock *history* endpoints render each row's date as ``YYY/MM/DD``
    (slash-separated) rather than the packed ``1150603`` the T86/OpenAPI feeds
    use, so ``roc_to_iso`` can't parse it directly. Tolerates non-padded parts
    ('115/6/3'); returns None for blank or malformed input.
    """
    if raw is None:
        return None
    parts = str(raw).strip().split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    year, month, day = (int(p) for p in parts)
    try:
        return date(year + 1911, month, day).isoformat()
    except ValueError:
        return None


def to_number(raw: object) -> float | None:
    """Parse an exchange numeric string to float; blanks/'--' → None.

    Strips thousands separators and surrounding whitespace, and tolerates the
    leading '+' sign TPEx uses on positive changes.
    """
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if text.lower() in _EMPTY_TOKENS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(raw: object) -> int | None:
    """Parse a whole-number column (e.g. share volume) to int; blanks → None."""
    value = to_number(raw)
    return int(value) if value is not None else None


def change_pct(close: float | None, change: float | None) -> float | None:
    """Percent change from the price delta.

    The exchanges report ``change`` as an absolute price delta, so the prior
    close is ``close - change``. Returns None when either input is missing or
    the prior close is zero (division guard).
    """
    if close is None or change is None:
        return None
    prev_close = close - change
    if prev_close == 0:
        return None
    return change / prev_close * 100


def roc_to_iso(raw: object) -> str | None:
    """Convert a Minguo (ROC) date like '1150709' to ISO '2026-07-09'.

    The trailing 4 chars are MMDD; the remaining leading digits are the ROC
    year (AD = ROC + 1911). Returns None for blank or malformed input.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit() or len(text) < 7:
        return None
    year = int(text[:-4]) + 1911
    month = int(text[-4:-2])
    day = int(text[-2:])
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None
