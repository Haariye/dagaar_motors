from __future__ import annotations

from pathlib import Path

import frappe
from dagaar_motors.services.settings import clear_settings_cache
from dagaar_motors.utils.constants import APP_ROLES, DEFAULT_CHARGE_CODES


LEGACY_CUSTOM_FIELDS = {
    "Sales Invoice": (
        "dagaar_rental_agreement",
        "dagaar_rental_extension",
        "dagaar_rental_return",
        "dagaar_traffic_fine",
        "dagaar_vehicle_damage_report",
        "dagaar_motor_vehicle",
        "dagaar_vehicle_sale",
    ),
    "Payment Entry": (
        "dagaar_rental_agreement",
        "dagaar_security_deposit",
        "dagaar_motor_vehicle",
    ),
    "Journal Entry": (
        "dagaar_security_deposit",
        "dagaar_motor_vehicle",
    ),
    "Purchase Invoice": (
        "dagaar_motor_vehicle",
        "dagaar_vehicle_expense",
        "dagaar_maintenance_work_order",
    ),
}


LEGACY_WORKSPACES = (
    "Dagaar Motors",
    "Dagaar Rental",
    "Dagaar Fleet",
    "Dagaar Maintenance",
    "Dagaar Sales",
    "Dagaar Finance",
    "Dagaar Analytics",
    "Dagaar Administration",
)


PRINT_FORMATS = (
    ("Dagaar Motors - Rental Agreement", "Rental Agreement", "rental_agreement.html"),
    ("Dagaar Motors - Reservation Confirmation", "Rental Reservation", "reservation_confirmation.html"),
    ("Dagaar Motors - Rental Extension", "Rental Extension", "rental_extension.html"),
    ("Dagaar Motors - Rental Return", "Rental Return", "rental_return.html"),
    ("Dagaar Motors - Security Deposit Receipt", "Security Deposit", "security_deposit_receipt.html"),
    ("Dagaar Motors - Vehicle Sale Agreement", "Vehicle Sale", "vehicle_sale_agreement.html"),
    ("Dagaar Motors - Vehicle Inspection", "Vehicle Inspection", "vehicle_inspection.html"),
    ("Dagaar Motors - Vehicle Damage Report", "Vehicle Damage Report", "vehicle_damage_report.html"),
)


def before_migrate():
    cleanup_legacy_custom_fields()


def after_install():
    cleanup_legacy_custom_fields()
    create_roles()
    create_default_masters()
    initialize_settings()
    create_print_formats()
    cleanup_legacy_workspaces()
    clear_settings_cache()


def after_migrate():
    cleanup_legacy_custom_fields()
    create_roles()
    create_default_masters()
    initialize_settings()
    create_print_formats()
    cleanup_legacy_workspaces()
    clear_settings_cache()


def before_tests():
    cleanup_legacy_custom_fields()
    create_roles()
    create_default_masters()
    initialize_settings()
    create_print_formats()
    cleanup_legacy_workspaces()



def cleanup_legacy_custom_fields():
    """Remove v0.1.0/v0.1.1 core-table link fields.

    Older releases added several Link columns to ERPNext transaction tables.
    On mature sites those tables can already be close to MariaDB's 65,535-byte
    row limit. v0.1.2 stores all source references in Dagaar Motors ERP Link
    instead, so these Custom Field metadata rows must be removed before schema
    synchronization can try to add them again. Existing physical columns, if any,
    are intentionally left untouched to avoid destructive DDL on customer tables.
    """
    if not frappe.db.exists("DocType", "Custom Field"):
        return

    for doctype, fieldnames in LEGACY_CUSTOM_FIELDS.items():
        names = frappe.get_all(
            "Custom Field",
            filters={"dt": doctype, "fieldname": ["in", list(fieldnames)]},
            pluck="name",
            limit_page_length=100,
        )
        if names:
            frappe.db.delete("Custom Field", {"name": ["in", names]})
            frappe.clear_cache(doctype=doctype)


