from __future__ import annotations

from functools import lru_cache

import frappe
from frappe import _

from dagaar_motors.compat.accounting import get_company_currency
from dagaar_motors.utils.validation import (
    validate_account_company,
    validate_cost_center_company,
    validate_warehouse_company,
)


@lru_cache(maxsize=1)
def get_settings_dict() -> dict:
    if not frappe.db.exists("DocType", "Dagaar Motors Settings"):
        return {}
    return frappe.get_single("Dagaar Motors Settings").as_dict()


def clear_settings_cache():
    get_settings_dict.cache_clear()


def get_settings():
    return frappe.get_single("Dagaar Motors Settings")


def resolve_company(company: str | None = None) -> str:
    value = company or get_settings_dict().get("default_company") or frappe.defaults.get_user_default("Company")
    if not value:
        frappe.throw(_("Configure a default company in Dagaar Motors Settings."))
    return value


def resolve_currency(company: str, currency: str | None = None) -> str:
    return currency or get_settings_dict().get("default_currency") or get_company_currency(company)


def get_branch(branch: str | None):
    return frappe.get_cached_doc("Motor Branch", branch) if branch else None


def resolve_dimension(fieldname: str, company: str, branch: str | None = None, vehicle: str | None = None):
    """Resolve Vehicle -> Category -> Branch -> Settings for supported fields."""
    if vehicle:
        vehicle_doc = frappe.get_cached_doc("Motor Vehicle", vehicle)
        value = vehicle_doc.get(fieldname)
        if value:
            return value
        if vehicle_doc.category and frappe.db.exists("Vehicle Category", vehicle_doc.category):
            category = frappe.get_cached_doc("Vehicle Category", vehicle_doc.category)
            value = category.get(fieldname)
            if value:
                return value
        branch = branch or vehicle_doc.branch

    if branch:
        branch_doc = get_branch(branch)
        value = branch_doc.get(fieldname) if branch_doc else None
        if value:
            return value

    return get_settings_dict().get(fieldname)


def resolve_account(fieldname: str, company: str, branch: str | None = None, vehicle: str | None = None) -> str | None:
    account = resolve_dimension(fieldname, company, branch, vehicle)
    validate_account_company(account, company)
    return account


def resolve_cost_center(company: str, branch: str | None = None, vehicle: str | None = None) -> str | None:
    value = resolve_dimension("cost_center", company, branch, vehicle) or get_settings_dict().get("default_cost_center")
    validate_cost_center_company(value, company)
    return value


def resolve_warehouse(company: str, branch: str | None = None, vehicle: str | None = None) -> str | None:
    value = resolve_dimension("warehouse", company, branch, vehicle) or get_settings_dict().get("default_warehouse")
    validate_warehouse_company(value, company)
    return value


def validate_settings_document(doc):
    company = doc.default_company
    if not company:
        return
    for fieldname in (
        "rental_income_account",
        "extension_income_account",
        "late_return_income_account",
        "excess_mileage_income_account",
        "fuel_charge_income_account",
        "damage_recovery_income_account",
        "cleaning_charge_income_account",
        "cancellation_income_account",
        "driver_service_income_account",
        "delivery_income_account",
        "collection_income_account",
        "insurance_charge_income_account",
        "miscellaneous_rental_income_account",
        "vehicle_sale_income_account",
        "deposit_liability_account",
        "deposit_clearing_account",
        "vehicle_operating_expense_account",
        "maintenance_expense_account",
        "repair_expense_account",
        "accident_expense_account",
        "insurance_expense_account",
        "registration_expense_account",
        "fuel_expense_account",
        "gain_on_vehicle_sale_account",
        "loss_on_vehicle_sale_account",
    ):
        validate_account_company(doc.get(fieldname), company)
    validate_cost_center_company(doc.default_cost_center, company)
    validate_warehouse_company(doc.default_warehouse, company)