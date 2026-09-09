from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from dagaar_motors.services.maintenance import validate_maintenance_rule
from dagaar_motors.services.settings import clear_settings_cache, validate_settings_document
from dagaar_motors.utils.validation import (
    validate_account_company,
    validate_cost_center_company,
    validate_warehouse_company,
)


def validate_settings(doc):
    validate_settings_document(doc)
    if cint(doc.currency_precision) < 0 or cint(doc.currency_precision) > 6:
        frappe.throw(_("Currency precision must be between 0 and 6."))
    if cint(doc.rounding_minutes) < 0:
        frappe.throw(_("Pricing rounding minutes cannot be negative."))
    if cint(doc.maximum_rental_duration_days) and flt(doc.minimum_rental_duration_hours) / 24 > cint(
        doc.maximum_rental_duration_days
    ):
        frappe.throw(_("Maximum rental duration must exceed the minimum rental duration."))
    for fieldname in (
        "reservation_series",
        "agreement_series",
        "extension_series",
        "return_series",
        "sale_series",
    ):
        value = (doc.get(fieldname) or "").strip()
        if not value or "#" not in value or "\n" in value or "\r" in value:
            frappe.throw(
                _("{0} must be a single valid naming series containing at least one # counter.").format(
                    doc.meta.get_label(fieldname)
                )
            )
        doc.set(fieldname, value)


def settings_updated(doc):
    clear_settings_cache()


def validate_branch(doc):
    doc.code = _code(doc.code)
    if not doc.code:
        frappe.throw(_("Branch code is required."))
    validate_warehouse_company(doc.warehouse, doc.company)
    validate_cost_center_company(doc.cost_center, doc.company)
    for fieldname in (
        "rental_income_account",
        "vehicle_operating_expense_account",
        "deposit_liability_account",
    ):
        validate_account_company(doc.get(fieldname), doc.company)
    if doc.currency and not frappe.db.exists("Currency", doc.currency):
        frappe.throw(_("Currency {0} does not exist.").format(doc.currency))


def validate_category(doc):
    doc.code = _code(doc.code)
    if cint(doc.minimum_driver_age) < 0:
        frappe.throw(_("Minimum driver age cannot be negative."))
    if flt(doc.base_daily_rate) < 0 or flt(doc.default_deposit_amount) < 0:
        frappe.throw(_("Category rates and deposits cannot be negative."))
    for fieldname in (
        "rental_income_account",
        "maintenance_expense_account",
        "vehicle_operating_expense_account",
        "deposit_liability_account",
    ):
        account = doc.get(fieldname)
        if account:
            company = frappe.get_cached_value("Account", account, "company")
            if not company:
                frappe.throw(_("Account {0} is invalid.").format(account))


def validate_rental_type(doc):
    doc.code = _code(doc.code)
    if flt(doc.minimum_duration_hours) < 0 or cint(doc.maximum_duration_days) < 0:
        frappe.throw(_("Rental duration limits cannot be negative."))
    if cint(doc.maximum_duration_days) and flt(doc.minimum_duration_hours) / 24 > cint(doc.maximum_duration_days):
        frappe.throw(_("Maximum rental duration must exceed the minimum duration."))


def validate_pricing_rule(doc):
    if doc.valid_from and doc.valid_to and getdate(doc.valid_to) < getdate(doc.valid_from):
        frappe.throw(_("Pricing rule Valid To cannot be before Valid From."))
    if flt(doc.rate) < 0 or flt(doc.minimum_charge) < 0 or flt(doc.excess_km_rate) < 0:
        frappe.throw(_("Pricing values cannot be negative."))
    if doc.company and doc.branch:
        branch_company = frappe.get_cached_value("Motor Branch", doc.branch, "company")
        if branch_company != doc.company:
            frappe.throw(_("Branch {0} does not belong to Company {1}.").format(doc.branch, doc.company))
    if doc.vehicle:
        vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
        if doc.company and vehicle.company != doc.company:
            frappe.throw(_("Vehicle {0} belongs to Company {1}.").format(vehicle.name, vehicle.company))
        if doc.vehicle_category and vehicle.category != doc.vehicle_category:
            frappe.throw(_("Vehicle {0} does not belong to category {1}.").format(vehicle.name, doc.vehicle_category))
    _validate_tiers(doc)


def validate_seasonal_rule(doc):
    if not doc.recurring_annually and getdate(doc.end_date) < getdate(doc.start_date):
        frappe.throw(_("Seasonal rule End Date cannot be before Start Date unless it recurs annually."))
    if not flt(doc.adjustment_value):
        frappe.throw(_("Seasonal adjustment value cannot be zero."))
    allowed_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    supplied = {value.strip().lower() for value in (doc.weekdays or "").split(",") if value.strip()}
    invalid = sorted(supplied - allowed_days)
    if invalid:
        frappe.throw(_("Invalid weekday values: {0}.").format(", ".join(invalid)))


def validate_deposit_rule(doc):
    if flt(doc.minimum_days) < 0 or flt(doc.maximum_days) < 0:
        frappe.throw(_("Deposit duration limits cannot be negative."))
    if flt(doc.maximum_days) and flt(doc.maximum_days) < flt(doc.minimum_days):
        frappe.throw(_("Deposit maximum days cannot be below minimum days."))
    if doc.amount_type == "Percentage of Rental":
        if flt(doc.percentage) <= 0:
            frappe.throw(_("Enter a positive rental percentage for this deposit rule."))
    elif flt(doc.amount) < 0:
        frappe.throw(_("Deposit amount cannot be negative."))


