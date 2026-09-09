from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate

from dagaar_motors.services.analytics import get_operations_board
from dagaar_motors.services.maintenance import generate_due_maintenance
from dagaar_motors.services.settings import get_settings_dict


def mark_overdue_rentals():
    now = now_datetime()
    rows = frappe.get_all(
        "Rental Agreement",
        filters={"docstatus": 1, "status": ["in", ["Active", "Extended"]], "expected_return_datetime": ["<", now]},
        pluck="name",
        limit_page_length=10000,
    )
    for name in rows:
        frappe.db.set_value(
            "Rental Agreement",
            name,
            {"status": "Overdue", "status_reason": f"Expected return passed at {now}"},
            update_modified=True,
        )


def refresh_operational_alerts():
    settings = get_settings_dict()
    company = settings.get("default_company")
    if not company:
        return
    try:
        frappe.cache.set_value(
            f"dagaar_motors:operations:{company}",
            get_operations_board(company=company, branch=settings.get("default_branch")),
            expires_in_sec=3600,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Dagaar Motors operational dashboard cache")


def generate_maintenance_due():
    generate_due_maintenance()


def send_expiry_notifications():
    settings = get_settings_dict()
    recipients = _notification_users()
    if not recipients:
        return
    today = getdate(nowdate())
    _notify_expiries(
        "Vehicle Document",
        "expiry_date",
        today,
        int(settings.get("document_expiry_days") or 30),
        recipients,
        "Vehicle document expiry",
        ["vehicle", "document_type", "document_number"],
    )
    _notify_expiries(
        "Vehicle Insurance",
        "expiry_date",
        today,
        int(settings.get("insurance_expiry_days") or 30),
        recipients,
        "Vehicle insurance expiry",
        ["vehicle", "policy_number"],
    )
    _notify_driver_expiries(today, int(settings.get("document_expiry_days") or 30), recipients)


def create_utilization_snapshot(snapshot_date=None):
    snapshot_date = getdate(snapshot_date or add_days(nowdate(), -1))
    start = datetime.combine(snapshot_date, time.min)
    end = start + timedelta(days=1)
    vehicles = frappe.get_all(
        "Motor Vehicle",
        filters={"status": ["not in", ["Sold", "Retired"]]},
        fields=["name", "company", "branch", "status"],
        limit_page_length=100000,
    )
    for vehicle in vehicles:
        hours = _classified_hours(vehicle.name, start, end)
        total_available = max(0, 24 - hours["rented"] - hours["maintenance"] - hours["blocked"])
        values = {
            "snapshot_date": snapshot_date,
            "company": vehicle.company,
            "branch": vehicle.branch,
            "vehicle": vehicle.name,
            "status": vehicle.status,
            "available_hours": total_available,
            "rented_hours": hours["rented"],
            "maintenance_hours": hours["maintenance"],
            "blocked_hours": hours["blocked"],
            "utilization_percent": hours["rented"] / 24 * 100,
        }
        existing = frappe.db.get_value(
            "Utilization Snapshot", {"snapshot_date": snapshot_date, "vehicle": vehicle.name}, "name"
        )
        if existing:
            frappe.db.set_value("Utilization Snapshot", existing, values, update_modified=False)
        else:
            frappe.get_doc({"doctype": "Utilization Snapshot", **values}).insert(ignore_permissions=True)


def _classified_hours(vehicle: str, start: datetime, end: datetime) -> dict:
    intervals: list[tuple[datetime, datetime, str]] = []
    agreement_rows = frappe.get_all(
        "Rental Agreement",
        filters={
            "vehicle": vehicle,
            "docstatus": 1,
            "pickup_datetime": ["<", end],
            "expected_return_datetime": [">", start],
            "status": ["not in", ["Cancelled"]],
        },
        fields=["pickup_datetime", "actual_return_datetime", "expected_return_datetime"],
    )
    for row in agreement_rows:
        intervals.append((get_datetime(row.pickup_datetime), get_datetime(row.actual_return_datetime or row.expected_return_datetime), "rented"))
    maintenance_rows = frappe.get_all(
        "Vehicle Maintenance",
        filters={"vehicle": vehicle, "docstatus": ["<", 2], "planned_start": ["<", end], "planned_end": [">", start], "status": ["in", ["Scheduled", "In Progress", "Quality Check", "Completed"]]},
        fields=["planned_start", "planned_end", "actual_start", "actual_end"],
    )
    for row in maintenance_rows:
        intervals.append((get_datetime(row.actual_start or row.planned_start), get_datetime(row.actual_end or row.planned_end), "maintenance"))
    block_rows = frappe.get_all(
        "Vehicle Block",
        filters={"vehicle": vehicle, "from_datetime": ["<", end], "status": ["in", ["Active", "Released"]]},
        fields=["from_datetime", "to_datetime", "released_on"],
    )
    for row in block_rows:
        block_end = get_datetime(row.released_on or row.to_datetime or end)
        if block_end > start:
            intervals.append((get_datetime(row.from_datetime), block_end, "blocked"))
    boundaries = {start, end}
    normalized = []
    for interval_start, interval_end, kind in intervals:
        clipped_start = max(start, interval_start)
        clipped_end = min(end, interval_end)
        if clipped_end > clipped_start:
            boundaries.update((clipped_start, clipped_end))
            normalized.append((clipped_start, clipped_end, kind))
    points = sorted(boundaries)
    totals = {"rented": 0.0, "maintenance": 0.0, "blocked": 0.0}
    priority = ("rented", "maintenance", "blocked")
    for left, right in zip(points, points[1:]):
        active = {kind for item_start, item_end, kind in normalized if item_start < right and item_end > left}
        chosen = next((kind for kind in priority if kind in active), None)
        if chosen:
            totals[chosen] += (right - left).total_seconds() / 3600
    return totals


def _notification_users() -> list[str]:
    roles = [
        "Dagaar Motors Administrator",
        "Dagaar Motors Fleet Manager",
        "Dagaar Motors Maintenance Manager",
        "Dagaar Motors Branch Manager",
    ]
    users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", roles], "parenttype": "User"},
        pluck="parent",
        limit_page_length=10000,
    )
    enabled = frappe.get_all("User", filters={"name": ["in", users or [""]], "enabled": 1}, pluck="name")
    return sorted(set(enabled))



