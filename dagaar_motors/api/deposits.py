from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import enforce_document_scope, require_any_role
from dagaar_motors.services.deposits import create_transaction


@frappe.whitelist()
def transact(
    security_deposit,
    transaction_type,
    amount,
    payment_method=None,
    reference_number=None,
    sales_invoice=None,
    allocations=None,
    remarks=None,
    request_token=None,
):
    require_any_role(
        "Dagaar Motors Cashier",
        "Dagaar Motors Accountant",
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Branch Manager",
    )
    if transaction_type == "Waiver":
        require_any_role(
            "Dagaar Motors Rental Manager",
            "Dagaar Motors Branch Manager",
            "Dagaar Motors Administrator",
        )
    enforce_document_scope("Security Deposit", security_deposit)
    parsed_allocations = frappe.parse_json(allocations) if isinstance(allocations, str) else allocations
    return create_transaction(
        security_deposit,
        transaction_type,
        float(amount or 0),
        payment_method=payment_method,
        reference_number=reference_number,
        sales_invoice=sales_invoice,
        allocations=parsed_allocations,
        remarks=remarks,
        request_token=request_token,
    ).as_dict()