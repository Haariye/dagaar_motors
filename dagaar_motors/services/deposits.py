from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.services.accounting import create_customer_payment_entry
from dagaar_motors.services.settings import get_settings_dict
from dagaar_motors.utils.money import quantize

DEPOSIT_ROLES = (
    "Dagaar Motors Rental Agent",
    "Dagaar Motors Rental Manager",
    "Dagaar Motors Branch Manager",
    "Dagaar Motors Accountant",
    "Dagaar Motors Cashier",
)

DEPOSIT_APPROVAL_ROLES = (
    "Dagaar Motors Rental Manager",
    "Dagaar Motors Branch Manager",
)


def _require_deposit_role():
    require_any_role(*DEPOSIT_ROLES)


# ---------------------------------------------------------------------------
# Required deposit resolution (Deposit Rule -> Settings fallback)
# ---------------------------------------------------------------------------
def _match_deposit_rule(context: dict):
    rules = frappe.get_all(
        "Deposit Rule", filters={"enabled": 1}, fields=["*"], order_by="priority desc, modified desc"
    )
    duration_days = flt(context.get("duration_days") or 0)
    customer_group = None
    if context.get("customer"):
        customer_group = frappe.db.get_value("Customer", context["customer"], "customer_group")
    for rule in rules:
        if rule.get("company") and rule["company"] != context.get("company"):
            continue
        if rule.get("branch") and rule["branch"] != context.get("branch"):
            continue
        if rule.get("vehicle") and rule["vehicle"] != context.get("vehicle"):
            continue
        if rule.get("vehicle_category") and rule["vehicle_category"] != context.get("vehicle_category"):
            continue
        if rule.get("rental_type") and rule["rental_type"] != context.get("rental_type"):
            continue
        if rule.get("customer_group") and rule["customer_group"] != customer_group:
            continue
        if flt(rule.get("minimum_days")) and duration_days < flt(rule["minimum_days"]):
            continue
        if flt(rule.get("maximum_days")) and duration_days > flt(rule["maximum_days"]):
            continue
        return rule
    return None


def _deposit_rule_amount(rule, rental_total: float, duration_days: int) -> float:
    amount_type = rule.get("amount_type")
    if amount_type == "Percentage of Rental":
        return flt(rental_total) * flt(rule.get("percentage")) / 100.0
    if amount_type == "Per Day":
        return flt(rule.get("amount")) * max(1, cint(duration_days))
    return flt(rule.get("amount"))


def resolve_required_deposit(context: dict) -> dict:
    """Determine the deposit a rental requires. Matches an enabled Deposit Rule
    (by company/branch/vehicle/category/rental type/customer group/day range,
    highest priority first); otherwise falls back to Motors Settings."""
    settings = get_settings_dict()
    rental_total = flt(context.get("rental_total"))
    duration_days = max(1, cint(context.get("duration_days") or 1))

    rule = _match_deposit_rule(context)
    if rule:
        return {
            "amount": quantize(_deposit_rule_amount(rule, rental_total, duration_days), 2),
            "deposit_type": rule.get("deposit_type") or "Cash",
            "rule": rule.get("name"),
            "waiver_allowed": cint(rule.get("waiver_allowed")),
        }

    if not cint(settings.get("require_deposit", 1)):
        return {"amount": 0.0, "deposit_type": "Cash", "rule": None, "waiver_allowed": cint(settings.get("allow_deposit_waiver"))}

    amount = flt(settings.get("default_deposit_amount"))
    if not amount:
        amount = rental_total * flt(settings.get("default_deposit_percentage")) / 100.0
    return {
        "amount": quantize(amount, 2),
        "deposit_type": "Cash",
        "rule": None,
        "waiver_allowed": cint(settings.get("allow_deposit_waiver")),
    }


