from __future__ import annotations

from datetime import date, datetime, timedelta


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


def parse_date(value: str | date | None) -> date:
    if value is None:
        return today()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()

