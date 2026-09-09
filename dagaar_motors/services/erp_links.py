from __future__ import annotations

from hashlib import sha256

import frappe

LINK_DOCTYPE = "Dagaar Motors ERP Link"

LEGACY_TO_LINK_FIELD = {
    "dagaar_rental_agreement": "rental_agreement",
    "dagaar_rental_extension": "rental_extension",
    "dagaar_rental_return": "rental_return",
    "dagaar_security_deposit": "security_deposit",
    "dagaar_traffic_fine": "traffic_fine",
    "dagaar_vehicle_damage_report": "vehicle_damage_report",
    "dagaar_motor_vehicle": "motor_vehicle",
    "dagaar_vehicle_sale": "vehicle_sale",
    "dagaar_vehicle_expense": "vehicle_expense",
    "dagaar_maintenance_work_order": "maintenance_work_order",
}
LINK_TO_LEGACY_FIELD = {value: key for key, value in LEGACY_TO_LINK_FIELD.items()}
LINK_FIELDS = tuple(LINK_TO_LEGACY_FIELD)


def set_pending_source_references(doc, **references) -> None:
    clean = {key: value for key, value in references.items() if key in LEGACY_TO_LINK_FIELD and value}
    doc.flags.dagaar_source_references = clean


def persist_source_references(doc, *, source_key: str | None = None) -> str | None:
    references = get_source_references(doc, database_fallback=False)
    if not references or not getattr(doc, "name", None):
        return None
    if not frappe.db.exists("DocType", LINK_DOCTYPE):
        return None

    values = {
        "reference_doctype": doc.doctype,
        "reference_name": doc.name,
        "source_key": source_key,
        "company": doc.get("company") if doc.meta.has_field("company") else None,
    }
    for legacy_field, value in references.items():
        link_field = LEGACY_TO_LINK_FIELD.get(legacy_field)
        if link_field:
            values[link_field] = value

    if not values.get("branch") and values.get("motor_vehicle") and frappe.db.exists("Motor Vehicle", values["motor_vehicle"]):
        values["branch"] = frappe.get_cached_value("Motor Vehicle", values["motor_vehicle"], "branch")
    if not values.get("company") and values.get("motor_vehicle") and frappe.db.exists("Motor Vehicle", values["motor_vehicle"]):
        values["company"] = frappe.get_cached_value("Motor Vehicle", values["motor_vehicle"], "company")

    key = _reference_key(doc.doctype, doc.name)
    existing = frappe.db.get_value(LINK_DOCTYPE, {"reference_key": key}, "name")
    if existing:
        frappe.db.set_value(LINK_DOCTYPE, existing, values, update_modified=False)
        return existing

    link = frappe.get_doc({"doctype": LINK_DOCTYPE, "reference_key": key, **values})
    link.insert(ignore_permissions=True)
    return link.name


def get_source_references(doc_or_doctype, name: str | None = None, *, database_fallback: bool = True) -> dict:
    if isinstance(doc_or_doctype, str):
        doctype = doc_or_doctype
        docname = name
        pending = {}
    else:
        doc = doc_or_doctype
        doctype = doc.doctype
        docname = getattr(doc, "name", None)
        pending = dict(getattr(doc.flags, "dagaar_source_references", {}) or {})
        if pending:
            return pending

    if not database_fallback or not docname or not frappe.db.exists("DocType", LINK_DOCTYPE):
        return pending

    row = frappe.db.get_value(
        LINK_DOCTYPE,
        {"reference_doctype": doctype, "reference_name": docname},
        list(LINK_FIELDS),
        as_dict=True,
    )
    if not row:
        return {}
    return {
        LINK_TO_LEGACY_FIELD[fieldname]: row.get(fieldname)
        for fieldname in LINK_FIELDS
        if row.get(fieldname)
    }


def get_source_reference(doc_or_doctype, fieldname: str, name: str | None = None):
    return get_source_references(doc_or_doctype, name).get(fieldname)


def get_linked_sales_invoice_names(*, rental_agreement: str | None = None, vehicle: str | None = None) -> list[str]:
    if not frappe.db.exists("DocType", LINK_DOCTYPE):
        return []
    filters = {"reference_doctype": "Sales Invoice"}
    if rental_agreement:
        filters["rental_agreement"] = rental_agreement
    if vehicle:
        filters["motor_vehicle"] = vehicle
    return frappe.get_all(LINK_DOCTYPE, filters=filters, pluck="reference_name", limit_page_length=100000)


def get_payment_entry_source_references(doc) -> list[dict]:
    references = []
    seen = set()
    for row in doc.get("references") or []:
        if row.reference_doctype != "Sales Invoice" or not row.reference_name:
            continue
        source = get_source_references("Sales Invoice", row.reference_name)
        identity = tuple(sorted(source.items()))
        if source and identity not in seen:
            seen.add(identity)
            references.append(source)
    return references


def remove_erp_link(doc, method=None) -> None:
    if not getattr(doc, "name", None) or not frappe.db.exists("DocType", LINK_DOCTYPE):
        return
    frappe.db.delete(
        LINK_DOCTYPE,
        {"reference_doctype": doc.doctype, "reference_name": doc.name},
    )


def _reference_key(doctype: str, name: str) -> str:
    return sha256(f"{doctype}\n{name}".encode()).hexdigest()[:40]
