from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from dagaar_motors.api.permissions import require_any_role


CRITICAL_SETTINGS = (
    ("default_company", "Default Company", "Company"),
    ("rental_income_account", "Rental Income Account", "Accounting"),
    ("extension_income_account", "Extension Income Account", "Accounting"),
    ("deposit_liability_account", "Deposit Liability Account", "Accounting"),
    ("deposit_clearing_account", "Deposit Clearing Account", "Accounting"),
    ("default_cost_center", "Default Cost Center", "Accounting"),
    ("default_rental_item", "Rental Item", "Items"),
    ("default_extension_item", "Extension Item", "Items"),
)

RECOMMENDED_SETTINGS = (
    ("default_currency", "Default Currency", "Company"),
    ("default_warehouse", "Default Warehouse", "Stock"),
    ("default_mileage_item", "Excess Mileage Item", "Items"),
    ("default_fuel_item", "Fuel Charge Item", "Items"),
    ("default_damage_item", "Damage Recovery Item", "Items"),
    ("default_cleaning_item", "Cleaning Item", "Items"),
    ("checkout_inspection_template", "Checkout Inspection Template", "Rental Policy"),
    ("return_inspection_template", "Return Inspection Template", "Rental Policy"),
)


@frappe.whitelist()
def health_check(update_settings=0):
    """Return an actionable setup-readiness report for administrators."""
    require_any_role(
        "Dagaar Motors Administrator",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    settings = frappe.get_single("Dagaar Motors Settings")
    checks: list[dict] = []

    for fieldname, label, group in CRITICAL_SETTINGS:
        _append_setting_check(checks, settings, fieldname, label, group, critical=True)
    for fieldname, label, group in RECOMMENDED_SETTINGS:
        _append_setting_check(checks, settings, fieldname, label, group, critical=False)

    _append_count_check(checks, "Motor Branch", "Operational Branch", critical=True)
    _append_count_check(checks, "Vehicle Category", "Vehicle Category", critical=True, filters={"active": 1})
    _append_count_check(checks, "Rental Type", "Rental Type", critical=True, filters={"active": 1})
    _append_count_check(checks, "Rental Pricing Rule", "Active Pricing Rule", critical=True, filters={"active": 1})
    _append_count_check(checks, "Deposit Rule", "Active Deposit Rule", critical=False, filters={"active": 1})
    _append_count_check(checks, "Inspection Template", "Inspection Template", critical=False, filters={"active": 1})
    _append_count_check(checks, "Motor Vehicle", "Motor Vehicle", critical=False)

    missing_critical = [row for row in checks if row["critical"] and row["status"] != "Pass"]
    missing_recommended = [row for row in checks if not row["critical"] and row["status"] != "Pass"]
    ready = not missing_critical
    score = round(100 * sum(row["status"] == "Pass" for row in checks) / max(1, len(checks)))
    validated_on = now_datetime()
    notes = _summary_text(missing_critical, missing_recommended)

    if cint(update_settings):
        settings.setup_complete = int(ready)
        settings.last_setup_validation = validated_on
        settings.setup_notes = notes
        settings.save(ignore_permissions=True)

    return {
        "ready": ready,
        "score": score,
        "validated_on": validated_on,
        "summary": notes,
        "critical_missing": len(missing_critical),
        "recommended_missing": len(missing_recommended),
        "checks": checks,
    }


def _append_setting_check(checks, settings, fieldname, label, group, *, critical):
    configured = bool(settings.get(fieldname))
    checks.append(
        {
            "key": fieldname,
            "label": label,
            "group": group,
            "critical": critical,
            "status": "Pass" if configured else "Missing",
            "detail": str(settings.get(fieldname)) if configured else _("Configure this field in Dagaar Motors Settings."),
            "fieldname": fieldname,
        }
    )


def _append_count_check(checks, doctype, label, *, critical, filters=None):
    count = frappe.db.count(doctype, filters or {})
    checks.append(
        {
            "key": doctype,
            "label": label,
            "group": "Master Data",
            "critical": critical,
            "status": "Pass" if count else "Missing",
            "detail": _("{0} configured").format(count) if count else _("Create at least one {0}.").format(label),
            "doctype": doctype,
            "count": count,
        }
    )


def _summary_text(missing_critical, missing_recommended):
    if not missing_critical and not missing_recommended:
        return _("Setup is ready. All critical and recommended checks passed.")
    parts = []
    if missing_critical:
        parts.append(_("Critical: {0}").format(", ".join(row["label"] for row in missing_critical)))
    if missing_recommended:
        parts.append(_("Recommended: {0}").format(", ".join(row["label"] for row in missing_recommended)))
    return "\n".join(parts)