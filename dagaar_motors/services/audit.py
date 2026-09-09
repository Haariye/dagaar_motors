from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def append_audit(doc, event: str, details: dict | None = None):
    """Append an explicit audit note without replacing Frappe Version history."""
    payload = {
        "event": event,
        "user": frappe.session.user,
        "timestamp": str(now_datetime()),
        "details": details or {},
    }
    if doc.meta.has_field("audit_log"):
        existing = doc.get("audit_log") or ""
        doc.set("audit_log", (existing + "\n" + json.dumps(payload, default=str)).strip())
    return payload


def append_audit_event(doc, event: str, details: dict | None = None):
    return append_audit(doc, event, details)