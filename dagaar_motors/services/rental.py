from __future__ import annotations

import json
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.accounting import create_agreement_invoice
from dagaar_motors.services.audit import append_audit_event
from dagaar_motors.services.availability import assert_available, lock_vehicle
from dagaar_motors.services.deposits import ensure_security_deposit
from dagaar_motors.services.documents import validate_required_documents
from dagaar_motors.services.fleet import add_mileage_log, transition_vehicle
from dagaar_motors.services.form_defaults import (
    apply_branch_defaults,
    apply_customer_defaults,
    apply_vehicle_defaults,
    driver_row_from_customer,
)
from dagaar_motors.services.idempotency import ensure_idempotency_key
from dagaar_motors.services.pricing import calculate_price
from dagaar_motors.services.settings import get_settings_dict, resolve_company, resolve_currency
from dagaar_motors.services.state_machine import validate_transition
from dagaar_motors.utils.constants import (
    RENTAL_AGREEMENT_TRANSITIONS,
    RESERVATION_BLOCKING_STATUSES,
    RESERVATION_TRANSITIONS,
)


def _sync_charge_amounts(doc) -> float:
    """Compute each Charges row amount (quantity x rate) and return the total."""
    total = 0.0
    for row in doc.get("charges") or []:
        quantity = flt(row.get("quantity")) or (1 if row.get("charge_type") else 0)
        row.quantity = quantity
        row.amount = flt(quantity) * flt(row.get("rate"))
        total += flt(row.amount)
    return total


def apply_pricing(doc, *, start_field: str, end_field: str) -> dict:
    charges_total = _sync_charge_amounts(doc)
    # The discount_amount field doubles as a manual (fixed) discount input. When
    # a percentage is entered the percentage drives the discount; otherwise the
    # amount the user typed is honoured directly.
    manual_discount = 0.0
    if not flt(doc.get("discount_percent")):
        manual_discount = flt(doc.get("discount_amount"))
    result = calculate_price(
        {
            "pickup_datetime": doc.get(start_field),
            "return_datetime": doc.get(end_field),
            "company": doc.get("company"),
            "branch": doc.get("branch"),
            "currency": doc.get("currency"),
            "vehicle": doc.get("vehicle") or doc.get("requested_vehicle"),
            "vehicle_category": doc.get("vehicle_category"),
            "rental_type": doc.get("rental_type"),
            "customer": doc.get("customer"),
            "booking_channel": doc.get("reservation_source"),
            "promo_code": doc.get("promo_code"),
            "pickup_location": doc.get("pickup_location"),
            "return_location": doc.get("return_location"),
            "one_way": bool(doc.get("one_way"))
            or bool(doc.get("pickup_location") and doc.get("return_location") and doc.pickup_location != doc.return_location),
            "discount_percent": flt(doc.get("discount_percent")),
            "fixed_discount": manual_discount or flt(doc.get("fixed_discount")),
            "additional_charges": charges_total,
            "approved_by": doc.get("approved_by") or doc.get("price_override_approved_by"),
            "user": frappe.session.user,
            "extras": _pricing_extras(doc.get("extras") or []),
        }
    )
    field_map = {
        "base_rate": "base_rate",
        "base_amount": "base_amount",
        "extras_amount": "extras_amount",
        "user_discount": "discount_amount",
        "net_amount": "net_amount",
        "tax_template": "tax_template",
        "tax_amount": "tax_amount",
        "grand_total": "grand_total",
        "deposit_required": "deposit_required",
        "pricing_rule": "pricing_rule",
        "billable_units": "duration_units",
        "duration_label": "duration_label",
    }
    for source, target in field_map.items():
        if doc.meta.has_field(target):
            doc.set(target, result.get(source))
    if doc.meta.has_field("rate"):
        doc.rate = result.get("base_rate")
    _apply_extra_amounts(doc, result)
    if doc.meta.has_field("pricing_breakdown"):
        doc.set("pricing_breakdown", [])
        for index, line in enumerate(result.get("lines") or [], start=1):
            doc.append(
                "pricing_breakdown",
                {
                    "sequence": index,
                    "component": line.get("component"),
                    "description": line.get("description"),
                    "quantity": line.get("quantity"),
                    "rate": line.get("rate"),
                    "amount": line.get("amount"),
                    "rule": line.get("rule"),
                },
            )
    if doc.meta.has_field("pricing_snapshot"):
        doc.pricing_snapshot = json.dumps(result, default=str, sort_keys=True)
    return result


