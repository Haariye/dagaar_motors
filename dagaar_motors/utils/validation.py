from __future__ import annotations

import frappe
from frappe import _


def require(value, message: str):
    if value in (None, "", [], ()):  # zero is a valid commercial value
        frappe.throw(_(message))
    return value


def validate_link_company(doctype: str, name: str | None, company: str | None, company_field: str = "company"):
    if not name or not company or not frappe.db.exists("DocType", doctype):
        return
    meta = frappe.get_meta(doctype)
    if not meta.has_field(company_field):
        return
    linked_company = frappe.db.get_value(doctype, name, company_field)
    if linked_company and linked_company != company:
        frappe.throw(_("{0} {1} belongs to company {2}, not {3}.").format(doctype, name, linked_company, company))


def validate_account_company(account: str | None, company: str | None):
    validate_link_company("Account", account, company)


def validate_cost_center_company(cost_center: str | None, company: str | None):
    validate_link_company("Cost Center", cost_center, company)


def validate_warehouse_company(warehouse: str | None, company: str | None):
    validate_link_company("Warehouse", warehouse, company)


def ensure_not_cancelled(doc):
    if getattr(doc, "docstatus", 0) == 2:
        frappe.throw(_("Cancelled document {0} cannot be processed.").format(doc.name))