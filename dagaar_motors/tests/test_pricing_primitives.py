from __future__ import annotations

from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase

from dagaar_motors.services.pricing import (
    PricingContext,
    _billable_units,
    _calculate_base_amount,
    _match_score,
    _season_applies,
)
from dagaar_motors.utils.dates import Duration


class TestPricingPrimitives(FrappeTestCase):
    def test_billable_units_for_supported_rate_bases(self):
        duration = Duration(minutes=12_960, hours=216, days=9, weeks=9 / 7, months=0.3)
        self.assertEqual(_billable_units("Hourly", duration, 0)[0], 216)
        self.assertEqual(_billable_units("Daily", duration, 0)[0], 9)
        self.assertEqual(_billable_units("Weekly", duration, 0)[0], 2)
        self.assertEqual(_billable_units("Monthly", duration, 0)[0], 1)
        self.assertEqual(_billable_units("Fixed Trip", duration, 0)[0], 1)
        self.assertEqual(_billable_units("Kilometer", duration, 650)[0], 650)

    def test_whole_duration_tier_prices_all_units_at_selected_rate(self):
        rule = frappe._dict(
            name="RULE-WHOLE",
            whole_duration_pricing=1,
            duration_tiers=[
                frappe._dict(from_units=1, to_units=2, rate=100, label="Short"),
                frappe._dict(from_units=3, to_units=6, rate=80, label="Medium"),
            ],
        )
        amount, lines, effective_rate = _calculate_base_amount(rule, "Daily", 5, 120)
        self.assertEqual(amount, 400)
        self.assertEqual(effective_rate, 80)
        self.assertEqual(lines[0].description, "Medium")

    def test_slab_duration_tiers_preserve_each_slab_rate(self):
        rule = frappe._dict(
            name="RULE-SLAB",
            whole_duration_pricing=0,
            duration_tiers=[
                frappe._dict(from_units=1, to_units=2, rate=100, label="Days 1-2"),
                frappe._dict(from_units=3, to_units=5, rate=80, label="Days 3-5"),
            ],
        )
        amount, lines, effective_rate = _calculate_base_amount(rule, "Daily", 5, 120)
        self.assertEqual(amount, 440)
        self.assertEqual([line.amount for line in lines], [200, 240])
        self.assertEqual(effective_rate, 88)

    def test_specific_rule_scores_above_generic_rule(self):
        context = PricingContext(
            pickup_datetime="2026-08-01 10:00:00",
            return_datetime="2026-08-03 10:00:00",
            company="Dagaar",
            branch="Hargeisa",
            vehicle="VEH-0001",
            vehicle_category="SUV",
            rental_type="City Rate",
        )
        generic = frappe._dict(company="Dagaar", branch=None, vehicle=None, vehicle_category=None, rental_type=None, one_way=0)
        specific = frappe._dict(company="Dagaar", branch="Hargeisa", vehicle="VEH-0001", vehicle_category="SUV", rental_type="City Rate", one_way=0)
        self.assertGreater(_match_score(specific, context), _match_score(generic, context))

    def test_recurring_season_can_cross_year_end(self):
        season = frappe._dict(
            start_date=date(2026, 12, 15),
            end_date=date(2027, 1, 15),
            recurring_annually=1,
            weekdays="",
        )
        self.assertTrue(_season_applies(season, date(2028, 1, 5)))
        self.assertFalse(_season_applies(season, date(2028, 2, 5)))