def cleanup_legacy_workspaces():
    """Remove obsolete v0.1 workspace names after the simplified menu is synced."""
    if not frappe.db.exists("DocType", "Workspace"):
        return
    for workspace in LEGACY_WORKSPACES:
        if frappe.db.exists("Workspace", workspace):
            frappe.delete_doc("Workspace", workspace, force=True, ignore_permissions=True)


def create_roles():
    for role_name in APP_ROLES:
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc(
                {
                    "doctype": "Role",
                    "role_name": role_name,
                    "desk_access": 1,
                    "is_custom": 0,
                }
            ).insert(ignore_permissions=True)


def create_default_masters():
    if frappe.db.exists("DocType", "Rental Charge Type"):
        for code, title, category in DEFAULT_CHARGE_CODES:
            if not frappe.db.exists("Rental Charge Type", {"code": code}):
                frappe.get_doc(
                    {
                        "doctype": "Rental Charge Type",
                        "charge_name": title,
                        "code": code,
                        "category": category,
                        "active": 1,
                    }
                ).insert(ignore_permissions=True)

    if frappe.db.exists("DocType", "Rental Type"):
        defaults = (
            ("City Rate", "CITY", "Daily", "Daily Allowance"),
            ("Trip Rate", "TRIP", "Fixed Trip", "Trip Allowance"),
        )
        for title, code, billing, mileage in defaults:
            if not frappe.db.exists("Rental Type", {"code": code}):
                frappe.get_doc(
                    {
                        "doctype": "Rental Type",
                        "type_name": title,
                        "code": code,
                        "billing_method": billing,
                        "mileage_behavior": mileage,
                        "active": 1,
                    }
                ).insert(ignore_permissions=True)


def initialize_settings():
    if not frappe.db.exists("DocType", "Dagaar Motors Settings"):
        return
    settings = frappe.get_single("Dagaar Motors Settings")
    changed = False
    defaults = {
        "currency_precision": 2,
        "rounding_minutes": 60,
        "grace_period_minutes": 15,
        "minimum_rental_hours": 1,
        "invoice_timing": "On Checkout",
        "default_fuel_policy": "Full to Full",
        "default_pricing_method": "Best Valid Rule",
        "project_per_vehicle": 1,
        "auto_create_vehicle_item": 1,
        "auto_create_vehicle_asset": 1,
        "prevent_overbooking": 1,
        "block_sale_for_future_reservations": 1,
        "reservation_series": "RSV-.YYYY.-.#####",
        "agreement_series": "RA-.YYYY.-.#####",
        "extension_series": "RE-.YYYY.-.#####",
        "return_series": "RR-.YYYY.-.#####",
        "sale_series": "VS-.YYYY.-.#####",
        "default_stock_uom": "Nos",
    }
    for fieldname, value in defaults.items():
        if settings.meta.has_field(fieldname) and not settings.get(fieldname):
            settings.set(fieldname, value)
            changed = True
    if changed:
        settings.save(ignore_permissions=True)


def create_print_formats():
    """Install and update the app-managed customer-facing Jinja print formats."""
    if not frappe.db.exists("DocType", "Print Format"):
        return

    print_root = Path(frappe.get_app_path("dagaar_motors", "templates", "print_formats"))
    for name, doc_type, filename in PRINT_FORMATS:
        if not frappe.db.exists("DocType", doc_type):
            continue

        html = (print_root / filename).read_text(encoding="utf-8")
        values = {
            "print_format_for": "DocType",
            "doc_type": doc_type,
            "module": "Dagaar Motors",
            # App-managed, but intentionally non-standard so production migrations do
            # not trigger Frappe's developer-mode export of Print Format JSON files.
            "standard": "No",
            "custom_format": 1,
            "print_format_type": "Jinja",
            "disabled": 0,
            "raw_printing": 0,
            "html": html,
            "margin_top": 8,
            "margin_bottom": 8,
            "margin_left": 8,
            "margin_right": 8,
            "page_number": "Bottom Center",
        }

        if frappe.db.exists("Print Format", name):
            print_format = frappe.get_doc("Print Format", name)
            print_format.update(values)
            print_format.save(ignore_permissions=True)
        else:
            frappe.get_doc({"doctype": "Print Format", "name": name, **values}).insert(
                ignore_permissions=True
            )