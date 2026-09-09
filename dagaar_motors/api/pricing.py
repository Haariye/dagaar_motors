from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import enforce_company_branch, require_app_access
from dagaar_motors.services.pricing import calculate_price
from dagaar_motors.services.settings import resolve_company


@frappe.whitelist()
def preview(context=None, **kwargs):
    require_app_access()
    payload = frappe.parse_json(context) if isinstance(context, str) else dict(context or {})
    payload.update({key: value for key, value in kwargs.items() if value is not None})
    if payload.get("vehicle"):
        vehicle_scope = frappe.db.get_value(
            "Motor Vehicle", payload["vehicle"], ["company", "branch", "category"], as_dict=True
        )
        if not vehicle_scope:
            frappe.throw(f"Motor Vehicle {payload['vehicle']} does not exist.")
        payload["company"] = payload.get("company") or vehicle_scope.company
        payload["branch"] = payload.get("branch") or vehicle_scope.branch
        payload["vehicle_category"] = payload.get("vehicle_category") or vehicle_scope.category
    payload["company"] = resolve_company(payload.get("company"))
    scope = enforce_company_branch(
        payload["company"], payload.get("branch"), applicable_for="Rental Reservation"
    )
    if not payload.get("branch") and len(scope["branches"]) == 1:
        payload["branch"] = scope["branches"][0]
    return calculate_price(payload)