def _notify_driver_expiries(today, lead_days, recipients):
    """Notify from inline Rental Agreement drivers; no persistent Driver master is required."""
    deadline = add_days(today, lead_days)
    rows = frappe.get_all(
        "Rental Agreement Driver",
        filters={"license_expiry_date": ["between", [today, deadline]], "parenttype": "Rental Agreement"},
        fields=["name", "parent", "full_name", "license_number", "license_expiry_date"],
        limit_page_length=10000,
    )
    for row in rows:
        agreement = frappe.db.get_value(
            "Rental Agreement", row.parent, ["docstatus", "status"], as_dict=True
        )
        if not agreement or agreement.docstatus == 2 or agreement.status == "Cancelled":
            continue
        key = f"motors-driver-expiry:{row.name}:{row.license_expiry_date}"
        if frappe.cache.get_value(key):
            continue
        details = " · ".join(value for value in (row.full_name, row.license_number) if value)
        for user in recipients:
            try:
                frappe.get_doc(
                    {
                        "doctype": "Notification Log",
                        "subject": f"Driving license expiry: {details}",
                        "email_content": f"Driver {row.full_name} on Rental Agreement {row.parent} has a license expiring on {row.license_expiry_date}.",
                        "for_user": user,
                        "type": "Alert",
                        "document_type": "Rental Agreement",
                        "document_name": row.parent,
                    }
                ).insert(ignore_permissions=True)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Motors driver expiry notification: {row.parent}")
        frappe.cache.set_value(key, 1, expires_in_sec=60 * 60 * 24 * 45)

def _notify_expiries(doctype, date_field, today, lead_days, recipients, subject, detail_fields):
    deadline = add_days(today, lead_days)
    fields = ["name", date_field, *detail_fields]
    rows = frappe.get_all(
        doctype,
        filters={date_field: ["between", [today, deadline]]},
        fields=fields,
        limit_page_length=10000,
    )
    for row in rows:
        key = f"dagaar-expiry:{doctype}:{row.name}:{row.get(date_field)}"
        if frappe.cache.get_value(key):
            continue
        details = " · ".join(str(row.get(field)) for field in detail_fields if row.get(field))
        for user in recipients:
            try:
                frappe.get_doc(
                    {
                        "doctype": "Notification Log",
                        "subject": f"{subject}: {details}",
                        "email_content": f"{doctype} {row.name} expires on {row.get(date_field)}.",
                        "for_user": user,
                        "type": "Alert",
                        "document_type": doctype,
                        "document_name": row.name,
                    }
                ).insert(ignore_permissions=True)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Dagaar Motors expiry notification: {doctype} {row.name}")
        frappe.cache.set_value(key, 1, expires_in_sec=60 * 60 * 24 * 45)