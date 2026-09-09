from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.accounting import set_source_references
from dagaar_motors.services.erp_links import persist_source_references
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.idempotency import make_key
from dagaar_motors.services.settings import get_settings_dict, resolve_account, resolve_company, resolve_currency
from dagaar_motors.utils.money import quantize
from dagaar_motors.utils.validation import validate_account_company


ALLOWED_TRANSACTION_TYPES = {"Collection", "Allocation", "Refund", "Forfeiture", "Waiver"}
DEPOSIT_APPROVAL_ROLES = (
    "Dagaar Motors Rental Manager",
    "Dagaar Motors Branch Manager",
    "Dagaar Motors Administrator",
)


DEPOSIT_MATCH_FIELDS = (
    "company",
    "branch",
    "vehicle",
    "vehicle_category",
    "rental_type",
    "customer_group",
    "country",
    "risk_classification",
)


def resolve_required_deposit(context: dict) -> dict:
    context = frappe._dict(context or {})
    company = resolve_company(context.company)
    settings = get_settings_dict()
    if not cint(settings.get("require_deposit")):
        return {"amount": 0.0, "rule": None, "deposit_type": None, "waiver_allowed": True}

    if context.customer and not context.customer_group:
        context.customer_group = frappe.get_cached_value("Customer", context.customer, "customer_group")
    if context.vehicle:
        vehicle = frappe.get_cached_doc("Motor Vehicle", context.vehicle)
        context.vehicle_category = context.vehicle_category or vehicle.category
        context.branch = context.branch or vehicle.branch

    rules = frappe.get_all(
        "Deposit Rule",
        filters={"enabled": 1},
        fields=[
            "name",
            "priority",
            *DEPOSIT_MATCH_FIELDS,
            "minimum_days",
            "maximum_days",
            "deposit_type",
            "amount_type",
            "amount",
            "percentage",
            "waiver_allowed",
            "waiver_requires_approval",
        ],
        order_by="priority desc, modified desc",
    )
    matches = []
    for rule in rules:
        score = 0
        rejected = False
        for fieldname in DEPOSIT_MATCH_FIELDS:
            expected = rule.get(fieldname)
            if expected not in (None, ""):
                if str(expected) != str(context.get(fieldname) or ""):
                    rejected = True
                    break
                score += 1
        if rejected:
            continue
        duration_days = flt(context.duration_days)
        if flt(rule.minimum_days) and duration_days < flt(rule.minimum_days):
            continue
        if flt(rule.maximum_days) and duration_days > flt(rule.maximum_days):
            continue
        matches.append((cint(rule.priority), score, rule))

    if matches:
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        rule = matches[0][2]
        amount = _rule_amount(rule, context)
        return {
            "amount": quantize(amount, _precision()),
            "rule": rule.name,
            "deposit_type": rule.deposit_type,
            "waiver_allowed": bool(rule.waiver_allowed),
            "waiver_requires_approval": bool(rule.waiver_requires_approval),
        }

    amount = 0.0
    if context.vehicle:
        vehicle = frappe.get_cached_doc("Motor Vehicle", context.vehicle)
        if vehicle.category:
            amount = flt(frappe.get_cached_value("Vehicle Category", vehicle.category, "default_deposit_amount"))
    if not amount and context.vehicle_category:
        amount = flt(frappe.get_cached_value("Vehicle Category", context.vehicle_category, "default_deposit_amount"))
    amount = amount or flt(settings.get("default_deposit_amount"))
    # Ensure a deposit is always requested: when nothing else applies, fall back
    # to a percentage of the rental total so checkout always collects a deposit.
    if not amount:
        percentage = flt(settings.get("default_deposit_percentage"))
        if percentage and flt(context.rental_total):
            amount = flt(context.rental_total) * percentage / 100
    return {
        "amount": quantize(amount, _precision()),
        "rule": None,
        "deposit_type": "Cash",
        "waiver_allowed": bool(settings.get("allow_deposit_waiver")),
        "waiver_requires_approval": bool(settings.get("deposit_waiver_requires_approval")),
    }


def _rule_amount(rule, context) -> float:
    if rule.amount_type == "Percentage of Rental":
        return flt(context.rental_total) * flt(rule.percentage) / 100
    if rule.amount_type == "Per Day":
        return flt(rule.amount) * max(1, math.ceil(flt(context.duration_days)))
    return flt(rule.amount)


