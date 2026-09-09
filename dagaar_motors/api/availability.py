from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import enforce_company_branch, require_app_access
from dagaar_motors.services.availability import get_available_vehicles, get_conflicts
from dagaar_motors.services.settings import resolve_company


@frappe.whitelist()
def available_vehicles(
    start_datetime,
    end_datetime,
    company=None,
    branch=None,
    vehicle_category=None,
    rental_type=None,
    limit=100,
):
    require_app_access()
    company = resolve_company(company)
    scope = enforce_company_branch(company, branch, applicable_for="Motor Vehicle")
    branch_filter = branch or (scope["branches"] if scope["branches"] else None)
    return get_available_vehicles(
        company=company,
        branch=branch_filter,
        vehicle_category=vehicle_category,
        rental_type=rental_type,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        limit=int(limit or 100),
    )


@frappe.whitelist()
def vehicle_conflicts(vehicle, start_datetime, end_datetime, exclude_doctype=None, exclude_name=None):
    require_app_access()
    vehicle_scope = frappe.db.get_value("Motor Vehicle", vehicle, ["company", "branch"], as_dict=True)
    if not vehicle_scope:
        frappe.throw(f"Motor Vehicle {vehicle} does not exist.")
    enforce_company_branch(vehicle_scope.company, vehicle_scope.branch)
    return get_conflicts(
        vehicle,
        start_datetime,
        end_datetime,
        exclude_doctype=exclude_doctype,
        exclude_name=exclude_name,
    )