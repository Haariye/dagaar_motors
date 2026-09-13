from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.accounting import set_if_present, set_source_references
from dagaar_motors.services.erp_links import persist_source_references
from dagaar_motors.services.idempotency import make_key
from dagaar_motors.services.settings import (
    get_settings_dict,
    resolve_account,
    resolve_cost_center,
    resolve_currency,
    resolve_warehouse,
)
from dagaar_motors.utils.money import quantize
from dagaar_motors.utils.validation import validate_account_company, validate_cost_center_company


CHARGE_MAPPING = {
    "Rental": ("default_rental_item", "rental_income_account"),
    "Extension": ("default_extension_item", "extension_income_account"),
    "Late Return": ("default_misc_item", "late_return_income_account"),
    "Mileage": ("default_mileage_item", "excess_mileage_income_account"),
    "Fuel": ("default_fuel_item", "fuel_charge_income_account"),
    "Damage": ("default_damage_item", "damage_recovery_income_account"),
    "Cleaning": ("default_cleaning_item", "cleaning_charge_income_account"),
    "Fine": ("default_misc_item", "miscellaneous_rental_income_account"),
    "Insurance": ("default_misc_item", "insurance_charge_income_account"),
    "Delivery": ("default_misc_item", "delivery_income_account"),
    "Collection": ("default_misc_item", "collection_income_account"),
    "Driver": ("default_misc_item", "driver_service_income_account"),
    "Other": ("default_misc_item", "miscellaneous_rental_income_account"),
}


def ensure_vehicle_project(vehicle: str | object) -> str | None:
    vehicle_doc = frappe.get_doc("Motor Vehicle", vehicle) if isinstance(vehicle, str) else vehicle
    if vehicle_doc.project:
        return vehicle_doc.project
    settings = get_settings_dict()
    if not cint(settings.get("project_per_vehicle")):
        return settings.get("default_project")

    project_name = f"{vehicle_doc.name} - {vehicle_doc.vehicle_title or vehicle_doc.license_plate}"
    existing = frappe.db.get_value("Project", {"project_name": project_name, "company": vehicle_doc.company}, "name")
    if existing:
        project = existing
    else:
        project_doc = frappe.new_doc("Project")
        project_doc.project_name = project_name[:140]
        set_if_present(project_doc, "company", vehicle_doc.company)
        set_if_present(project_doc, "status", "Open")
        set_if_present(project_doc, "is_active", "Yes")
        project_doc.insert(ignore_permissions=True)
        project = project_doc.name
    frappe.db.set_value("Motor Vehicle", vehicle_doc.name, "project", project, update_modified=False)
    vehicle_doc.project = project
    return project


def resolve_charge_mapping(
    *,
    category: str,
    company: str,
    branch: str | None,
    vehicle: str | None,
    charge_type: str | None = None,
) -> dict:
    item = None
    account = None
    label = category
    if charge_type:
        charge = frappe.get_cached_doc("Rental Charge Type", charge_type)
        if not charge.active:
            frappe.throw(_("Rental Charge Type {0} is disabled.").format(charge_type))
        category = charge.category or category
        label = charge.charge_name
        item = charge.item
        account = charge.income_account

    item_field, account_field = CHARGE_MAPPING.get(category, CHARGE_MAPPING["Other"])
    settings = get_settings_dict()
    item = item or settings.get(item_field)
    account = account or resolve_account(account_field, company, branch, vehicle)
    if not item:
        frappe.throw(
            _("Configure an Item for {0} charges in Rental Charge Type or Dagaar Motors Settings.").format(category)
        )
    if not account:
        frappe.throw(_("Configure an income account for {0} charges.").format(category))
    validate_account_company(account, company)
    return {"item_code": item, "income_account": account, "description": label, "category": category}


