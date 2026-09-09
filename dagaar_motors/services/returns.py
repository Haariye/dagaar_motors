from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.accounting import create_return_invoice
from dagaar_motors.services.audit import append_audit_event
from dagaar_motors.services.deposits import create_transaction, update_deposit_totals
from dagaar_motors.services.fleet import add_mileage_log, refresh_vehicle_availability_status
from dagaar_motors.services.idempotency import ensure_idempotency_key
from dagaar_motors.services.settings import get_settings_dict


FUEL_LEVEL_UNITS = {
    "Empty": 0,
    "1/8": 1,
    "1/4": 2,
    "3/8": 3,
    "1/2": 4,
    "5/8": 5,
    "3/4": 6,
    "7/8": 7,
    "Full": 8,
}


def validate_return(doc):
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    if agreement.docstatus != 1 or agreement.status not in {"Active", "Extended", "Overdue", "Return Processing"}:
        frappe.throw(_("Rental Agreement {0} is not active and cannot be returned.").format(agreement.name))
    _copy_agreement_context(doc, agreement)
    doc.status = doc.status or "Draft"
    if get_datetime(doc.return_datetime) < get_datetime(agreement.pickup_datetime):
        frappe.throw(_("Return date and time cannot be before checkout."))
    if flt(doc.return_odometer) < flt(agreement.checkout_odometer):
        frappe.throw(
            _("Return odometer {0} cannot be lower than checkout odometer {1}.").format(
                doc.return_odometer, agreement.checkout_odometer
            )
        )
    doc.checkout_odometer = agreement.checkout_odometer
    doc.checkout_fuel_level = agreement.checkout_fuel_level
    doc.mileage_used = flt(doc.return_odometer) - flt(agreement.checkout_odometer)
    _calculate_included_mileage(doc, agreement)
    _refresh_automatic_charges(doc, agreement)
    _apply_actual_usage(doc, agreement)
    _calculate_reconciliation(doc, agreement)
    ensure_idempotency_key(
        doc,
        "return",
        {"agreement": agreement.name, "datetime": doc.return_datetime, "odometer": doc.return_odometer},
    )
    if cint(get_settings_dict().get("require_return_inspection")) and not doc.inspection:
        doc.status = "Inspection Pending"
    if doc.inspection:
        inspection = frappe.get_doc("Vehicle Inspection", doc.inspection)
        if inspection.vehicle != doc.vehicle or inspection.status not in {"Passed", "Failed", "Requires Action"}:
            frappe.throw(_("Inspection {0} is not a completed return inspection for this vehicle.").format(inspection.name))


