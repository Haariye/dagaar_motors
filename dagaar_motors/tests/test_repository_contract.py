from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from frappe.tests.utils import FrappeTestCase
from jinja2 import Environment


APP_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = APP_ROOT / "dagaar_motors"
DOMAIN_ROOT = PACKAGE_ROOT / "dagaar_motors"


class TestRepositoryContract(FrappeTestCase):
    def test_doctypes_are_normalized_and_field_order_is_valid(self):
        definitions = sorted((DOMAIN_ROOT / "doctype").glob("*/*.json"))
        self.assertGreaterEqual(len(definitions), 49)
        names = set()
        for path in definitions:
            definition = json.loads(path.read_text(encoding="utf-8"))
            names.add(definition["name"])
            fields = [row["fieldname"] for row in definition.get("fields", []) if row.get("fieldname")]
            order = definition.get("field_order", [])
            self.assertFalse([name for name, count in Counter(fields).items() if count > 1], path)
            self.assertFalse([name for name, count in Counter(order).items() if count > 1], path)
            self.assertEqual(set(fields), set(order), path)
        self.assertIn("Motor Vehicle", names)
        self.assertIn("Rental Agreement", names)
        self.assertIn("Deposit Transaction", names)

    def test_report_and_workspace_bundles_are_complete(self):
        reports = [path for path in (DOMAIN_ROOT / "report").iterdir() if path.is_dir() and path.name != "__pycache__"]
        self.assertGreaterEqual(len(reports), 34)
        for report in reports:
            for suffix in (".json", ".js", ".py"):
                self.assertTrue((report / f"{report.name}{suffix}").exists(), report)
        workspaces = sorted((DOMAIN_ROOT / "workspace").glob("*/*.json"))
        self.assertGreaterEqual(len(workspaces), 8)
        for path in workspaces:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["module"], "Dagaar Motors")

    def test_customer_print_formats_parse_as_jinja(self):
        print_root = PACKAGE_ROOT / "templates" / "print_formats"
        expected = {
            "rental_agreement.html",
            "reservation_confirmation.html",
            "rental_extension.html",
            "rental_return.html",
            "security_deposit_receipt.html",
            "vehicle_sale_agreement.html",
            "vehicle_inspection.html",
            "vehicle_damage_report.html",
        }
        self.assertTrue(expected.issubset({path.name for path in print_root.glob("*.html")}))
        environment = Environment(autoescape=True)
        for path in print_root.glob("*.html"):
            environment.parse(path.read_text(encoding="utf-8"))

    def test_critical_code_has_no_placeholder_implementation(self):
        prohibited = re.compile(
            r"\b(?:"
            + "TO"
            + "DO|FIX"
            + "ME)\b|implement "
            + "later|your logic "
            + "here",
            re.IGNORECASE,
        )
        for path in PACKAGE_ROOT.rglob("*"):
            if path.suffix not in {".py", ".js", ".html", ".json"} or "__pycache__" in path.parts:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            self.assertIsNone(prohibited.search(path.read_text(encoding="utf-8")), path)

    def test_sensitive_submit_permissions_match_server_commands(self):
        for doctype in ("vehicle_maintenance", "maintenance_work_order"):
            path = DOMAIN_ROOT / "doctype" / doctype / f"{doctype}.json"
            definition = json.loads(path.read_text(encoding="utf-8"))
            workshop = next(
                row for row in definition["permissions"]
                if row.get("role") == "Dagaar Motors Workshop User"
            )
            self.assertFalse(workshop.get("submit"), path)
            self.assertFalse(workshop.get("cancel"), path)

    def test_agreement_availability_excludes_only_its_source_reservation(self):
        availability = (PACKAGE_ROOT / "services" / "availability.py").read_text(encoding="utf-8")
        rental = (PACKAGE_ROOT / "services" / "rental.py").read_text(encoding="utf-8")
        constants = (PACKAGE_ROOT / "utils" / "constants.py").read_text(encoding="utf-8")
        self.assertIn("exclude_documents", availability)
        self.assertIn('{"Rental Reservation": doc.reservation}', rental)
        self.assertIn('"Inspection",', constants)
        self.assertIn('"Preparation",', constants)

    def test_vehicle_sale_has_server_side_submission_approval_gate(self):
        controller = (
            DOMAIN_ROOT / "doctype" / "vehicle_sale" / "vehicle_sale.py"
        ).read_text(encoding="utf-8")
        service = (PACKAGE_ROOT / "services" / "vehicle_sales.py").read_text(encoding="utf-8")
        self.assertIn("def before_submit", controller)
        self.assertIn("validate_vehicle_sale_submission", controller)
        self.assertIn("def _protect_sale_approval", service)

    def test_deposit_transactions_are_api_controlled_and_retry_safe(self):
        transaction_path = (
            DOMAIN_ROOT
            / "doctype"
            / "deposit_transaction"
            / "deposit_transaction.json"
        )
        definition = json.loads(transaction_path.read_text(encoding="utf-8"))
        fields = {row["fieldname"]: row for row in definition["fields"]}
        transaction_types = fields["transaction_type"]["options"].splitlines()
        self.assertIn("request_token", fields)
        self.assertNotIn("Reversal", transaction_types)
        cashier = next(
            row
            for row in definition["permissions"]
            if row.get("role") == "Dagaar Motors Cashier"
        )
        self.assertFalse(cashier.get("create"))
        self.assertFalse(cashier.get("submit"))

        service = (PACKAGE_ROOT / "services" / "deposits.py").read_text(encoding="utf-8")
        client = (PACKAGE_ROOT / "public" / "js" / "security_deposit.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('"balance": 0', service)
        self.assertIn('"request_token": request_token', service)
        self.assertIn("request_token: requestToken", client)
        self.assertIn("received - deducted - refunded", service)

    def test_services_never_commit_inside_domain_commands(self):
        for path in (PACKAGE_ROOT / "services").glob("*.py"):
            self.assertNotIn("frappe.db.commit(", path.read_text(encoding="utf-8"), path)