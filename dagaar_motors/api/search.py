from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import get_permission_scope, require_app_access


@frappe.whitelist()
def global_search(text, limit=20):
    require_app_access()
    value = f"%{str(text or '').strip()}%"
    if value == "%%":
        return []
    limit = max(1, min(int(limit or 20), 100))
    vehicle_scope = get_permission_scope(applicable_for="Motor Vehicle")
    vehicle_filters = {}
    if vehicle_scope["companies"]:
        vehicle_filters["company"] = ["in", vehicle_scope["companies"]]
    if vehicle_scope["branches"]:
        vehicle_filters["branch"] = ["in", vehicle_scope["branches"]]
    results = []
    vehicles = frappe.get_list(
        "Motor Vehicle",
        filters=vehicle_filters,
        or_filters={
            "name": ["like", value],
            "license_plate": ["like", value],
            "vin": ["like", value],
            "vehicle_title": ["like", value],
            "model": ["like", value],
        },
        fields=["name", "vehicle_title as title", "license_plate as subtitle", "status"],
        order_by="modified desc",
        limit_page_length=limit,
    )
    results.extend({**row, "doctype": "Motor Vehicle"} for row in vehicles)
    remaining = max(0, limit - len(results))
    if remaining:
        agreement_scope = get_permission_scope(applicable_for="Rental Agreement")
        agreement_filters = {}
        if agreement_scope["companies"]:
            agreement_filters["company"] = ["in", agreement_scope["companies"]]
        if agreement_scope["branches"]:
            agreement_filters["branch"] = ["in", agreement_scope["branches"]]
        matching_vehicles = [row.name for row in vehicles]
        agreement_or_filters = [
            ["Rental Agreement", "name", "like", value],
            ["Rental Agreement", "customer", "like", value],
        ]
        if matching_vehicles:
            agreement_or_filters.append(["Rental Agreement", "vehicle", "in", matching_vehicles])
        agreements = frappe.get_list(
            "Rental Agreement",
            filters=agreement_filters,
            or_filters=agreement_or_filters,
            fields=["name", "customer", "vehicle", "expected_return_datetime", "status"],
            order_by="modified desc",
            limit_page_length=remaining,
        )
        for row in agreements:
            plate = frappe.get_cached_value("Motor Vehicle", row.vehicle, "license_plate") if row.vehicle else None
            results.append(
                {
                    "name": row.name,
                    "title": f"{row.customer} · {plate or row.vehicle or 'No vehicle'}",
                    "subtitle": row.expected_return_datetime,
                    "status": row.status,
                    "doctype": "Rental Agreement",
                }
            )
    return results[:limit]