def make_invoice_source_key(source_references: dict) -> str:
    """Create a stable key from every non-empty source reference.

    Using the complete reference set keeps separate extensions, returns,
    damage reports, and sales under the same agreement independently
    idempotent.
    """
    stable_references = {
        fieldname: str(value)
        for fieldname, value in sorted(source_references.items())
        if value not in (None, "")
    }
    if not stable_references:
        frappe.throw(_("At least one Dagaar Motors source reference is required."))
    return make_key(
        "sales_invoice",
        "Dagaar Motors",
        "source_references",
        stable_references,
    )

def create_sales_invoice(
    *,
    company: str,
    customer: str,
    currency: str | None,
    branch: str | None,
    vehicle: str | None,
    lines: Iterable[dict],
    source_references: dict,
    tax_template: str | None = None,
    posting_date: str | None = None,
    due_date: str | None = None,
    submit: bool | None = None,
    update_stock: bool = False,
    remarks: str | None = None,
    allocate_advances: bool = False,
) -> object:
    require_any_role(
        "Dagaar Motors Rental Manager",
        "Dagaar Motors Rental Agent",
        "Dagaar Motors Accountant",
        "Dagaar Motors Vehicle Sales Manager",
        "Dagaar Motors Vehicle Salesperson",
    )
    source_key = make_invoice_source_key(source_references)
    existing = _find_existing_invoice(source_references, source_key)
    if existing:
        invoice = frappe.get_doc("Sales Invoice", existing)
        set_source_references(invoice, **source_references)
        persist_source_references(invoice, source_key=source_key)
        return invoice

    settings = get_settings_dict()
    invoice = frappe.new_doc("Sales Invoice")
    invoice.company = company
    invoice.customer = customer
    invoice.currency = resolve_currency(company, currency)
    invoice.posting_date = posting_date or nowdate()
    if due_date:
        invoice.due_date = due_date
    if tax_template:
        invoice.taxes_and_charges = tax_template
    if settings.get("payment_terms_template"):
        set_if_present(invoice, "payment_terms_template", settings.get("payment_terms_template"))
    invoice.update_stock = cint(update_stock)
    invoice.remarks = _merge_remarks(remarks, f"Dagaar Motors Source Key: {source_key}")
    set_source_references(invoice, **source_references)

    project = ensure_vehicle_project(vehicle) if vehicle else settings.get("default_project")
    cost_center = resolve_cost_center(company, branch, vehicle)
    validate_cost_center_company(cost_center, company)
    warehouse = resolve_warehouse(company, branch, vehicle) if update_stock else None

    appended = 0
    for raw in lines:
        row = frappe._dict(raw)
        amount = flt(row.amount)
        quantity = flt(row.qty or row.quantity or 1)
        rate = flt(row.rate)
        if not rate and quantity:
            rate = amount / quantity
        if amount <= 0 and rate <= 0:
            continue
        item_row = {
            "item_code": row.item_code,
            "description": row.description or row.item_code,
            "qty": quantity,
            "rate": rate,
            "income_account": row.income_account,
            "cost_center": row.cost_center or cost_center,
            "project": row.project or project,
        }
        if update_stock:
            item_row["warehouse"] = row.warehouse or warehouse
        invoice.append("items", item_row)
        appended += 1
    if not appended:
        frappe.throw(_("No billable lines were supplied for the Sales Invoice."))

    invoice.set_missing_values()
    if allocate_advances:
        # Apply the customer's unallocated advances (e.g. the security deposit
        # collected via Payment Entry) against this invoice. We allocate manually
        # and cap each row to the invoice total so ERPNext never tries to
        # over-allocate an advance to an already-covered invoice.
        try:
            invoice.calculate_taxes_and_totals()
            invoice.set("advances", [])
            invoice.set_advances()
            remaining = flt(invoice.rounded_total or invoice.grand_total)
            kept = []
            for adv in list(invoice.get("advances") or []):
                allocatable = min(flt(adv.advance_amount), remaining)
                if allocatable > 0:
                    adv.allocated_amount = allocatable
                    remaining = flt(remaining) - allocatable
                    kept.append(adv)
            invoice.set("advances", kept)
        except Exception:
            invoice.set("advances", [])
            frappe.log_error(frappe.get_traceback(), "Dagaar Motors: advance allocation failed")
    invoice.calculate_taxes_and_totals()
    invoice.insert(ignore_permissions=True)
    persist_source_references(invoice, source_key=source_key)
    should_submit = cint(settings.get("auto_submit_rental_invoice")) if submit is None else cint(submit)
    if should_submit:
        invoice.submit()
    return invoice