def complete_return(return_name: str):
    require_any_role(
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Rental Return", return_name)
    doc = frappe.get_doc("Rental Return", return_name)
    if doc.docstatus == 1:
        return doc
    if cint(get_settings_dict().get("require_return_inspection")) and not doc.inspection:
        frappe.throw(_("Complete the return inspection before finalizing the return."))
    doc.status = "Completed"
    doc.submit()
    return doc


def process_return(doc):
    lock_document("Rental Agreement", doc.rental_agreement)
    lock_document("Motor Vehicle", doc.vehicle)
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    if agreement.rental_return and agreement.rental_return != doc.name:
        frappe.throw(_("Rental Agreement {0} was already returned under {1}.").format(agreement.name, agreement.rental_return))

    invoice = None
    if flt(doc.additional_charge_total) > 0:
        # Submit immediately so the amount can be settled against the deposit.
        invoice = create_return_invoice(doc, submit=True)
        frappe.db.set_value(
            "Rental Return",
            doc.name,
            {"final_sales_invoice": invoice.name, "additional_invoice_total": invoice.grand_total},
            update_modified=False,
        )

    if flt(doc.deposit_utilized) > 0:
        if not doc.security_deposit:
            frappe.throw(_("A security deposit is required before applying a deposit amount."))
        if not invoice or invoice.docstatus != 1:
            frappe.throw(_("Submit the final return invoice before applying the security deposit."))
        create_transaction(
            doc.security_deposit,
            "Allocation",
            doc.deposit_utilized,
            sales_invoice=invoice.name,
            allocations=[
                {
                    "allocation_type": "Outstanding Rent",
                    "amount": doc.deposit_utilized,
                    "source_doctype": "Rental Return",
                    "source_name": doc.name,
                    "description": f"Return reconciliation {doc.name}",
                }
            ],
            remarks=f"Applied during return {doc.name}",
            request_token=f"rental-return:{doc.name}:deposit-allocation",
        )
        update_deposit_totals(doc.security_deposit)

    add_mileage_log(
        doc.vehicle,
        "Return",
        doc.return_odometer,
        source_doctype=doc.doctype,
        source_name=doc.name,
        event_datetime=doc.return_datetime,
        reason=f"Rental return {doc.name}",
    )
    agreement_values = {
        "actual_return_datetime": doc.return_datetime,
        "return_odometer": doc.return_odometer,
        "return_fuel_level": doc.return_fuel_level,
        "return_inspection": doc.inspection,
        "rental_return": doc.name,
        "status": "Completed",
        "status_reason": f"Completed through Rental Return {doc.name}",
    }
    frappe.db.set_value("Rental Agreement", agreement.name, agreement_values, update_modified=True)
    if agreement.reservation:
        frappe.db.set_value("Rental Reservation", agreement.reservation, "status", "Completed", update_modified=True)

    needs_action = doc.condition in {"Damaged", "Unsafe"}
    next_status = "Maintenance" if doc.condition == "Unsafe" else "Inspection" if needs_action or doc.inspection else "Available"
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "status": next_status,
            "current_customer": None,
            "current_rental_agreement": None,
            "last_return_odometer": doc.return_odometer,
            "fuel_level": doc.return_fuel_level,
            "available_from": None if next_status == "Available" else now_datetime(),
            "status_reason": f"Returned under {doc.name}",
        },
        update_modified=True,
    )
    if next_status == "Available":
        refresh_vehicle_availability_status(doc.vehicle)

    if doc.security_deposit:
        update_deposit_totals(doc.security_deposit)
        balance = flt(frappe.db.get_value("Security Deposit", doc.security_deposit, "balance"))
        if balance > 0:
            frappe.db.set_value("Security Deposit", doc.security_deposit, "status", "Refund Pending")
            frappe.db.set_value("Rental Return", doc.name, "refund_amount", balance, update_modified=False)

    frappe.db.set_value("Rental Return", doc.name, "status", "Completed", update_modified=False)

    append_audit_event(
        agreement,
        "Rental Returned",
        {
            "return": doc.name,
            "odometer": doc.return_odometer,
            "condition": doc.condition,
            "invoice": invoice.name if invoice else None,
        },
    )
    agreement.db_set("audit_log", agreement.audit_log, update_modified=False)


def cancel_return(doc):
    if doc.final_sales_invoice and frappe.db.exists("Sales Invoice", doc.final_sales_invoice):
        invoice = frappe.get_doc("Sales Invoice", doc.final_sales_invoice)
        if invoice.docstatus == 1:
            frappe.throw(_("Cancel Sales Invoice {0} before cancelling this return.").format(invoice.name))
    allocations = frappe.get_all(
        "Deposit Transaction",
        filters={"security_deposit": doc.security_deposit, "sales_invoice": doc.final_sales_invoice, "docstatus": 1},
        pluck="name",
    ) if doc.security_deposit and doc.final_sales_invoice else []
    if allocations:
        frappe.throw(_("Cancel the linked deposit allocation before cancelling this return."))
    frappe.db.set_value(
        "Rental Agreement",
        doc.rental_agreement,
        {
            "actual_return_datetime": None,
            "return_odometer": None,
            "return_fuel_level": None,
            "return_inspection": None,
            "rental_return": None,
            "status": "Active",
            "status_reason": f"Rental Return {doc.name} cancelled",
        },
        update_modified=True,
    )
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "status": "Rented",
            "current_customer": doc.customer,
            "current_rental_agreement": doc.rental_agreement,
            "available_from": frappe.db.get_value("Rental Agreement", doc.rental_agreement, "expected_return_datetime"),
            "status_reason": f"Rental Return {doc.name} cancelled",
        },
        update_modified=True,
    )


def _copy_agreement_context(doc, agreement):
    values = {
        "vehicle": agreement.vehicle,
        "customer": agreement.customer,
        "company": agreement.company,
        "branch": agreement.branch,
        "currency": agreement.currency,
        "security_deposit": agreement.security_deposit,
    }
    for fieldname, value in values.items():
        if doc.get(fieldname) and doc.get(fieldname) != value:
            frappe.throw(_("{0} must match Rental Agreement {1}.").format(fieldname.replace("_", " ").title(), agreement.name))
        doc.set(fieldname, value)
    if doc.is_new():
        doc.return_datetime = doc.return_datetime or now_datetime()
        doc.checkout_odometer = agreement.checkout_odometer
        doc.checkout_fuel_level = agreement.checkout_fuel_level