# ---------------------------------------------------------------------------
# Deposit status (derived entirely from Payment Entries)
# ---------------------------------------------------------------------------
def get_deposit_status(agreement_name: str) -> dict:
    """Deposit state for an agreement, derived from its Payment Entries.

    collected  : amount received on the deposit Payment Entry
    applied    : portion of the deposit allocated to invoices (advance used)
    unallocated: portion of the deposit still sitting as a customer advance
    refunded   : amount already paid back to the customer
    refundable : unallocated - refunded (what the Refund button will return)
    """
    agreement = frappe.get_doc("Rental Agreement", agreement_name)
    required = flt(agreement.deposit_required)
    collected = applied = unallocated = refunded = 0.0

    pe = agreement.get("deposit_payment_entry")
    if pe and frappe.db.exists("Payment Entry", pe):
        info = frappe.db.get_value(
            "Payment Entry", pe, ["docstatus", "paid_amount", "unallocated_amount"], as_dict=True
        )
        if info and info.docstatus == 1:
            collected = flt(info.paid_amount)
            unallocated = flt(info.unallocated_amount)
            applied = collected - unallocated

    rpe = agreement.get("deposit_refund_payment_entry")
    if rpe and frappe.db.exists("Payment Entry", rpe):
        rinfo = frappe.db.get_value("Payment Entry", rpe, ["docstatus", "paid_amount"], as_dict=True)
        if rinfo and rinfo.docstatus == 1:
            refunded = flt(rinfo.paid_amount)

    return {
        "required": quantize(required, 2),
        "collected": quantize(collected, 2),
        "applied": quantize(applied, 2),
        "unallocated": quantize(unallocated, 2),
        "refunded": quantize(refunded, 2),
        "refundable": quantize(max(0.0, unallocated - refunded), 2),
        "outstanding": quantize(max(0.0, required - collected), 2),
        "waived": bool(agreement.get("deposit_waived")),
        "deposit_payment_entry": pe,
        "deposit_refund_payment_entry": rpe,
    }


# ---------------------------------------------------------------------------
# Collect deposit -> Payment Entry (Receive) advance on the customer
# ---------------------------------------------------------------------------
def collect_agreement_deposit(
    agreement_name: str,
    amount: float | None = None,
    payment_method: str | None = None,
    reference_number: str | None = None,
):
    _require_deposit_role()
    agreement = frappe.get_doc("Rental Agreement", agreement_name)
    required = flt(agreement.deposit_required)
    if required <= 0:
        frappe.throw(_("No security deposit is required for this rental agreement."))

    status = get_deposit_status(agreement_name)
    outstanding = flt(status["outstanding"])
    if outstanding <= 0:
        if agreement.get("deposit_payment_entry"):
            return frappe.get_doc("Payment Entry", agreement.deposit_payment_entry)
        return None

    collect = quantize(flt(amount) if amount else outstanding, 2)
    if collect <= 0 or collect > outstanding:
        collect = outstanding

    pe = create_customer_payment_entry(
        company=agreement.company,
        customer=agreement.customer,
        amount=collect,
        currency=agreement.currency,
        branch=agreement.branch,
        vehicle=agreement.vehicle,
        payment_type="Receive",
        mode_of_payment=payment_method,
        reference_no=reference_number or agreement.name,
        source_references={
            "dagaar_rental_agreement": agreement.name,
            "dagaar_motor_vehicle": agreement.vehicle,
        },
        remarks=f"Security deposit for {agreement.name}",
        submit=True,
    )
    frappe.db.set_value("Rental Agreement", agreement.name, "deposit_payment_entry", pe.name)
    return pe


