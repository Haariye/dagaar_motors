from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from frappe.utils import get_datetime


@dataclass(frozen=True)
class Duration:
    minutes: int
    hours: float
    days: float
    weeks: float
    months: float


def calculate_duration(start, end, rounding_minutes: int = 0, grace_minutes: int = 0) -> Duration:
    start_dt = get_datetime(start)
    end_dt = get_datetime(end)
    if not start_dt or not end_dt or end_dt <= start_dt:
        raise ValueError("Return date and time must be later than pickup date and time.")

    total_minutes = max(0, math.ceil((end_dt - start_dt).total_seconds() / 60) - max(0, grace_minutes))
    if rounding_minutes and total_minutes:
        total_minutes = int(math.ceil(total_minutes / rounding_minutes) * rounding_minutes)

    hours = total_minutes / 60
    days = hours / 24
    return Duration(
        minutes=total_minutes,
        hours=hours,
        days=days,
        weeks=days / 7,
        months=days / 30,
    )


def add_months_approx(value, months: int):
    return get_datetime(value) + timedelta(days=30 * months)


def overlaps(start_a, end_a, start_b, end_b) -> bool:
    return get_datetime(start_a) < get_datetime(end_b) and get_datetime(end_a) > get_datetime(start_b)