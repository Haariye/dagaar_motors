from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from dagaar_motors.api.permissions import enforce_company_branch, require_app_access
from dagaar_motors.services.settings import resolve_company


def get_management_dashboard(
    company: str | None = None,
    branch: str | None = None,
    from_date=None,
    to_date=None,
) -> dict:
    require_app_access()
    company = resolve_company(company)
    scope = enforce_company_branch(company, branch)
    branch_filter = branch or (["in", scope["branches"]] if scope["branches"] else None)
    to_date = getdate(to_date or nowdate())
    from_date = getdate(from_date or add_days(to_date, -365))
    vehicle_filters = {"company": company}
    if branch_filter:
        vehicle_filters["branch"] = branch_filter

    status_rows = frappe.get_all(
        "Motor Vehicle",
        filters=vehicle_filters,
        fields=["status", "count(name) as count"],
        group_by="status",
    )
    status_counts = {row.status: int(row.count or 0) for row in status_rows}
    fleet_size = sum(status_counts.values())

    invoice_conditions = [
        "si.docstatus = 1",
        "si.company = %(company)s",
        "si.posting_date between %(from_date)s and %(to_date)s",
        "dl.reference_doctype = 'Sales Invoice'",
        "coalesce(dl.motor_vehicle, '') != ''",
    ]
    invoice_params = {"company": company, "from_date": from_date, "to_date": to_date}
    if branch_filter:
        vehicles = frappe.get_all("Motor Vehicle", filters=vehicle_filters, pluck="name")
        if vehicles:
            placeholders = []
            for index, vehicle in enumerate(vehicles):
                key = f"dashboard_vehicle_{index}"
                invoice_params[key] = vehicle
                placeholders.append(f"%({key})s")
            invoice_conditions.append(f"dl.motor_vehicle in ({', '.join(placeholders)})")
        else:
            invoice_conditions.append("1 = 0")

    invoices = frappe.db.sql(
        f"""
        select
            si.posting_date,
            si.base_net_total,
            si.base_grand_total,
            si.outstanding_amount,
            dl.motor_vehicle as dagaar_motor_vehicle,
            dl.vehicle_sale as dagaar_vehicle_sale,
            dl.rental_extension as dagaar_rental_extension
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        where {' and '.join(invoice_conditions)}
        order by si.posting_date asc
        """,
        invoice_params,
        as_dict=True,
    )
    rental_revenue = sum(flt(row.base_net_total) for row in invoices if not row.dagaar_vehicle_sale)
    sales_revenue = sum(flt(row.base_net_total) for row in invoices if row.dagaar_vehicle_sale)
    outstanding = sum(flt(row.outstanding_amount) for row in invoices)

    held_deposits = flt(
        frappe.db.sql(
            """
            select coalesce(sum(pe.unallocated_amount), 0)
            from `tabPayment Entry` pe
            inner join `tabRental Agreement` ra on ra.deposit_payment_entry = pe.name
            where pe.docstatus = 1 and pe.company = %(company)s
            """,
            {"company": company},
        )[0][0]
    )
    maintenance_cost = _sum_value(
        "Maintenance Work Order",
        "grand_total",
        {"company": company, "docstatus": 1, **({"branch": branch_filter} if branch_filter else {})},
    )
    operating_cost = _sum_value(
        "Vehicle Expense",
        "amount",
        {"company": company, "docstatus": 1, **({"branch": branch_filter} if branch_filter else {})},
    )
    utilization = _average_value(
        "Utilization Snapshot",
        "utilization_percent",
        {
            "company": company,
            "snapshot_date": ["between", [from_date, to_date]],
            **({"branch": branch_filter} if branch_filter else {}),
        },
    )
    active_filter = {"company": company, "docstatus": 1, **({"branch": branch_filter} if branch_filter else {})}
    today = getdate(nowdate())
    pickups = frappe.db.count(
        "Rental Agreement",
        {**active_filter, "pickup_datetime": ["between", [today, add_days(today, 1)]], "status": ["in", ["Ready for Pickup", "Reserved"]]},
    )
    returns = frappe.db.count(
        "Rental Agreement",
        {**active_filter, "expected_return_datetime": ["between", [today, add_days(today, 1)]], "status": ["in", ["Active", "Extended", "Overdue"]]},
    )
    overdue = frappe.db.count("Rental Agreement", {**active_filter, "status": "Overdue"})
    available = status_counts.get("Available", 0)
    active_rentals = status_counts.get("Rented", 0)
    average_daily_rate = rental_revenue / max(
        1,
        _sum_value(
            "Rental Agreement",
            "duration_units",
            {"company": company, "docstatus": 1, "status": ["in", ["Completed", "Closed"]], **({"branch": branch_filter} if branch_filter else {})},
        ),
    )

    return {
        "filters": {"company": company, "branch": branch, "from_date": from_date, "to_date": to_date},
        "kpis": {
            "fleet_size": fleet_size,
            "available_vehicles": available,
            "reserved_vehicles": status_counts.get("Reserved", 0),
            "active_rentals": active_rentals,
            "overdue_rentals": overdue,
            "maintenance_vehicles": status_counts.get("Maintenance", 0),
            "blocked_vehicles": status_counts.get("Blocked", 0),
            "vehicles_for_sale": status_counts.get("For Sale", 0),
            "sold_vehicles": status_counts.get("Sold", 0),
            "todays_pickups": pickups,
            "todays_returns": returns,
            "rental_revenue": rental_revenue,
            "sales_revenue": sales_revenue,
            "outstanding_receivables": outstanding,
            "deposits_held": held_deposits,
            "maintenance_cost": maintenance_cost,
            "fleet_profit": rental_revenue + sales_revenue - maintenance_cost - operating_cost,
            "utilization_percent": utilization,
            "average_daily_rate": average_daily_rate,
        },
        "charts": {
            "revenue_by_month": _revenue_by_month(invoices),
            "fleet_status": [{"label": key, "value": value} for key, value in sorted(status_counts.items())],
            "top_vehicles": _top_vehicles(invoices),
            "branch_performance": _branch_performance(company, from_date, to_date, branch_filter),
        },
        "operations": get_operations_board(company=company, branch=branch),
    }


