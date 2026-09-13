from __future__ import annotations

from collections import defaultdict
from typing import Callable

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_datetime, getdate, now_datetime, nowdate

from dagaar_motors.api.permissions import enforce_company_branch, get_permission_scope
from dagaar_motors.services.settings import resolve_company


ReportResult = tuple[list[dict], list[dict], dict | None, list[dict]]


REPORT_HANDLERS: dict[str, Callable] = {}


def report(name: str):
    def decorator(function: Callable):
        REPORT_HANDLERS[name] = function
        return function

    return decorator


def execute_report(report_name: str, filters=None):
    handler = REPORT_HANDLERS.get(report_name)
    if not handler:
        frappe.throw(_("Unknown Dagaar Motors report: {0}").format(report_name))
    normalized = _normalize_filters(filters)
    columns, data, chart, summary = handler(normalized)
    return columns, data, None, chart, summary


def _normalize_filters(filters=None):
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    values = frappe._dict(filters or {})
    scope = get_permission_scope()
    company = values.get("company")
    if not company and scope["companies"]:
        company = scope["companies"][0]
    company = resolve_company(company)
    branch = values.get("branch")
    enforce_company_branch(company, branch)

    from_date = getdate(values.get("from_date") or add_months(nowdate(), -12))
    to_date = getdate(values.get("to_date") or nowdate())
    if to_date < from_date:
        frappe.throw(_("To Date cannot be before From Date."))

    values.company = company
    values.branch = branch
    values.from_date = from_date
    values.to_date = to_date
    values.to_date_exclusive = add_days(to_date, 1)
    values.allowed_branches = [] if branch else scope["branches"]
    values.currency = frappe.get_cached_value("Company", company, "default_currency")
    values.expiry_days = cint(values.get("expiry_days") or 60)
    return values


def _conditions(
    filters,
    alias: str,
    *,
    company_field: str | None = "company",
    branch_field: str | None = "branch",
    date_field: str | None = None,
    datetime_range: bool = True,
):
    conditions: list[str] = []
    params: dict = {
        "company": filters.company,
        "branch": filters.branch,
        "from_date": filters.from_date,
        "to_date": filters.to_date,
        "to_date_exclusive": filters.to_date_exclusive,
    }
    prefix = f"{alias}." if alias else ""
    if company_field:
        conditions.append(f"{prefix}`{company_field}` = %(company)s")
    if branch_field:
        if filters.branch:
            conditions.append(f"{prefix}`{branch_field}` = %(branch)s")
        elif filters.allowed_branches:
            placeholders = []
            for index, branch in enumerate(filters.allowed_branches):
                key = f"allowed_branch_{index}"
                params[key] = branch
                placeholders.append(f"%({key})s")
            conditions.append(f"{prefix}`{branch_field}` in ({', '.join(placeholders)})")
    if date_field:
        if datetime_range:
            conditions.extend(
                [
                    f"{prefix}`{date_field}` >= %(from_date)s",
                    f"{prefix}`{date_field}` < %(to_date_exclusive)s",
                ]
            )
        else:
            conditions.extend(
                [
                    f"{prefix}`{date_field}` >= %(from_date)s",
                    f"{prefix}`{date_field}` <= %(to_date)s",
                ]
            )
    return conditions, params


def _append_optional(conditions: list[str], params: dict, expression: str, key: str, value):
    if value not in (None, "", []):
        conditions.append(f"{expression} = %({key})s")
        params[key] = value


def _sql(query: str, conditions: list[str], params: dict, *, order_by: str = ""):
    where = " and ".join([condition for condition in conditions if condition]) or "1=1"
    statement = query.format(where=where, order_by=(f" order by {order_by}" if order_by else ""))
    return frappe.db.sql(statement, params, as_dict=True)


def _col(label, fieldname, fieldtype="Data", width=120, options=None):
    column = {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
    if options:
        column["options"] = options
    return column


def _summary(label, value, datatype="Currency", indicator="Blue", currency=None):
    item = {"label": _(label), "value": value, "datatype": datatype, "indicator": indicator}
    if currency:
        item["currency"] = currency
    return item


def _status_chart(data, fieldname="status"):
    totals = defaultdict(float)
    for row in data:
        totals[str(row.get(fieldname) or _("Unspecified"))] += 1
    if not totals:
        return None
    return {
        "data": {"labels": list(totals), "datasets": [{"name": _("Records"), "values": list(totals.values())}]},
        "type": "donut",
        "height": 280,
    }


def _currency_summary(label, value, filters, indicator="Blue"):
    return _summary(label, flt(value), "Currency", indicator, filters.currency)


@report("Fleet Availability")
def fleet_availability(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    params["now_datetime"] = now_datetime()
    _append_optional(conditions, params, "v.status", "status", filters.get("status"))
    _append_optional(conditions, params, "v.category", "category", filters.get("vehicle_category"))
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.status,
            v.current_customer,
            v.current_rental_agreement,
            v.available_from,
            v.current_odometer,
            v.rentable,
            v.sellable,
            v.status_reason,
            (
                select min(r.pickup_datetime)
                from `tabRental Reservation` r
                where r.vehicle = v.name
                  and r.docstatus < 2
                  and r.status in ('Confirmed', 'Vehicle Assigned')
                  and r.pickup_datetime >= %(now_datetime)s
            ) as next_reservation
        from `tabMotor Vehicle` v
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="v.branch, v.status, v.vehicle_title",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 105),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 120, "Motor Branch"),
        _col("Status", "status", "Data", 105),
        _col("Current Customer", "current_customer", "Link", 145, "Customer"),
        _col("Active Agreement", "current_rental_agreement", "Link", 130, "Rental Agreement"),
        _col("Available From", "available_from", "Datetime", 145),
        _col("Next Reservation", "next_reservation", "Datetime", 145),
        _col("Odometer", "current_odometer", "Float", 105),
        _col("Reason", "status_reason", "Data", 230),
    ]
    summary = [
        _summary("Fleet", len(data), "Int"),
        _summary("Available", sum(1 for row in data if row.status == "Available"), "Int", "Green"),
        _summary("Rented", sum(1 for row in data if row.status == "Rented"), "Int", "Blue"),
        _summary("Unavailable", sum(1 for row in data if row.status in {"Maintenance", "Blocked", "In Transit"}), "Int", "Orange"),
    ]
    return columns, data, _status_chart(data), summary


@report("Fleet Utilization")
def fleet_utilization(filters) -> ReportResult:
    conditions, params = _conditions(filters, "s", date_field="snapshot_date", datetime_range=False)
    data = _sql(
        """
        select
            s.vehicle,
            max(v.vehicle_title) as vehicle_title,
            max(v.license_plate) as license_plate,
            max(v.category) as category,
            s.branch,
            count(distinct s.snapshot_date) as snapshot_days,
            sum(s.available_hours) as available_hours,
            sum(s.rented_hours) as rented_hours,
            sum(s.maintenance_hours) as maintenance_hours,
            sum(s.blocked_hours) as blocked_hours,
            case
                when sum(s.available_hours + s.rented_hours) > 0
                then (sum(s.rented_hours) / sum(s.available_hours + s.rented_hours)) * 100
                else avg(s.utilization_percent)
            end as utilization_percent
        from `tabUtilization Snapshot` s
        left join `tabMotor Vehicle` v on v.name = s.vehicle
        where {where}
        group by s.vehicle, s.branch
        {order_by}
        """,
        conditions,
        params,
        order_by="utilization_percent desc, vehicle_title",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 105),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 120, "Motor Branch"),
        _col("Snapshot Days", "snapshot_days", "Int", 105),
        _col("Available Hours", "available_hours", "Float", 120),
        _col("Rented Hours", "rented_hours", "Float", 115),
        _col("Maintenance Hours", "maintenance_hours", "Float", 135),
        _col("Blocked Hours", "blocked_hours", "Float", 115),
        _col("Utilization %", "utilization_percent", "Percent", 110),
    ]
    average = sum(flt(row.utilization_percent) for row in data) / max(len(data), 1)
    chart = {
        "data": {
            "labels": [row.vehicle_title or row.vehicle for row in data[:15]],
            "datasets": [{"name": _("Utilization %"), "values": [flt(row.utilization_percent) for row in data[:15]]}],
        },
        "type": "bar",
        "height": 300,
    } if data else None
    return columns, data, chart, [_summary("Average Utilization", average, "Percent", "Green"), _summary("Vehicles", len(data), "Int")]