def ensure_security_deposit(source_doc, amount: float | None = None) -> str | None:
    if source_doc.get("deposit_waived"):
        if not source_doc.get("deposit_waiver_approved_by"):
            frappe.throw(_("Deposit waiver requires an authorized approver."))
        return None

    required = flt(amount if amount is not None else source_doc.get("deposit_required"))
    if required <= 0:
        return None
    existing = source_doc.get("security_deposit")
    if existing and frappe.db.exists("Security Deposit", existing):
        deposit = frappe.get_doc("Security Deposit", existing)
        if deposit.amount_required != required and not deposit.amount_received:
            frappe.db.set_value(
                "Security Deposit",
                deposit.name,
                {
                    "amount_required": required,
                    "held_amount": 0,
                    "balance": 0,
                    "status": "Required",
                },
                update_modified=True,
            )
        return deposit.name

    company = source_doc.company
    settings = get_settings_dict()
    deposit = frappe.get_doc(
        {
            "doctype": "Security Deposit",
            "company": company,
            "branch": source_doc.branch,
            "customer": source_doc.customer,
            "reservation": source_doc.name if source_doc.doctype == "Rental Reservation" else source_doc.get("reservation"),
            "rental_agreement": source_doc.name if source_doc.doctype == "Rental Agreement" else source_doc.get("rental_agreement"),
            "vehicle": source_doc.get("vehicle"),
            "currency": source_doc.get("currency") or resolve_currency(company),
            "amount_required": required,
            "held_amount": 0,
            "balance": 0,
            "deposit_type": "Cash",
            "receipt_account": settings.get("default_deposit_payment_account"),
            "refund_account": settings.get("default_refund_payment_account"),
            "status": "Required",
            "idempotency_key": make_key("security_deposit", source_doc.doctype, source_doc.name),
        }
    )
    deposit.insert(ignore_permissions=True)
    return deposit.name


def prepare_transaction_identity(tx):
    tx.transaction_type = (tx.transaction_type or "").strip()
    if tx.transaction_type not in ALLOWED_TRANSACTION_TYPES:
        frappe.throw(_("Unsupported deposit transaction type {0}.").format(tx.transaction_type or _("blank")))
    tx.request_token = (tx.request_token or "").strip() or (
        f"reference:{tx.reference_number}" if tx.reference_number else frappe.generate_hash(length=20)
    )
    tx.idempotency_key = make_key(
        "deposit_transaction",
        "Security Deposit",
        tx.security_deposit,
        {"request_token": tx.request_token},
    )


def validate_transaction_document(tx):
    if not tx.security_deposit or not frappe.db.exists("Security Deposit", tx.security_deposit):
        frappe.throw(_("Select a valid Security Deposit."))
    lock_document("Security Deposit", tx.security_deposit)
    deposit = frappe.get_doc("Security Deposit", tx.security_deposit)
    tx.transaction_type = (tx.transaction_type or "").strip()
    tx.amount = _validate_transaction_values(deposit, tx.transaction_type, tx.amount)
    return deposit


def _validate_transaction_values(deposit, transaction_type: str, amount: float) -> float:
    if transaction_type not in ALLOWED_TRANSACTION_TYPES:
        frappe.throw(_("Unsupported deposit transaction type {0}.").format(transaction_type or _("blank")))

    amount = quantize(amount, _precision())
    if transaction_type == "Waiver":
        require_any_role(*DEPOSIT_APPROVAL_ROLES)
        if any(
            flt(deposit.get(fieldname)) > 0
            for fieldname in ("amount_received", "deducted_amount", "refund_amount")
        ):
            frappe.throw(
                _("Security Deposit {0} cannot be waived after money has been collected or used.").format(
                    deposit.name
                )
            )
        amount = quantize(amount or deposit.amount_required, _precision())

    if amount <= 0:
        frappe.throw(_("Deposit transaction amount must be greater than zero."))

    received = flt(deposit.amount_received)
    deducted = flt(deposit.deducted_amount)
    refunded = flt(deposit.refund_amount)
    available = quantize(max(0, received - deducted - refunded), _precision())

    if transaction_type == "Collection":
        remaining_required = quantize(max(0, flt(deposit.amount_required) - received), _precision())
        if amount > remaining_required:
            frappe.throw(
                _("Security Deposit {0} requires only {1} more; requested collection is {2}.").format(
                    deposit.name,
                    frappe.format_value(remaining_required, {"fieldtype": "Currency", "options": deposit.currency}),
                    frappe.format_value(amount, {"fieldtype": "Currency", "options": deposit.currency}),
                )
            )
    elif transaction_type in {"Allocation", "Refund", "Forfeiture"} and amount > available:
        frappe.throw(
            _("Security Deposit {0} has only {1} collected and available; requested {2}.").format(
                deposit.name,
                frappe.format_value(available, {"fieldtype": "Currency", "options": deposit.currency}),
                frappe.format_value(amount, {"fieldtype": "Currency", "options": deposit.currency}),
            )
        )
    return amount


