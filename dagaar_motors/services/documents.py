from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate


DRIVER_DOCUMENT_FIELDS = {
    "National ID": "id_attachment",
    "Passport": "passport_attachment",
    "Driving License": "license_attachment",
}


def get_required_documents(source_doc) -> list[dict]:
    """Return enabled document rules that apply to this rental context."""
    customer_type = _customer_type(source_doc.get("customer"))
    country = _driver_country(source_doc)
    rows = frappe.get_all(
        "Rental Document Requirement",
        filters={"enabled": 1, "required": 1},
        fields=[
            "name", "requirement_name", "document_type", "customer_type", "country",
            "vehicle_category", "rental_type", "company", "branch",
            "expiry_must_cover_rental", "description",
        ],
        order_by="modified asc",
    )
    context = {
        "customer_type": customer_type,
        "country": country,
        "vehicle_category": source_doc.get("vehicle_category"),
        "rental_type": source_doc.get("rental_type"),
        "company": source_doc.get("company"),
        "branch": source_doc.get("branch"),
    }
    return [row for row in rows if _matches(row, context)]


def get_missing_documents(source_doc) -> list[str]:
    requirements = get_required_documents(source_doc)
    if not requirements:
        return []

    drivers = _get_driver_docs(source_doc)
    missing: list[str] = []
    for requirement in requirements:
        document_type = requirement.document_type
        if document_type in DRIVER_DOCUMENT_FIELDS:
            fieldname = DRIVER_DOCUMENT_FIELDS[document_type]
            if not drivers or any(not driver.get(fieldname) for driver in drivers):
                missing.append(requirement.requirement_name or document_type)
                continue
            if requirement.expiry_must_cover_rental and document_type in {"Passport", "Driving License"}:
                expiry_field = "license_expiry_date" if document_type == "Driving License" else "passport_expiry_date"
                rental_end = source_doc.get("return_datetime") or source_doc.get("expected_return_datetime")
                if rental_end and any(
                    driver.get(expiry_field) and getdate(driver.get(expiry_field)) < getdate(rental_end)
                    for driver in drivers
                ):
                    missing.append(f"{requirement.requirement_name or document_type} (expires before return)")
        elif not source_doc.get("documents_complete"):
            missing.append(requirement.requirement_name or document_type)
    return sorted(set(missing))


def validate_required_documents(source_doc):
    missing = get_missing_documents(source_doc)
    if missing:
        frappe.throw(
            _("Required rental documents are incomplete: {0}.").format(", ".join(missing)),
            title=_("Documents Required"),
        )


def _get_driver_docs(source_doc) -> list[dict]:
    """Drivers live directly on Rental Agreement; no Driver master is required."""
    rows = source_doc.get("drivers") or []
    return [
        {
            "full_name": row.get("full_name"),
            "license_attachment": row.get("license_attachment"),
            "passport_attachment": row.get("passport_attachment"),
            "id_attachment": row.get("id_attachment"),
            "license_expiry_date": row.get("license_expiry_date"),
            "passport_expiry_date": row.get("passport_expiry_date"),
            "international_permit_expiry": row.get("international_permit_expiry"),
            "nationality": row.get("nationality"),
        }
        for row in rows
    ]


def _customer_type(customer: str | None) -> str | None:
    if not customer:
        return None
    value = frappe.get_cached_value("Customer", customer, "customer_type")
    return "Company" if value == "Company" else "Individual"


def _driver_country(source_doc) -> str | None:
    drivers = source_doc.get("drivers") or []
    if not drivers:
        return None
    primary = next((row for row in drivers if row.get("primary_driver")), drivers[0])
    return primary.get("nationality")


def _matches(row, context: dict) -> bool:
    for fieldname, actual in context.items():
        expected = row.get(fieldname)
        if expected and str(expected) != str(actual or ""):
            return False
    return True