def _calculate_included_mileage(doc, agreement):
    included_per_unit = 0.0
    try:
        snapshot = frappe.parse_json(agreement.pricing_snapshot or "{}")
        included_per_unit = flt(snapshot.get("included_km"))
    except Exception:
        included_per_unit = 0.0
    if not included_per_unit:
        included_per_unit = flt(
            frappe.get_cached_value("Motor Vehicle", agreement.vehicle, "included_km_per_day")
        )
    units = max(1, math.ceil(flt(agreement.duration_units or 1)))
    doc.included_mileage = included_per_unit * units
    doc.excess_mileage = max(0, flt(doc.mileage_used) - flt(doc.included_mileage))


def _refresh_automatic_charges(doc, agreement):
    automated_codes = {"MILEAGE", "FUEL", "LATE"}
    preserved = []
    for row in doc.charges or []:
        code = frappe.get_cached_value("Rental Charge Type", row.charge_type, "code") if row.charge_type else None
        if code not in automated_codes:
            preserved.append(row.as_dict())
    doc.set("charges", [])
    for row in preserved:
        doc.append(
            "charges",
            {field: row.get(field) for field in ("charge_type", "description", "quantity", "rate", "amount", "source_doctype", "source_name")},
        )

    snapshot = frappe.parse_json(agreement.pricing_snapshot or "{}")
    excess_rate = flt(snapshot.get("excess_km_rate")) or flt(
        frappe.get_cached_value("Motor Vehicle", agreement.vehicle, "excess_km_rate")
    )
    if flt(doc.excess_mileage) > 0 and excess_rate > 0:
        _append_charge(doc, "MILEAGE", doc.excess_mileage, excess_rate, "Excess mileage")

    settings = get_settings_dict()
    missing_fuel_units = max(
        0,
        FUEL_LEVEL_UNITS.get(doc.checkout_fuel_level, 0) - FUEL_LEVEL_UNITS.get(doc.return_fuel_level, 0),
    )
    fuel_unit_price = flt(settings.get("fuel_unit_price"))
    if missing_fuel_units and fuel_unit_price:
        _append_charge(doc, "FUEL", missing_fuel_units, fuel_unit_price, "Fuel replenishment")

    grace_minutes = cint(settings.get("grace_period_minutes"))
    late_minutes = max(
        0,
        math.ceil((get_datetime(doc.return_datetime) - get_datetime(agreement.expected_return_datetime)).total_seconds() / 60)
        - grace_minutes,
    )
    if late_minutes:
        late_hours = math.ceil(late_minutes / 60)
        hourly_rate = flt(agreement.base_rate) / 24 if flt(agreement.base_rate) else 0
        if hourly_rate:
            _append_charge(doc, "LATE", late_hours, hourly_rate, "Late return")
    doc.additional_charge_total = sum(flt(row.amount) for row in doc.charges)


def _base_billed_at_checkout(agreement) -> bool:
    return bool(agreement.current_invoice and frappe.db.exists("Sales Invoice", agreement.current_invoice))


