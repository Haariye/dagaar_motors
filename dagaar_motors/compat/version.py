from __future__ import annotations

import re

import frappe


def frappe_version() -> str:
    try:
        from frappe import __version__

        return __version__
    except Exception:
        return "15.0.0"


def major_version() -> int:
    match = re.match(r"(\d+)", frappe_version() or "")
    return int(match.group(1)) if match else 15


def is_v16_or_newer() -> bool:
    return major_version() >= 16


def installed_app_version(app_name: str) -> str | None:
    try:
        versions = frappe.get_attr("frappe.utils.change_log.get_versions")()
        return versions.get(app_name, {}).get("version")
    except Exception:
        return None