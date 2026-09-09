from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.accounting import create_vehicle_sale_invoice
from dagaar_motors.services.audit import append_audit_event
from dagaar_motors.services.availability import get_conflicts, lock_vehicle
from dagaar_motors.services.fleet import recalculate_vehicle_financials
from dagaar_motors.services.idempotency import ensure_idempotency_key
from dagaar_motors.services.settings import get_settings_dict


def validate_vehicle_sale(doc):
    vehicle = frappe.get_cached_doc("Motor Vehicle", doc.vehicle)
    doc.company = doc.company or vehicle.company
    doc.branch = doc.branch or vehicle.branch
    doc.currency = doc.currency or frappe.get_cached_value("Company", doc.company, "default_currency")
    doc.item = doc.item or vehicle.selling_item or vehicle.item
    doc.asking_price = flt(doc.asking_price or vehicle.selling_price)
    doc.minimum_price = flt(doc.minimum_price or vehicle.minimum_selling_price)
    doc.commission_percent = flt(doc.commission_percent or vehicle.sales_commission_percent)
    doc.discount_amount = max(0, flt(doc.asking_price) - flt(doc.sale_price))
    doc.commission_amount = flt(doc.sale_price) * flt(doc.commission_percent) / 100
    doc.sale_date = doc.sale_date or nowdate()
    doc.status = doc.status or "Draft"
    if vehicle.company != doc.company or vehicle.branch != doc.branch:
        frappe.throw(_("Vehicle Sale company and branch must match Vehicle {0}.").format(vehicle.name))
    if not vehicle.sellable:
        frappe.throw(_("Vehicle {0} is not marked sellable.").format(vehicle.name))
    if vehicle.status in {"Sold", "Retired"}:
        frappe.throw(_("Vehicle {0} cannot be sold because its status is {1}.").format(vehicle.name, vehicle.status))
    if flt(doc.sale_price) <= 0:
        frappe.throw(_("Vehicle sale price must be greater than zero."))
    settings = get_settings_dict()
    below_minimum = flt(doc.minimum_price) and flt(doc.sale_price) < flt(doc.minimum_price)
    doc.approval_required = cint(below_minimum and settings.get("vehicle_sale_below_minimum_requires_approval"))
    _protect_sale_approval(doc)
    if doc.approval_required and not doc.approved_by and doc.status not in {"Cancelled", "Completed"}:
        doc.status = "Awaiting Approval"
    ensure_idempotency_key(doc, "vehicle_sale", {"vehicle": doc.vehicle, "buyer": doc.buyer})
    if doc.docstatus == 1 or doc.status in {"Approved", "Invoiced", "Delivered", "Completed"}:
        assert_sale_allowed(doc.vehicle, sale_name=doc.name, sale_date=doc.sale_date)


def validate_vehicle_sale_submission(doc):
    if doc.approval_required and not doc.approved_by:
        frappe.throw(
            _("Vehicle Sale {0} is below the minimum price and must be approved before submission.").format(
                doc.name
            )
        )
    if doc.approval_required and doc.status not in {"Approved", "Invoiced", "Delivered", "Completed"}:
        frappe.throw(_("Approve Vehicle Sale {0} before submission.").format(doc.name))


def _protect_sale_approval(doc):
    """Invalidate stale approvals and prevent approval-field impersonation."""
    previous = None
    if not doc.is_new():
        previous = frappe.db.get_value(
            "Vehicle Sale",
            doc.name,
            ["vehicle", "buyer", "sale_price", "minimum_price", "approved_by", "approval_timestamp"],
            as_dict=True,
        )

    if previous and previous.approved_by:
        commercial_changed = any(
            doc.get(fieldname) != previous.get(fieldname)
            for fieldname in ("vehicle", "buyer", "sale_price", "minimum_price")
        )
        if commercial_changed:
            doc.approved_by = None
            doc.approval_timestamp = None

    previous_approver = previous.approved_by if previous else None
    if doc.approved_by and doc.approved_by != previous_approver:
        require_any_role(
            "Dagaar Motors Vehicle Sales Manager",
            "Dagaar Motors Branch Manager",
            "Dagaar Motors Administrator",
        )
        if doc.approved_by != frappe.session.user:
            frappe.throw(_("The approving user must be the signed-in manager."), frappe.PermissionError)
        approver_roles = set(frappe.get_roles(doc.approved_by))
        allowed = {
            "System Manager",
            "Dagaar Motors Administrator",
            "Dagaar Motors Vehicle Sales Manager",
            "Dagaar Motors Branch Manager",
        }
        if not approver_roles.intersection(allowed):
            frappe.throw(_("User {0} is not authorized to approve vehicle sales.").format(doc.approved_by))
        doc.approval_timestamp = doc.approval_timestamp or now_datetime()


def approve_vehicle_sale(sale_name: str):
    require_any_role(
        "Dagaar Motors Vehicle Sales Manager",
        "Dagaar Motors Branch Manager",
        "Dagaar Motors Administrator",
    )
    lock_document("Vehicle Sale", sale_name)
    doc = frappe.get_doc("Vehicle Sale", sale_name)
    if doc.docstatus != 0 or doc.status in {"Cancelled", "Completed"}:
        frappe.throw(_("Vehicle Sale {0} cannot be approved from status {1}.").format(doc.name, doc.status))
    assert_sale_allowed(doc.vehicle, sale_name=doc.name, sale_date=doc.sale_date)
    doc.approved_by = frappe.session.user
    doc.approval_timestamp = now_datetime()
    doc.status = "Approved"
    doc.save()
    return doc


