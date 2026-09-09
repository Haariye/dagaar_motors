from __future__ import annotations

import hashlib
import json

import frappe


def make_key(action: str, source_doctype: str, source_name: str, payload: dict | None = None) -> str:
    raw = json.dumps(
        {
            "action": action,
            "source_doctype": source_doctype,
            "source_name": source_name,
            "payload": payload or {},
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def find_existing(doctype: str, key: str) -> str | None:
    if not frappe.db.exists("DocType", doctype) or not frappe.get_meta(doctype).has_field("idempotency_key"):
        return None
    return frappe.db.get_value(doctype, {"idempotency_key": key, "docstatus": ["<", 2]}, "name")


def stamp(doc, key: str):
    if doc.meta.has_field("idempotency_key"):
        doc.idempotency_key = key


def ensure_idempotency_key(doc, action: str, payload: dict | None = None) -> str | None:
    if not doc.meta.has_field("idempotency_key"):
        return None
    if doc.get("idempotency_key"):
        return doc.idempotency_key
    source_name = doc.name if doc.name and not str(doc.name).startswith("new-") else "unsaved"
    stable_payload = payload or {
        fieldname: doc.get(fieldname)
        for fieldname in (
            "company",
            "branch",
            "customer",
            "vehicle",
            "reservation",
            "rental_agreement",
            "pickup_datetime",
            "return_datetime",
            "expected_return_datetime",
        )
        if doc.meta.has_field(fieldname)
    }
    key = make_key(action, doc.doctype, source_name, stable_payload)
    stamp(doc, key)
    return key