def _apply_actual_usage(doc, agreement):
    """Recalculate rental revenue from the actual hours used.

    Time is billed in whole days (each 24 hours started counts as one day,
    matching the pricing engine). When the customer returns early the base
    rental is recomputed for the actual period; when the base was not billed
    at checkout (invoice timing "On Return") the base rental and extras are
    billed now so the final invoice reflects real usage before it is settled
    against the security deposit.
    """
    from dagaar_motors.services.pricing import calculate_price

    # Remove any base/extras rows this function added on a previous validation
    # so repeated saves never duplicate them.
    managed = {"Rental usage", "Rental extras"}
    kept = [row for row in (doc.charges or []) if (row.description or "") not in managed]
    if len(kept) != len(doc.charges or []):
        doc.set("charges", [])
        for row in kept:
            doc.append(
                "charges",
                {field: row.get(field) for field in ("charge_type", "description", "quantity", "rate", "amount", "source_doctype", "source_name")},
            )

    return_dt = get_datetime(doc.return_datetime)
    expected_dt = get_datetime(agreement.expected_return_datetime)
    is_early = return_dt < expected_dt
    effective_end = return_dt if is_early else expected_dt

    original_base = flt(agreement.base_amount)
    actual_base = original_base
    actual_units = flt(agreement.duration_units) or 1
    if is_early:
        try:
            pricing = calculate_price(
                {
                    "pickup_datetime": agreement.pickup_datetime,
                    "return_datetime": effective_end,
                    "company": agreement.company,
                    "branch": agreement.branch,
                    "currency": agreement.currency,
                    "vehicle": agreement.vehicle,
                    "vehicle_category": agreement.vehicle_category,
                    "rental_type": agreement.rental_type,
                    "customer": agreement.customer,
                }
            )
            actual_base = min(flt(pricing.get("base_amount")), original_base)
            actual_units = flt(pricing.get("billable_units")) or actual_units
        except Exception:
            # If anything about the recalculation fails, fall back to the
            # originally agreed base rather than blocking the return.
            actual_base = original_base

    doc.actual_rental_units = actual_units
    doc.actual_rental_amount = actual_base
    doc.early_return_credit = max(0.0, original_base - actual_base) if is_early else 0.0

    if not _base_billed_at_checkout(agreement):
        # Bill the base rental (for the actual usage) and any extras now.
        if actual_base > 0:
            rate = actual_base / (actual_units or 1)
            _append_charge(doc, "RENTAL", actual_units or 1, rate, "Rental usage")
        extras_amount = flt(agreement.extras_amount)
        if extras_amount > 0:
            _append_charge(doc, "OTHER", 1, extras_amount, "Rental extras")

    doc.additional_charge_total = sum(flt(row.amount) for row in doc.charges)


def _append_charge(doc, code: str, quantity: float, rate: float, description: str):
    charge_type = frappe.db.get_value("Rental Charge Type", {"code": code, "active": 1}, "name")
    if not charge_type:
        frappe.throw(_("Create an active Rental Charge Type with code {0}.").format(code))
    doc.append(
        "charges",
        {
            "charge_type": charge_type,
            "description": description,
            "quantity": quantity,
            "rate": rate,
            "amount": flt(quantity) * flt(rate),
        },
    )


def _calculate_reconciliation(doc, agreement):
    original = frappe.db.sql(
        """
        select coalesce(sum(grand_total), 0) as total, coalesce(sum(outstanding_amount), 0) as outstanding
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        where si.docstatus = 1 and dl.rental_agreement = %s and coalesce(dl.rental_extension, '') = ''
          and coalesce(dl.rental_return, '') = ''
        """,
        (agreement.name,),
        as_dict=True,
    )[0]
    extensions = frappe.db.sql(
        """
        select coalesce(sum(grand_total), 0) as total, coalesce(sum(outstanding_amount), 0) as outstanding
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        where si.docstatus = 1 and dl.rental_agreement = %s and coalesce(dl.rental_extension, '') != ''
        """,
        (agreement.name,),
        as_dict=True,
    )[0]
    doc.original_invoice_total = flt(original.total)
    doc.extension_invoice_total = flt(extensions.total)
    total_invoiced = flt(original.total) + flt(extensions.total)
    total_outstanding = flt(original.outstanding) + flt(extensions.outstanding)
    doc.payments_received = max(0, total_invoiced - total_outstanding)
    if doc.security_deposit:
        doc.deposit_available = flt(
            frappe.db.get_value("Security Deposit", doc.security_deposit, "balance")
        )
    else:
        doc.deposit_available = 0

    # Total the customer owes for this rental. When the base was billed in full
    # at checkout and the vehicle came back early, reduce what is still owed by
    # the value of the unused days (the early-return credit).
    amount_owed = total_outstanding + flt(doc.additional_charge_total)
    if _base_billed_at_checkout(agreement):
        amount_owed = max(0, amount_owed - flt(doc.early_return_credit))

    # Deduct the final amount from the security deposit automatically. The agent
    # can still override the amount before submitting; only auto-fill when the
    # field is empty.
    if not flt(doc.deposit_utilized) and doc.security_deposit and amount_owed > 0:
        doc.deposit_utilized = min(flt(doc.deposit_available), amount_owed)

    if flt(doc.deposit_utilized) > flt(doc.deposit_available):
        frappe.throw(_("Deposit utilized cannot exceed the available security deposit."))

    doc.outstanding_balance = max(0, amount_owed - flt(doc.deposit_utilized))
    doc.refund_amount = max(0, flt(doc.deposit_available) - flt(doc.deposit_utilized))