def get_operations_board(company: str | None = None, branch: str | None = None) -> dict:
    require_app_access()
    company = resolve_company(company)
    scope = enforce_company_branch(company, branch)
    branch_filter = branch or (["in", scope["branches"]] if scope["branches"] else None)
    common = {"company": company, **({"branch": branch_filter} if branch_filter else {})}
    today = getdate(nowdate())
    tomorrow = add_days(today, 1)
    agreement_fields = [
        "name",
        "customer",
        "vehicle",
        "pickup_datetime",
        "expected_return_datetime",
        "status",
        "branch",
    ]
    return {
        "pickups": frappe.get_all(
            "Rental Agreement",
            filters={**common, "docstatus": ["<", 2], "pickup_datetime": ["between", [today, tomorrow]], "status": ["in", ["Reserved", "Ready for Pickup"]]},
            fields=agreement_fields,
            order_by="pickup_datetime asc",
            limit_page_length=50,
        ),
        "returns": frappe.get_all(
            "Rental Agreement",
            filters={**common, "docstatus": 1, "expected_return_datetime": ["between", [today, tomorrow]], "status": ["in", ["Active", "Extended", "Overdue"]]},
            fields=agreement_fields,
            order_by="expected_return_datetime asc",
            limit_page_length=50,
        ),
        "overdue": frappe.get_all(
            "Rental Agreement",
            filters={**common, "docstatus": 1, "status": "Overdue"},
            fields=agreement_fields,
            order_by="expected_return_datetime asc",
            limit_page_length=50,
        ),
        "extensions_pending": frappe.get_all(
            "Rental Extension",
            filters={**common, "docstatus": 0, "status": ["in", ["Draft", "Awaiting Approval"]]},
            fields=["name", "rental_agreement", "vehicle", "new_end_datetime", "grand_total", "status"],
            order_by="new_end_datetime asc",
            limit_page_length=50,
        ),
        "deposits_pending": frappe.get_all(
            "Rental Agreement",
            filters={**common, "docstatus": ["<", 2], "deposit_required": [">", 0], "deposit_payment_entry": ["is", "not set"], "deposit_waived": 0},
            fields=["name", "customer", "vehicle", "deposit_required", "status"],
            order_by="modified desc",
            limit_page_length=50,
        ),
        "maintenance": frappe.get_all(
            "Vehicle Maintenance",
            filters={**common, "docstatus": ["<", 2], "status": ["in", ["Due", "Scheduled", "In Progress", "Quality Check"]]},
            fields=["name", "vehicle", "maintenance_type", "due_date", "planned_start", "status"],
            order_by="due_date asc, planned_start asc",
            limit_page_length=50,
        ),
        "available_fleet": frappe.get_all(
            "Motor Vehicle",
            filters={**common, "status": "Available", "rentable": 1},
            fields=["name", "vehicle_title", "license_plate", "category", "branch", "current_odometer", "vehicle_image"],
            order_by="vehicle_title asc",
            limit_page_length=100,
        ),
    }