def _assert_idempotent_match(existing, transaction_type, amount, reference_number, sales_invoice):
    expected = {
        "transaction_type": transaction_type,
        "amount": quantize(amount, _precision()),
        "reference_number": reference_number or None,
        "sales_invoice": sales_invoice or None,
    }
    actual = {
        "transaction_type": existing.transaction_type,
        "amount": quantize(existing.amount, _precision()),
        "reference_number": existing.reference_number or None,
        "sales_invoice": existing.sales_invoice or None,
    }
    if actual != expected:
        frappe.throw(
            _("This deposit request token was already used with different transaction details."),
            frappe.ValidationError,
        )


def create_transaction(
    deposit_name: str,
    transaction_type: str,
    amount: float,
    *,
    payment_method: str | None = None,
    reference_number: str | None = None,
    sales_invoice: str | None = None,
    allocations: list[dict] | None = None,
    remarks: str | None = None,
    request_token: str | None = None,
    submit: bool = True,
):
    transaction_type = (transaction_type or "").strip()
    if transaction_type not in ALLOWED_TRANSACTION_TYPES:
        frappe.throw(_("Unsupported deposit transaction type {0}.").format(transaction_type or _("blank")))

    lock_document("Security Deposit", deposit_name)
    deposit = frappe.get_doc("Security Deposit", deposit_name)
    amount = quantize(amount, _precision())
    if transaction_type == "Waiver":
        require_any_role(*DEPOSIT_APPROVAL_ROLES)
        amount = quantize(amount or deposit.amount_required, _precision())
    if amount <= 0:
        frappe.throw(_("Deposit transaction amount must be greater than zero."))

    request_token = (request_token or "").strip() or (
        f"reference:{reference_number}" if reference_number else frappe.generate_hash(length=20)
    )
    key = make_key(
        "deposit_transaction",
        "Security Deposit",
        deposit_name,
        {"request_token": request_token},
    )
    existing_name = frappe.db.get_value(
        "Deposit Transaction", {"idempotency_key": key, "docstatus": ["<", 2]}, "name"
    )
    if existing_name:
        existing = frappe.get_doc("Deposit Transaction", existing_name)
        _assert_idempotent_match(existing, transaction_type, amount, reference_number, sales_invoice)
        return existing

    amount = _validate_transaction_values(deposit, transaction_type, amount)
    tx = frappe.get_doc(
        {
            "doctype": "Deposit Transaction",
            "security_deposit": deposit_name,
            "transaction_type": transaction_type,
            "posting_date": nowdate(),
            "amount": amount,
            "payment_method": payment_method,
            "reference_number": reference_number,
            "sales_invoice": sales_invoice,
            "remarks": remarks,
            "request_token": request_token,
            "idempotency_key": key,
            "allocations": allocations or [],
        }
    )
    tx.insert(ignore_permissions=True)
    if submit:
        tx.flags.ignore_permissions = True
        tx.submit()
    return tx


def post_transaction(tx):
    lock_document("Security Deposit", tx.security_deposit)
    deposit = frappe.get_doc("Security Deposit", tx.security_deposit)
    if tx.transaction_type != "Waiver":
        tx.journal_entry = _create_deposit_journal_entry(tx, deposit)
    else:
        frappe.db.set_value(
            "Security Deposit",
            deposit.name,
            {"waiver_approved_by": frappe.session.user, "deposit_type": "Waiver"},
            update_modified=False,
        )
    tx.status = "Posted"
    update_deposit_totals(deposit.name)