def create_customer_payment_entry(
    *,
    company: str,
    customer: str,
    amount: float,
    currency: str | None = None,
    branch: str | None = None,
    vehicle: str | None = None,
    payment_type: str = "Receive",
    mode_of_payment: str | None = None,
    reference_no: str | None = None,
    reference_date: str | None = None,
    bank_account: str | None = None,
    source_references: dict | None = None,
    remarks: str | None = None,
    submit: bool | None = True,
) -> object:
    """Create an ERPNext Payment Entry against a Customer.

    Using a Payment Entry (rather than a Journal Entry) means the money is
    posted to the customer's party ledger, so security deposits and rental
    payments appear in the customer's balance/statement and can be reconciled
    against invoices natively. A "Receive" with no invoice reference becomes an
    unallocated advance (credit) on the customer; "Pay" is used for refunds.
    """
    from erpnext.accounts.party import get_party_account

    settings = get_settings_dict()
    amount = quantize(flt(amount), 2)
    if amount <= 0:
        frappe.throw(_("Payment amount must be greater than zero."))

    party_account = settings.get("customer_receivable_account") or get_party_account("Customer", customer, company)
    if not party_account:
        frappe.throw(_("Configure a Customer Receivable Account for company {0}.").format(company))
    validate_account_company(party_account, company)

    if payment_type == "Receive":
        bank = bank_account or settings.get("default_deposit_payment_account")
        if not bank:
            frappe.throw(_("Configure a Default Deposit Receipt Account (bank/cash) in Motors Settings."))
        paid_from, paid_to = party_account, bank
    else:  # "Pay" — refund to the customer
        bank = bank_account or settings.get("default_refund_payment_account") or settings.get("default_deposit_payment_account")
        if not bank:
            frappe.throw(_("Configure a Default Deposit Refund Account (bank/cash) in Motors Settings."))
        paid_from, paid_to = bank, party_account
    validate_account_company(bank, company)

    company_currency = resolve_currency(company)
    from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency
    to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = payment_type
    pe.company = company
    pe.posting_date = nowdate()
    pe.party_type = "Customer"
    pe.party = customer
    pe.paid_from = paid_from
    pe.paid_to = paid_to
    pe.paid_from_account_currency = from_currency
    pe.paid_to_account_currency = to_currency
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.source_exchange_rate = 1
    pe.target_exchange_rate = 1
    if mode_of_payment:
        pe.mode_of_payment = mode_of_payment
        # Non-cash modes need a reference; fall back to the source doc reference.
        pe.reference_no = reference_no or f"{payment_type}-{customer}"
        pe.reference_date = reference_date or nowdate()
    elif reference_no:
        pe.reference_no = reference_no
        pe.reference_date = reference_date or nowdate()
    # Establish the party account fields up front. ERPNext normally does this in
    # setup_party_account_field() during validate(); doing it here means the
    # party account exists no matter what order later code runs in (and avoids an
    # AttributeError when a third-party app overrides the Payment Entry class).
    pe.party_account = paid_from if payment_type == "Receive" else paid_to
    pe.party_account_field = "paid_from" if payment_type == "Receive" else "paid_to"
    pe.party_account_currency = from_currency if payment_type == "Receive" else to_currency

    set_if_present(pe, "branch", branch)
    cost_center = resolve_cost_center(company, branch, vehicle)
    if cost_center:
        set_if_present(pe, "cost_center", cost_center)
    if source_references:
        set_source_references(pe, **source_references)
    if remarks:
        pe.remarks = remarks

    # insert() runs validate(), which calls setup_party_account_field() and then
    # set_missing_values() in the correct order, so we don't call the latter here.
    pe.flags.ignore_permissions = True
    pe.insert(ignore_permissions=True)
    if source_references:
        persist_source_references(pe)
    should_submit = True if submit is None else submit
    if should_submit:
        pe.submit()
    return pe


