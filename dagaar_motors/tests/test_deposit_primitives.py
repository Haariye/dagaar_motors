from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from dagaar_motors.services.deposits import _deposit_status


class TestDepositPrimitives(FrappeTestCase):
    def test_uncollected_deposit_is_required_not_held(self):
        self.assertEqual(
            _deposit_status(
                required=1_000,
                received=0,
                allocated=0,
                forfeited=0,
                refunded=0,
            ),
            "Required",
        )

    def test_partial_collection_is_tracked(self):
        self.assertEqual(
            _deposit_status(
                required=1_000,
                received=400,
                allocated=0,
                forfeited=0,
                refunded=0,
            ),
            "Partially Collected",
        )

    def test_mixed_allocation_and_refund_is_fully_used(self):
        self.assertEqual(
            _deposit_status(
                required=1_000,
                received=1_000,
                allocated=600,
                forfeited=0,
                refunded=400,
            ),
            "Fully Used",
        )

    def test_complete_forfeiture_is_distinct(self):
        self.assertEqual(
            _deposit_status(
                required=1_000,
                received=1_000,
                allocated=0,
                forfeited=1_000,
                refunded=0,
            ),
            "Forfeited",
        )

    def test_waiver_has_priority(self):
        self.assertEqual(
            _deposit_status(
                required=1_000,
                received=0,
                allocated=0,
                forfeited=0,
                refunded=0,
                waived_count=1,
            ),
            "Waived",
        )
