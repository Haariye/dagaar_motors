from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from dagaar_motors.utils.constants import ADMIN_ROLES


def get_discount_authority(user: str | None = None, company: str | None = None, branch: str | None = None) -> dict:
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    if roles.intersection(ADMIN_ROLES):
        return {
            "maximum_discount_percent": 100,
            "maximum_fixed_discount": float("inf"),
            "approval_threshold_percent": 100,
            "source": "Administrator",
        }

    rows = frappe.get_all(
        "Discount Authority",
        filters={"enabled": 1},
        fields=[
            "name",
            "user",
            "role",
            "company",
            "branch",
            "priority",
            "maximum_discount_percent",
            "maximum_fixed_discount",
            "approval_threshold_percent",
            "approval_role",
        ],
        order_by="priority desc, modified desc",
    )
    matches = []
    for row in rows:
        if row.user and row.user != user:
            continue
        if row.role and row.role not in roles:
            continue
        if row.company and row.company != company:
            continue
        if row.branch and row.branch != branch:
            continue
        specificity = sum(bool(row.get(field)) for field in ("user", "role", "company", "branch"))
        matches.append((int(row.priority or 0), specificity, row))

    if not matches:
        return {
            "maximum_discount_percent": 0,
            "maximum_fixed_discount": 0,
            "approval_threshold_percent": 0,
            "source": None,
        }
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    row = matches[0][2]
    return {
        "maximum_discount_percent": flt(row.maximum_discount_percent),
        "maximum_fixed_discount": flt(row.maximum_fixed_discount),
        "approval_threshold_percent": flt(row.approval_threshold_percent),
        "approval_role": row.approval_role,
        "source": row.name,
    }


def validate_discount(
    *,
    base_amount: float,
    discount_percent: float = 0,
    fixed_discount: float = 0,
    company: str | None = None,
    branch: str | None = None,
    user: str | None = None,
    approved_by: str | None = None,
) -> dict:
    authority = get_discount_authority(user=user, company=company, branch=branch)
    discount_percent = flt(discount_percent)
    fixed_discount = flt(fixed_discount)
    calculated_fixed = flt(base_amount) * discount_percent / 100
    total_fixed = calculated_fixed + fixed_discount

    exceeds_percent = discount_percent > flt(authority["maximum_discount_percent"])
    exceeds_fixed = total_fixed > flt(authority["maximum_fixed_discount"])
    approval_required = exceeds_percent or exceeds_fixed

    if approval_required and not approved_by:
        frappe.throw(
            _(
                "Discount requires approval. Your limit is {0}% or {1}; requested discount is {2}% / {3}."
            ).format(
                flt(authority["maximum_discount_percent"]),
                frappe.format_value(authority["maximum_fixed_discount"], {"fieldtype": "Currency"}),
                discount_percent,
                frappe.format_value(total_fixed, {"fieldtype": "Currency"}),
            )
        )

    if approved_by:
        approver_roles = set(frappe.get_roles(approved_by))
        required_role = authority.get("approval_role")
        if required_role and required_role not in approver_roles and not approver_roles.intersection(ADMIN_ROLES):
            frappe.throw(_("Approver {0} does not have required role {1}.").format(approved_by, required_role))

    return {
        "discount_amount": total_fixed,
        "approval_required": approval_required,
        "authority": authority,
    }