def create_agreement_invoice(agreement: str | object, submit: bool | None = None):
    doc = frappe.get_doc("Rental Agreement", agreement) if isinstance(agreement, str) else agreement
    mapping = resolve_charge_mapping(
        category="Rental", company=doc.company, branch=doc.branch, vehicle=doc.vehicle
    )
    lines = [
        {
            **mapping,
            "qty": doc.duration_units or 1,
            "rate": doc.base_rate or (flt(doc.base_amount) / max(flt(doc.duration_units), 1)),
            "amount": doc.base_amount,
            "description": f"Rental {doc.pickup_datetime} to {doc.original_end_datetime or doc.expected_return_datetime}",
        }
    ]
    lines.extend(_extra_invoice_lines(doc.extras, doc.company, doc.branch, doc.vehicle))
    lines.extend(_charge_invoice_lines(doc.charges, doc.company, doc.branch, doc.vehicle))
    invoice = create_sales_invoice(
        company=doc.company,
        customer=doc.customer,
        currency=doc.currency,
        branch=doc.branch,
        vehicle=doc.vehicle,
        lines=lines,
        source_references={"dagaar_rental_agreement": doc.name, "dagaar_motor_vehicle": doc.vehicle},
        tax_template=doc.tax_template,
        submit=submit,
        remarks=f"Original rental billing for {doc.name}",
    )
    if doc.meta.has_field("current_invoice"):
        frappe.db.set_value("Rental Agreement", doc.name, "current_invoice", invoice.name, update_modified=False)
    return invoice


def create_extension_invoice(extension: str | object, submit: bool | None = None):
    doc = frappe.get_doc("Rental Extension", extension) if isinstance(extension, str) else extension
    agreement = frappe.get_doc("Rental Agreement", doc.rental_agreement)
    mapping = resolve_charge_mapping(
        category="Extension", company=doc.company, branch=doc.branch, vehicle=doc.vehicle
    )
    invoice = create_sales_invoice(
        company=doc.company,
        customer=agreement.customer,
        currency=doc.currency,
        branch=doc.branch,
        vehicle=doc.vehicle,
        lines=[
            {
                **mapping,
                "qty": doc.duration_units or 1,
                "rate": doc.rate or (flt(doc.base_amount) / max(flt(doc.duration_units), 1)),
                "amount": doc.net_amount or doc.grand_total,
                "description": f"Rental extension {doc.original_end_datetime} to {doc.new_end_datetime}",
            }
        ],
        source_references={
            "dagaar_rental_agreement": doc.rental_agreement,
            "dagaar_rental_extension": doc.name,
            "dagaar_motor_vehicle": doc.vehicle,
        },
        tax_template=doc.tax_template,
        submit=submit,
        remarks=f"Extension billing for {doc.name}",
    )
    frappe.db.set_value("Rental Extension", doc.name, {"sales_invoice": invoice.name, "status": "Invoiced"}, update_modified=False)
    return invoice


def create_return_invoice(rental_return: str | object, submit: bool | None = None):
    doc = frappe.get_doc("Rental Return", rental_return) if isinstance(rental_return, str) else rental_return
    lines = _charge_invoice_lines(doc.charges, doc.company, doc.branch, doc.vehicle)
    if not lines:
        return None
    invoice = create_sales_invoice(
        company=doc.company,
        customer=doc.customer,
        currency=doc.currency,
        branch=doc.branch,
        vehicle=doc.vehicle,
        lines=lines,
        source_references={
            "dagaar_rental_agreement": doc.rental_agreement,
            "dagaar_rental_return": doc.name,
            "dagaar_motor_vehicle": doc.vehicle,
        },
        submit=submit,
        remarks=f"Final return charges for {doc.name}",
        allocate_advances=True,
    )
    frappe.db.set_value("Rental Return", doc.name, {"final_sales_invoice": invoice.name, "status": "Invoiced"}, update_modified=False)
    return invoice


