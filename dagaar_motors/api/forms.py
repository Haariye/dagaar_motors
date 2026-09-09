from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import require_app_access
from dagaar_motors.services.form_defaults import (
    get_agreement_defaults,
    get_branch_defaults,
    get_customer_defaults,
    get_vehicle_defaults,
)


@frappe.whitelist()
def customer(customer):
    require_app_access()
    return get_customer_defaults(customer)


@frappe.whitelist()
def branch(branch):
    require_app_access()
    return get_branch_defaults(branch)


@frappe.whitelist()
def vehicle(vehicle):
    require_app_access()
    return get_vehicle_defaults(vehicle)


@frappe.whitelist()
def agreement(agreement):
    require_app_access()
    return get_agreement_defaults(agreement)
