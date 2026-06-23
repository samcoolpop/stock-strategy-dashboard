from __future__ import annotations

from datetime import date, datetime, time, timedelta


def today() -> date:
    return date.today()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_business_day(value: date) -> bool:
    return value.weekday() < 5


def add_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            remaining -= 1
    return current


def previous_business_day(value: date) -> date:
    current = value - timedelta(days=1)
    while not is_business_day(current):
        current -= timedelta(days=1)
    return current


def close_scan_default_date(now: datetime | None = None) -> date:
    """Return the trading date that a close-scan run should update."""
    current = now or datetime.now()
    current_date = current.date()
    if not is_business_day(current_date):
        return previous_business_day(current_date)
    if current.time() < time(9, 30):
        return previous_business_day(current_date)
    return current_date


def parse_date(value: str | date | None) -> date:
    if value is None:
        return today()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()
