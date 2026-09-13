from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from dagaar_motors.services.deposits import _deposit_rule_amount


class TestDepositPrimitives(FrappeTestCase):
    def test_fixed_amount(self):
        rule = {"amount_type": "Fixed", "amount": 500}
        self.assertEqual(_deposit_rule_amount(rule, rental_total=2_000, duration_days=5), 500)

    def test_percentage_of_rental(self):
        rule = {"amount_type": "Percentage of Rental", "percentage": 20}
        self.assertEqual(_deposit_rule_amount(rule, rental_total=1_000, duration_days=3), 200)

    def test_per_day(self):
        rule = {"amount_type": "Per Day", "amount": 50}
        self.assertEqual(_deposit_rule_amount(rule, rental_total=1_000, duration_days=4), 200)

    def test_per_day_minimum_one_day(self):
        rule = {"amount_type": "Per Day", "amount": 50}
        self.assertEqual(_deposit_rule_amount(rule, rental_total=0, duration_days=0), 50)
