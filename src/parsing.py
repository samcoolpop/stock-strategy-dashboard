from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "None", "nan"}:
        return None
    text = text.replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def parse_cny_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-"}:
        return None
    sign = Decimal("-1") if text.startswith("-") else Decimal("1")
    number = parse_decimal(text)
    if number is None:
        return None
    unit = Decimal("1")
    if "万" in text:
        unit = Decimal("10000")
    if "亿" in text:
        unit = Decimal("100000000")
    return sign * abs(number) * unit


def to_db_decimal(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)

