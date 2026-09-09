from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_months, cint, date_diff, flt, get_datetime, getdate, now_datetime, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.audit import append_audit_event
from dagaar_motors.services.fleet import add_mileage_log, refresh_vehicle_availability_status
from dagaar_motors.services.settings import resolve_cost_center


ACTIVE_MAINTENANCE_STATUSES = {"Planned", "Due", "Scheduled", "In Progress", "Quality Check"}


def validate_maintenance_rule(doc):
    if not any((flt(doc.interval_km), cint(doc.interval_months), flt(doc.interval_engine_hours))):
        frappe.throw(_("Set at least one maintenance interval: mileage, months, or engine hours."))
    if flt(doc.interval_km) < 0 or cint(doc.interval_months) < 0 or flt(doc.interval_engine_hours) < 0:
        frappe.throw(_("Maintenance intervals cannot be negative."))


def calculate_due(vehicle: str, rule: str) -> dict:
    vehicle_doc = frappe.get_cached_doc("Motor Vehicle", vehicle)
    rule_doc = frappe.get_cached_doc("Vehicle Maintenance Rule", rule)
    last = frappe.db.get_value(
        "Vehicle Maintenance",
        {"vehicle": vehicle, "maintenance_rule": rule, "docstatus": 1, "status": "Completed"},
        ["actual_end", "odometer"],
        as_dict=True,
        order_by="actual_end desc, creation desc",
    )
    base_date = getdate(last.actual_end) if last and last.actual_end else getdate(vehicle_doc.last_service_date or vehicle_doc.purchase_date or vehicle_doc.creation)
    base_odometer = flt(last.odometer) if last and last.odometer is not None else flt(
        vehicle_doc.last_service_odometer or vehicle_doc.acquisition_odometer
    )
    due_date = add_months(base_date, cint(rule_doc.interval_months)) if cint(rule_doc.interval_months) else None
    due_odometer = base_odometer + flt(rule_doc.interval_km) if flt(rule_doc.interval_km) else None
    date_due = bool(due_date and getdate(nowdate()) >= getdate(due_date) - timedelta(days=cint(rule_doc.lead_days)))
    mileage_due = bool(
        due_odometer
        and flt(vehicle_doc.current_odometer) >= flt(due_odometer) - flt(rule_doc.lead_km)
    )
    if rule_doc.whichever_occurs_first:
        is_due = date_due or mileage_due
    else:
        checks = [value for value in (date_due if due_date else None, mileage_due if due_odometer else None) if value is not None]
        is_due = all(checks) if checks else False
    return {
        "vehicle": vehicle,
        "rule": rule,
        "due_date": due_date,
        "due_odometer": due_odometer,
        "date_due": date_due,
        "mileage_due": mileage_due,
        "is_due": is_due,
    }


def generate_due_maintenance(
    vehicle: str | None = None,
    *,
    companies: list[str] | None = None,
    branches: list[str] | None = None,
) -> list[str]:
    filters = {"status": ["not in", ["Sold", "Retired"]]}
    if vehicle:
        filters["name"] = vehicle
    if companies:
        filters["company"] = ["in", companies]
    if branches:
        filters["branch"] = ["in", branches]
    vehicles = frappe.get_all("Motor Vehicle", filters=filters, fields=["name", "company", "branch", "category"])
    created: list[str] = []
    for vehicle_row in vehicles:
        rules = _applicable_rules(vehicle_row)
        for rule in rules:
            due = calculate_due(vehicle_row.name, rule.name)
            if not due["is_due"]:
                continue
            existing = frappe.db.get_value(
                "Vehicle Maintenance",
                {
                    "vehicle": vehicle_row.name,
                    "maintenance_rule": rule.name,
                    "status": ["in", list(ACTIVE_MAINTENANCE_STATUSES)],
                    "docstatus": ["<", 2],
                },
                "name",
            )
            if existing:
                continue
            doc = frappe.get_doc(
                {
                    "doctype": "Vehicle Maintenance",
                    "vehicle": vehicle_row.name,
                    "company": vehicle_row.company,
                    "branch": vehicle_row.branch,
                    "maintenance_rule": rule.name,
                    "maintenance_type": rule.maintenance_type,
                    "status": "Due",
                    "due_date": due["due_date"],
                    "due_odometer": due["due_odometer"],
                    "estimated_cost": rule.estimated_cost,
                    "description": rule.instructions,
                }
            )
            doc.insert(ignore_permissions=True)
            created.append(doc.name)
    return created


