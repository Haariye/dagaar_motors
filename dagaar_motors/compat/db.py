from __future__ import annotations

from contextlib import contextmanager

import frappe


def lock_document(doctype: str, name: str):
    if not name:
        return None
    rows = frappe.db.sql(
        f"select name from `tab{doctype}` where name = %s for update",  # nosec B608 - table is internal constant
        (name,),
        as_dict=True,
    )
    return rows[0].name if rows else None


@contextmanager
def savepoint(name: str):
    frappe.db.savepoint(name)
    try:
        yield
    except Exception:
        frappe.db.rollback(save_point=name)
        raise


def add_index(doctype: str, fields: list[str], index_name: str | None = None):
    return frappe.db.add_index(doctype, fields, index_name=index_name)