@report("Rental Revenue")
def rental_revenue(filters) -> ReportResult:
    conditions, params = _conditions(filters, "si", branch_field=None, date_field="posting_date", datetime_range=False)
    conditions.extend(["si.docstatus = 1", "coalesce(dl.rental_agreement, '') != ''", "coalesce(dl.vehicle_sale, '') = ''"])
    if filters.branch:
        conditions.append("coalesce(ra.branch, v.branch) = %(branch)s")
    elif filters.allowed_branches:
        placeholders = []
        for index, branch in enumerate(filters.allowed_branches):
            key = f"revenue_branch_{index}"
            params[key] = branch
            placeholders.append(f"%({key})s")
        conditions.append(f"coalesce(ra.branch, v.branch) in ({', '.join(placeholders)})")
    _append_optional(conditions, params, "si.customer", "customer", filters.get("customer"))
    _append_optional(conditions, params, "dl.motor_vehicle", "vehicle", filters.get("vehicle"))
    data = _sql(
        """
        select
            si.name as sales_invoice,
            si.posting_date,
            si.customer,
            dl.rental_agreement as rental_agreement,
            dl.rental_extension as rental_extension,
            dl.rental_return as rental_return,
            dl.traffic_fine as traffic_fine,
            dl.motor_vehicle as vehicle,
            coalesce(ra.branch, v.branch) as branch,
            si.currency,
            si.net_total,
            si.base_net_total,
            si.outstanding_amount,
            si.status
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        left join `tabRental Agreement` ra on ra.name = dl.rental_agreement
        left join `tabMotor Vehicle` v on v.name = dl.motor_vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="si.posting_date desc, si.name desc",
    )
    columns = [
        _col("Sales Invoice", "sales_invoice", "Link", 130, "Sales Invoice"),
        _col("Posting Date", "posting_date", "Date", 105),
        _col("Customer", "customer", "Link", 150, "Customer"),
        _col("Rental Agreement", "rental_agreement", "Link", 130, "Rental Agreement"),
        _col("Extension", "rental_extension", "Link", 120, "Rental Extension"),
        _col("Return", "rental_return", "Link", 115, "Rental Return"),
        _col("Traffic Fine", "traffic_fine", "Link", 110, "Traffic Fine"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 115, "Motor Branch"),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Net Total", "net_total", "Currency", 115, "currency"),
        _col("Company Total", "base_net_total", "Currency", 120),
        _col("Outstanding", "outstanding_amount", "Currency", 115, "currency"),
        _col("Status", "status", "Data", 95),
    ]
    revenue = sum(flt(row.base_net_total) for row in data)
    outstanding = sum(flt(row.outstanding_amount) for row in data)
    chart = _monthly_chart(data, "posting_date", "base_net_total", _("Revenue"))
    return columns, data, chart, [_currency_summary("Rental Revenue", revenue, filters, "Green"), _currency_summary("Outstanding", outstanding, filters, "Orange"), _summary("Invoices", len(data), "Int")]


def _rental_revenue_dimension(filters, dimension: str) -> ReportResult:
    dimensions = {
        "Vehicle": ("coalesce(dl.motor_vehicle, 'Unassigned')", "vehicle", "Motor Vehicle", "max(v.vehicle_title)"),
        "Category": ("coalesce(v.category, 'Unassigned')", "vehicle_category", "Vehicle Category", "coalesce(v.category, 'Unassigned')"),
        "Branch": ("coalesce(ra.branch, v.branch, 'Unassigned')", "branch", "Motor Branch", "coalesce(ra.branch, v.branch, 'Unassigned')"),
        "Customer": ("si.customer", "customer", "Customer", "si.customer"),
        "Agent": ("coalesce(ra.rental_agent, 'Unassigned')", "rental_agent", "User", "coalesce(ra.rental_agent, 'Unassigned')"),
    }
    expression, fieldname, options, label_expression = dimensions[dimension]
    conditions, params = _conditions(filters, "si", branch_field=None, date_field="posting_date", datetime_range=False)
    conditions.extend(["si.docstatus = 1", "coalesce(dl.rental_agreement, '') != ''", "coalesce(dl.vehicle_sale, '') = ''"])
    if filters.branch:
        conditions.append("coalesce(ra.branch, v.branch) = %(branch)s")
    elif filters.allowed_branches:
        placeholders = []
        for index, branch in enumerate(filters.allowed_branches):
            key = f"dimension_branch_{index}"
            params[key] = branch
            placeholders.append(f"%({key})s")
        conditions.append(f"coalesce(ra.branch, v.branch) in ({', '.join(placeholders)})")
    data = _sql(
        f"""
        select
            {expression} as `{fieldname}`,
            {label_expression} as dimension_label,
            count(distinct si.name) as invoice_count,
            count(distinct dl.rental_agreement) as rental_count,
            sum(si.base_net_total) as revenue,
            sum(si.outstanding_amount) as outstanding,
            avg(si.base_net_total) as average_invoice
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        left join `tabRental Agreement` ra on ra.name = dl.rental_agreement
        left join `tabMotor Vehicle` v on v.name = dl.motor_vehicle
        where {{where}}
        group by {expression}
        {{order_by}}
        """,
        conditions,
        params,
        order_by="revenue desc",
    )
    columns = [
        _col(dimension, fieldname, "Link" if options else "Data", 155, options),
        _col("Display", "dimension_label", "Data", 190),
        _col("Invoices", "invoice_count", "Int", 90),
        _col("Rentals", "rental_count", "Int", 90),
        _col("Revenue", "revenue", "Currency", 125),
        _col("Outstanding", "outstanding", "Currency", 120),
        _col("Average Invoice", "average_invoice", "Currency", 120),
    ]
    chart = {
        "data": {
            "labels": [row.dimension_label or row.get(fieldname) for row in data[:15]],
            "datasets": [{"name": _("Revenue"), "values": [flt(row.revenue) for row in data[:15]]}],
        },
        "type": "bar",
        "height": 300,
    } if data else None
    return columns, data, chart, [_currency_summary("Revenue", sum(flt(row.revenue) for row in data), filters, "Green"), _summary("Groups", len(data), "Int")]


@report("Rental Revenue by Vehicle")
def rental_revenue_by_vehicle(filters):
    return _rental_revenue_dimension(filters, "Vehicle")


@report("Rental Revenue by Category")
def rental_revenue_by_category(filters):
    return _rental_revenue_dimension(filters, "Category")


@report("Rental Revenue by Branch")
def rental_revenue_by_branch(filters):
    return _rental_revenue_dimension(filters, "Branch")


@report("Rental Revenue by Customer")
def rental_revenue_by_customer(filters):
    return _rental_revenue_dimension(filters, "Customer")


@report("Rental Revenue by Agent")
def rental_revenue_by_agent(filters):
    return _rental_revenue_dimension(filters, "Agent")


@report("Active Rentals")
def active_rentals(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field=None)
    current_time = now_datetime()
    conditions.extend(["ra.docstatus = 1", "ra.status in ('Active', 'Extended', 'Overdue', 'Return Processing')"])
    _append_optional(conditions, params, "ra.vehicle", "vehicle", filters.get("vehicle"))
    _append_optional(conditions, params, "ra.customer", "customer", filters.get("customer"))
    data = _sql(
        """
        select
            ra.name as rental_agreement,
            ra.status,
            ra.customer,
            ra.vehicle,
            v.vehicle_title,
            v.license_plate,
            ra.branch,
            ra.pickup_datetime,
            ra.expected_return_datetime,
            ra.actual_return_datetime,
            ra.duration_label,
            ra.currency,
            ra.grand_total,
            ra.deposit_required,
            ra.rental_agent
        from `tabRental Agreement` ra
        left join `tabMotor Vehicle` v on v.name = ra.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="ra.expected_return_datetime asc",
    )
    for row in data:
        delta = current_time - get_datetime(row.expected_return_datetime)
        row.overdue_hours = max(0, int(delta.total_seconds() / 3600))
    columns = _rental_columns(include_overdue=True)
    return columns, data, _status_chart(data), [_summary("Active Rentals", len(data), "Int", "Blue"), _summary("Overdue", sum(1 for row in data if row.status == "Overdue"), "Int", "Red"), _currency_summary("Contract Value", sum(flt(row.grand_total) for row in data), filters)]