def reverse_transaction(tx):
    if tx.journal_entry and frappe.db.exists("Journal Entry", tx.journal_entry):
        journal_entry = frappe.get_doc("Journal Entry", tx.journal_entry)
        if journal_entry.docstatus == 1:
            journal_entry.cancel()
    update_deposit_totals(tx.security_deposit)


def _create_deposit_journal_entry(tx, deposit) -> str:
    settings = get_settings_dict()
    company = deposit.company
    liability = resolve_account("deposit_liability_account", company, deposit.branch, deposit.vehicle)
    clearing = resolve_account("deposit_clearing_account", company, deposit.branch, deposit.vehicle)
    if not liability:
        frappe.throw(_("Configure a Deposit Liability Account for company {0}.").format(company))

    receipt_account = deposit.receipt_account or settings.get("default_deposit_payment_account")
    refund_account = deposit.refund_account or settings.get("default_refund_payment_account") or receipt_account
    validate_account_company(receipt_account, company)
    validate_account_company(refund_account, company)

    remark = f"Dagaar Motors {tx.transaction_type}: {deposit.name} / {tx.name}"
    existing = frappe.db.get_value(
        "Journal Entry",
        {"user_remark": remark, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return existing

    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = company
    journal.posting_date = tx.posting_date
    journal.user_remark = remark
    set_source_references(journal, dagaar_security_deposit=deposit.name, dagaar_motor_vehicle=deposit.vehicle)
    amount = flt(tx.amount)

    if tx.transaction_type == "Collection":
        if not receipt_account:
            frappe.throw(_("Select a receipt account on Security Deposit {0}.").format(deposit.name))
        journal.append("accounts", {"account": receipt_account, "debit_in_account_currency": amount})
        journal.append("accounts", {"account": liability, "credit_in_account_currency": amount})
    elif tx.transaction_type == "Refund":
        if not refund_account:
            frappe.throw(_("Select a refund account on Security Deposit {0}.").format(deposit.name))
        journal.append("accounts", {"account": liability, "debit_in_account_currency": amount})
        journal.append("accounts", {"account": refund_account, "credit_in_account_currency": amount})
    elif tx.transaction_type == "Allocation":
        destination = clearing
        account_row = {"account": destination, "credit_in_account_currency": amount}
        if tx.sales_invoice:
            invoice = frappe.get_doc("Sales Invoice", tx.sales_invoice)
            if invoice.docstatus != 1:
                frappe.throw(_("Sales Invoice {0} must be submitted before deposit allocation.").format(invoice.name))
            if invoice.company != company:
                frappe.throw(
                    _("Sales Invoice {0} belongs to company {1}, not {2}.").format(
                        invoice.name, invoice.company, company
                    )
                )
            if invoice.customer != deposit.customer:
                frappe.throw(
                    _("Sales Invoice {0} belongs to customer {1}, not {2}.").format(
                        invoice.name, invoice.customer, deposit.customer
                    )
                )
            if invoice.currency != deposit.currency:
                frappe.throw(
                    _(
                        "Sales Invoice {0} uses currency {1}, while Security Deposit {2} uses {3}. "
                        "Use matching currencies for deposit allocation."
                    ).format(invoice.name, invoice.currency, deposit.name, deposit.currency)
                )
            outstanding = max(0, flt(invoice.outstanding_amount))
            if amount > outstanding:
                frappe.throw(
                    _("Sales Invoice {0} has only {1} outstanding; requested allocation is {2}.").format(
                        invoice.name,
                        frappe.format_value(outstanding, {"fieldtype": "Currency", "options": invoice.currency}),
                        frappe.format_value(amount, {"fieldtype": "Currency", "options": invoice.currency}),
                    )
                )
            destination = invoice.debit_to
            account_row = {
                "account": destination,
                "party_type": "Customer",
                "party": deposit.customer,
                "reference_type": "Sales Invoice",
                "reference_name": invoice.name,
                "credit_in_account_currency": amount,
            }
        if not destination:
            frappe.throw(_("Configure a Deposit Clearing Account or select a Sales Invoice."))
        journal.append("accounts", {"account": liability, "debit_in_account_currency": amount})
        journal.append("accounts", account_row)
    elif tx.transaction_type == "Forfeiture":
        income = resolve_account("miscellaneous_rental_income_account", company, deposit.branch, deposit.vehicle)
        if not income:
            frappe.throw(_("Configure a Miscellaneous Rental Income Account."))
        journal.append("accounts", {"account": liability, "debit_in_account_currency": amount})
        journal.append("accounts", {"account": income, "credit_in_account_currency": amount})
    else:
        frappe.throw(_("Unsupported deposit transaction type {0}.").format(tx.transaction_type))

    journal.insert(ignore_permissions=True)
    persist_source_references(journal)
    journal.submit()
    return journal.name


def update_deposit_totals(deposit_name: str):
    lock_document("Security Deposit", deposit_name)
    deposit = frappe.get_doc("Security Deposit", deposit_name)
    totals = frappe.db.sql(
        """
        select
            sum(case when transaction_type = 'Collection' then amount else 0 end) as collected,
            sum(case when transaction_type = 'Allocation' then amount else 0 end) as allocated,
            sum(case when transaction_type = 'Forfeiture' then amount else 0 end) as forfeited,
            sum(case when transaction_type = 'Refund' then amount else 0 end) as refunded,
            sum(case when transaction_type = 'Waiver' then 1 else 0 end) as waived_count
        from `tabDeposit Transaction`
        where security_deposit = %s and docstatus = 1
        """,
        (deposit_name,),
        as_dict=True,
    )[0]
    received = flt(totals.collected)
    allocated = flt(totals.allocated)
    forfeited = flt(totals.forfeited)
    deducted = allocated + forfeited
    refunded = flt(totals.refunded)
    balance = max(0, received - deducted - refunded)
    required = flt(deposit.amount_required)
    status = _deposit_status(
        required=required,
        received=received,
        allocated=allocated,
        forfeited=forfeited,
        refunded=refunded,
        waived_count=cint(totals.waived_count),
        precision=_precision(),
    )

    waiver_approved_by = None
    if cint(totals.waived_count):
        waiver_approved_by = frappe.db.get_value(
            "Deposit Transaction",
            {"security_deposit": deposit_name, "transaction_type": "Waiver", "docstatus": 1},
            "owner",
            order_by="creation desc",
        )

    frappe.db.set_value(
        "Security Deposit",
        deposit_name,
        {
            "amount_received": quantize(received, _precision()),
            "held_amount": quantize(balance, _precision()),
            "deducted_amount": quantize(deducted, _precision()),
            "refund_amount": quantize(refunded, _precision()),
            "balance": quantize(balance, _precision()),
            "status": status,
            "waiver_approved_by": waiver_approved_by,
            "deposit_type": (
                "Waiver"
                if waiver_approved_by
                else "Cash" if deposit.deposit_type == "Waiver" else deposit.deposit_type
            ),
        },
        update_modified=True,
    )
    latest = frappe.db.get_value(
        "Deposit Transaction",
        {"security_deposit": deposit_name, "docstatus": 1},
        "name",
        order_by="posting_date desc, creation desc",
    )
    frappe.db.set_value(
        "Security Deposit",
        deposit_name,
        "latest_transaction",
        latest,
        update_modified=False,
    )



def _deposit_status(
    *,
    required: float,
    received: float,
    allocated: float,
    forfeited: float,
    refunded: float,
    waived_count: int = 0,
    precision: int = 2,
) -> str:
    precision = max(0, int(precision))
    tolerance = 10 ** -precision
    deducted = flt(allocated) + flt(forfeited)
    balance = max(0, flt(received) - deducted - flt(refunded))

    if waived_count:
        return "Waived"
    if flt(received) <= tolerance:
        return "Required"
    if balance <= tolerance:
        if flt(refunded) >= flt(received) - tolerance and deducted <= tolerance:
            return "Refunded"
        if (
            flt(forfeited) >= flt(received) - tolerance
            and flt(allocated) <= tolerance
            and flt(refunded) <= tolerance
        ):
            return "Forfeited"
        return "Fully Used"
    if deducted > tolerance or flt(refunded) > tolerance:
        return "Partially Used"
    if flt(received) < flt(required) - tolerance:
        return "Partially Collected"
    return "Held"

def _precision() -> int:
    return max(0, cint(get_settings_dict().get("currency_precision") or 2))