def submit_vehicle_sale(sale_name: str):
    require_any_role(
        "Dagaar Motors Vehicle Sales Manager",
        "Dagaar Motors Vehicle Salesperson",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Vehicle Sale", sale_name)
    doc = frappe.get_doc("Vehicle Sale", sale_name)
    if doc.docstatus == 1:
        return doc
    if doc.approval_required and not doc.approved_by:
        frappe.throw(_("This sale requires manager approval."))
    if doc.status not in {"Approved", "Qualified", "Reserved"}:
        doc.status = "Approved"
    assert_sale_allowed(doc.vehicle, sale_name=doc.name, sale_date=doc.sale_date)
    doc.submit()
    return doc


def process_vehicle_sale(doc):
    validate_vehicle_sale_submission(doc)
    assert_sale_allowed(doc.vehicle, sale_name=doc.name, sale_date=doc.sale_date)
    invoice = create_vehicle_sale_invoice(doc)
    vehicle_status = frappe.db.get_value("Motor Vehicle", doc.vehicle, "status")
    if invoice.docstatus == 1 and cint(get_settings_dict().get("auto_mark_vehicle_sold")):
        if vehicle_status != "Sold":
            finalize_vehicle_sale(doc.name, invoice.name)
        else:
            frappe.db.set_value(
                "Vehicle Sale", doc.name, {"sales_invoice": invoice.name, "status": "Completed"}, update_modified=False
            )
    else:
        frappe.db.set_value(
            "Vehicle Sale", doc.name, {"sales_invoice": invoice.name, "status": "Invoiced"}, update_modified=False
        )


def finalize_vehicle_sale(sale_name: str, invoice_name: str | None = None):
    lock_document("Vehicle Sale", sale_name)
    sale = frappe.get_doc("Vehicle Sale", sale_name)
    invoice_name = invoice_name or sale.sales_invoice
    if not invoice_name:
        frappe.throw(_("Create the vehicle Sales Invoice before finalizing the sale."))
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1:
        frappe.throw(_("Sales Invoice {0} must be submitted before the vehicle is marked sold.").format(invoice.name))
    vehicle = frappe.get_doc("Motor Vehicle", sale.vehicle)
    if vehicle.status == "Sold" and vehicle.sale_invoice == invoice.name:
        return sale
    lock_vehicle(sale.vehicle)
    assert_sale_allowed(sale.vehicle, sale_name=sale.name, sale_date=sale.sale_date)
    vehicle = frappe.get_doc("Motor Vehicle", sale.vehicle)
    profit_loss = flt(sale.sale_price) - flt(vehicle.initial_total_cost) - flt(vehicle.operating_cost) - flt(vehicle.maintenance_cost)
    frappe.db.set_value(
        "Vehicle Sale",
        sale.name,
        {"status": "Completed", "profit_loss": profit_loss, "sales_invoice": invoice.name},
        update_modified=True,
    )
    frappe.db.set_value(
        "Motor Vehicle",
        vehicle.name,
        {
            "status": "Sold",
            "rentable": 0,
            "sellable": 0,
            "buyer": sale.buyer,
            "sale_date": sale.sale_date,
            "sale_invoice": invoice.name,
            "total_sale_revenue": invoice.base_net_total,
            "current_customer": None,
            "current_rental_agreement": None,
            "available_from": None,
            "status_reason": f"Sold through Vehicle Sale {sale.name}",
        },
        update_modified=True,
    )
    sale_item = vehicle.selling_item or vehicle.item
    if sale_item and frappe.db.exists("Item", sale_item) and frappe.get_meta("Item").has_field("is_sales_item"):
        frappe.db.set_value("Item", sale_item, "is_sales_item", 0, update_modified=False)
    append_audit_event(sale, "Vehicle Sold", {"invoice": invoice.name, "profit_loss": profit_loss})
    sale.db_set("audit_log", sale.audit_log, update_modified=False)
    recalculate_vehicle_financials(vehicle.name)
    return sale


def cancel_vehicle_sale(doc):
    if doc.sales_invoice and frappe.db.exists("Sales Invoice", doc.sales_invoice):
        invoice = frappe.get_doc("Sales Invoice", doc.sales_invoice)
        if invoice.docstatus == 1:
            frappe.throw(_("Cancel Sales Invoice {0} before cancelling Vehicle Sale {1}.").format(invoice.name, doc.name))
    vehicle = frappe.get_doc("Motor Vehicle", doc.vehicle)
    if vehicle.sale_invoice == doc.sales_invoice and vehicle.status == "Sold":
        frappe.throw(_("A completed vehicle disposal requires an authorized reversal workflow; it cannot be cancelled directly."))


def assert_sale_allowed(vehicle_name: str, *, sale_name: str | None = None, sale_date=None):
    lock_vehicle(vehicle_name)
    vehicle = frappe.get_doc("Motor Vehicle", vehicle_name)
    if not vehicle.sellable:
        frappe.throw(_("Vehicle {0} is not marked sellable.").format(vehicle.name), title=_("Vehicle Sale Blocked"))
    if vehicle.status in {"Sold", "Retired"}:
        frappe.throw(_("Vehicle {0} cannot be sold because its status is {1}.").format(vehicle.name, vehicle.status))
    handover = get_datetime(sale_date or now_datetime())
    conflicts = get_conflicts(
        vehicle.name,
        handover,
        handover + timedelta(days=1),
        exclude_doctype="Vehicle Sale",
        exclude_name=sale_name,
        include_vehicle_state=False,
    )
    relevant = [row for row in conflicts if row.get("doctype") != "Vehicle Sale"]
    if relevant:
        first = relevant[0]
        frappe.throw(
            _("Vehicle {0} cannot be sold because it conflicts with {1} {2} ({3}).").format(
                vehicle.name,
                first.get("doctype"),
                first.get("name"),
                first.get("status") or first.get("reason"),
            ),
            title=_("Vehicle Sale Blocked"),
        )