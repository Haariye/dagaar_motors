from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import (
    enforce_company_branch,
    enforce_document_scope,
    enforce_vehicle_scope,
    get_permission_scope,
    require_any_role,
    require_app_access,
)
from dagaar_motors.services.analytics import get_vehicle_summary
from dagaar_motors.services.fleet import update_mileage
from dagaar_motors.services.maintenance import (
    complete_maintenance,
    complete_work_order,
    generate_due_maintenance,
    schedule_maintenance,
    start_maintenance,
    start_work_order,
)
from dagaar_motors.services.operations import (
    complete_transfer,
    invoice_traffic_fine,
    release_vehicle_block,
    start_transfer,
)
from dagaar_motors.services.vehicle_sales import approve_vehicle_sale, submit_vehicle_sale


@frappe.whitelist()
def vehicle_summary(vehicle):
    require_app_access()
    return get_vehicle_summary(vehicle)


@frappe.whitelist()
def correct_mileage(vehicle, odometer, reason, approved_by):
    require_any_role("Dagaar Motors Fleet Manager", "Dagaar Motors Administrator")
    enforce_vehicle_scope(vehicle)
    return update_mileage(
        vehicle,
        float(odometer),
        "Manual Correction",
        correction=True,
        reason=reason,
        approved_by=approved_by,
    ).as_dict()


@frappe.whitelist()
def generate_maintenance(vehicle=None):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Fleet Manager",
        "Dagaar Motors Branch Manager",
    )
    scope = get_permission_scope(applicable_for="Motor Vehicle")
    if vehicle:
        enforce_vehicle_scope(vehicle)
    return generate_due_maintenance(
        vehicle,
        companies=scope["companies"] or None,
        branches=scope["branches"] or None,
    )


@frappe.whitelist()
def schedule(maintenance, planned_start, planned_end):
    enforce_document_scope("Vehicle Maintenance", maintenance)
    return schedule_maintenance(maintenance, planned_start, planned_end).as_dict()


@frappe.whitelist()
def start_maintenance_job(maintenance):
    enforce_document_scope("Vehicle Maintenance", maintenance)
    return start_maintenance(maintenance).as_dict()


@frappe.whitelist()
def complete_maintenance_job(maintenance, odometer=None):
    enforce_document_scope("Vehicle Maintenance", maintenance)
    return complete_maintenance(maintenance, float(odometer) if odometer not in (None, "") else None).as_dict()


@frappe.whitelist()
def start_workshop_job(work_order):
    enforce_document_scope("Maintenance Work Order", work_order)
    return start_work_order(work_order).as_dict()


@frappe.whitelist()
def complete_workshop_job(work_order):
    enforce_document_scope("Maintenance Work Order", work_order)
    return complete_work_order(work_order).as_dict()


@frappe.whitelist()
def release_block(vehicle_block):
    enforce_document_scope("Vehicle Block", vehicle_block)
    return release_vehicle_block(vehicle_block).as_dict()


@frappe.whitelist()
def start_vehicle_transfer(vehicle_transfer):
    _enforce_transfer_scope(vehicle_transfer)
    return start_transfer(vehicle_transfer).as_dict()


@frappe.whitelist()
def complete_vehicle_transfer(vehicle_transfer, arrival_odometer, arrival_fuel=None):
    _enforce_transfer_scope(vehicle_transfer)
    return complete_transfer(vehicle_transfer, float(arrival_odometer), arrival_fuel).as_dict()


@frappe.whitelist()
def bill_fine(traffic_fine):
    vehicle = frappe.db.get_value("Traffic Fine", traffic_fine, "vehicle")
    if not vehicle:
        frappe.throw(f"Traffic Fine {traffic_fine} does not exist or has no vehicle.")
    enforce_vehicle_scope(vehicle)
    return invoice_traffic_fine(traffic_fine).as_dict()


@frappe.whitelist()
def approve_sale(vehicle_sale):
    enforce_document_scope("Vehicle Sale", vehicle_sale)
    return approve_vehicle_sale(vehicle_sale).as_dict()


@frappe.whitelist()
def submit_sale(vehicle_sale):
    enforce_document_scope("Vehicle Sale", vehicle_sale)
    return submit_vehicle_sale(vehicle_sale).as_dict()


def _enforce_transfer_scope(vehicle_transfer):
    row = frappe.db.get_value(
        "Vehicle Transfer",
        vehicle_transfer,
        ["company", "source_branch", "destination_branch"],
        as_dict=True,
    )
    if not row:
        frappe.throw(f"Vehicle Transfer {vehicle_transfer} does not exist.")
    enforce_company_branch(row.company, row.source_branch)
    enforce_company_branch(row.company, row.destination_branch)