def validate_maintenance(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.branch = doc.branch or vehicle.branch
    if doc.company != vehicle.company or doc.branch != vehicle.branch:
        frappe.throw(_("Maintenance company and branch must match Vehicle {0}.").format(vehicle.name))
    if doc.planned_start and doc.planned_end and get_datetime(doc.planned_end) <= get_datetime(doc.planned_start):
        frappe.throw(_("Planned maintenance end must be later than its start."))
    if doc.actual_start and doc.actual_end and get_datetime(doc.actual_end) < get_datetime(doc.actual_start):
        frappe.throw(_("Actual maintenance end cannot be before its start."))
    if flt(doc.odometer) and flt(doc.odometer) < flt(vehicle.current_odometer):
        frappe.throw(_("Maintenance odometer cannot be below the vehicle's current odometer."))
    if doc.maintenance_rule:
        rule = frappe.get_cached_doc("Vehicle Maintenance Rule", doc.maintenance_rule)
        if rule.vehicle and rule.vehicle != doc.vehicle:
            frappe.throw(_("Maintenance Rule {0} is restricted to Vehicle {1}.").format(rule.name, rule.vehicle))
        if rule.vehicle_category and rule.vehicle_category != vehicle.category:
            frappe.throw(_("Maintenance Rule {0} does not apply to category {1}.").format(rule.name, vehicle.category))


def schedule_maintenance(maintenance_name: str, planned_start, planned_end):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Fleet Manager",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Vehicle Maintenance", maintenance_name)
    doc = frappe.get_doc("Vehicle Maintenance", maintenance_name)
    if doc.docstatus != 0 or doc.status in {"Completed", "Cancelled"}:
        frappe.throw(_("Maintenance {0} cannot be scheduled from status {1}.").format(doc.name, doc.status))
    doc.planned_start = planned_start
    doc.planned_end = planned_end
    doc.status = "Scheduled"
    doc.save()
    _mark_vehicle_maintenance(doc)
    return doc


def start_maintenance(maintenance_name: str):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Workshop User",
        "Dagaar Motors Fleet Manager",
    )
    lock_document("Vehicle Maintenance", maintenance_name)
    doc = frappe.get_doc("Vehicle Maintenance", maintenance_name)
    if doc.status not in {"Scheduled", "Due"} or doc.docstatus != 0:
        frappe.throw(_("Maintenance {0} must be Due or Scheduled before starting.").format(doc.name))
    doc.status = "In Progress"
    doc.actual_start = now_datetime()
    doc.save()
    _mark_vehicle_maintenance(doc)
    return doc


def complete_maintenance(maintenance_name: str, odometer: float | None = None):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Fleet Manager",
    )
    lock_document("Vehicle Maintenance", maintenance_name)
    doc = frappe.get_doc("Vehicle Maintenance", maintenance_name)
    if doc.docstatus == 1:
        return doc
    if doc.status not in {"In Progress", "Quality Check", "Scheduled", "Due"}:
        frappe.throw(_("Maintenance {0} cannot be completed from status {1}.").format(doc.name, doc.status))
    doc.odometer = odometer if odometer is not None else doc.odometer
    if not flt(doc.odometer):
        doc.odometer = frappe.get_cached_value("Motor Vehicle", doc.vehicle, "current_odometer")
    doc.actual_start = doc.actual_start or now_datetime()
    doc.actual_end = now_datetime()
    doc.status = "Completed"
    doc.submit()
    return doc


def validate_maintenance_submission(doc):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Fleet Manager",
    )
    if doc.status != "Completed":
        frappe.throw(_("Set maintenance status to Completed before submission."))

def process_completed_maintenance(doc):
    if doc.status != "Completed":
        frappe.throw(_("Set maintenance status to Completed before submission."))
    add_mileage_log(
        doc.vehicle,
        "Maintenance",
        doc.odometer,
        source_doctype=doc.doctype,
        source_name=doc.name,
        event_datetime=doc.actual_end or now_datetime(),
        reason=f"Maintenance {doc.name}",
    )
    duration = 0.0
    if doc.actual_start and doc.actual_end:
        duration = max(0, (get_datetime(doc.actual_end) - get_datetime(doc.actual_start)).total_seconds() / 3600)
        frappe.db.set_value("Vehicle Maintenance", doc.name, "downtime_hours", duration, update_modified=False)
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "last_service_date": getdate(doc.actual_end or nowdate()),
            "last_service_odometer": doc.odometer,
            "status": "Inspection",
            "status_reason": f"Maintenance {doc.name} completed; inspection required",
        },
        update_modified=True,
    )
    append_audit_event(doc, "Maintenance Completed", {"odometer": doc.odometer, "downtime_hours": duration})


def cancel_maintenance(doc):
    if doc.work_order and frappe.db.exists("Maintenance Work Order", doc.work_order):
        work_order = frappe.get_doc("Maintenance Work Order", doc.work_order)
        if work_order.docstatus == 1:
            frappe.throw(_("Cancel Work Order {0} before cancelling maintenance.").format(work_order.name))
    refresh_vehicle_availability_status(doc.vehicle)


