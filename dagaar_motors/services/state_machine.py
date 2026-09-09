from __future__ import annotations

import frappe
from frappe import _

from dagaar_motors.services.audit import append_audit
from dagaar_motors.utils.constants import RENTAL_AGREEMENT_TRANSITIONS, VEHICLE_TRANSITIONS


def assert_transition(current: str, target: str, transitions: dict[str, set[str]], label: str):
    if current == target:
        return
    allowed = transitions.get(current, set())
    if target not in allowed:
        frappe.throw(_("{0} cannot move from {1} to {2}.").format(label, current, target))


def validate_transition(current: str, target: str, transitions: dict[str, set[str]], label: str):
    return assert_transition(current, target, transitions, label)


def transition_vehicle(vehicle, target: str, reason: str | None = None):
    doc = frappe.get_doc("Motor Vehicle", vehicle) if isinstance(vehicle, str) else vehicle
    current = doc.status or "Preparation"
    assert_transition(current, target, VEHICLE_TRANSITIONS, _("Vehicle {0}").format(doc.name))
    doc.status = target
    if doc.meta.has_field("status_reason"):
        doc.status_reason = reason
    append_audit(doc, "vehicle_status", {"from": current, "to": target, "reason": reason})
    doc.save(ignore_permissions=True)
    return doc


def transition_agreement(agreement, target: str, reason: str | None = None):
    doc = frappe.get_doc("Rental Agreement", agreement) if isinstance(agreement, str) else agreement
    current = doc.status or "Draft"
    assert_transition(current, target, RENTAL_AGREEMENT_TRANSITIONS, _("Rental Agreement {0}").format(doc.name))
    doc.status = target
    if doc.meta.has_field("status_reason"):
        doc.status_reason = reason
    append_audit(doc, "rental_status", {"from": current, "to": target, "reason": reason})
    doc.save(ignore_permissions=True)
    return doc