def validate_discount_authority(doc):
    if not doc.user and not doc.role:
        frappe.throw(_("Select a User or Role for this discount authority."))
    for fieldname in ("maximum_discount_percent", "approval_threshold_percent"):
        value = flt(doc.get(fieldname))
        if value < 0 or value > 100:
            frappe.throw(_("{0} must be between 0 and 100.").format(doc.meta.get_label(fieldname)))
    if flt(doc.maximum_fixed_discount) < 0:
        frappe.throw(_("Maximum fixed discount cannot be negative."))
    if doc.company and doc.branch:
        branch_company = frappe.get_cached_value("Motor Branch", doc.branch, "company")
        if branch_company != doc.company:
            frappe.throw(_("Branch {0} does not belong to Company {1}.").format(doc.branch, doc.company))


def validate_extra(doc):
    doc.code = _code(doc.code)
    if flt(doc.rate) < 0:
        frappe.throw(_("Rental extra rate cannot be negative."))


def validate_charge_type(doc):
    doc.code = _code(doc.code)
    if doc.income_account:
        account_company = frappe.get_cached_value("Account", doc.income_account, "company")
        if not account_company:
            frappe.throw(_("Income Account {0} is invalid.").format(doc.income_account))


def validate_document_requirement(doc):
    if doc.expiry_must_cover_rental and doc.document_type not in {
        "Passport",
        "Driving License",
        "International Driving Permit",
        "Visa",
        "Insurance Document",
    }:
        frappe.throw(_("Expiry coverage is not applicable to document type {0}.").format(doc.document_type))


def validate_inspection_template(doc):
    seen = set()
    for row in doc.items:
        key = (row.area.strip().lower(), row.item.strip().lower())
        if key in seen:
            frappe.throw(_("Inspection item {0} / {1} is duplicated.").format(row.area, row.item))
        seen.add(key)



def validate_driver(doc):
    """Legacy v0.1 compatibility for stale Rental Driver controller files.

    Drivers are inline child rows in v0.2+, but an older checkout may still contain
    the removed Rental Driver controller during an overlay upgrade. Keeping this
    callable allows Frappe to finish DocType sync without restoring the old master
    to the active v0.2 source tree.
    """
    birth = doc.get("date_of_birth")
    license_issue = doc.get("license_issue_date")
    license_expiry = doc.get("license_expiry_date")
    passport_issue = doc.get("passport_issue_date")
    passport_expiry = doc.get("passport_expiry_date")

    if birth and license_expiry and getdate(license_expiry) <= getdate(birth):
        frappe.throw(_("Driving license expiry date is invalid."))
    if license_issue and license_expiry and getdate(license_expiry) <= getdate(license_issue):
        frappe.throw(_("Driving license expiry must be after its issue date."))
    if passport_issue and passport_expiry and getdate(passport_expiry) <= getdate(passport_issue):
        frappe.throw(_("Passport expiry must be after its issue date."))
    if birth and passport_expiry and getdate(passport_expiry) <= getdate(birth):
        frappe.throw(_("Passport expiry date is invalid."))


def validate_vehicle_document(doc):
    if doc.issue_date and doc.expiry_date and getdate(doc.expiry_date) < getdate(doc.issue_date):
        frappe.throw(_("Vehicle document expiry cannot be before its issue date."))
    if doc.expiry_date:
        today = getdate()
        if getdate(doc.expiry_date) < today:
            doc.status = "Expired"
        elif (getdate(doc.expiry_date) - today).days <= 30:
            doc.status = "Expiring"
        elif doc.status not in {"Cancelled"}:
            doc.status = "Valid"


def validate_vehicle_insurance(doc):
    if getdate(doc.expiry_date) < getdate(doc.start_date):
        frappe.throw(_("Insurance expiry cannot be before its start date."))
    if getdate(doc.expiry_date) < getdate() and doc.status != "Cancelled":
        doc.status = "Expired"
    elif doc.status in {None, "Draft", "Expired"} and getdate(doc.start_date) <= getdate() <= getdate(doc.expiry_date):
        doc.status = "Active"


def _validate_tiers(doc):
    tiers = sorted(doc.duration_tiers or [], key=lambda row: flt(row.from_units))
    previous_end = None
    for row in tiers:
        if flt(row.from_units) < 0 or flt(row.rate) < 0:
            frappe.throw(_("Duration tier units and rates cannot be negative."))
        if row.to_units not in (None, "") and flt(row.to_units) < flt(row.from_units):
            frappe.throw(_("A duration tier cannot end before it starts."))
        if previous_end is not None and flt(row.from_units) <= previous_end:
            frappe.throw(_("Duration pricing tiers overlap at unit {0}.").format(row.from_units))
        previous_end = flt(row.to_units) if row.to_units not in (None, "") else None
        if previous_end is None and row.idx != len(tiers):
            frappe.throw(_("Only the final duration tier may have no upper limit."))


def _code(value) -> str:
    return "-".join(str(value or "").strip().upper().replace("_", "-").split())