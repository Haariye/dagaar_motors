from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate, now_datetime

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.accounting import create_sales_invoice, resolve_charge_mapping
from dagaar_motors.services.availability import assert_available, lock_vehicle
from dagaar_motors.services.fleet import add_mileage_log, refresh_vehicle_availability_status
from dagaar_motors.services.settings import resolve_currency


def validate_vehicle_block(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.branch = doc.branch or vehicle.branch
    if doc.company != vehicle.company or doc.branch != vehicle.branch:
        frappe.throw(_("Vehicle Block company and branch must match Vehicle {0}.").format(vehicle.name))
    if doc.to_datetime and get_datetime(doc.to_datetime) <= get_datetime(doc.from_datetime):
        frappe.throw(_("Vehicle block end must be later than its start."))
    doc.status = doc.status or "Active"


def apply_vehicle_block(doc):
    if doc.status == "Active":
        frappe.db.set_value(
            "Motor Vehicle",
            doc.vehicle,
            {
                "status": "Blocked",
                "available_from": doc.to_datetime,
                "status_reason": f"{doc.block_type} block {doc.name}: {doc.reason}",
            },
            update_modified=True,
        )
    elif doc.status in {"Released", "Cancelled"}:
        refresh_vehicle_availability_status(doc.vehicle)


def release_vehicle_block(block_name: str):
    require_any_role(
        "Dagaar Motors Fleet Manager",
        "Dagaar Motors Branch Manager",
        "Dagaar Motors Administrator",
    )
    doc = frappe.get_doc("Vehicle Block", block_name)
    if doc.status != "Active":
        return doc
    doc.status = "Released"
    doc.released_on = now_datetime()
    doc.released_by = frappe.session.user
    doc.save()
    return doc


def populate_inspection_from_template(doc):
    if not doc.template or doc.items:
        return
    template = frappe.get_cached_doc("Inspection Template", doc.template)
    if not template.active:
        frappe.throw(_("Inspection Template {0} is disabled.").format(template.name))
    if template.vehicle_category:
        category = frappe.get_cached_value("Motor Vehicle", doc.vehicle, "category")
        if category != template.vehicle_category:
            frappe.throw(_("Inspection Template {0} does not apply to this vehicle category.").format(template.name))
    for item in template.items:
        doc.append("items", {"area": item.area, "item": item.item})


def validate_inspection(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    if flt(doc.odometer) < flt(vehicle.current_odometer):
        frappe.throw(_("Inspection odometer cannot be below the current vehicle odometer."))
    if not doc.inspector:
        doc.inspector = frappe.session.user
    populate_inspection_from_template(doc)
    template = frappe.get_cached_doc("Inspection Template", doc.template)
    template_map = {(row.area, row.item): row for row in template.items}
    failures = 0
    for row in doc.items:
        item_rule = template_map.get((row.area, row.item))
        if item_rule and item_rule.mandatory and not row.result:
            frappe.throw(_("Inspection result is required for {0} / {1}.").format(row.area, row.item))
        if row.result in {"Fail", "Poor", "No"}:
            failures += 1
            if item_rule and item_rule.photo_required_on_fail and not row.photo:
                frappe.throw(_("A photo is required for failed item {0} / {1}.").format(row.area, row.item))
    if doc.docstatus == 0 and doc.status not in {"Cancelled"}:
        doc.status = "Requires Action" if failures else "Passed"


def process_inspection(doc):
    failed = any(row.result in {"Fail", "Poor", "No"} for row in doc.items)
    status = "Requires Action" if failed else "Passed"
    frappe.db.set_value("Vehicle Inspection", doc.name, "status", status, update_modified=False)
    if doc.inspection_type == "Post-Rental":
        frappe.db.set_value(
            "Motor Vehicle",
            doc.vehicle,
            {
                "status": "Inspection" if failed else "Available",
                "status_reason": f"Post-rental inspection {doc.name}: {status}",
            },
            update_modified=True,
        )
    elif doc.inspection_type in {"Maintenance", "Sales"} and not failed:
        refresh_vehicle_availability_status(doc.vehicle)


def validate_damage_report(doc):
    if doc.rental_agreement:
        agreement = frappe.get_cached_doc("Rental Agreement", doc.rental_agreement)
        if agreement.vehicle != doc.vehicle:
            frappe.throw(_("Damage report vehicle must match Rental Agreement {0}.").format(agreement.name))
        doc.customer = doc.customer or agreement.customer
    if flt(doc.customer_liability) + flt(doc.company_liability) > max(
        flt(doc.actual_repair_cost), flt(doc.repair_estimate)
    ) and max(flt(doc.actual_repair_cost), flt(doc.repair_estimate)):
        frappe.throw(_("Customer and company liability cannot exceed the damage cost."))


def validate_accident(doc):
    if doc.rental_agreement:
        agreement = frappe.get_cached_doc("Rental Agreement", doc.rental_agreement)
        if agreement.vehicle != doc.vehicle:
            frappe.throw(_("Accident vehicle must match Rental Agreement {0}.").format(agreement.name))
    if flt(doc.customer_liability) + flt(doc.company_liability) > max(flt(doc.actual_cost), flt(doc.estimated_cost)) and max(
        flt(doc.actual_cost), flt(doc.estimated_cost)
    ):
        frappe.throw(_("Customer and company liability cannot exceed the accident cost."))
    if doc.status in {"Reported", "Under Investigation", "Claim Filed", "Repairing"}:
        frappe.db.set_value(
            "Motor Vehicle",
            doc.vehicle,
            {"status": "Blocked", "status_reason": f"Accident {doc.name or 'new'}"},
            update_modified=True,
        )


def validate_traffic_fine(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.plate_number = doc.plate_number or vehicle.license_plate
    if not doc.rental_agreement:
        agreement = frappe.db.sql(
            """
            select name, customer
            from `tabRental Agreement`
            where vehicle = %(vehicle)s and docstatus = 1
              and pickup_datetime <= %(violation)s
              and coalesce(actual_return_datetime, expected_return_datetime) >= %(violation)s
            order by pickup_datetime desc
            limit 1
            """,
            {"vehicle": doc.vehicle, "violation": doc.violation_datetime},
            as_dict=True,
        )
        if agreement:
            doc.rental_agreement = agreement[0].name
            doc.customer = doc.customer or agreement[0].customer
    if doc.rental_agreement:
        agreement = frappe.get_cached_doc("Rental Agreement", doc.rental_agreement)
        doc.customer = doc.customer or agreement.customer
        if not doc.driver and agreement.drivers:
            primary = next((row.full_name for row in agreement.drivers if row.primary_driver), agreement.drivers[0].full_name)
            doc.driver = primary
    if flt(doc.fine_amount) <= 0:
        frappe.throw(_("Traffic fine amount must be greater than zero."))


def invoice_traffic_fine(fine_name: str):
    require_any_role(
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Accountant",
        "Dagaar Motors Branch Manager",
    )
    fine = frappe.get_doc("Traffic Fine", fine_name)
    if fine.sales_invoice:
        return frappe.get_doc("Sales Invoice", fine.sales_invoice)
    if not fine.customer or not fine.rental_agreement:
        frappe.throw(_("Identify the responsible rental and customer before invoicing this fine."))
    agreement = frappe.get_cached_doc("Rental Agreement", fine.rental_agreement)
    mapping = resolve_charge_mapping(
        category="Fine", company=agreement.company, branch=agreement.branch, vehicle=fine.vehicle
    )
    invoice = create_sales_invoice(
        company=agreement.company,
        customer=fine.customer,
        currency=agreement.currency,
        branch=agreement.branch,
        vehicle=fine.vehicle,
        lines=[
            {
                **mapping,
                "qty": 1,
                "rate": flt(fine.fine_amount) + flt(fine.administration_fee),
                "amount": flt(fine.fine_amount) + flt(fine.administration_fee),
                "description": f"Traffic fine {fine.reference_number or fine.name}",
            }
        ],
        source_references={
            "dagaar_rental_agreement": fine.rental_agreement,
            "dagaar_traffic_fine": fine.name,
            "dagaar_motor_vehicle": fine.vehicle,
        },
        remarks=f"Traffic Fine {fine.name}",
    )
    fine.db_set({"sales_invoice": invoice.name, "status": "Invoiced", "customer_charge_status": "Charged"})
    return invoice


def validate_transfer(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.source_branch = doc.source_branch or vehicle.branch
    if doc.source_branch == doc.destination_branch:
        frappe.throw(_("Source and destination branches must be different."))
    for branch in (doc.source_branch, doc.destination_branch):
        if frappe.get_cached_value("Motor Branch", branch, "company") != doc.company:
            frappe.throw(_("Branch {0} does not belong to Company {1}.").format(branch, doc.company))
    if get_datetime(doc.arrival_datetime) <= get_datetime(doc.departure_datetime):
        frappe.throw(_("Transfer arrival must be later than departure."))
    if flt(doc.departure_odometer) < flt(vehicle.current_odometer):
        frappe.throw(_("Transfer departure odometer cannot be below the current vehicle odometer."))
    if doc.arrival_odometer and flt(doc.arrival_odometer) < flt(doc.departure_odometer):
        frappe.throw(_("Transfer arrival odometer cannot be below departure odometer."))
    if doc.status in {"Approved", "In Transit", "Arrived", "Completed"}:
        assert_available(
            doc.vehicle,
            doc.departure_datetime,
            doc.actual_arrival_datetime or doc.arrival_datetime,
            exclude_doctype="Vehicle Transfer",
            exclude_name=doc.name,
            lock=not doc.is_new(),
        )


def start_transfer(transfer_name: str):
    require_any_role("Dagaar Motors Fleet Manager", "Dagaar Motors Branch Manager")
    lock_document("Vehicle Transfer", transfer_name)
    doc = frappe.get_doc("Vehicle Transfer", transfer_name)
    if doc.docstatus != 0 or doc.status not in {"Draft", "Approved"}:
        frappe.throw(_("Vehicle Transfer {0} cannot start from status {1}.").format(doc.name, doc.status))
    assert_available(
        doc.vehicle,
        doc.departure_datetime,
        doc.arrival_datetime,
        exclude_doctype="Vehicle Transfer",
        exclude_name=doc.name,
    )
    doc.status = "In Transit"
    doc.save()
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {"status": "In Transit", "available_from": doc.arrival_datetime, "status_reason": f"Transfer {doc.name}"},
        update_modified=True,
    )
    return doc


def complete_transfer(transfer_name: str, arrival_odometer: float, arrival_fuel: str | None = None):
    require_any_role("Dagaar Motors Fleet Manager", "Dagaar Motors Branch Manager")
    lock_document("Vehicle Transfer", transfer_name)
    doc = frappe.get_doc("Vehicle Transfer", transfer_name)
    if doc.docstatus == 1:
        return doc
    if doc.status != "In Transit":
        frappe.throw(_("Vehicle Transfer {0} must be In Transit before completion.").format(doc.name))
    doc.actual_arrival_datetime = now_datetime()
    doc.arrival_odometer = arrival_odometer
    doc.arrival_fuel = arrival_fuel
    doc.status = "Completed"
    doc.submit()
    return doc


def process_transfer(doc):
    if doc.status != "Completed":
        frappe.throw(_("Set transfer status to Completed before submission."))
    add_mileage_log(
        doc.vehicle,
        "Transfer",
        doc.arrival_odometer,
        source_doctype=doc.doctype,
        source_name=doc.name,
        event_datetime=doc.actual_arrival_datetime or doc.arrival_datetime,
        reason=f"Vehicle Transfer {doc.name}",
    )
    destination = frappe.get_cached_doc("Motor Branch", doc.destination_branch)
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "branch": doc.destination_branch,
            "warehouse": destination.warehouse,
            "cost_center": destination.cost_center,
            "current_location": destination.city or destination.pickup_location,
            "fuel_level": doc.arrival_fuel,
            "status": "Inspection",
            "available_from": None,
            "status_reason": f"Arrived under Transfer {doc.name}; inspection required",
        },
        update_modified=True,
    )