def create_vehicle_sale_invoice(vehicle_sale: str | object, submit: bool | None = None):
    doc = frappe.get_doc("Vehicle Sale", vehicle_sale) if isinstance(vehicle_sale, str) else vehicle_sale
    vehicle = frappe.get_doc("Motor Vehicle", doc.vehicle)
    if not doc.item:
        frappe.throw(_("Select a selling Item on Vehicle Sale {0}.").format(doc.name))
    income_account = frappe.get_cached_value("Item Default", {"parent": doc.item, "company": doc.company}, "income_account")
    income_account = income_account or resolve_account("vehicle_sale_income_account", doc.company, doc.branch, doc.vehicle)
    if not income_account:
        frappe.throw(_("Configure an income account for vehicle sales."))
    invoice = create_sales_invoice(
        company=doc.company,
        customer=doc.buyer,
        currency=doc.currency,
        branch=doc.branch,
        vehicle=doc.vehicle,
        lines=[
            {
                "item_code": doc.item,
                "description": vehicle.vehicle_title,
                "qty": 1,
                "rate": doc.sale_price,
                "amount": doc.sale_price,
                "income_account": income_account,
            }
        ],
        source_references={"dagaar_vehicle_sale": doc.name, "dagaar_motor_vehicle": doc.vehicle},
        submit=submit,
        update_stock=bool(frappe.get_cached_value("Item", doc.item, "is_stock_item")),
        remarks=f"Vehicle sale {doc.name}",
    )
    values = {"sales_invoice": invoice.name}
    if invoice.docstatus != 1:
        values["status"] = "Invoiced"
    frappe.db.set_value("Vehicle Sale", doc.name, values, update_modified=False)
    return invoice


def _extra_invoice_lines(extras, company, branch, vehicle):
    lines = []
    for row in extras or []:
        if not row.rental_extra or flt(row.amount) <= 0:
            continue
        extra = frappe.get_cached_doc("Rental Extra", row.rental_extra)
        mapping = resolve_charge_mapping(category="Other", company=company, branch=branch, vehicle=vehicle)
        lines.append(
            {
                "item_code": extra.item or mapping["item_code"],
                "income_account": extra.income_account or mapping["income_account"],
                "description": row.description or extra.extra_name,
                "qty": row.quantity or 1,
                "rate": row.rate,
                "amount": row.amount,
            }
        )
    return lines


def _charge_invoice_lines(charges, company, branch, vehicle):
    lines = []
    for row in charges or []:
        if flt(row.amount) <= 0:
            continue
        charge_type = frappe.get_cached_doc("Rental Charge Type", row.charge_type) if row.charge_type else None
        category = charge_type.category if charge_type else "Other"
        mapping = resolve_charge_mapping(
            category=category,
            company=company,
            branch=branch,
            vehicle=vehicle,
            charge_type=row.charge_type,
        )
        lines.append(
            {
                "item_code": row.get("item") or mapping["item_code"],
                "income_account": row.get("income_account") or mapping["income_account"],
                "description": row.description or mapping["description"],
                "qty": row.quantity or 1,
                "rate": row.rate or (flt(row.amount) / max(flt(row.quantity), 1)),
                "amount": row.amount,
            }
        )
    return lines


def _find_existing_invoice(source_references: dict, source_key: str) -> str | None:
    # Idempotency no longer depends on custom columns on Sales Invoice. The stable
    # source key is embedded in remarks and remains queryable on every ERPNext site.
    existing = frappe.db.get_value(
        "Sales Invoice",
        {"docstatus": ["<", 2], "remarks": ["like", f"%{source_key}%"]},
        "name",
    )
    return existing or None


def _merge_remarks(*parts):
    return "\n".join(str(part).strip() for part in parts if part and str(part).strip())