from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from frappe.utils import flt


def quantize(value, precision: int = 2) -> float:
    amount = Decimal(str(flt(value)))
    unit = Decimal("1").scaleb(-max(0, int(precision)))
    return float(amount.quantize(unit, rounding=ROUND_HALF_UP))


def percent(amount, percentage, precision: int = 2) -> float:
    return quantize(flt(amount) * flt(percentage) / 100, precision)