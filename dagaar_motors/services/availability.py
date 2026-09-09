from __future__ import annotations

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_datetime

from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.settings import get_settings_dict
from dagaar_motors.utils.constants import (
    AGREEMENT_BLOCKING_STATUSES,
    BLOCKING_VEHICLE_STATUSES,
    MAINTENANCE_BLOCKING_STATUSES,
    RESERVATION_BLOCKING_STATUSES,
    TRANSFER_BLOCKING_STATUSES,
)


def lock_vehicle(vehicle: str):
    if not lock_document("Motor Vehicle", vehicle):
        frappe.throw(_("Vehicle {0} does not exist.").format(vehicle))


def get_conflicts(
    vehicle: str,
    start_datetime,
    end_datetime,
    *,
    exclude_doctype: str | None = None,
    exclude_name: str | None = None,
    exclude_documents: dict[str, str | list[str] | tuple[str, ...] | set[str]] | None = None,
    include_vehicle_state: bool = True,
) -> list[dict]:
    start = get_datetime(start_datetime)
    end = get_datetime(end_datetime)
    if not start or not end or end <= start:
        frappe.throw(_("Availability end date and time must be later than start date and time."))

    exclusions = _normalize_exclusions(exclude_doctype, exclude_name, exclude_documents)
    conflicts: list[dict] = []
    if include_vehicle_state:
        vehicle_row = frappe.db.get_value(
            "Motor Vehicle",
            vehicle,
            ["status", "rentable", "available_from", "current_rental_agreement"],
            as_dict=True,
        )
        if not vehicle_row:
            return [{"doctype": "Motor Vehicle", "name": vehicle, "reason": "Vehicle does not exist"}]
        if not vehicle_row.rentable:
            conflicts.append({"doctype": "Motor Vehicle", "name": vehicle, "status": vehicle_row.status, "reason": "Vehicle is not marked rentable"})
        if vehicle_row.status in BLOCKING_VEHICLE_STATUSES or vehicle_row.status == "For Sale":
            allow_current = _state_belongs_to_excluded_source(vehicle, vehicle_row, exclusions)
            if not allow_current:
                conflicts.append(
                    {
                        "doctype": "Motor Vehicle",
                        "name": vehicle,
                        "status": vehicle_row.status,
                        "reason": f"Vehicle status is {vehicle_row.status}",
                        "start": vehicle_row.available_from,
                    }
                )

    conflicts.extend(_reservation_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    conflicts.extend(_agreement_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    conflicts.extend(_maintenance_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    conflicts.extend(_block_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    conflicts.extend(_transfer_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    conflicts.extend(_sale_conflicts(vehicle, start, end, exclude_doctype, exclude_name))
    return [
        row for row in conflicts
        if row.get("name") not in exclusions.get(row.get("doctype"), set())
    ]


def assert_available(
    vehicle: str,
    start_datetime,
    end_datetime,
    *,
    exclude_doctype: str | None = None,
    exclude_name: str | None = None,
    exclude_documents: dict[str, str | list[str] | tuple[str, ...] | set[str]] | None = None,
    lock: bool = True,
):
    if lock:
        lock_vehicle(vehicle)
    conflicts = get_conflicts(
        vehicle,
        start_datetime,
        end_datetime,
        exclude_doctype=exclude_doctype,
        exclude_name=exclude_name,
        exclude_documents=exclude_documents,
    )
    if conflicts:
        first = conflicts[0]
        period = _format_period(first.get("start"), first.get("end"))
        reason = first.get("reason") or f"conflicting {first.get('doctype')} {first.get('name')}"
        frappe.throw(
            _("Vehicle {0} is unavailable{1}: {2}.").format(
                vehicle,
                f" {period}" if period else "",
                reason,
            ),
            title=_("Vehicle Unavailable"),
        )
    return True


def get_available_vehicles(
    *,
    company: str,
    branch: str | list[str] | tuple[str, ...] | None,
    vehicle_category: str | None,
    rental_type: str | None,
    start_datetime,
    end_datetime,
    limit: int = 100,
) -> list[dict]:
    filters: dict = {"company": company, "rentable": 1, "status": ["in", ["Available", "Reserved"]]}
    if branch:
        filters["branch"] = ["in", list(branch)] if isinstance(branch, (list, tuple, set)) else branch
    if vehicle_category:
        filters["category"] = vehicle_category
    rows = frappe.get_all(
        "Motor Vehicle",
        filters=filters,
        fields=[
            "name",
            "vehicle_title",
            "license_plate",
            "brand",
            "model",
            "model_year",
            "category",
            "branch",
            "status",
            "current_odometer",
            "base_daily_rate",
            "vehicle_image",
        ],
        order_by="status asc, vehicle_title asc",
        limit_page_length=max(1, min(int(limit or 100), 500)),
    )
    available = []
    for row in rows:
        if rental_type and not _vehicle_allows_rental_type(row.name, rental_type):
            continue
        if not get_conflicts(row.name, start_datetime, end_datetime, include_vehicle_state=False):
            available.append(row)
    return available


def _reservation_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    rows = frappe.db.sql(
        """
        select name, status, pickup_datetime as start, return_datetime as end
        from `tabRental Reservation`
        where vehicle = %(vehicle)s
          and status in %(statuses)s
          and pickup_datetime < %(end)s
          and return_datetime > %(start)s
          and not (%(exclude_doctype)s = 'Rental Reservation' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "statuses": tuple(RESERVATION_BLOCKING_STATUSES),
            "start": start,
            "end": end,
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Rental Reservation", row) for row in rows]


def _agreement_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    rows = frappe.db.sql(
        """
        select name, status, pickup_datetime as start, expected_return_datetime as end
        from `tabRental Agreement`
        where vehicle = %(vehicle)s
          and docstatus < 2
          and status in %(statuses)s
          and pickup_datetime < %(end)s
          and expected_return_datetime > %(start)s
          and not (%(exclude_doctype)s = 'Rental Agreement' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "statuses": tuple(AGREEMENT_BLOCKING_STATUSES),
            "start": start,
            "end": end,
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Rental Agreement", row) for row in rows]


def _maintenance_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    rows = frappe.db.sql(
        """
        select name, status, planned_start as start, coalesce(planned_end, actual_end, planned_start) as end
        from `tabVehicle Maintenance`
        where vehicle = %(vehicle)s
          and docstatus < 2
          and status in %(statuses)s
          and planned_start < %(end)s
          and coalesce(planned_end, actual_end, planned_start) > %(start)s
          and not (%(exclude_doctype)s = 'Vehicle Maintenance' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "statuses": tuple(MAINTENANCE_BLOCKING_STATUSES),
            "start": start,
            "end": end,
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Vehicle Maintenance", row) for row in rows]


def _block_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    rows = frappe.db.sql(
        """
        select name, status, from_datetime as start, to_datetime as end, reason
        from `tabVehicle Block`
        where vehicle = %(vehicle)s
          and status = 'Active'
          and from_datetime < %(end)s
          and (to_datetime is null or to_datetime > %(start)s)
          and not (%(exclude_doctype)s = 'Vehicle Block' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "start": start,
            "end": end,
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Vehicle Block", row, row.reason) for row in rows]


def _transfer_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    rows = frappe.db.sql(
        """
        select name, status, departure_datetime as start, coalesce(actual_arrival_datetime, arrival_datetime) as end
        from `tabVehicle Transfer`
        where vehicle = %(vehicle)s
          and docstatus < 2
          and status in %(statuses)s
          and departure_datetime < %(end)s
          and coalesce(actual_arrival_datetime, arrival_datetime) > %(start)s
          and not (%(exclude_doctype)s = 'Vehicle Transfer' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "statuses": tuple(TRANSFER_BLOCKING_STATUSES),
            "start": start,
            "end": end,
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Vehicle Transfer", row) for row in rows]


def _sale_conflicts(vehicle, start, end, exclude_doctype, exclude_name):
    settings = get_settings_dict()
    if not settings.get("block_sale_for_future_reservations"):
        return []
    rows = frappe.db.sql(
        """
        select name, status, sale_date as start, sale_date as end
        from `tabVehicle Sale`
        where vehicle = %(vehicle)s
          and docstatus < 2
          and status in ('Approved', 'Invoiced', 'Delivered')
          and sale_date is not null
          and sale_date <= %(end_date)s
          and not (%(exclude_doctype)s = 'Vehicle Sale' and name = %(exclude_name)s)
        """,
        {
            "vehicle": vehicle,
            "end_date": end.date(),
            "exclude_doctype": exclude_doctype or "",
            "exclude_name": exclude_name or "",
        },
        as_dict=True,
    )
    return [_conflict("Vehicle Sale", row, "Vehicle has an approved sale") for row in rows]


def _normalize_exclusions(exclude_doctype, exclude_name, exclude_documents):
    exclusions: dict[str, set[str]] = {}
    if exclude_doctype and exclude_name:
        exclusions.setdefault(exclude_doctype, set()).add(str(exclude_name))
    for doctype, names in (exclude_documents or {}).items():
        if not names:
            continue
        values = names if isinstance(names, (list, tuple, set)) else [names]
        exclusions.setdefault(doctype, set()).update(str(name) for name in values if name)
    return exclusions


def _state_belongs_to_excluded_source(vehicle, vehicle_row, exclusions) -> bool:
    if vehicle_row.status == "Rented":
        return bool(
            vehicle_row.current_rental_agreement
            and vehicle_row.current_rental_agreement in exclusions.get("Rental Agreement", set())
        )
    if vehicle_row.status == "Reserved":
        reservation_names = exclusions.get("Rental Reservation", set())
        if not reservation_names:
            return False
        return bool(
            frappe.db.exists(
                "Rental Reservation",
                {
                    "name": ["in", list(reservation_names)],
                    "vehicle": vehicle,
                    "status": ["in", list(RESERVATION_BLOCKING_STATUSES)],
                },
            )
        )
    return False


def _vehicle_allows_rental_type(vehicle: str, rental_type: str) -> bool:
    count = frappe.db.count("Vehicle Rental Type", {"parent": vehicle, "parenttype": "Motor Vehicle", "active": 1})
    if not count:
        return True
    return bool(
        frappe.db.exists(
            "Vehicle Rental Type",
            {"parent": vehicle, "parenttype": "Motor Vehicle", "rental_type": rental_type, "active": 1},
        )
    )


def _conflict(doctype: str, row, reason: str | None = None):
    return {
        "doctype": doctype,
        "name": row.name,
        "status": row.status,
        "start": row.start,
        "end": row.end,
        "reason": reason or f"{doctype} {row.name} is {row.status}",
    }


def _format_period(start, end):
    if not start:
        return ""
    start_dt = get_datetime(start)
    end_dt = get_datetime(end) if end else None
    if end_dt and end_dt != start_dt:
        return f"from {start_dt:%d %b %Y %H:%M} until {end_dt:%d %b %Y %H:%M}"
    return f"on {start_dt:%d %b %Y}"