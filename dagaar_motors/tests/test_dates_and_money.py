from __future__ import annotations

from datetime import datetime

from frappe.tests.utils import FrappeTestCase

from dagaar_motors.utils.dates import calculate_duration, overlaps
from dagaar_motors.utils.money import percent, quantize


class TestDatesAndMoney(FrappeTestCase):
    def test_duration_applies_grace_before_rounding(self):
        duration = calculate_duration(
            datetime(2026, 8, 1, 10, 0),
            datetime(2026, 8, 1, 11, 10),
            rounding_minutes=30,
            grace_minutes=15,
        )
        self.assertEqual(duration.minutes, 60)
        self.assertEqual(duration.hours, 1)

    def test_duration_rounds_up_to_configured_interval(self):
        duration = calculate_duration(
            datetime(2026, 8, 1, 10, 0),
            datetime(2026, 8, 1, 11, 1),
            rounding_minutes=60,
        )
        self.assertEqual(duration.minutes, 120)
        self.assertEqual(duration.days, 2 / 24)

    def test_invalid_period_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "later than pickup"):
            calculate_duration(datetime(2026, 8, 1, 10, 0), datetime(2026, 8, 1, 10, 0))

    def test_overlap_uses_half_open_intervals(self):
        self.assertTrue(
            overlaps(
                datetime(2026, 8, 1, 10),
                datetime(2026, 8, 2, 10),
                datetime(2026, 8, 2, 9),
                datetime(2026, 8, 3, 10),
            )
        )
        self.assertFalse(
            overlaps(
                datetime(2026, 8, 1, 10),
                datetime(2026, 8, 2, 10),
                datetime(2026, 8, 2, 10),
                datetime(2026, 8, 3, 10),
            )
        )

    def test_money_uses_commercial_half_up_rounding(self):
        self.assertEqual(quantize("10.005", 2), 10.01)
        self.assertEqual(percent(250, 7.5), 18.75)