def validate_work_order(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.branch = doc.branch or vehicle.branch
    if doc.workshop_type == "External" and not doc.supplier:
        frappe.throw(_("Select a Supplier for an external workshop."))
    if get_datetime(doc.planned_end) <= get_datetime(doc.planned_start):
        frappe.throw(_("Work order planned end must be later than planned start."))
    parts = labor = expense = 0.0
    for row in doc.items:
        row.quantity = flt(row.quantity or 1)
        row.amount = flt(row.quantity) * flt(row.rate)
        if row.item_type == "Part":
            parts += flt(row.amount)
        elif row.item_type == "Labor":
            labor += flt(row.amount)
        else:
            expense += flt(row.amount)
    doc.parts_total = parts
    doc.labor_total = labor
    doc.expense_total = expense
    doc.grand_total = parts + labor + expense
    doc.project = doc.project or vehicle.project
    doc.cost_center = doc.cost_center or resolve_cost_center(doc.company, doc.branch, doc.vehicle)
    doc.warehouse = doc.warehouse or vehicle.warehouse
    if doc.actual_start and doc.actual_end:
        doc.downtime_hours = max(0, (get_datetime(doc.actual_end) - get_datetime(doc.actual_start)).total_seconds() / 3600)


def start_work_order(work_order_name: str):
    require_any_role("Dagaar Motors Maintenance Manager", "Dagaar Motors Workshop User")
    lock_document("Maintenance Work Order", work_order_name)
    doc = frappe.get_doc("Maintenance Work Order", work_order_name)
    if doc.docstatus != 0 or doc.status not in {"Draft", "Approved", "Waiting for Parts"}:
        frappe.throw(_("Work Order {0} cannot be started from status {1}.").format(doc.name, doc.status))
    doc.status = "In Progress"
    doc.actual_start = doc.actual_start or now_datetime()
    doc.save()
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {"status": "Maintenance", "status_reason": f"Work Order {doc.name}"},
        update_modified=True,
    )
    if doc.vehicle_maintenance:
        frappe.db.set_value(
            "Vehicle Maintenance",
            doc.vehicle_maintenance,
            {"status": "In Progress", "actual_start": doc.actual_start, "work_order": doc.name},
            update_modified=True,
        )
    return doc


def complete_work_order(work_order_name: str):
    require_any_role("Dagaar Motors Maintenance Manager", "Dagaar Motors Fleet Manager")
    lock_document("Maintenance Work Order", work_order_name)
    doc = frappe.get_doc("Maintenance Work Order", work_order_name)
    if doc.docstatus == 1:
        return doc
    doc.status = "Completed"
    doc.actual_start = doc.actual_start or now_datetime()
    doc.actual_end = now_datetime()
    doc.submit()
    return doc


def validate_work_order_submission(doc):
    require_any_role(
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Fleet Manager",
    )
    if doc.status != "Completed":
        frappe.throw(_("Set Work Order status to Completed before submission."))

def process_completed_work_order(doc):
    if doc.status != "Completed":
        frappe.throw(_("Set Work Order status to Completed before submission."))
    if doc.vehicle_maintenance:
        maintenance = frappe.get_doc("Vehicle Maintenance", doc.vehicle_maintenance)
        frappe.db.set_value(
            "Vehicle Maintenance",
            maintenance.name,
            {
                "work_order": doc.name,
                "actual_cost": doc.grand_total,
                "odometer": doc.odometer,
                "actual_start": doc.actual_start,
                "actual_end": doc.actual_end,
                "status": "Quality Check" if maintenance.docstatus == 0 else maintenance.status,
            },
            update_modified=True,
        )


def validate_vehicle_expense(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.branch = doc.branch or vehicle.branch
    if doc.company != vehicle.company:
        frappe.throw(_("Vehicle Expense company must match Vehicle {0}.").format(vehicle.name))
    doc.project = doc.project or vehicle.project
    doc.cost_center = doc.cost_center or resolve_cost_center(doc.company, doc.branch, doc.vehicle)
    if flt(doc.amount) <= 0:
        frappe.throw(_("Vehicle expense amount must be greater than zero."))
    for source in (doc.purchase_invoice, doc.expense_claim, doc.journal_entry):
        if source:
            break
    else:
        if doc.status == "Posted":
            frappe.throw(_("A posted Vehicle Expense must link to a Purchase Invoice, Expense Claim, or Journal Entry."))


def _mark_vehicle_maintenance(doc):
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "status": "Maintenance",
            "available_from": doc.planned_end,
            "status_reason": f"Maintenance {doc.name}",
        },
        update_modified=True,
    )


def _applicable_rules(vehicle_row) -> list:
    rows = frappe.get_all(
        "Vehicle Maintenance Rule",
        filters={"active": 1},
        fields=[
            "name",
            "maintenance_type",
            "vehicle",
            "vehicle_category",
            "company",
            "estimated_cost",
            "instructions",
        ],
    )
    applicable = []
    for row in rows:
        if row.vehicle and row.vehicle != vehicle_row.name:
            continue
        if row.vehicle_category and row.vehicle_category != vehicle_row.category:
            continue
        if row.company and row.company != vehicle_row.company:
            continue
        applicable.append(row)
    return applicable