@report("Overdue Rentals")
def overdue_rentals(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field=None)
    current_time = now_datetime()
    params["now_datetime"] = current_time
    conditions.extend(["ra.docstatus = 1", "ra.status in ('Active', 'Extended', 'Overdue')", "ra.expected_return_datetime < %(now_datetime)s"])
    data = _sql(
        """
        select
            ra.name as rental_agreement,
            ra.status,
            ra.customer,
            ra.vehicle,
            v.vehicle_title,
            v.license_plate,
            ra.branch,
            ra.pickup_datetime,
            ra.expected_return_datetime,
            ra.actual_return_datetime,
            ra.duration_label,
            ra.currency,
            ra.grand_total,
            ra.deposit_required,
            ra.rental_agent
        from `tabRental Agreement` ra
        left join `tabMotor Vehicle` v on v.name = ra.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="ra.expected_return_datetime asc",
    )
    for row in data:
        delta = current_time - get_datetime(row.expected_return_datetime)
        row.overdue_hours = max(0, int(delta.total_seconds() / 3600))
    return _rental_columns(include_overdue=True), data, None, [_summary("Overdue Rentals", len(data), "Int", "Red"), _summary("Overdue Hours", sum(cint(row.overdue_hours) for row in data), "Int", "Orange"), _currency_summary("Contract Value", sum(flt(row.grand_total) for row in data), filters)]


def _rental_columns(include_overdue=False):
    columns = [
        _col("Rental Agreement", "rental_agreement", "Link", 130, "Rental Agreement"),
        _col("Status", "status", "Data", 105),
        _col("Customer", "customer", "Link", 150, "Customer"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 175),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 115, "Motor Branch"),
        _col("Pickup", "pickup_datetime", "Datetime", 145),
        _col("Expected Return", "expected_return_datetime", "Datetime", 145),
    ]
    if include_overdue:
        columns.append(_col("Overdue Hours", "overdue_hours", "Int", 105))
    columns.extend([
        _col("Duration", "duration_label", "Data", 105),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Grand Total", "grand_total", "Currency", 115, "currency"),
        _col("Deposit", "deposit_required", "Currency", 105, "currency"),
        _col("Agent", "rental_agent", "Link", 130, "User"),
    ])
    return columns


@report("Rental Pipeline")
def rental_pipeline(filters) -> ReportResult:
    conditions, params = _conditions(filters, "r", date_field="pickup_datetime")
    conditions.append("r.docstatus < 2")
    _append_optional(conditions, params, "r.status", "status", filters.get("status"))
    data = _sql(
        """
        select
            r.name as rental_agreement,
            r.status,
            r.customer,
            r.vehicle_category,
            r.vehicle,
            r.branch,
            r.pickup_datetime,
            r.expected_return_datetime,
            r.currency,
            r.grand_total,
            r.deposit_required,
            r.rental_agent
        from `tabRental Agreement` r
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="r.pickup_datetime asc, r.status",
    )
    columns = [
        _col("Rental Agreement", "rental_agreement", "Link", 150, "Rental Agreement"),
        _col("Status", "status", "Data", 120),
        _col("Customer", "customer", "Link", 145, "Customer"),
        _col("Category", "vehicle_category", "Link", 120, "Vehicle Category"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Pickup", "pickup_datetime", "Datetime", 145),
        _col("Expected Return", "expected_return_datetime", "Datetime", 150),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Value", "grand_total", "Currency", 110, "currency"),
        _col("Deposit Required", "deposit_required", "Currency", 120, "currency"),
        _col("Agent", "rental_agent", "Link", 125, "User"),
    ]
    return columns, data, _status_chart(data), [_summary("Rentals", len(data), "Int"), _currency_summary("Pipeline Value", sum(flt(row.grand_total) for row in data), filters, "Green"), _currency_summary("Deposit Required", sum(flt(row.deposit_required) for row in data), filters, "Orange")]


@report("Rental Extensions")
def rental_extensions(filters) -> ReportResult:
    conditions, params = _conditions(filters, "e", date_field="creation")
    _append_optional(conditions, params, "e.status", "status", filters.get("status"))
    data = _sql(
        """
        select
            e.name as rental_extension,
            e.rental_agreement,
            e.vehicle,
            e.branch,
            e.status,
            e.original_end_datetime,
            e.new_end_datetime,
            e.duration_label,
            e.currency,
            e.rate,
            e.base_amount,
            e.discount_amount,
            e.tax_amount,
            e.grand_total,
            e.pricing_rule,
            e.sales_invoice,
            e.requested_by,
            e.approved_by,
            e.reason
        from `tabRental Extension` e
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="e.creation desc",
    )
    columns = [
        _col("Extension", "rental_extension", "Link", 125, "Rental Extension"),
        _col("Agreement", "rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Status", "status", "Data", 110),
        _col("Original End", "original_end_datetime", "Datetime", 145),
        _col("New End", "new_end_datetime", "Datetime", 145),
        _col("Duration", "duration_label", "Data", 100),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Rate", "rate", "Currency", 95, "currency"),
        _col("Base", "base_amount", "Currency", 105, "currency"),
        _col("Discount", "discount_amount", "Currency", 100, "currency"),
        _col("Tax", "tax_amount", "Currency", 95, "currency"),
        _col("Grand Total", "grand_total", "Currency", 110, "currency"),
        _col("Pricing Rule", "pricing_rule", "Link", 125, "Rental Pricing Rule"),
        _col("Invoice", "sales_invoice", "Link", 125, "Sales Invoice"),
        _col("Requested By", "requested_by", "Link", 120, "User"),
        _col("Approved By", "approved_by", "Link", 120, "User"),
        _col("Reason", "reason", "Data", 180),
    ]
    return columns, data, _status_chart(data), [_summary("Extensions", len(data), "Int"), _currency_summary("Extension Revenue", sum(flt(row.grand_total) for row in data if row.status in {"Invoiced", "Completed", "Approved"}), filters, "Green"), _currency_summary("Discounts", sum(flt(row.discount_amount) for row in data), filters, "Orange")]


@report("Rental Discounts")
def rental_discounts(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field="pickup_datetime")
    conditions.extend(["ra.docstatus < 2", "coalesce(ra.discount_amount, 0) > 0"])
    data = _sql(
        """
        select
            ra.name as rental_agreement,
            ra.customer,
            ra.vehicle,
            ra.branch,
            ra.pickup_datetime,
            ra.rental_agent,
            ra.currency,
            ra.base_amount,
            ra.discount_percent,
            ra.discount_amount,
            ra.net_amount,
            ra.approved_by,
            ra.status
        from `tabRental Agreement` ra
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="ra.discount_amount desc",
    )
    columns = [
        _col("Agreement", "rental_agreement", "Link", 130, "Rental Agreement"),
        _col("Customer", "customer", "Link", 150, "Customer"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Pickup", "pickup_datetime", "Datetime", 145),
        _col("Agent", "rental_agent", "Link", 125, "User"),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Base", "base_amount", "Currency", 105, "currency"),
        _col("Discount %", "discount_percent", "Percent", 100),
        _col("Discount", "discount_amount", "Currency", 105, "currency"),
        _col("Net", "net_amount", "Currency", 105, "currency"),
        _col("Approved By", "approved_by", "Link", 125, "User"),
        _col("Status", "status", "Data", 100),
    ]
    return columns, data, None, [_summary("Discounted Rentals", len(data), "Int"), _currency_summary("Total Discounts", sum(flt(row.discount_amount) for row in data), filters, "Orange")]


@report("Deposit Liability")
def deposit_liability(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field=None)
    data = _sql(
        """
        select
            ra.name as rental_agreement,
            ra.status,
            ra.customer,
            ra.vehicle,
            ra.branch,
            ra.currency,
            ra.deposit_required,
            pe.paid_amount as amount_received,
            (pe.paid_amount - pe.unallocated_amount) as deducted_amount,
            pe.unallocated_amount as held_amount,
            ra.deposit_payment_entry,
            ra.deposit_refund_payment_entry,
            ra.modified
        from `tabRental Agreement` ra
        inner join `tabPayment Entry` pe on pe.name = ra.deposit_payment_entry and pe.docstatus = 1
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="ra.modified desc",
    )
    columns = _deposit_columns()
    return columns, data, None, [_currency_summary("Deposits Held", sum(flt(row.held_amount) for row in data), filters, "Blue"), _currency_summary("Applied to Invoices", sum(flt(row.deducted_amount) for row in data), filters, "Orange"), _summary("Open Deposits", len(data), "Int")]


@report("Deposit Refunds")
def deposit_refunds(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field=None)
    data = _sql(
        """
        select
            pe.name as payment_entry,
            ra.name as rental_agreement,
            pe.posting_date,
            ra.customer,
            ra.vehicle,
            ra.branch,
            ra.currency,
            pe.paid_amount as amount,
            pe.mode_of_payment as payment_method,
            pe.reference_no as reference_number,
            pe.docstatus
        from `tabPayment Entry` pe
        inner join `tabRental Agreement` ra on ra.deposit_refund_payment_entry = pe.name and pe.docstatus = 1
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="pe.posting_date desc, pe.name desc",
    )
    columns = [
        _col("Refund Payment", "payment_entry", "Link", 145, "Payment Entry"),
        _col("Date", "posting_date", "Date", 100),
        _col("Customer", "customer", "Link", 145, "Customer"),
        _col("Agreement", "rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Amount", "amount", "Currency", 110, "currency"),
        _col("Method", "payment_method", "Data", 105),
        _col("Reference", "reference_number", "Data", 120),
    ]
    return columns, data, None, [_currency_summary("Refunded", sum(flt(row.amount) for row in data), filters, "Green"), _summary("Refunds", len(data), "Int")]


def _deposit_columns():
    return [
        _col("Agreement", "rental_agreement", "Link", 130, "Rental Agreement"),
        _col("Status", "status", "Data", 110),
        _col("Customer", "customer", "Link", 145, "Customer"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Required", "deposit_required", "Currency", 105, "currency"),
        _col("Received", "amount_received", "Currency", 105, "currency"),
        _col("Applied", "deducted_amount", "Currency", 105, "currency"),
        _col("Held", "held_amount", "Currency", 105, "currency"),
        _col("Deposit PE", "deposit_payment_entry", "Link", 140, "Payment Entry"),
        _col("Refund PE", "deposit_refund_payment_entry", "Link", 140, "Payment Entry"),
        _col("Modified", "modified", "Datetime", 145),
    ]


@report("Vehicle Profitability")
def vehicle_profitability(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    _append_optional(conditions, params, "v.status", "status", filters.get("status"))
    _append_optional(conditions, params, "v.category", "category", filters.get("vehicle_category"))
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.status,
            c.default_currency as currency,
            v.initial_total_cost,
            v.total_rental_revenue,
            v.total_extension_revenue,
            v.total_other_revenue,
            v.total_sale_revenue,
            v.maintenance_cost,
            v.operating_cost,
            v.total_cost,
            v.profit,
            v.profit_margin,
            v.roi,
            v.rental_days,
            v.available_days,
            v.idle_days,
            v.maintenance_downtime_days,
            v.utilization_percent,
            v.average_daily_revenue,
            v.revenue_per_km,
            v.cost_per_km,
            v.current_odometer
        from `tabMotor Vehicle` v
        left join `tabCompany` c on c.name = v.company
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="v.profit desc, v.vehicle_title",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Status", "status", "Data", 100),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Acquisition", "initial_total_cost", "Currency", 115, "currency"),
        _col("Rental Revenue", "total_rental_revenue", "Currency", 120, "currency"),
        _col("Extension Revenue", "total_extension_revenue", "Currency", 125, "currency"),
        _col("Other Revenue", "total_other_revenue", "Currency", 115, "currency"),
        _col("Sale Revenue", "total_sale_revenue", "Currency", 115, "currency"),
        _col("Maintenance", "maintenance_cost", "Currency", 115, "currency"),
        _col("Operating Cost", "operating_cost", "Currency", 115, "currency"),
        _col("Total Cost", "total_cost", "Currency", 115, "currency"),
        _col("Profit", "profit", "Currency", 115, "currency"),
        _col("Margin %", "profit_margin", "Percent", 95),
        _col("ROI %", "roi", "Percent", 90),
        _col("Rental Days", "rental_days", "Float", 100),
        _col("Idle Days", "idle_days", "Float", 90),
        _col("Downtime Days", "maintenance_downtime_days", "Float", 110),
        _col("Utilization %", "utilization_percent", "Percent", 105),
        _col("Avg Daily Revenue", "average_daily_revenue", "Currency", 125, "currency"),
        _col("Revenue / KM", "revenue_per_km", "Currency", 110, "currency"),
        _col("Cost / KM", "cost_per_km", "Currency", 105, "currency"),
        _col("Odometer", "current_odometer", "Float", 100),
    ]
    chart = {
        "data": {
            "labels": [row.vehicle_title or row.vehicle for row in data[:15]],
            "datasets": [{"name": _("Profit"), "values": [flt(row.profit) for row in data[:15]]}],
        },
        "type": "bar",
        "height": 300,
    } if data else None
    return columns, data, chart, [_currency_summary("Fleet Revenue", sum(flt(row.total_rental_revenue)+flt(row.total_extension_revenue)+flt(row.total_other_revenue)+flt(row.total_sale_revenue) for row in data), filters, "Green"), _currency_summary("Fleet Cost", sum(flt(row.total_cost) for row in data), filters, "Orange"), _currency_summary("Fleet Profit", sum(flt(row.profit) for row in data), filters, "Blue")]


@report("Vehicle Cost")
def vehicle_cost(filters) -> ReportResult:
    conditions, params = _conditions(filters, "e", date_field="posting_date", datetime_range=False)
    conditions.append("e.docstatus = 1")
    _append_optional(conditions, params, "e.expense_type", "expense_type", filters.get("expense_type"))
    data = _sql(
        """
        select
            e.vehicle,
            max(v.vehicle_title) as vehicle_title,
            max(v.license_plate) as license_plate,
            max(v.category) as category,
            e.branch,
            e.expense_type,
            count(*) as transaction_count,
            sum(e.amount) as amount
        from `tabVehicle Expense` e
        left join `tabMotor Vehicle` v on v.name = e.vehicle
        where {where}
        group by e.vehicle, e.branch, e.expense_type
        {order_by}
        """,
        conditions,
        params,
        order_by="amount desc",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 185),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Expense Type", "expense_type", "Data", 120),
        _col("Transactions", "transaction_count", "Int", 100),
        _col("Amount", "amount", "Currency", 120),
    ]
    return columns, data, None, [_currency_summary("Vehicle Cost", sum(flt(row.amount) for row in data), filters, "Orange"), _summary("Cost Lines", len(data), "Int")]


@report("Maintenance Expense")
def maintenance_expense(filters) -> ReportResult:
    conditions, params = _conditions(filters, "w", date_field="actual_end")
    conditions.extend(["w.docstatus = 1", "w.status in ('Completed', 'Closed')"])
    data = _sql(
        """
        select
            w.name as work_order,
            w.vehicle,
            v.vehicle_title,
            v.license_plate,
            w.branch,
            w.workshop_type,
            w.supplier,
            w.actual_start,
            w.actual_end,
            w.downtime_hours,
            w.parts_total,
            w.labor_total,
            w.expense_total,
            w.grand_total,
            w.purchase_invoice
        from `tabMaintenance Work Order` w
        left join `tabMotor Vehicle` v on v.name = w.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="w.actual_end desc, w.grand_total desc",
    )
    columns = [
        _col("Work Order", "work_order", "Link", 130, "Maintenance Work Order"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Workshop", "workshop_type", "Data", 105),
        _col("Supplier", "supplier", "Link", 135, "Supplier"),
        _col("Started", "actual_start", "Datetime", 140),
        _col("Completed", "actual_end", "Datetime", 140),
        _col("Downtime Hours", "downtime_hours", "Float", 115),
        _col("Parts", "parts_total", "Currency", 105),
        _col("Labor", "labor_total", "Currency", 105),
        _col("Expenses", "expense_total", "Currency", 105),
        _col("Total", "grand_total", "Currency", 115),
        _col("Purchase Invoice", "purchase_invoice", "Link", 125, "Purchase Invoice"),
    ]
    return columns, data, None, [_currency_summary("Maintenance Expense", sum(flt(row.grand_total) for row in data), filters, "Orange"), _summary("Work Orders", len(data), "Int"), _summary("Downtime Hours", sum(flt(row.downtime_hours) for row in data), "Float")]


@report("Maintenance Due")
def maintenance_due(filters) -> ReportResult:
    conditions, params = _conditions(filters, "m", date_field=None)
    conditions.extend(["m.docstatus < 2", "m.status in ('Due', 'Scheduled', 'In Progress', 'Quality Check')"])
    _append_optional(conditions, params, "m.status", "status", filters.get("status"))
    data = _sql(
        """
        select
            m.name as vehicle_maintenance,
            m.vehicle,
            v.vehicle_title,
            v.license_plate,
            v.current_odometer,
            m.branch,
            m.maintenance_type,
            m.status,
            m.due_date,
            m.due_odometer,
            m.planned_start,
            m.planned_end,
            m.estimated_cost,
            m.work_order
        from `tabVehicle Maintenance` m
        left join `tabMotor Vehicle` v on v.name = m.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="m.due_date asc, m.due_odometer asc",
    )
    today = getdate(nowdate())
    for row in data:
        row.days_to_due = (getdate(row.due_date) - today).days if row.due_date else None
        row.km_to_due = flt(row.due_odometer) - flt(row.current_odometer) if row.due_odometer is not None else None
    columns = [
        _col("Maintenance", "vehicle_maintenance", "Link", 130, "Vehicle Maintenance"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Type", "maintenance_type", "Data", 130),
        _col("Status", "status", "Data", 105),
        _col("Due Date", "due_date", "Date", 105),
        _col("Days to Due", "days_to_due", "Int", 105),
        _col("Due Odometer", "due_odometer", "Float", 115),
        _col("Current Odometer", "current_odometer", "Float", 125),
        _col("KM to Due", "km_to_due", "Float", 100),
        _col("Planned Start", "planned_start", "Datetime", 140),
        _col("Planned End", "planned_end", "Datetime", 140),
        _col("Estimated Cost", "estimated_cost", "Currency", 115),
        _col("Work Order", "work_order", "Link", 125, "Maintenance Work Order"),
    ]
    overdue = sum(1 for row in data if (row.days_to_due is not None and cint(row.days_to_due) < 0) or (row.km_to_due is not None and flt(row.km_to_due) <= 0))
    return columns, data, _status_chart(data), [_summary("Maintenance Due", len(data), "Int", "Orange"), _summary("Overdue", overdue, "Int", "Red"), _currency_summary("Estimated Cost", sum(flt(row.estimated_cost) for row in data), filters)]


@report("Vehicle Downtime")
def vehicle_downtime(filters) -> ReportResult:
    conditions, params = _conditions(filters, "w", date_field="actual_start")
    conditions.append("w.docstatus < 2")
    data = _sql(
        """
        select
            w.vehicle,
            max(v.vehicle_title) as vehicle_title,
            max(v.license_plate) as license_plate,
            max(v.category) as category,
            w.branch,
            count(distinct w.name) as work_orders,
            sum(coalesce(w.downtime_hours, 0)) as downtime_hours,
            sum(coalesce(w.grand_total, 0)) as maintenance_cost,
            max(w.actual_end) as last_completion
        from `tabMaintenance Work Order` w
        left join `tabMotor Vehicle` v on v.name = w.vehicle
        where {where}
        group by w.vehicle, w.branch
        {order_by}
        """,
        conditions,
        params,
        order_by="downtime_hours desc",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 185),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Work Orders", "work_orders", "Int", 100),
        _col("Downtime Hours", "downtime_hours", "Float", 120),
        _col("Downtime Days", "downtime_days", "Float", 115),
        _col("Maintenance Cost", "maintenance_cost", "Currency", 125),
        _col("Last Completion", "last_completion", "Datetime", 145),
    ]
    for row in data:
        row.downtime_days = flt(row.downtime_hours) / 24
    return columns, data, None, [_summary("Downtime Hours", sum(flt(row.downtime_hours) for row in data), "Float", "Orange"), _currency_summary("Downtime Cost", sum(flt(row.maintenance_cost) for row in data), filters, "Orange"), _summary("Vehicles", len(data), "Int")]


@report("Vehicle Mileage")
def vehicle_mileage(filters) -> ReportResult:
    conditions, params = _conditions(filters, "l", company_field=None, branch_field=None, date_field="event_datetime")
    conditions.append("v.company = %(company)s")
    if filters.branch:
        conditions.append("v.branch = %(branch)s")
    elif filters.allowed_branches:
        placeholders = []
        for index, branch in enumerate(filters.allowed_branches):
            key = f"mileage_branch_{index}"
            params[key] = branch
            placeholders.append(f"%({key})s")
        conditions.append(f"v.branch in ({', '.join(placeholders)})")
    _append_optional(conditions, params, "l.vehicle", "vehicle", filters.get("vehicle"))
    data = _sql(
        """
        select
            l.name as mileage_log,
            l.vehicle,
            v.vehicle_title,
            v.license_plate,
            v.branch,
            l.event_type,
            l.event_datetime,
            l.previous_odometer,
            l.odometer,
            l.distance,
            l.is_correction,
            l.approved_by,
            l.source_doctype,
            l.source_name,
            l.reason
        from `tabVehicle Mileage Log` l
        inner join `tabMotor Vehicle` v on v.name = l.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="l.event_datetime desc, l.name desc",
    )
    columns = [
        _col("Mileage Log", "mileage_log", "Link", 125, "Vehicle Mileage Log"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Event", "event_type", "Data", 120),
        _col("Date and Time", "event_datetime", "Datetime", 145),
        _col("Previous", "previous_odometer", "Float", 100),
        _col("Odometer", "odometer", "Float", 100),
        _col("Distance", "distance", "Float", 100),
        _col("Correction", "is_correction", "Check", 85),
        _col("Approved By", "approved_by", "Link", 120, "User"),
        _col("Source Type", "source_doctype", "Link", 110, "DocType"),
        _col("Source", "source_name", "Dynamic Link", 125, "source_doctype"),
        _col("Reason", "reason", "Data", 200),
    ]
    return columns, data, None, [_summary("Distance", sum(flt(row.distance) for row in data), "Float", "Blue"), _summary("Mileage Events", len(data), "Int"), _summary("Corrections", sum(cint(row.is_correction) for row in data), "Int", "Orange")]


@report("Fleet Aging")
def fleet_aging(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.status,
            v.model_year,
            v.purchase_date,
            v.current_odometer,
            v.initial_total_cost,
            v.total_rental_revenue,
            v.total_cost,
            v.profit,
            v.rental_days,
            v.idle_days
        from `tabMotor Vehicle` v
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="age_days desc, v.vehicle_title",
    )
    today = getdate(nowdate())
    for row in data:
        if row.purchase_date:
            row.age_days = (today - getdate(row.purchase_date)).days
            row.age_years = row.age_days / 365.25
        else:
            row.age_days = None
            row.age_years = None
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Status", "status", "Data", 100),
        _col("Model Year", "model_year", "Int", 90),
        _col("Purchase Date", "purchase_date", "Date", 105),
        _col("Age Days", "age_days", "Int", 95),
        _col("Age Years", "age_years", "Float", 95),
        _col("Odometer", "current_odometer", "Float", 100),
        _col("Initial Cost", "initial_total_cost", "Currency", 110),
        _col("Rental Revenue", "total_rental_revenue", "Currency", 120),
        _col("Total Cost", "total_cost", "Currency", 110),
        _col("Profit", "profit", "Currency", 110),
        _col("Rental Days", "rental_days", "Float", 100),
        _col("Idle Days", "idle_days", "Float", 90),
    ]
    average_age = sum(flt(row.age_years) for row in data if row.age_years is not None) / max(sum(1 for row in data if row.age_years is not None), 1)
    return columns, data, None, [_summary("Fleet Vehicles", len(data), "Int"), _summary("Average Age", average_age, "Float"), _summary("5+ Years", sum(1 for row in data if flt(row.age_years) >= 5), "Int", "Orange")]


@report("Vehicle Sale Profit")
def vehicle_sale_profit(filters) -> ReportResult:
    conditions, params = _conditions(filters, "s", date_field="sale_date", datetime_range=False)
    conditions.append("s.docstatus < 2")
    data = _sql(
        """
        select
            s.name as vehicle_sale,
            s.sale_date,
            s.status,
            s.vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            s.branch,
            s.buyer,
            s.salesperson,
            s.currency,
            s.asking_price,
            s.minimum_price,
            s.sale_price,
            s.discount_amount,
            s.commission_amount,
            s.profit_loss,
            s.sales_invoice,
            s.ownership_transfer_reference,
            s.ownership_transfer_date
        from `tabVehicle Sale` s
        left join `tabMotor Vehicle` v on v.name = s.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="s.sale_date desc, s.name desc",
    )
    columns = [
        _col("Vehicle Sale", "vehicle_sale", "Link", 125, "Vehicle Sale"),
        _col("Sale Date", "sale_date", "Date", 100),
        _col("Status", "status", "Data", 100),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Buyer", "buyer", "Link", 145, "Customer"),
        _col("Salesperson", "salesperson", "Link", 125, "Sales Person"),
        _col("Currency", "currency", "Link", 85, "Currency"),
        _col("Asking Price", "asking_price", "Currency", 110, "currency"),
        _col("Minimum Price", "minimum_price", "Currency", 115, "currency"),
        _col("Sale Price", "sale_price", "Currency", 110, "currency"),
        _col("Discount", "discount_amount", "Currency", 105, "currency"),
        _col("Commission", "commission_amount", "Currency", 110, "currency"),
        _col("Profit / Loss", "profit_loss", "Currency", 115, "currency"),
        _col("Sales Invoice", "sales_invoice", "Link", 125, "Sales Invoice"),
        _col("Transfer Ref", "ownership_transfer_reference", "Data", 125),
        _col("Transfer Date", "ownership_transfer_date", "Date", 105),
    ]
    return columns, data, _status_chart(data), [_currency_summary("Sale Proceeds", sum(flt(row.sale_price) for row in data if row.status in {"Completed", "Delivered", "Invoiced"}), filters, "Green"), _currency_summary("Sale Profit", sum(flt(row.profit_loss) for row in data), filters, "Blue"), _summary("Sales", len(data), "Int")]


@report("Vehicles for Sale")
def vehicles_for_sale(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    conditions.extend(["v.sellable = 1", "v.status not in ('Sold', 'Retired')"])
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.status,
            v.model_year,
            v.current_odometer,
            v.selling_item,
            v.selling_price,
            v.minimum_selling_price,
            v.sales_commission_percent,
            v.initial_total_cost,
            v.total_rental_revenue,
            v.maintenance_cost,
            v.operating_cost,
            v.current_customer,
            v.current_rental_agreement,
            v.available_from
        from `tabMotor Vehicle` v
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="v.status, v.selling_price desc, v.vehicle_title",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Status", "status", "Data", 100),
        _col("Model Year", "model_year", "Int", 90),
        _col("Odometer", "current_odometer", "Float", 100),
        _col("Selling Item", "selling_item", "Link", 125, "Item"),
        _col("Selling Price", "selling_price", "Currency", 115),
        _col("Minimum Price", "minimum_selling_price", "Currency", 115),
        _col("Commission %", "sales_commission_percent", "Percent", 105),
        _col("Acquisition", "initial_total_cost", "Currency", 110),
        _col("Rental Revenue", "total_rental_revenue", "Currency", 120),
        _col("Maintenance", "maintenance_cost", "Currency", 110),
        _col("Operating", "operating_cost", "Currency", 105),
        _col("Current Customer", "current_customer", "Link", 145, "Customer"),
        _col("Active Agreement", "current_rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Available From", "available_from", "Datetime", 140),
    ]
    return columns, data, _status_chart(data), [_summary("Vehicles for Sale", len(data), "Int"), _currency_summary("Asking Value", sum(flt(row.selling_price) for row in data), filters, "Green"), _summary("Rental Conflicts", sum(1 for row in data if row.current_rental_agreement), "Int", "Orange")]


@report("Driver Document Expiry")
def driver_document_expiry(filters) -> ReportResult:
    params = {
        "today": getdate(nowdate()),
        "expiry_date": add_days(nowdate(), filters.expiry_days),
    }
    conditions = [
        "a.docstatus < 2",
        "a.status != 'Cancelled'",
        "(d.license_expiry_date <= %(expiry_date)s or d.passport_expiry_date <= %(expiry_date)s or d.international_permit_expiry <= %(expiry_date)s)",
    ]
    _append_optional(conditions, params, "a.customer", "customer", filters.get("customer"))
    data = _sql(
        """
        select
            a.name as rental_agreement,
            a.customer,
            a.vehicle,
            a.status as rental_status,
            d.full_name,
            d.phone,
            d.email,
            d.nationality,
            d.license_number,
            d.license_country,
            d.license_expiry_date,
            d.passport_number,
            d.passport_expiry_date,
            d.international_permit_number,
            d.international_permit_expiry
        from `tabRental Agreement Driver` d
        inner join `tabRental Agreement` a on a.name = d.parent and d.parenttype = 'Rental Agreement'
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="d.license_expiry_date asc, a.expected_return_datetime desc",
    )
    today = getdate(nowdate())
    for row in data:
        row.license_days_remaining = (getdate(row.license_expiry_date) - today).days if row.license_expiry_date else None
        row.passport_days_remaining = (getdate(row.passport_expiry_date) - today).days if row.passport_expiry_date else None
        row.permit_days_remaining = (getdate(row.international_permit_expiry) - today).days if row.international_permit_expiry else None
    data.sort(key=lambda row: min([value for value in (row.license_days_remaining, row.passport_days_remaining, row.permit_days_remaining) if value is not None] or [999999]))
    columns = [
        _col("Rental Agreement", "rental_agreement", "Link", 135, "Rental Agreement"),
        _col("Driver", "full_name", "Data", 180),
        _col("Customer", "customer", "Link", 140, "Customer"),
        _col("Vehicle", "vehicle", "Link", 120, "Motor Vehicle"),
        _col("Rental Status", "rental_status", "Data", 105),
        _col("Phone", "phone", "Data", 115),
        _col("Nationality", "nationality", "Link", 105, "Country"),
        _col("License", "license_number", "Data", 115),
        _col("License Country", "license_country", "Link", 115, "Country"),
        _col("License Expiry", "license_expiry_date", "Date", 105),
        _col("License Days", "license_days_remaining", "Int", 100),
        _col("Passport", "passport_number", "Data", 110),
        _col("Passport Expiry", "passport_expiry_date", "Date", 110),
        _col("Passport Days", "passport_days_remaining", "Int", 105),
        _col("International Permit", "international_permit_number", "Data", 130),
        _col("Permit Expiry", "international_permit_expiry", "Date", 105),
        _col("Permit Days", "permit_days_remaining", "Int", 95),
    ]
    expired = sum(1 for row in data if any(value is not None and cint(value) < 0 for value in (row.license_days_remaining, row.passport_days_remaining, row.permit_days_remaining)))
    return columns, data, None, [_summary("Documents Due", len(data), "Int", "Orange"), _summary("Drivers with Expired Documents", expired, "Int", "Red"), _summary("Window", filters.expiry_days, "Int")]


@report("Insurance Expiry")
def insurance_expiry(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", company_field=None, branch_field=None, date_field=None)
    params.update({"today": getdate(nowdate()), "expiry_date": add_days(nowdate(), filters.expiry_days), "company": filters.company})
    conditions.extend(["m.company = %(company)s", "i.status != 'Cancelled'", "i.expiry_date <= %(expiry_date)s"])
    if filters.branch:
        conditions.append("m.branch = %(branch)s")
    elif filters.allowed_branches:
        placeholders = []
        for index, branch in enumerate(filters.allowed_branches):
            key = f"insurance_branch_{index}"
            params[key] = branch
            placeholders.append(f"%({key})s")
        conditions.append(f"m.branch in ({', '.join(placeholders)})")
    data = _sql(
        """
        select
            i.name as vehicle_insurance,
            i.vehicle,
            m.vehicle_title,
            m.license_plate,
            m.branch,
            i.provider,
            i.policy_number,
            i.coverage,
            i.start_date,
            i.expiry_date,
            i.premium,
            i.deductible,
            i.status,
            i.attachment
        from `tabVehicle Insurance` i
        inner join `tabMotor Vehicle` m on m.name = i.vehicle
        left join `tabMotor Vehicle` v on v.name = i.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="i.expiry_date asc",
    )
    today = getdate(nowdate())
    for row in data:
        row.days_remaining = (getdate(row.expiry_date) - today).days if row.expiry_date else None
    columns = [
        _col("Insurance", "vehicle_insurance", "Link", 125, "Vehicle Insurance"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Provider", "provider", "Link", 135, "Supplier"),
        _col("Policy", "policy_number", "Data", 125),
        _col("Coverage", "coverage", "Data", 180),
        _col("Start", "start_date", "Date", 100),
        _col("Expiry", "expiry_date", "Date", 100),
        _col("Days Remaining", "days_remaining", "Int", 110),
        _col("Premium", "premium", "Currency", 105),
        _col("Deductible", "deductible", "Currency", 105),
        _col("Status", "status", "Data", 95),
        _col("Attachment", "attachment", "Attach", 120),
    ]
    return columns, data, None, [_summary("Policies Due", len(data), "Int", "Orange"), _summary("Expired", sum(1 for row in data if cint(row.days_remaining) < 0), "Int", "Red"), _currency_summary("Premium", sum(flt(row.premium) for row in data), filters)]


@report("Registration Expiry")
def registration_expiry(filters) -> ReportResult:
    params = {"company": filters.company, "branch": filters.branch, "today": getdate(nowdate()), "expiry_date": add_days(nowdate(), filters.expiry_days)}
    conditions = ["v.company = %(company)s", "d.document_type = 'Registration'", "d.status != 'Cancelled'", "d.expiry_date <= %(expiry_date)s"]
    if filters.branch:
        conditions.append("v.branch = %(branch)s")
    elif filters.allowed_branches:
        placeholders=[]
        for index, branch in enumerate(filters.allowed_branches):
            key=f"registration_branch_{index}"
            params[key]=branch
            placeholders.append(f"%({key})s")
        conditions.append(f"v.branch in ({', '.join(placeholders)})")
    data = _sql(
        """
        select
            d.name as vehicle_document,
            d.vehicle,
            v.vehicle_title,
            v.license_plate,
            v.branch,
            d.document_number,
            d.issuer,
            d.issue_date,
            d.expiry_date,
            d.status,
            d.attachment
        from `tabVehicle Document` d
        inner join `tabMotor Vehicle` v on v.name = d.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="d.expiry_date asc",
    )
    today = getdate(nowdate())
    for row in data:
        row.days_remaining = (getdate(row.expiry_date) - today).days if row.expiry_date else None
    columns = [
        _col("Vehicle Document", "vehicle_document", "Link", 130, "Vehicle Document"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 180),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Registration No.", "document_number", "Data", 125),
        _col("Issuer", "issuer", "Data", 120),
        _col("Issue Date", "issue_date", "Date", 100),
        _col("Expiry Date", "expiry_date", "Date", 100),
        _col("Days Remaining", "days_remaining", "Int", 110),
        _col("Status", "status", "Data", 95),
        _col("Attachment", "attachment", "Attach", 120),
    ]
    return columns, data, None, [_summary("Registrations Due", len(data), "Int", "Orange"), _summary("Expired", sum(1 for row in data if cint(row.days_remaining) < 0), "Int", "Red")]


@report("Traffic Fines")
def traffic_fines(filters) -> ReportResult:
    params = {"company": filters.company, "branch": filters.branch, "from_date": filters.from_date, "to_date_exclusive": filters.to_date_exclusive}
    conditions = ["v.company = %(company)s", "f.violation_datetime >= %(from_date)s", "f.violation_datetime < %(to_date_exclusive)s"]
    if filters.branch:
        conditions.append("v.branch = %(branch)s")
    elif filters.allowed_branches:
        placeholders=[]
        for index, branch in enumerate(filters.allowed_branches):
            key=f"fine_branch_{index}"
            params[key]=branch
            placeholders.append(f"%({key})s")
        conditions.append(f"v.branch in ({', '.join(placeholders)})")
    _append_optional(conditions, params, "f.status", "status", filters.get("status"))
    data = _sql(
        """
        select
            f.name as traffic_fine,
            f.vehicle,
            v.vehicle_title,
            f.plate_number,
            v.branch,
            f.violation_datetime,
            f.authority,
            f.status,
            f.rental_agreement,
            f.customer,
            f.driver,
            f.fine_amount,
            f.administration_fee,
            f.fine_amount + f.administration_fee as total_charge,
            f.customer_charge_status,
            f.sales_invoice,
            f.reference_number
        from `tabTraffic Fine` f
        inner join `tabMotor Vehicle` v on v.name = f.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="f.violation_datetime desc",
    )
    columns = [
        _col("Traffic Fine", "traffic_fine", "Link", 125, "Traffic Fine"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 175),
        _col("Plate", "plate_number", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Violation", "violation_datetime", "Datetime", 145),
        _col("Authority", "authority", "Data", 120),
        _col("Status", "status", "Data", 105),
        _col("Agreement", "rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Customer", "customer", "Link", 140, "Customer"),
        _col("Driver", "driver", "Data", 140),
        _col("Fine", "fine_amount", "Currency", 100),
        _col("Admin Fee", "administration_fee", "Currency", 100),
        _col("Total", "total_charge", "Currency", 105),
        _col("Charge Status", "customer_charge_status", "Data", 110),
        _col("Sales Invoice", "sales_invoice", "Link", 125, "Sales Invoice"),
        _col("Reference", "reference_number", "Data", 120),
    ]
    return columns, data, _status_chart(data), [_currency_summary("Fine Value", sum(flt(row.total_charge) for row in data), filters, "Orange"), _currency_summary("Unbilled", sum(flt(row.total_charge) for row in data if not row.sales_invoice and row.customer_charge_status != "Waived"), filters, "Red"), _summary("Fines", len(data), "Int")]


@report("Damage Recovery")
def damage_recovery(filters) -> ReportResult:
    params = {"company": filters.company, "branch": filters.branch, "from_date": filters.from_date, "to_date_exclusive": filters.to_date_exclusive}
    conditions = ["v.company = %(company)s", "d.reported_on >= %(from_date)s", "d.reported_on < %(to_date_exclusive)s"]
    if filters.branch:
        conditions.append("v.branch = %(branch)s")
    elif filters.allowed_branches:
        placeholders=[]
        for index, branch in enumerate(filters.allowed_branches):
            key=f"damage_branch_{index}"
            params[key]=branch
            placeholders.append(f"%({key})s")
        conditions.append(f"v.branch in ({', '.join(placeholders)})")
    data = _sql(
        """
        select
            d.name as damage_report,
            d.reported_on,
            d.status,
            d.vehicle,
            v.vehicle_title,
            v.license_plate,
            v.branch,
            d.rental_agreement,
            d.customer,
            d.driver,
            d.damage_type,
            d.severity,
            d.location_on_vehicle,
            d.repair_estimate,
            d.actual_repair_cost,
            d.customer_liability,
            d.company_liability,
            d.amount_charged,
            d.sales_invoice,
            d.insurance_claim,
            d.maintenance_work_order
        from `tabVehicle Damage Report` d
        inner join `tabMotor Vehicle` v on v.name = d.vehicle
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="d.reported_on desc",
    )
    columns = [
        _col("Damage Report", "damage_report", "Link", 130, "Vehicle Damage Report"),
        _col("Reported", "reported_on", "Datetime", 140),
        _col("Status", "status", "Data", 100),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 175),
        _col("Plate", "license_plate", "Data", 100),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Agreement", "rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Customer", "customer", "Link", 140, "Customer"),
        _col("Driver", "driver", "Data", 140),
        _col("Type", "damage_type", "Data", 100),
        _col("Severity", "severity", "Data", 95),
        _col("Location", "location_on_vehicle", "Data", 100),
        _col("Estimate", "repair_estimate", "Currency", 105),
        _col("Actual Cost", "actual_repair_cost", "Currency", 110),
        _col("Customer Liability", "customer_liability", "Currency", 125),
        _col("Company Liability", "company_liability", "Currency", 120),
        _col("Charged", "amount_charged", "Currency", 105),
        _col("Sales Invoice", "sales_invoice", "Link", 125, "Sales Invoice"),
        _col("Insurance Claim", "insurance_claim", "Data", 125),
        _col("Work Order", "maintenance_work_order", "Link", 125, "Maintenance Work Order"),
    ]
    return columns, data, _status_chart(data), [_currency_summary("Damage Cost", sum(flt(row.actual_repair_cost or row.repair_estimate) for row in data), filters, "Orange"), _currency_summary("Customer Liability", sum(flt(row.customer_liability) for row in data), filters, "Blue"), _currency_summary("Recovered", sum(flt(row.amount_charged) for row in data), filters, "Green")]


@report("Excess Mileage Revenue")
def excess_mileage_revenue(filters) -> ReportResult:
    conditions, params = _conditions(filters, "rr", date_field="return_datetime")
    conditions.extend(["rr.docstatus = 1", "ct.category = 'Mileage'"])
    data = _sql(
        """
        select
            rr.name as rental_return,
            rr.rental_agreement,
            rr.customer,
            rr.vehicle,
            rr.branch,
            rr.return_datetime,
            rr.mileage_used,
            rr.included_mileage,
            rr.excess_mileage,
            c.quantity,
            c.rate,
            c.amount,
            rr.currency,
            rr.final_sales_invoice
        from `tabRental Return` rr
        inner join `tabRental Return Charge` c on c.parent = rr.name and c.parenttype = 'Rental Return'
        inner join `tabRental Charge Type` ct on ct.name = c.charge_type
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="rr.return_datetime desc",
    )
    columns = [
        _col("Return", "rental_return", "Link", 125, "Rental Return"),
        _col("Agreement", "rental_agreement", "Link", 125, "Rental Agreement"),
        _col("Customer", "customer", "Link", 140, "Customer"),
        _col("Vehicle", "vehicle", "Link", 115, "Motor Vehicle"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Return Date", "return_datetime", "Datetime", 140),
        _col("Mileage Used", "mileage_used", "Float", 105),
        _col("Included", "included_mileage", "Float", 95),
        _col("Excess", "excess_mileage", "Float", 95),
        _col("Billed Qty", "quantity", "Float", 95),
        _col("Rate", "rate", "Currency", 95, "currency"),
        _col("Revenue", "amount", "Currency", 105, "currency"),
        _col("Invoice", "final_sales_invoice", "Link", 125, "Sales Invoice"),
    ]
    return columns, data, None, [_summary("Excess KM", sum(flt(row.excess_mileage) for row in data), "Float"), _currency_summary("Mileage Revenue", sum(flt(row.amount) for row in data), filters, "Green"), _summary("Returns", len(data), "Int")]


@report("Customer Rental History")
def customer_rental_history(filters) -> ReportResult:
    conditions, params = _conditions(filters, "ra", date_field="pickup_datetime")
    conditions.append("ra.docstatus = 1")
    _append_optional(conditions, params, "ra.customer", "customer", filters.get("customer"))
    data = _sql(
        """
        select
            ra.customer,
            max(c.customer_name) as customer_name,
            count(distinct ra.name) as rentals,
            sum(case when ra.status in ('Completed', 'Closed') then 1 else 0 end) as completed_rentals,
            sum(case when ra.status = 'Cancelled' then 1 else 0 end) as cancelled_rentals,
            sum(coalesce(ra.duration_units, 0)) as rental_units,
            sum(coalesce(ra.grand_total, 0)) as contract_value,
            sum(coalesce(ra.discount_amount, 0)) as discounts,
            max(ra.pickup_datetime) as last_rental,
            count(distinct ra.vehicle) as vehicles_used
        from `tabRental Agreement` ra
        left join `tabCustomer` c on c.name = ra.customer
        where {where}
        group by ra.customer
        {order_by}
        """,
        conditions,
        params,
        order_by="contract_value desc",
    )
    columns = [
        _col("Customer", "customer", "Link", 145, "Customer"),
        _col("Customer Name", "customer_name", "Data", 180),
        _col("Rentals", "rentals", "Int", 90),
        _col("Completed", "completed_rentals", "Int", 95),
        _col("Cancelled", "cancelled_rentals", "Int", 95),
        _col("Rental Units", "rental_units", "Float", 100),
        _col("Contract Value", "contract_value", "Currency", 120),
        _col("Discounts", "discounts", "Currency", 105),
        _col("Vehicles Used", "vehicles_used", "Int", 105),
        _col("Last Rental", "last_rental", "Datetime", 145),
    ]
    return columns, data, None, [_summary("Customers", len(data), "Int"), _summary("Rentals", sum(cint(row.rentals) for row in data), "Int"), _currency_summary("Contract Value", sum(flt(row.contract_value) for row in data), filters, "Green")]


@report("Idle Vehicles")
def idle_vehicles(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    params["now_datetime"] = now_datetime()
    conditions.extend(["v.rentable = 1", "v.status = 'Available'"])
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.model_year,
            v.current_odometer,
            v.idle_days,
            v.utilization_percent,
            v.average_daily_revenue,
            v.profit,
            v.available_from,
            (
                select max(ra.actual_return_datetime)
                from `tabRental Agreement` ra
                where ra.vehicle = v.name and ra.docstatus = 1 and ra.status in ('Completed', 'Closed')
            ) as last_return,
            (
                select min(r.pickup_datetime)
                from `tabRental Reservation` r
                where r.vehicle = v.name and r.docstatus < 2 and r.status in ('Confirmed', 'Vehicle Assigned') and r.pickup_datetime >= %(now_datetime)s
            ) as next_reservation
        from `tabMotor Vehicle` v
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="v.idle_days desc, v.vehicle_title",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Model Year", "model_year", "Int", 90),
        _col("Odometer", "current_odometer", "Float", 100),
        _col("Idle Days", "idle_days", "Float", 95),
        _col("Utilization %", "utilization_percent", "Percent", 105),
        _col("Avg Daily Revenue", "average_daily_revenue", "Currency", 125),
        _col("Profit", "profit", "Currency", 110),
        _col("Available From", "available_from", "Datetime", 140),
        _col("Last Return", "last_return", "Datetime", 140),
        _col("Next Reservation", "next_reservation", "Datetime", 145),
    ]
    return columns, data, None, [_summary("Idle Vehicles", len(data), "Int", "Orange"), _summary("Idle Days", sum(flt(row.idle_days) for row in data), "Float"), _currency_summary("Idle Fleet Profit", sum(flt(row.profit) for row in data), filters)]


@report("Underperforming Vehicles")
def underperforming_vehicles(filters) -> ReportResult:
    conditions, params = _conditions(filters, "v", date_field=None)
    threshold = flt(filters.get("profit_threshold") or 0)
    params["profit_threshold"] = threshold
    conditions.extend(["v.status not in ('Sold', 'Retired')", "coalesce(v.profit, 0) <= %(profit_threshold)s"])
    data = _sql(
        """
        select
            v.name as vehicle,
            v.vehicle_title,
            v.license_plate,
            v.category,
            v.branch,
            v.status,
            v.initial_total_cost,
            v.total_rental_revenue,
            v.maintenance_cost,
            v.operating_cost,
            v.total_cost,
            v.profit,
            v.profit_margin,
            v.roi,
            v.utilization_percent,
            v.rental_days,
            v.idle_days,
            v.current_odometer
        from `tabMotor Vehicle` v
        where {where}
        {order_by}
        """,
        conditions,
        params,
        order_by="v.profit asc, v.utilization_percent asc",
    )
    columns = [
        _col("Vehicle", "vehicle", "Link", 125, "Motor Vehicle"),
        _col("Vehicle", "vehicle_title", "Data", 190),
        _col("Plate", "license_plate", "Data", 100),
        _col("Category", "category", "Link", 115, "Vehicle Category"),
        _col("Branch", "branch", "Link", 110, "Motor Branch"),
        _col("Status", "status", "Data", 100),
        _col("Acquisition", "initial_total_cost", "Currency", 110),
        _col("Rental Revenue", "total_rental_revenue", "Currency", 120),
        _col("Maintenance", "maintenance_cost", "Currency", 110),
        _col("Operating", "operating_cost", "Currency", 105),
        _col("Total Cost", "total_cost", "Currency", 110),
        _col("Profit", "profit", "Currency", 110),
        _col("Margin %", "profit_margin", "Percent", 95),
        _col("ROI %", "roi", "Percent", 90),
        _col("Utilization %", "utilization_percent", "Percent", 105),
        _col("Rental Days", "rental_days", "Float", 100),
        _col("Idle Days", "idle_days", "Float", 90),
        _col("Odometer", "current_odometer", "Float", 100),
    ]
    return columns, data, None, [_summary("Underperforming", len(data), "Int", "Red"), _currency_summary("Combined Profit", sum(flt(row.profit) for row in data), filters, "Red"), _summary("Average Utilization", sum(flt(row.utilization_percent) for row in data)/max(len(data),1), "Percent", "Orange")]


@report("Branch Performance")
def branch_performance(filters) -> ReportResult:
    enforce_company_branch(filters.company, filters.branch)
    branches = frappe.get_all(
        "Motor Branch",
        filters={"company": filters.company, "active": 1, **({"name": filters.branch} if filters.branch else {})},
        fields=["name", "branch_name"],
        order_by="branch_name",
    )
    allowed = set(filters.allowed_branches or [])
    if allowed:
        branches = [row for row in branches if row.name in allowed]
    data = []
    for branch in branches:
        fleet = frappe.db.count("Motor Vehicle", {"company": filters.company, "branch": branch.name})
        available = frappe.db.count("Motor Vehicle", {"company": filters.company, "branch": branch.name, "status": "Available"})
        active = frappe.db.count("Rental Agreement", {"company": filters.company, "branch": branch.name, "docstatus": 1, "status": ["in", ["Active", "Extended", "Overdue"]]})
        reservations = frappe.db.count("Rental Reservation", {"company": filters.company, "branch": branch.name, "docstatus": ["<", 2], "pickup_datetime": ["between", [filters.from_date, filters.to_date_exclusive]]})
        revenue = _scalar(
            """
            select coalesce(sum(si.base_net_total), 0)
            from `tabSales Invoice` si
            inner join `tabDagaar Motors ERP Link` dl
                on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
            inner join `tabRental Agreement` ra on ra.name = dl.rental_agreement
            where si.docstatus = 1 and si.company = %(company)s and ra.branch = %(branch)s
              and si.posting_date >= %(from_date)s and si.posting_date <= %(to_date)s
              and coalesce(dl.vehicle_sale, '') = ''
            """,
            {"company": filters.company, "branch": branch.name, "from_date": filters.from_date, "to_date": filters.to_date},
        )
        sale_revenue = _scalar(
            """
            select coalesce(sum(s.sale_price), 0)
            from `tabVehicle Sale` s
            where s.company = %(company)s and s.branch = %(branch)s and s.docstatus < 2
              and s.status in ('Invoiced', 'Delivered', 'Completed')
              and s.sale_date >= %(from_date)s and s.sale_date <= %(to_date)s
            """,
            {"company": filters.company, "branch": branch.name, "from_date": filters.from_date, "to_date": filters.to_date},
        )
        maintenance = _scalar(
            """
            select coalesce(sum(w.grand_total), 0)
            from `tabMaintenance Work Order` w
            where w.company = %(company)s and w.branch = %(branch)s and w.docstatus = 1
              and w.actual_end >= %(from_date)s and w.actual_end < %(to_date_exclusive)s
            """,
            {"company": filters.company, "branch": branch.name, "from_date": filters.from_date, "to_date_exclusive": filters.to_date_exclusive},
        )
        utilization = _scalar(
            """
            select coalesce(avg(s.utilization_percent), 0)
            from `tabUtilization Snapshot` s
            where s.company = %(company)s and s.branch = %(branch)s
              and s.snapshot_date >= %(from_date)s and s.snapshot_date <= %(to_date)s
            """,
            {"company": filters.company, "branch": branch.name, "from_date": filters.from_date, "to_date": filters.to_date},
        )
        held_deposits = _scalar(
            """
            select coalesce(sum(pe.unallocated_amount), 0)
            from `tabPayment Entry` pe
            inner join `tabRental Agreement` ra on ra.deposit_payment_entry = pe.name
            where pe.docstatus = 1 and ra.company = %(company)s and ra.branch = %(branch)s
            """,
            {"company": filters.company, "branch": branch.name},
        )
        data.append(
            frappe._dict(
                branch=branch.name,
                branch_name=branch.branch_name,
                fleet_size=fleet,
                available_vehicles=available,
                active_rentals=active,
                reservations=reservations,
                rental_revenue=revenue,
                sale_revenue=sale_revenue,
                maintenance_cost=maintenance,
                contribution=revenue + sale_revenue - maintenance,
                utilization_percent=utilization,
                deposits_held=held_deposits,
            )
        )
    data.sort(key=lambda row: row.contribution, reverse=True)
    columns = [
        _col("Branch", "branch", "Link", 125, "Motor Branch"),
        _col("Branch Name", "branch_name", "Data", 170),
        _col("Fleet", "fleet_size", "Int", 80),
        _col("Available", "available_vehicles", "Int", 90),
        _col("Active Rentals", "active_rentals", "Int", 105),
        _col("Reservations", "reservations", "Int", 100),
        _col("Rental Revenue", "rental_revenue", "Currency", 120),
        _col("Sale Revenue", "sale_revenue", "Currency", 115),
        _col("Maintenance", "maintenance_cost", "Currency", 115),
        _col("Contribution", "contribution", "Currency", 115),
        _col("Utilization %", "utilization_percent", "Percent", 105),
        _col("Deposits Held", "deposits_held", "Currency", 115),
    ]
    chart = {
        "data": {
            "labels": [row.branch_name or row.branch for row in data],
            "datasets": [
                {"name": _("Rental Revenue"), "values": [flt(row.rental_revenue) for row in data]},
                {"name": _("Contribution"), "values": [flt(row.contribution) for row in data]},
            ],
        },
        "type": "bar",
        "height": 300,
    } if data else None
    return columns, data, chart, [_summary("Branches", len(data), "Int"), _currency_summary("Rental Revenue", sum(flt(row.rental_revenue) for row in data), filters, "Green"), _currency_summary("Contribution", sum(flt(row.contribution) for row in data), filters, "Blue")]


def _monthly_chart(data, date_field, value_field, label):
    grouped = defaultdict(float)
    for row in data:
        date_value = row.get(date_field)
        if date_value:
            grouped[getdate(date_value).strftime("%Y-%m")] += flt(row.get(value_field))
    if not grouped:
        return None
    labels = sorted(grouped)
    return {
        "data": {"labels": labels, "datasets": [{"name": label, "values": [grouped[key] for key in labels]}]},
        "type": "line",
        "height": 280,
        "colors": ["#0f766e"],
    }


def _scalar(query: str, params: dict) -> float:
    value = frappe.db.sql(query, params)
    return flt(value[0][0]) if value and value[0] else 0.0
