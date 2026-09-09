from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.accounting import create_extension_invoice
from dagaar_motors.services.audit import append_audit_event
from dagaar_motors.services.availability import assert_available, lock_vehicle
from dagaar_motors.services.idempotency import ensure_idempotency_key
from dagaar_motors.services.pricing import apply_result_to_document, calculate_price
from dagaar_motors.services.settings import get_settings_dict


def validate_extension(doc):
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    if agreement.docstatus != 1 or agreement.status not in {"Active", "Extended", "Overdue", "Extension Requested"}:
        frappe.throw(
            _("Rental Agreement {0} must be active before it can be extended.").format(agreement.name)
        )
    _copy_agreement_context(doc, agreement)
    doc.status = doc.status or "Draft"
    if not doc.requested_by:
        doc.requested_by = frappe.session.user

    current_end = get_datetime(agreement.expected_return_datetime)
    original_end = get_datetime(doc.original_end_datetime)
    new_end = get_datetime(doc.new_end_datetime)
    if original_end != current_end:
        frappe.throw(
            _(
                "The agreement currently ends on {0}. Refresh this extension before submitting it."
            ).format(agreement.expected_return_datetime)
        )
    if not new_end or new_end <= original_end:
        frappe.throw(_("The new return date must be later than the current agreement end date."))

    assert_available(
        agreement.vehicle,
        original_end,
        new_end,
        exclude_doctype="Rental Agreement",
        exclude_name=agreement.name,
        lock=not doc.is_new(),
    )
    result = calculate_price(
        {
            "pickup_datetime": original_end,
            "return_datetime": new_end,
            "company": agreement.company,
            "branch": agreement.branch,
            "currency": agreement.currency,
            "vehicle": agreement.vehicle,
            "vehicle_category": agreement.vehicle_category,
            "rental_type": agreement.rental_type,
            "customer": agreement.customer,
            "pickup_location": agreement.pickup_location,
            "return_location": agreement.return_location,
            "one_way": agreement.one_way,
            "discount_percent": doc.discount_percent,
            "approved_by": doc.approved_by,
            "user": frappe.session.user,
        }
    )
    apply_result_to_document(doc, result)
    doc.rate = result.get("base_rate")
    ensure_idempotency_key(
        doc,
        "extension",
        {
            "agreement": agreement.name,
            "from": original_end,
            "to": new_end,
        },
    )


def approve_and_submit_extension(extension_name: str):
    require_any_role(
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
        "Dagaar Motors Administrator",
    )
    lock_document("Rental Extension", extension_name)
    doc = frappe.get_doc("Rental Extension", extension_name)
    if doc.docstatus == 1:
        return doc
    doc.approved_by = frappe.session.user
    doc.approval_timestamp = now_datetime()
    doc.status = "Approved"
    doc.submit()
    return doc


def apply_extension(doc):
    lock_document("Rental Agreement", doc.rental_agreement)
    lock_vehicle(doc.vehicle)
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    if get_datetime(agreement.expected_return_datetime) != get_datetime(doc.original_end_datetime):
        frappe.throw(
            _("Rental Agreement {0} was changed by another user. Extension {1} was not applied.").format(
                agreement.name, doc.name
            )
        )
    assert_available(
        doc.vehicle,
        doc.original_end_datetime,
        doc.new_end_datetime,
        exclude_doctype="Rental Agreement",
        exclude_name=agreement.name,
        lock=False,
    )
    frappe.db.set_value(
        "Rental Agreement",
        agreement.name,
        {
            "expected_return_datetime": doc.new_end_datetime,
            "status": "Extended",
            "status_reason": f"Approved Extension {doc.name}",
        },
        update_modified=True,
    )
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {"available_from": doc.new_end_datetime, "status_reason": f"Extended under {doc.name}"},
        update_modified=True,
    )
    settings = get_settings_dict()
    invoice = None
    if settings.get("auto_invoice_extensions"):
        invoice = create_extension_invoice(doc)
        frappe.db.set_value(
            "Rental Extension",
            doc.name,
            {"sales_invoice": invoice.name, "status": "Invoiced"},
            update_modified=False,
        )
        frappe.db.set_value(
            "Rental Agreement",
            agreement.name,
            "invoiced_through_datetime",
            doc.new_end_datetime,
            update_modified=False,
        )
    append_audit_event(
        agreement,
        "Rental Extended",
        {
            "extension": doc.name,
            "from": str(doc.original_end_datetime),
            "to": str(doc.new_end_datetime),
            "invoice": invoice.name if invoice else None,
        },
    )
    agreement.db_set("audit_log", agreement.audit_log, update_modified=False)


def cancel_extension(doc):
    if doc.sales_invoice and frappe.db.exists("Sales Invoice", doc.sales_invoice):
        invoice = frappe.get_doc("Sales Invoice", doc.sales_invoice)
        if invoice.docstatus == 1:
            frappe.throw(_("Cancel Sales Invoice {0} before cancelling this extension.").format(invoice.name))
    lock_document("Rental Agreement", doc.rental_agreement)
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    if get_datetime(agreement.expected_return_datetime) != get_datetime(doc.new_end_datetime):
        frappe.throw(
            _("Extension {0} is not the latest applied extension and cannot be cancelled directly.").format(doc.name)
        )
    later = frappe.db.exists(
        "Rental Extension",
        {
            "rental_agreement": agreement.name,
            "docstatus": 1,
            "original_end_datetime": [">=", doc.new_end_datetime],
            "name": ["!=", doc.name],
        },
    )
    if later:
        frappe.throw(_("Cancel later extensions before cancelling Extension {0}.").format(doc.name))
    frappe.db.set_value(
        "Rental Agreement",
        agreement.name,
        {
            "expected_return_datetime": doc.original_end_datetime,
            "status": "Active",
            "status_reason": f"Extension {doc.name} cancelled",
        },
        update_modified=True,
    )
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {"available_from": doc.original_end_datetime, "status_reason": f"Extension {doc.name} cancelled"},
        update_modified=True,
    )


def _copy_agreement_context(doc, agreement):
    values = {
        "vehicle": agreement.vehicle,
        "company": agreement.company,
        "branch": agreement.branch,
        "currency": agreement.currency,
    }
    for fieldname, value in values.items():
        if doc.get(fieldname) and doc.get(fieldname) != value:
            frappe.throw(_("{0} must match Rental Agreement {1}.").format(fieldname.replace("_", " ").title(), agreement.name))
        doc.set(fieldname, value)
    if doc.is_new() and not doc.original_end_datetime:
        doc.original_end_datetime = agreement.expected_return_datetime