# ---------------------------------------------------------------------------
# Refund deposit -> Payment Entry (Pay) + reconcile against the advance
# ---------------------------------------------------------------------------
def refund_agreement_deposit(
    agreement_name: str,
    amount: float | None = None,
    payment_method: str | None = None,
    reference_number: str | None = None,
):
    _require_deposit_role()
    agreement = frappe.get_doc("Rental Agreement", agreement_name)
    status = get_deposit_status(agreement_name)
    refundable = flt(status["refundable"])
    if refundable <= 0:
        frappe.throw(_("There is no refundable deposit balance on this agreement."))

    refund = quantize(flt(amount) if amount else refundable, 2)
    if refund <= 0 or refund > refundable:
        refund = refundable

    pe = create_customer_payment_entry(
        company=agreement.company,
        customer=agreement.customer,
        amount=refund,
        currency=agreement.currency,
        branch=agreement.branch,
        vehicle=agreement.vehicle,
        payment_type="Pay",
        mode_of_payment=payment_method,
        reference_no=reference_number or agreement.name,
        source_references={
            "dagaar_rental_agreement": agreement.name,
            "dagaar_motor_vehicle": agreement.vehicle,
        },
        remarks=f"Security deposit refund for {agreement.name}",
        submit=True,
    )
    frappe.db.set_value("Rental Agreement", agreement.name, "deposit_refund_payment_entry", pe.name)
    _reconcile_refund_against_deposit(agreement, pe)
    return pe


def _reconcile_refund_against_deposit(agreement, refund_pe) -> None:
    """Best-effort: net the refund (Pay) against the deposit advance (Receive)
    via ERPNext Payment Reconciliation so both are marked reconciled. If it
    can't run on this setup, the ledger still nets correctly and the entries can
    be reconciled manually."""
    deposit_pe = agreement.get("deposit_payment_entry")
    if not deposit_pe:
        return
    try:
        account = frappe.db.get_value("Payment Entry", deposit_pe, "paid_from")
        pr = frappe.new_doc("Payment Reconciliation")
        pr.company = agreement.company
        pr.party_type = "Customer"
        pr.party = agreement.customer
        pr.receivable_payable_account = account
        pr.get_unreconciled_entries()
        invoices = [row.as_dict() for row in (pr.get("invoices") or []) if row.get("invoice_number") == refund_pe]
        payments = [row.as_dict() for row in (pr.get("payments") or []) if row.get("reference_name") == deposit_pe]
        if invoices and payments:
            pr.set("allocation", [])
            pr.allocate_entries({"invoices": invoices, "payments": payments})
            pr.reconcile()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Dagaar Motors: deposit refund reconciliation")


# ---------------------------------------------------------------------------
# Waiver (role-gated)
# ---------------------------------------------------------------------------
def deposit_waiver_roles() -> list:
    settings = frappe.get_single("Dagaar Motors Settings")
    roles = [row.role for row in (settings.get("deposit_waiver_roles") or []) if row.role]
    return roles or list(DEPOSIT_APPROVAL_ROLES)