def validate_quotation(doc):
    apply_vehicle_defaults(doc)
    _set_common_defaults(doc)
    apply_customer_defaults(doc)
    _validate_period(doc.pickup_datetime, doc.return_datetime)
    _validate_vehicle_scope(doc)
    apply_pricing(doc, start_field="pickup_datetime", end_field="return_datetime")
    if not doc.status:
        doc.status = "Draft"


def convert_quotation_to_reservation(quotation_name: str):
    require_any_role(
        "Dagaar Motors Reservation Agent",
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
    )
    quotation = frappe.get_doc("Rental Quotation", quotation_name)
    if quotation.converted_reservation:
        return frappe.get_doc("Rental Reservation", quotation.converted_reservation)
    if quotation.status in {"Expired", "Cancelled"}:
        frappe.throw(_("Quotation {0} cannot be converted because it is {1}.").format(quotation.name, quotation.status))
    reservation = frappe.get_doc(
        {
            "doctype": "Rental Reservation",
            "company": quotation.company,
            "branch": quotation.branch,
            "customer": quotation.customer,
            "contact": quotation.contact,
            "quotation": quotation.name,
            "status": "Pending",
            "rental_agent": quotation.sales_agent or frappe.session.user,
            "pickup_datetime": quotation.pickup_datetime,
            "return_datetime": quotation.return_datetime,
            "pickup_location": quotation.pickup_location,
            "return_location": quotation.return_location,
            "rental_type": quotation.rental_type,
            "vehicle_category": quotation.vehicle_category,
            "requested_vehicle": quotation.vehicle,
            "vehicle": quotation.vehicle,
            "currency": quotation.currency,
            "discount_percent": quotation.discount_percent,
            "extras": [_copy_extra(row) for row in quotation.extras],
            "notes": quotation.notes,
        }
    )
    reservation.insert(ignore_permissions=False)
    quotation.db_set({"converted_reservation": reservation.name, "status": "Converted"})
    return reservation


def validate_reservation(doc):
    if doc.requested_vehicle and not doc.vehicle:
        doc.vehicle = doc.requested_vehicle
    apply_vehicle_defaults(doc)
    _set_common_defaults(doc)
    apply_customer_defaults(doc)
    doc.status = doc.status or "Draft"
    _validate_period(doc.pickup_datetime, doc.return_datetime)
    _validate_status_change(doc, RESERVATION_TRANSITIONS)
    _validate_vehicle_scope(doc)
    apply_pricing(doc, start_field="pickup_datetime", end_field="return_datetime")
    ensure_idempotency_key(doc, "reservation")

    if doc.vehicle and doc.status in RESERVATION_BLOCKING_STATUSES:
        assert_available(
            doc.vehicle,
            doc.pickup_datetime,
            doc.return_datetime,
            exclude_doctype="Rental Reservation",
            exclude_name=doc.name,
            lock=not doc.is_new(),
        )
    if doc.status in {"Vehicle Assigned", "Checked Out"} and not doc.vehicle:
        frappe.throw(_("Assign a vehicle before setting the reservation to {0}.").format(doc.status))
    if doc.status == "Checked Out":
        validate_required_documents(doc)
    _validate_deposit_waiver(doc)


