from __future__ import annotations

import frappe
from frappe import _

from dagaar_motors.utils.constants import ADMIN_ROLES, APP_ROLES


def _roles(user: str | None = None) -> set[str]:
    return set(frappe.get_roles(user or frappe.session.user))


def can_access_app(user: str | None = None) -> bool:
    roles = _roles(user)
    return bool(roles.intersection(set(APP_ROLES) | ADMIN_ROLES))


def require_app_access(user: str | None = None):
    if not can_access_app(user):
        frappe.throw("You do not have access to Dagaar Motors.", frappe.PermissionError)


def require_any_role(*required_roles: str, user: str | None = None):
    user_roles = _roles(user)
    if user_roles.intersection(ADMIN_ROLES):
        return
    if not user_roles.intersection(set(required_roles)):
        frappe.throw(
            f"This action requires one of these roles: {', '.join(required_roles)}.",
            frappe.PermissionError,
        )


def _allowed_values(
    allow: str,
    user: str | None = None,
    *,
    applicable_for: str | None = None,
) -> list[str]:
    """Return allowed values using Frappe's global + target-specific semantics.

    When ``applicable_for`` is supplied, globally applicable permissions and
    permissions for that DocType are combined. Aggregate APIs deliberately use
    every explicit permission so a targeted restriction is never ignored.
    """
    user = user or frappe.session.user
    rows = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": allow},
        fields=["for_value", "applicable_for"],
        order_by="creation asc",
    )
    values: list[str] = []
    for row in rows:
        target = row.applicable_for or None
        if applicable_for and target not in (None, applicable_for):
            continue
        if row.for_value and row.for_value not in values:
            values.append(row.for_value)
    return values


def get_permission_scope(
    user: str | None = None,
    *,
    applicable_for: str | None = None,
) -> dict[str, list[str]]:
    """Return explicit Company and Motor Branch restrictions for the user.

    Empty lists mean the role is not restricted by a matching User Permission.
    Administrators are always unrestricted.
    """
    user = user or frappe.session.user
    if _roles(user).intersection(ADMIN_ROLES):
        return {"companies": [], "branches": []}
    return {
        "companies": _allowed_values("Company", user, applicable_for=applicable_for),
        "branches": _allowed_values("Motor Branch", user, applicable_for=applicable_for),
    }


def enforce_company_branch(
    company: str | None = None,
    branch: str | None = None,
    user: str | None = None,
    *,
    applicable_for: str | None = None,
):
    """Apply report/API scope checks in addition to normal DocType permissions."""
    user = user or frappe.session.user
    require_app_access(user)
    scope = get_permission_scope(user, applicable_for=applicable_for)
    if company and scope["companies"] and company not in scope["companies"]:
        frappe.throw(_("You are not permitted to access Company {0}.").format(company), frappe.PermissionError)
    if branch and scope["branches"] and branch not in scope["branches"]:
        frappe.throw(_("You are not permitted to access Branch {0}.").format(branch), frappe.PermissionError)
    if company and branch:
        branch_company = frappe.get_cached_value("Motor Branch", branch, "company")
        if branch_company and branch_company != company:
            frappe.throw(_("Branch {0} does not belong to Company {1}.").format(branch, company))
    return scope


def enforce_document_scope(
    doctype: str,
    name: str,
    *,
    company_field: str = "company",
    branch_field: str = "branch",
    user: str | None = None,
):
    """Validate an existing document against explicit Company/Branch restrictions."""
    meta = frappe.get_meta(doctype)
    fields = [field for field in (company_field, branch_field) if field and meta.has_field(field)]
    if not frappe.db.exists(doctype, name):
        frappe.throw(_("{0} {1} does not exist.").format(doctype, name))
    values = frappe.db.get_value(doctype, name, fields, as_dict=True) if fields else frappe._dict()
    company = values.get(company_field) if company_field else None
    branch = values.get(branch_field) if branch_field else None
    enforce_company_branch(company, branch, user=user, applicable_for=doctype)
    return values


def enforce_vehicle_scope(vehicle: str, user: str | None = None):
    return enforce_document_scope("Motor Vehicle", vehicle, user=user)


def _query_field_condition(doctype: str, fieldname: str, values: list[str]) -> str:
    if not values or not frappe.get_meta(doctype).has_field(fieldname):
        return ""
    escaped = ", ".join(frappe.db.escape(value) for value in values)
    return f"`tab{doctype}`.`{fieldname}` in ({escaped})"


def branch_query_conditions(user: str | None = None, *, doctype: str) -> str:
    user = user or frappe.session.user
    if _roles(user).intersection(ADMIN_ROLES):
        return ""
    conditions = []
    branch_condition = _query_field_condition(
        doctype, "branch", _allowed_values("Motor Branch", user, applicable_for=doctype)
    )
    company_condition = _query_field_condition(
        doctype, "company", _allowed_values("Company", user, applicable_for=doctype)
    )
    if branch_condition:
        conditions.append(branch_condition)
    if company_condition:
        conditions.append(company_condition)
    return " and ".join(conditions)


def vehicle_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Motor Vehicle")


def reservation_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Rental Reservation")


def agreement_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Rental Agreement")


def return_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Rental Return")


def deposit_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Security Deposit")


def maintenance_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Vehicle Maintenance")


def sale_query_conditions(user: str | None = None) -> str:
    return branch_query_conditions(user=user, doctype="Vehicle Sale")


def has_branch_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    user = user or frappe.session.user
    roles = _roles(user)
    if roles.intersection(ADMIN_ROLES):
        return True
    if not roles.intersection(set(APP_ROLES)):
        return False
    allowed_branches = _allowed_values("Motor Branch", user, applicable_for=doc.doctype)
    allowed_companies = _allowed_values("Company", user, applicable_for=doc.doctype)
    if allowed_branches and getattr(doc, "branch", None) not in allowed_branches:
        return False
    if allowed_companies and getattr(doc, "company", None) not in allowed_companies:
        return False
    return True