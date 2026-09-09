from __future__ import annotations

import frappe

from dagaar_motors.services.analytics import get_management_dashboard, get_operations_board


@frappe.whitelist()
def get_dashboard(company=None, branch=None, from_date=None, to_date=None):
    return get_management_dashboard(company=company, branch=branch, from_date=from_date, to_date=to_date)


@frappe.whitelist()
def get_operations(company=None, branch=None):
    return get_operations_board(company=company, branch=branch)