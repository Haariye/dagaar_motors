from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from dagaar_motors.services.idempotency import make_key
from dagaar_motors.services.state_machine import assert_transition
from dagaar_motors.utils.constants import RENTAL_AGREEMENT_TRANSITIONS, VEHICLE_TRANSITIONS


class TestStateAndIdempotency(FrappeTestCase):
    def test_allowed_vehicle_transition(self):
        self.assertIsNone(assert_transition("Available", "Rented", VEHICLE_TRANSITIONS, "Vehicle"))

    def test_sold_vehicle_cannot_return_to_rental(self):
        with self.assertRaises(frappe.ValidationError):
            assert_transition("Sold", "Rented", VEHICLE_TRANSITIONS, "Vehicle ABC123")

    def test_closed_agreement_is_terminal(self):
        with self.assertRaises(frappe.ValidationError):
            assert_transition("Closed", "Active", RENTAL_AGREEMENT_TRANSITIONS, "Rental Agreement RA-1")

    def test_idempotency_key_is_stable_and_payload_sensitive(self):
        first = make_key("invoice", "Rental Agreement", "RA-0001", {"period": "original"})
        repeated = make_key("invoice", "Rental Agreement", "RA-0001", {"period": "original"})
        changed = make_key("invoice", "Rental Agreement", "RA-0001", {"period": "extension"})
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(first), 64)