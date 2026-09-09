from __future__ import annotations

import frappe
from frappe import _

from dagaar_motors.services.erp_links import get_payment_entry_source_references, get_source_references
from dagaar_motors.services.fleet import recalculate_vehicle_financials
from dagaar_motors.services.vehicle_sales import finalize_vehicle_sale


def validate_sales_invoice(doc, method=None):
    refs = get_source_references(doc)
    vehicle = refs.get("dagaar_motor_vehicle")
    if vehicle:
        _validate_vehicle_company(vehicle, doc.company)

    agreement_name = refs.get("dagaar_rental_agreement")
    if agreement_name:
        agreement = frappe.get_cached_doc("Rental Agreement", agreement_name)
        if agreement.company != doc.company or agreement.customer != doc.customer:
            frappe.throw(_("Sales Invoice company/customer must match Rental Agreement {0}.").format(agreement.name))

    sale_name = refs.get("dagaar_vehicle_sale")
    if sale_name:
        sale = frappe.get_cached_doc("Vehicle Sale", sale_name)
        if sale.company != doc.company or sale.buyer != doc.customer:
            frappe.throw(_("Sales Invoice company/customer must match Vehicle Sale {0}.").format(sale.name))


def on_sales_invoice_submit(doc, method=None):
    refs = get_source_references(doc)
    sale_name = refs.get("dagaar_vehicle_sale")
    agreement_name = refs.get("dagaar_rental_agreement")
    vehicle = refs.get("dagaar_motor_vehicle")

    if sale_name:
        finalize_vehicle_sale(sale_name, doc.name)
    if agreement_name:
        _update_reservation_payment_status(agreement_name)
    if vehicle:
        recalculate_vehicle_financials(vehicle)


def on_sales_invoice_cancel(doc, method=None):
    refs = get_source_references(doc)
    sale_name = refs.get("dagaar_vehicle_sale")
    agreement_name = refs.get("dagaar_rental_agreement")
    vehicle = refs.get("dagaar_motor_vehicle")

    if sale_name:
        sale = frappe.get_doc("Vehicle Sale", sale_name)
        if sale.status == "Completed":
            frappe.throw(_("Reverse the completed Vehicle Sale before cancelling this Sales Invoice."))
    if agreement_name:
        _update_reservation_payment_status(agreement_name)
    if vehicle:
        recalculate_vehicle_financials(vehicle)


def validate_payment_entry(doc, method=None):
    for refs in get_payment_entry_source_references(doc):
        vehicle = refs.get("dagaar_motor_vehicle")
        if vehicle:
            _validate_vehicle_company(vehicle, doc.company)
        agreement_name = refs.get("dagaar_rental_agreement")
        if agreement_name:
            agreement = frappe.get_cached_doc("Rental Agreement", agreement_name)
            if doc.party_type == "Customer" and agreement.customer != doc.party:
                frappe.throw(_("Payment Entry party must match Rental Agreement customer {0}.").format(agreement.customer))


def on_payment_entry_submit(doc, method=None):
    agreements = set()
    vehicles = set()
    for refs in get_payment_entry_source_references(doc):
        if refs.get("dagaar_rental_agreement"):
            agreements.add(refs["dagaar_rental_agreement"])
        if refs.get("dagaar_motor_vehicle"):
            vehicles.add(refs["dagaar_motor_vehicle"])
    for agreement in agreements:
        _update_reservation_payment_status(agreement)
    for vehicle in vehicles:
        recalculate_vehicle_financials(vehicle)


def on_payment_entry_cancel(doc, method=None):
    on_payment_entry_submit(doc, method)


def _validate_vehicle_company(vehicle: str, company: str):
    vehicle_company = frappe.get_cached_value("Motor Vehicle", vehicle, "company")
    if vehicle_company != company:
        frappe.throw(_("Motor Vehicle {0} belongs to company {1}, not {2}.").format(vehicle, vehicle_company, company))


def _update_reservation_payment_status(agreement_name: str):
    reservation = frappe.get_cached_value("Rental Agreement", agreement_name, "reservation")
    if not reservation:
        return
    outstanding = frappe.db.sql(
        """
        select coalesce(sum(si.outstanding_amount), 0), coalesce(sum(si.grand_total), 0)
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        where si.docstatus = 1 and dl.rental_agreement = %s
        """,
        (agreement_name,),
    )[0]
    outstanding_amount, total = float(outstanding[0] or 0), float(outstanding[1] or 0)
    status = "Unpaid" if total and outstanding_amount >= total else "Paid" if outstanding_amount <= 0 and total else "Partly Paid"
    frappe.db.set_value("Rental Reservation", reservation, "payment_status", status, update_modified=False)