def on_reservation_update(doc):
    if doc.vehicle and doc.status in {"Confirmed", "Vehicle Assigned"}:
        _set_vehicle_reservation_state(doc)
    if doc.status in {"Cancelled", "No Show", "Completed"} and doc.vehicle:
        _release_vehicle_reservation_state(doc)


def assign_vehicle(reservation_name: str, vehicle: str):
    require_any_role(
        "Dagaar Motors Reservation Agent",
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Rental Reservation", reservation_name)
    lock_vehicle(vehicle)
    doc = frappe.get_doc("Rental Reservation", reservation_name)
    if doc.status in {"Cancelled", "No Show", "Completed", "Checked Out"}:
        frappe.throw(_("Reservation {0} is already {1}.").format(doc.name, doc.status))
    _validate_vehicle_category(vehicle, doc.vehicle_category)
    assert_available(
        vehicle,
        doc.pickup_datetime,
        doc.return_datetime,
        exclude_doctype="Rental Reservation",
        exclude_name=doc.name,
        lock=False,
    )
    old_vehicle = doc.vehicle
    doc.vehicle = vehicle
    doc.status = "Vehicle Assigned"
    doc.save()
    if old_vehicle and old_vehicle != vehicle:
        _release_vehicle_reservation_state(doc, vehicle=old_vehicle)
    _set_vehicle_reservation_state(doc)
    append_audit_event(doc, "Vehicle Assigned", {"vehicle": vehicle})
    return doc


def confirm_reservation(reservation_name: str):
    require_any_role(
        "Dagaar Motors Reservation Agent",
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
    )
    lock_document("Rental Reservation", reservation_name)
    doc = frappe.get_doc("Rental Reservation", reservation_name)
    if doc.status in {"Cancelled", "No Show", "Completed", "Checked Out"}:
        frappe.throw(_("Reservation {0} cannot be confirmed from status {1}.").format(doc.name, doc.status))
    if doc.vehicle:
        assert_available(
            doc.vehicle,
            doc.pickup_datetime,
            doc.return_datetime,
            exclude_doctype="Rental Reservation",
            exclude_name=doc.name,
        )
        doc.status = "Vehicle Assigned"
    else:
        doc.status = "Confirmed"
    doc.save()
    return doc


def create_agreement_from_reservation(reservation_name: str):
    require_any_role(
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Rental Reservation", reservation_name)
    reservation = frappe.get_doc("Rental Reservation", reservation_name)
    if reservation.rental_agreement and frappe.db.exists("Rental Agreement", reservation.rental_agreement):
        return frappe.get_doc("Rental Agreement", reservation.rental_agreement)
    if reservation.status not in {"Confirmed", "Vehicle Assigned"}:
        frappe.throw(_("Reservation {0} must be confirmed before creating an agreement.").format(reservation.name))
    if not reservation.vehicle:
        frappe.throw(_("Assign a vehicle to Reservation {0} first.").format(reservation.name))
    assert_available(
        reservation.vehicle,
        reservation.pickup_datetime,
        reservation.return_datetime,
        exclude_doctype="Rental Reservation",
        exclude_name=reservation.name,
    )
    drivers = [driver_row_from_customer(reservation.customer)]
    agreement = frappe.get_doc(
        {
            "doctype": "Rental Agreement",
            "company": reservation.company,
            "branch": reservation.branch,
            "customer": reservation.customer,
            "contact": reservation.contact,
            "vehicle": reservation.vehicle,
            "status": "Ready for Pickup",
            "reservation": reservation.name,
            "rental_type": reservation.rental_type,
            "vehicle_category": reservation.vehicle_category,
            "rental_agent": reservation.rental_agent or frappe.session.user,
            "pickup_datetime": reservation.pickup_datetime,
            "expected_return_datetime": reservation.return_datetime,
            "original_end_datetime": reservation.return_datetime,
            "pickup_location": reservation.pickup_location,
            "return_location": reservation.return_location,
            "currency": reservation.currency,
            "discount_percent": reservation.discount_percent,
            "drivers": drivers,
            "extras": [_copy_extra(row) for row in reservation.extras],
            "documents_complete": reservation.documents_complete,
            "remarks": reservation.notes,
            "idempotency_key": reservation.idempotency_key,
        }
    )
    agreement.insert()
    reservation.db_set("rental_agreement", agreement.name)
    return agreement


def validate_agreement(doc):
    apply_vehicle_defaults(doc)
    _set_common_defaults(doc)
    apply_customer_defaults(doc, suggest_driver=True)
    doc.status = doc.status or "Draft"
    _validate_period(doc.pickup_datetime, doc.expected_return_datetime)
    _validate_status_change(doc, RENTAL_AGREEMENT_TRANSITIONS)
    _validate_vehicle_scope(doc)
    if doc.is_new() and not doc.original_end_datetime:
        doc.original_end_datetime = doc.expected_return_datetime
    if not doc.is_new():
        old = frappe.db.get_value(
            "Rental Agreement",
            doc.name,
            ["expected_return_datetime", "original_end_datetime", "status", "docstatus"],
            as_dict=True,
        )
        if old and old.docstatus == 1 and get_datetime(old.expected_return_datetime) != get_datetime(doc.expected_return_datetime):
            frappe.throw(_("Use Rental Extension to change the expected return date of a submitted agreement."))
        if old and old.original_end_datetime and get_datetime(old.original_end_datetime) != get_datetime(doc.original_end_datetime):
            frappe.throw(_("The original rental end date cannot be changed after the agreement is created."))
    if doc.docstatus == 0:
        apply_pricing(doc, start_field="pickup_datetime", end_field="expected_return_datetime")
    ensure_idempotency_key(doc, "agreement")
    _validate_agreement_drivers(
        doc,
        strict=doc.docstatus == 1 or doc.status in {"Active", "Extended", "Overdue", "Return Processing", "Completed", "Closed"},
    )
    _validate_deposit_waiver(doc)
    if doc.status in {"Reserved", "Ready for Pickup", "Active", "Extended", "Overdue", "Return Processing"}:
        assert_available(
            doc.vehicle,
            doc.pickup_datetime,
            doc.expected_return_datetime,
            exclude_doctype="Rental Agreement",
            exclude_name=doc.name,
            exclude_documents={"Rental Reservation": doc.reservation} if doc.reservation else None,
            lock=not doc.is_new(),
        )


def validate_checkout(doc):
    settings = get_settings_dict()
    vehicle = frappe.get_doc("Motor Vehicle", doc.vehicle)
    if vehicle.status not in {"Available", "Reserved"}:
        frappe.throw(
            _("Vehicle {0} cannot be checked out because its status is {1}.").format(
                vehicle.name, vehicle.status
            )
        )
    _validate_agreement_drivers(doc, strict=True)
    validate_required_documents(doc)
    if cint(settings.get("require_checkout_inspection")) and not doc.checkout_inspection:
        frappe.throw(_("A completed checkout inspection is required before the vehicle can leave."))
    if doc.checkout_inspection:
        inspection = frappe.get_doc("Vehicle Inspection", doc.checkout_inspection)
        if inspection.vehicle != doc.vehicle or inspection.status not in {"Passed", "Requires Action"}:
            frappe.throw(_("Checkout Inspection {0} is not a valid completed inspection for this vehicle.").format(inspection.name))
    if flt(doc.checkout_odometer) < flt(vehicle.current_odometer):
        frappe.throw(
            _("Checkout odometer {0} cannot be lower than vehicle odometer {1}.").format(
                doc.checkout_odometer, vehicle.current_odometer
            )
        )
    if not doc.checkout_fuel_level:
        frappe.throw(_("Enter the checkout fuel level."))
    required = flt(doc.deposit_required)
    if required:
        deposit = frappe.get_doc("Security Deposit", doc.security_deposit) if doc.security_deposit else None
        if not deposit or flt(deposit.amount_received) < required:
            frappe.throw(_("Collect the required security deposit of {0} before checkout.").format(required))


def checkout_agreement(agreement_name: str):
    require_any_role(
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    lock_document("Rental Agreement", agreement_name)
    doc = frappe.get_doc("Rental Agreement", agreement_name)
    if doc.docstatus == 1 and doc.status in {"Active", "Extended", "Overdue"}:
        return doc
    if doc.docstatus != 0:
        frappe.throw(_("Rental Agreement {0} cannot be checked out from its current document state.").format(doc.name))
    assert_available(
        doc.vehicle,
        doc.pickup_datetime,
        doc.expected_return_datetime,
        exclude_doctype="Rental Agreement",
        exclude_name=doc.name,
        exclude_documents={"Rental Reservation": doc.reservation} if doc.reservation else None,
    )
    if flt(doc.deposit_required) and not doc.security_deposit:
        deposit = ensure_security_deposit(doc)
        if deposit:
            doc.security_deposit = deposit
    validate_checkout(doc)
    doc.status = "Active"
    doc.checkout_completed_on = now_datetime()
    doc.submit()
    return doc


def activate_agreement(doc):
    lock_vehicle(doc.vehicle)
    assert_available(
        doc.vehicle,
        doc.pickup_datetime,
        doc.expected_return_datetime,
        exclude_doctype="Rental Agreement",
        exclude_name=doc.name,
        exclude_documents={"Rental Reservation": doc.reservation} if doc.reservation else None,
        lock=False,
    )
    add_mileage_log(
        doc.vehicle,
        "Checkout",
        doc.checkout_odometer,
        source_doctype=doc.doctype,
        source_name=doc.name,
        reason=f"Rental checkout {doc.name}",
    )
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {
            "status": "Rented",
            "current_customer": doc.customer,
            "current_rental_agreement": doc.name,
            "last_checkout_odometer": doc.checkout_odometer,
            "fuel_level": doc.checkout_fuel_level,
            "available_from": doc.expected_return_datetime,
            "status_reason": f"Active Rental Agreement {doc.name}",
        },
        update_modified=True,
    )
    if doc.reservation:
        frappe.db.set_value("Rental Reservation", doc.reservation, "status", "Checked Out", update_modified=True)
    deposit = ensure_security_deposit(doc)
    if deposit:
        frappe.db.set_value("Rental Agreement", doc.name, "security_deposit", deposit, update_modified=False)
    settings = get_settings_dict()
    if settings.get("invoice_timing") in {"Before Checkout", "On Checkout"} and not doc.current_invoice:
        invoice = create_agreement_invoice(doc)
        frappe.db.set_value(
            "Rental Agreement",
            doc.name,
            {"current_invoice": invoice.name, "invoiced_through_datetime": doc.original_end_datetime},
            update_modified=False,
        )
    append_audit_event(doc, "Checked Out", {"vehicle": doc.vehicle, "odometer": doc.checkout_odometer})


def cancel_agreement(doc):
    if doc.current_invoice and frappe.db.exists("Sales Invoice", doc.current_invoice):
        invoice = frappe.get_doc("Sales Invoice", doc.current_invoice)
        if invoice.docstatus == 1:
            frappe.throw(_("Cancel Sales Invoice {0} before cancelling the rental agreement.").format(invoice.name))
    if doc.status in {"Completed", "Closed"}:
        frappe.throw(_("A completed rental agreement cannot be cancelled."))
    if doc.vehicle:
        vehicle = frappe.get_doc("Motor Vehicle", doc.vehicle)
        if vehicle.current_rental_agreement == doc.name:
            frappe.db.set_value(
                "Motor Vehicle",
                doc.vehicle,
                {
                    "status": "Inspection" if doc.checkout_completed_on else "Available",
                    "current_customer": None,
                    "current_rental_agreement": None,
                    "available_from": None,
                    "status_reason": f"Rental Agreement {doc.name} cancelled",
                },
                update_modified=True,
            )
    if doc.reservation:
        frappe.db.set_value("Rental Reservation", doc.reservation, "status", "Cancelled", update_modified=True)


def _set_common_defaults(doc):
    settings = get_settings_dict()
    doc.branch = doc.get("branch") or settings.get("default_branch")
    if doc.branch:
        apply_branch_defaults(doc)
    doc.company = doc.get("company") or resolve_company()
    if doc.meta.has_field("currency"):
        doc.currency = doc.get("currency") or resolve_currency(doc.company)
    if not doc.branch:
        frappe.throw(_("Select a Branch."))
    branch_company = frappe.get_cached_value("Motor Branch", doc.branch, "company")
    if branch_company != doc.company:
        frappe.throw(_("Branch {0} belongs to {1}, not {2}.").format(doc.branch, branch_company, doc.company))


def _validate_period(start, end):
    if not start or not end or get_datetime(end) <= get_datetime(start):
        frappe.throw(_("Return date and time must be later than pickup date and time."))


def _validate_vehicle_scope(doc):
    vehicle_name = doc.get("vehicle") or doc.get("requested_vehicle")
    if not vehicle_name:
        return
    vehicle = frappe.get_cached_doc("Motor Vehicle", vehicle_name)
    if vehicle.company != doc.company:
        frappe.throw(_("Vehicle {0} belongs to company {1}.").format(vehicle.name, vehicle.company))
    if vehicle.branch != doc.branch:
        frappe.throw(_("Vehicle {0} is assigned to branch {1}.").format(vehicle.name, vehicle.branch))
    _validate_vehicle_category(vehicle.name, doc.get("vehicle_category"))
    if doc.meta.has_field("vehicle_category") and not doc.vehicle_category:
        doc.vehicle_category = vehicle.category
    _validate_rental_type(vehicle, doc.get("rental_type"))


def _validate_vehicle_category(vehicle: str, category: str | None):
    if not category:
        return
    actual = frappe.get_cached_value("Motor Vehicle", vehicle, "category")
    if actual != category:
        frappe.throw(_("Vehicle {0} is category {1}, not {2}.").format(vehicle, actual, category))


def _validate_rental_type(vehicle, rental_type: str | None):
    if not rental_type or not vehicle.get("allowed_rental_types"):
        return
    allowed = {row.rental_type for row in vehicle.allowed_rental_types if row.active}
    if allowed and rental_type not in allowed:
        frappe.throw(_("Rental Type {0} is not allowed for Vehicle {1}.").format(rental_type, vehicle.name))


def _validate_status_change(doc, transitions):
    if doc.is_new():
        return
    old_status = frappe.db.get_value(doc.doctype, doc.name, "status")
    if old_status and old_status != doc.status:
        validate_transition(old_status, doc.status, transitions, doc.doctype)


def _validate_agreement_drivers(doc, *, strict: bool = False):
    rows = list(doc.get("drivers") or [])
    if not rows:
        if strict:
            frappe.throw(_("Add at least one driver before checkout."))
        return

    # Make the common one-driver case effortless.
    primary_rows = [row for row in rows if cint(row.primary_driver)]
    if not primary_rows:
        rows[0].primary_driver = 1
        primary_rows = [rows[0]]
    if len(primary_rows) > 1:
        frappe.throw(_("Mark only one driver as the primary driver."))

    seen = set()
    minimum_age = cint(frappe.get_cached_value("Vehicle Category", doc.vehicle_category, "minimum_driver_age")) if doc.vehicle_category else 0
    for row in rows:
        if not row.full_name:
            frappe.throw(_("Enter the driver's name."))
        key = (row.license_number or f"{row.full_name}|{row.phone or ''}").strip().lower()
        if key in seen:
            frappe.throw(_("Driver {0} appears more than once.").format(row.full_name))
        seen.add(key)

        if strict:
            if not row.license_number:
                frappe.throw(_("Enter the driving license number for {0}.").format(row.full_name))
            if not row.license_expiry_date:
                frappe.throw(_("Enter the driving license expiry date for {0}.").format(row.full_name))
            if getdate(row.license_expiry_date) < getdate(doc.expected_return_datetime):
                frappe.throw(_("{0}'s driving license expires before the rental return date.").format(row.full_name))
            if minimum_age:
                if not row.date_of_birth:
                    frappe.throw(_("Enter the date of birth for {0} to verify the minimum driver age.").format(row.full_name))
                age = _age_on(row.date_of_birth, getdate(doc.expected_return_datetime))
                if age < minimum_age:
                    frappe.throw(_("{0} must be at least {1} years old for this vehicle category.").format(row.full_name, minimum_age))
            row.approved = 1
        else:
            row.approved = 0


def _validate_deposit_waiver(doc):
    if not doc.meta.has_field("deposit_waived") or not doc.get("deposit_waived"):
        return
    settings = get_settings_dict()
    if not cint(settings.get("allow_deposit_waiver")):
        frappe.throw(_("Security deposit waivers are disabled in Dagaar Motors Settings."))
    if cint(settings.get("deposit_waiver_requires_approval")) and not doc.get("deposit_waiver_approved_by"):
        frappe.throw(_("Select the manager who approved the security deposit waiver."))


def _set_vehicle_reservation_state(doc):
    vehicle = frappe.get_doc("Motor Vehicle", doc.vehicle)
    if vehicle.status == "Available":
        transition_vehicle(vehicle, "Reserved", reason=f"Reservation {doc.name}")
    frappe.db.set_value(
        "Motor Vehicle",
        doc.vehicle,
        {"available_from": doc.return_datetime, "status_reason": f"Reservation {doc.name}"},
        update_modified=False,
    )


def _release_vehicle_reservation_state(doc, vehicle: str | None = None):
    vehicle_name = vehicle or doc.vehicle
    if not vehicle_name or not frappe.db.exists("Motor Vehicle", vehicle_name):
        return
    row = frappe.db.get_value(
        "Motor Vehicle", vehicle_name, ["status", "current_rental_agreement"], as_dict=True
    )
    if row and row.status == "Reserved" and not row.current_rental_agreement:
        frappe.db.set_value(
            "Motor Vehicle",
            vehicle_name,
            {"status": "Available", "available_from": None, "status_reason": None},
            update_modified=True,
        )


def _pricing_extras(rows) -> list[dict]:
    return [
        {
            "rental_extra": row.get("rental_extra"),
            "quantity": flt(row.get("quantity") or 1),
            "rate": flt(row.get("rate")),
        }
        for row in rows
        if row.get("rental_extra")
    ]


def _copy_extra(row) -> dict:
    return {
        "rental_extra": row.get("rental_extra"),
        "description": row.get("description"),
        "price_basis": row.get("price_basis"),
        "quantity": row.get("quantity"),
        "rate": row.get("rate"),
        "amount": row.get("amount"),
    }


def _apply_extra_amounts(doc, result):
    line_by_extra = {}
    for line in result.get("lines") or []:
        if line.get("component") == "Extra" and line.get("rule"):
            line_by_extra[line["rule"]] = line
    for row in doc.get("extras") or []:
        extra = frappe.get_cached_doc("Rental Extra", row.rental_extra)
        line = line_by_extra.get(row.rental_extra)
        row.description = extra.extra_name
        row.price_basis = extra.price_basis
        if line:
            row.quantity = line.get("quantity")
            row.rate = line.get("rate")
            row.amount = line.get("amount")


def _age_on(date_of_birth, on_date: date) -> int:
    dob = getdate(date_of_birth)
    return on_date.year - dob.year - ((on_date.month, on_date.day) < (dob.month, dob.day))