def can_user_waive_deposit(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    user_roles = set(frappe.get_roles(user))
    if "System Manager" in user_roles:
        return True
    return bool(set(deposit_waiver_roles()) & user_roles)


def waive_agreement_deposit(agreement_name: str, reason: str | None = None):
    settings = get_settings_dict()
    if not cint(settings.get("allow_deposit_waiver")):
        frappe.throw(_("Deposit waivers are disabled. Enable 'Allow Deposit Waiver' in Motors Settings."))
    if not can_user_waive_deposit():
        frappe.throw(_("You are not permitted to waive security deposits."), frappe.PermissionError)
    agreement = frappe.get_doc("Rental Agreement", agreement_name)
    frappe.db.set_value(
        "Rental Agreement",
        agreement.name,
        {
            "deposit_waived": 1,
            "deposit_waiver_approved_by": frappe.session.user,
            "deposit_waiver_reason": reason,
        },
        update_modified=True,
    )
    return frappe.get_doc("Rental Agreement", agreement_name)


# ---------------------------------------------------------------------------
# Account statement (rent accrual vs. payments)
# ---------------------------------------------------------------------------
def build_account_statement(agreement_name: str) -> dict:
    agreement = frappe.get_doc("Rental Agreement", agreement_name)
    currency = agreement.currency
    pickup = get_datetime(agreement.pickup_datetime) if agreement.pickup_datetime else None

    actual_return = frappe.db.get_value(
        "Rental Return", {"rental_agreement": agreement.name, "docstatus": 1}, "return_datetime"
    )
    accrual_end = get_datetime(actual_return) if actual_return else now_datetime()

    lines: list[dict] = []
    total_debit = 0.0
    total_credit = 0.0

    daily_rate = flt(agreement.base_rate) or (flt(agreement.base_amount) / max(flt(agreement.duration_units), 1))
    days = 0
    if pickup and accrual_end and accrual_end > pickup:
        hours = (accrual_end - pickup).total_seconds() / 3600.0
        days = int(math.ceil(hours / 24.0))
    for i in range(days):
        total_debit += daily_rate
        lines.append({
            "date": str(add_days(pickup, i))[:10],
            "description": _("Rental day {0}").format(i + 1),
            "debit": quantize(daily_rate, 2),
            "credit": 0,
        })

    for row in agreement.get("charges") or []:
        amt = flt(row.amount)
        if amt:
            total_debit += amt
            lines.append({
                "date": nowdate(),
                "description": row.description or row.charge_type or _("Charge"),
                "debit": quantize(amt, 2),
                "credit": 0,
            })

    tax = flt(agreement.tax_amount)
    if tax:
        total_debit += tax
        lines.append({"date": nowdate(), "description": _("Tax"), "debit": quantize(tax, 2), "credit": 0})

    discount = flt(agreement.discount_amount)
    if discount:
        total_credit += discount
        lines.append({"date": nowdate(), "description": _("Discount"), "debit": 0, "credit": quantize(discount, 2)})

    status = get_deposit_status(agreement_name)
    if status["collected"]:
        total_credit += flt(status["collected"])
        lines.append({
            "date": nowdate(),
            "description": _("Security deposit received"),
            "debit": 0,
            "credit": quantize(flt(status["collected"]), 2),
        })
    if status["refunded"]:
        total_debit += flt(status["refunded"])
        lines.append({
            "date": nowdate(),
            "description": _("Security deposit refunded"),
            "debit": quantize(flt(status["refunded"]), 2),
            "credit": 0,
        })

    # Other (non-deposit) customer payments linked to this agreement.
    exclude = {status.get("deposit_payment_entry"), status.get("deposit_refund_payment_entry")}
    if frappe.db.exists("DocType", "Dagaar Motors ERP Link"):
        pe_names = frappe.get_all(
            "Dagaar Motors ERP Link",
            filters={"reference_doctype": "Payment Entry", "rental_agreement": agreement.name},
            pluck="reference_name",
        )
        for pe in set(pe_names) - exclude:
            info = frappe.db.get_value(
                "Payment Entry", pe, ["payment_type", "paid_amount", "docstatus", "posting_date"], as_dict=True
            )
            if not info or info.docstatus != 1:
                continue
            if info.payment_type == "Receive":
                total_credit += flt(info.paid_amount)
                lines.append({"date": str(info.posting_date), "description": _("Payment {0}").format(pe), "debit": 0, "credit": quantize(flt(info.paid_amount), 2)})
            else:
                total_debit += flt(info.paid_amount)
                lines.append({"date": str(info.posting_date), "description": _("Payment out {0}").format(pe), "debit": quantize(flt(info.paid_amount), 2), "credit": 0})

    return {
        "agreement": agreement.name,
        "customer": agreement.customer,
        "currency": currency,
        "accrued_days": days,
        "daily_rate": quantize(daily_rate, 2),
        "agreed_total": quantize(flt(agreement.grand_total), 2),
        "deposit_required": flt(status["required"]),
        "deposit_received": flt(status["collected"]),
        "deposit_refundable": flt(status["refundable"]),
        "total_debit": quantize(total_debit, 2),
        "total_credit": quantize(total_credit, 2),
        "balance": quantize(total_debit - total_credit, 2),
        "lines": lines,
    }
