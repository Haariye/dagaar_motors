from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from dagaar_motors.services.accounting import make_invoice_source_key


class TestAccountingIdempotency(FrappeTestCase):
    def test_invoice_source_key_is_order_independent(self):
        first = make_invoice_source_key(
            {
                "dagaar_rental_agreement": "RA-0001",
                "dagaar_rental_extension": "RE-0001",
            }
        )
        second = make_invoice_source_key(
            {
                "dagaar_rental_extension": "RE-0001",
                "dagaar_rental_agreement": "RA-0001",
            }
        )
        self.assertEqual(first, second)

    def test_separate_extensions_get_separate_invoice_keys(self):
        first = make_invoice_source_key(
            {
                "dagaar_rental_agreement": "RA-0001",
                "dagaar_rental_extension": "RE-0001",
            }
        )
        second = make_invoice_source_key(
            {
                "dagaar_rental_agreement": "RA-0001",
                "dagaar_rental_extension": "RE-0002",
            }
        )
        self.assertNotEqual(first, second)