def get_vehicle_summary(vehicle: str) -> dict:
    require_app_access()
    doc = frappe.get_doc("Motor Vehicle", vehicle)
    enforce_company_branch(doc.company, doc.branch)
    if not frappe.has_permission("Motor Vehicle", "read", doc=doc):
        frappe.throw("You are not permitted to view this vehicle.", frappe.PermissionError)
    return {
        "vehicle": doc.as_dict(),
        "future_reservations": frappe.get_all(
            "Rental Reservation",
            filters={"vehicle": vehicle, "return_datetime": [">=", nowdate()], "status": ["in", ["Confirmed", "Vehicle Assigned"]]},
            fields=["name", "customer", "pickup_datetime", "return_datetime", "status"],
            order_by="pickup_datetime asc",
            limit_page_length=20,
        ),
        "maintenance_due": frappe.get_all(
            "Vehicle Maintenance",
            filters={"vehicle": vehicle, "status": ["in", ["Due", "Scheduled", "In Progress", "Quality Check"]], "docstatus": ["<", 2]},
            fields=["name", "maintenance_type", "due_date", "due_odometer", "status"],
            order_by="due_date asc",
            limit_page_length=20,
        ),
        "recent_agreements": frappe.get_all(
            "Rental Agreement",
            filters={"vehicle": vehicle},
            fields=["name", "customer", "pickup_datetime", "expected_return_datetime", "status", "grand_total"],
            order_by="pickup_datetime desc",
            limit_page_length=10,
        ),
    }


def _sum_value(doctype: str, fieldname: str, filters: dict) -> float:
    value = frappe.get_all(doctype, filters=filters, fields=[f"coalesce(sum(`{fieldname}`), 0) as value"], limit_page_length=1)
    return flt(value[0].value) if value else 0.0


def _average_value(doctype: str, fieldname: str, filters: dict) -> float:
    value = frappe.get_all(doctype, filters=filters, fields=[f"coalesce(avg(`{fieldname}`), 0) as value"], limit_page_length=1)
    return flt(value[0].value) if value else 0.0


def _revenue_by_month(invoices) -> list[dict]:
    grouped = defaultdict(lambda: {"rental": 0.0, "sales": 0.0})
    for row in invoices:
        key = getdate(row.posting_date).strftime("%Y-%m")
        bucket = "sales" if row.dagaar_vehicle_sale else "rental"
        grouped[key][bucket] += flt(row.base_net_total)
    return [
        {"month": key, "rental": values["rental"], "sales": values["sales"]}
        for key, values in sorted(grouped.items())
    ]


def _top_vehicles(invoices) -> list[dict]:
    totals = defaultdict(float)
    for row in invoices:
        if row.dagaar_motor_vehicle and not row.dagaar_vehicle_sale:
            totals[row.dagaar_motor_vehicle] += flt(row.base_net_total)
    return [
        {"vehicle": vehicle, "revenue": revenue}
        for vehicle, revenue in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]
    ]


def _branch_performance(company, from_date, to_date, branch_filter=None) -> list[dict]:
    filters = {"company": company, "snapshot_date": ["between", [from_date, to_date]]}
    if branch_filter:
        filters["branch"] = branch_filter
    rows = frappe.get_all(
        "Utilization Snapshot",
        filters=filters,
        fields=["branch", "avg(utilization_percent) as utilization"],
        group_by="branch",
    )
    return [{"branch": row.branch or "Unassigned", "utilization": flt(row.utilization)} for row in rows]