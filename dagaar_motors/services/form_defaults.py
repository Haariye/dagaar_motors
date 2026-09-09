from __future__ import annotations

import frappe
from frappe.utils import getdate


def get_customer_defaults(customer: str | None) -> dict:
    if not customer or not frappe.db.exists("Customer", customer):
        return {}

    customer_doc = frappe.get_cached_doc("Customer", customer)
    contact_name = customer_doc.get("customer_primary_contact") or _first_customer_contact(customer)
    contact = frappe.get_cached_doc("Contact", contact_name) if contact_name and frappe.db.exists("Contact", contact_name) else None

    full_name = (
        (contact.get("full_name") if contact else None)
        or customer_doc.get("customer_name")
        or customer
    )
    phone = (
        (contact.get("mobile_no") if contact else None)
        or (contact.get("phone") if contact else None)
        or customer_doc.get("mobile_no")
    )
    email = (
        (contact.get("email_id") if contact else None)
        or customer_doc.get("email_id")
    )

    return {
        "customer": customer,
        "customer_name": customer_doc.get("customer_name") or customer,
        "contact": contact_name,
        "contact_name": full_name,
        "phone": phone,
        "email": email,
        "territory": customer_doc.get("territory"),
        "customer_group": customer_doc.get("customer_group"),
    }


def get_branch_defaults(branch: str | None) -> dict:
    if not branch or not frappe.db.exists("Motor Branch", branch):
        return {}
    doc = frappe.get_cached_doc("Motor Branch", branch)
    currency = doc.get("currency") or frappe.get_cached_value("Company", doc.company, "default_currency")
    return {
        "branch": doc.name,
        "company": doc.company,
        "currency": currency,
        "pickup_location": doc.get("pickup_location") or doc.get("city") or doc.get("branch_name"),
        "return_location": doc.get("return_location") or doc.get("pickup_location") or doc.get("city") or doc.get("branch_name"),
        "warehouse": doc.get("warehouse"),
        "cost_center": doc.get("cost_center"),
        "asset_location": doc.get("asset_location"),
    }


def get_vehicle_defaults(vehicle: str | None) -> dict:
    if not vehicle or not frappe.db.exists("Motor Vehicle", vehicle):
        return {}
    doc = frappe.get_cached_doc("Motor Vehicle", vehicle)
    return {
        "vehicle": doc.name,
        "vehicle_name": doc.vehicle_title,
        "company": doc.company,
        "branch": doc.branch,
        "vehicle_category": doc.get("category"),
        "category": doc.get("category"),
        "rental_category": doc.get("rental_category") or doc.get("category"),
        "currency": frappe.get_cached_value("Company", doc.company, "default_currency"),
        "current_odometer": doc.get("current_odometer"),
        "fuel_level": doc.get("fuel_level"),
        "current_location": doc.get("current_location"),
        "item": doc.get("item"),
        "selling_item": doc.get("selling_item") or doc.get("item"),
        "asset": doc.get("asset"),
        "project": doc.get("project"),
        "warehouse": doc.get("warehouse"),
        "cost_center": doc.get("cost_center"),
        "sellable": doc.get("sellable"),
        "rentable": doc.get("rentable"),
        "asking_price": doc.get("selling_price"),
        "minimum_price": doc.get("minimum_selling_price"),
        "commission_percent": doc.get("sales_commission_percent"),
    }


def get_agreement_defaults(agreement: str | None) -> dict:
    if not agreement or not frappe.db.exists("Rental Agreement", agreement):
        return {}
    doc = frappe.get_cached_doc("Rental Agreement", agreement)
    result = {
        "rental_agreement": doc.name,
        "company": doc.company,
        "branch": doc.branch,
        "customer": doc.customer,
        "contact": doc.contact,
        "vehicle": doc.vehicle,
        "vehicle_category": doc.vehicle_category,
        "rental_type": doc.rental_type,
        "currency": doc.currency,
        "pickup_datetime": doc.pickup_datetime,
        "expected_return_datetime": doc.expected_return_datetime,
        "checkout_odometer": doc.checkout_odometer,
        "checkout_fuel_level": doc.checkout_fuel_level,
        "security_deposit": doc.security_deposit,
        "pickup_location": doc.pickup_location,
        "return_location": doc.return_location,
    }
    return result


def apply_customer_defaults(doc, *, suggest_driver: bool = False) -> dict:
    customer = doc.get("customer")
    values = get_customer_defaults(customer)
    if not values:
        return values

    if doc.meta.has_field("contact") and not doc.get("contact") and values.get("contact"):
        doc.contact = values["contact"]

    if suggest_driver and doc.meta.has_field("drivers") and not doc.get("drivers"):
        doc.append("drivers", driver_row_from_customer(customer, values=values))
    return values


def apply_branch_defaults(doc) -> dict:
    values = get_branch_defaults(doc.get("branch"))
    if not values:
        return values
    for fieldname in ("company", "currency", "pickup_location", "return_location", "warehouse", "cost_center"):
        if doc.meta.has_field(fieldname) and not doc.get(fieldname) and values.get(fieldname):
            doc.set(fieldname, values[fieldname])
    return values


def apply_vehicle_defaults(doc, vehicle_field: str = "vehicle") -> dict:
    vehicle_name = doc.get(vehicle_field) or doc.get("requested_vehicle")
    values = get_vehicle_defaults(vehicle_name)
    if not values:
        return values
    mapping = {
        "company": "company",
        "branch": "branch",
        "currency": "currency",
        "vehicle_category": "vehicle_category",
        "category": "category",
        "warehouse": "warehouse",
        "cost_center": "cost_center",
    }
    for source, target in mapping.items():
        if doc.meta.has_field(target) and not doc.get(target) and values.get(source):
            doc.set(target, values[source])
    return values


def driver_row_from_customer(customer: str, *, values: dict | None = None) -> dict:
    values = values or get_customer_defaults(customer)
    return {
        "full_name": values.get("contact_name") or values.get("customer_name") or customer,
        "phone": values.get("phone"),
        "email": values.get("email"),
        "primary_driver": 1,
        "source_contact": values.get("contact"),
        "source_customer": customer,
        "suggested_from_customer": 1,
    }


def _first_customer_contact(customer: str) -> str | None:
    if not frappe.db.exists("DocType", "Dynamic Link"):
        return None
    rows = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
        fields=["parent"],
        order_by="idx asc",
        limit_page_length=1,
    )
    return rows[0].parent if rows else None
