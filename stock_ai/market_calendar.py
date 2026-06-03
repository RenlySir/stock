from __future__ import annotations

from datetime import date, datetime, time as dtime


# 2026 A-share exchange holidays from official SSE/SZSE/BSE annual market-closure notices.
A_SHARE_2026_CLOSED_DAYS = {
    "2026-01-01",
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-23",
    "2026-04-06",
    "2026-05-01",
    "2026-05-04",
    "2026-05-05",
    "2026-06-19",
    "2026-09-25",
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
}


def is_a_share_trading_day(value: str | date | datetime | None = None) -> bool:
    current = _as_date(value)
    if current.weekday() >= 5:
        return False
    return current.strftime("%Y-%m-%d") not in A_SHARE_2026_CLOSED_DAYS


def is_a_share_trading_time(value: datetime | None = None) -> bool:
    current = value or datetime.now()
    if not is_a_share_trading_day(current):
        return False
    now = current.time()
    return dtime(9, 30) <= now <= dtime(11, 30) or dtime(13, 0) <= now <= dtime(15, 0)


def _as_date(value: str | date | datetime | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()
