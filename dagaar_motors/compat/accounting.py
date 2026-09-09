from __future__ import annotations

import frappe

from dagaar_motors.services.erp_links import set_pending_source_references


def set_if_present(doc, fieldname: str, value):
    if value is None:
        return
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def set_source_references(doc, **references):
    """Attach Dagaar source references without adding columns to ERPNext tables."""
    set_pending_source_references(doc, **references)


def get_company_currency(company: str) -> str:
    return frappe.get_cached_value("Company", company, "default_currency")


def get_default_bank_cash_account(company: str, account_type: str = "Bank") -> str | None:
    filters = {"company": company, "is_group": 0, "disabled": 0, "account_type": account_type}
    return frappe.db.get_value("Account", filters, "name")
