from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from dagaar_motors.api.permissions import require_any_role
from dagaar_motors.compat.db import lock_document
from dagaar_motors.services.audit import append_audit
from dagaar_motors.services.settings import get_settings_dict
from dagaar_motors.services.state_machine import transition_vehicle
from dagaar_motors.utils.money import quantize


def prepare_vehicle_document(doc):
    # Vehicle names are human-readable, never a series. Suggest a useful name but
    # keep the user's own name when they entered one.
    if not doc.vehicle_title:
        title_parts = [doc.model_year, doc.brand or doc.manufacturer, doc.model, doc.license_plate]
        doc.vehicle_title = " ".join(str(part).strip() for part in title_parts if part and str(part).strip())
    if not doc.vehicle_title:
        frappe.throw(_("Enter a Vehicle Name, or enter enough vehicle details for Motors to suggest one."))

    doc.initial_total_cost = sum(
        flt(doc.get(fieldname))
        for fieldname in (
            "purchase_price",
            "acquisition_taxes",
            "import_cost",
            "customs_cost",
            "registration_cost",
            "preparation_cost",
        )
    )
    if not doc.rental_category:
        doc.rental_category = doc.category
    if doc.is_new():
        # Everything is measured from the vehicle's beginning (acquisition)
        # odometer, so seed the running and reference readings from it. This
        # keeps mileage, service-due, and profitability distance calculations
        # correct from the very first save without any manual entry.
        beginning = flt(doc.acquisition_odometer)
        if not flt(doc.current_odometer):
            doc.current_odometer = beginning
        if not flt(doc.last_service_odometer):
            doc.last_service_odometer = beginning
        if not flt(doc.last_checkout_odometer):
            doc.last_checkout_odometer = beginning
        if not flt(doc.last_return_odometer):
            doc.last_return_odometer = beginning
    if doc.is_new() and doc.rentable and doc.status in {None, "", "Preparation"}:
        doc.status = "Available"
    if doc.branch and not doc.current_location:
        branch = frappe.get_cached_doc("Motor Branch", doc.branch)
        doc.current_location = branch.get("pickup_location") or branch.get("city") or branch.get("branch_name")


def ensure_vehicle_item(vehicle: str | object) -> str | None:
    doc = frappe.get_doc("Motor Vehicle", vehicle) if isinstance(vehicle, str) else vehicle
    if doc.item and frappe.db.exists("Item", doc.item):
        _sync_vehicle_item_flags(doc.item, doc.sellable)
        return doc.item

    settings = get_settings_dict()
    if settings.get("auto_create_vehicle_item") in (0, "0", False):
        return None

    asset_category = _ensure_asset_category(doc.company, settings)
    item_code = doc.name
    if frappe.db.exists("Item", item_code):
        item_name = item_code
        item = frappe.get_doc("Item", item_name)
        if item.meta.has_field("is_fixed_asset") and not item.is_fixed_asset:
            if frappe.db.exists("Stock Ledger Entry", {"item_code": item.name}):
                frappe.throw(
                    _("Item {0} already has stock activity and cannot be converted into a vehicle Asset item. Link a fixed-asset Item instead.").format(item.name)
                )
            item.is_stock_item = 0
            item.is_fixed_asset = 1
            item.asset_category = asset_category
            if item.meta.has_field("is_sales_item"):
                item.is_sales_item = cint(doc.sellable)
            item.save(ignore_permissions=True)
        else:
            _sync_vehicle_item_flags(item.name, doc.sellable)
    else:
        item_group = settings.get("vehicle_item_group") or "Vehicles"
        if not frappe.db.exists("Item Group", item_group):
            root_group = (
                frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
                or frappe.db.get_value("Item Group", {"is_group": 1}, "name")
                or "All Item Groups"
            )
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": item_group,
                    "parent_item_group": root_group,
                    "is_group": 0,
                }
            ).insert(ignore_permissions=True)

        stock_uom = settings.get("default_stock_uom") or (
            "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")
        )
        if not stock_uom:
            frappe.throw(_("Configure a default Stock UOM before creating vehicle Items."))

        item_values = {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": doc.vehicle_title,
            "description": f"{doc.vehicle_title} · Plate {doc.license_plate or 'N/A'} · VIN {doc.vin or 'N/A'}",
            "item_group": item_group,
            "stock_uom": stock_uom,
            "is_stock_item": 0,
            "is_sales_item": cint(doc.sellable),
            "is_purchase_item": 0,
        }
        item_meta = frappe.get_meta("Item")
        if item_meta.has_field("is_fixed_asset"):
            item_values["is_fixed_asset"] = 1
        if item_meta.has_field("asset_category"):
            item_values["asset_category"] = asset_category
        if item_meta.has_field("auto_create_assets"):
            item_values["auto_create_assets"] = 0
        item = frappe.get_doc(item_values)
        item.insert(ignore_permissions=True)
        item_name = item.name

    frappe.db.set_value(
        "Motor Vehicle",
        doc.name,
        {"item": item_name, "selling_item": item_name},
        update_modified=False,
    )
    doc.item = item_name
    doc.selling_item = item_name
    return item_name



def _sync_vehicle_item_flags(item_code: str, sellable) -> None:
    """Keep the ERPNext Item sales flag aligned with the vehicle's explicit Sellable checkbox."""
    meta = frappe.get_meta("Item")
    if not meta.has_field("is_sales_item"):
        return
    desired = cint(sellable)
    current = cint(frappe.db.get_value("Item", item_code, "is_sales_item"))
    if current != desired:
        frappe.db.set_value("Item", item_code, "is_sales_item", desired, update_modified=False)


def ensure_vehicle_asset(vehicle: str | object) -> str | None:
    doc = frappe.get_doc("Motor Vehicle", vehicle) if isinstance(vehicle, str) else vehicle
    if doc.asset and frappe.db.exists("Asset", doc.asset):
        return doc.asset

    settings = get_settings_dict()
    if settings.get("auto_create_vehicle_asset") in (0, "0", False):
        return None

    item_code = doc.item or ensure_vehicle_item(doc)
    if not item_code:
        return None

    existing = frappe.db.get_value(
        "Asset",
        {"item_code": item_code, "company": doc.company, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        frappe.db.set_value("Motor Vehicle", doc.name, "asset", existing, update_modified=False)
        doc.asset = existing
        return existing

    location = _ensure_asset_location(doc.branch)
    purchase_date = doc.purchase_date or nowdate()
    asset_value = flt(doc.initial_total_cost or doc.purchase_price)
    if asset_value <= 0:
        frappe.throw(
            _("Enter a Purchase Price greater than zero so Motors can create the linked ERPNext Asset."),
            title=_("Vehicle Asset Value Required"),
        )
    asset_meta = frappe.get_meta("Asset")
    asset_values = {
        "doctype": "Asset",
        "asset_name": doc.vehicle_title,
        "item_code": item_code,
        "company": doc.company,
        "purchase_date": purchase_date,
        "available_for_use_date": purchase_date,
        "gross_purchase_amount": asset_value,
        "location": location,
    }
    optional_values = {
        "asset_owner": "Company",
        "asset_owner_company": doc.company,
        "is_existing_asset": 1,
        "calculate_depreciation": 0,
        "asset_quantity": 1,
        "cost_center": doc.cost_center,
    }
    for fieldname, value in optional_values.items():
        if value is not None and asset_meta.has_field(fieldname):
            asset_values[fieldname] = value
    asset = frappe.get_doc(asset_values)
    asset.insert(ignore_permissions=True)
    frappe.db.set_value("Motor Vehicle", doc.name, "asset", asset.name, update_modified=False)
    doc.asset = asset.name
    return asset.name


def ensure_vehicle_erp_links(vehicle: str | object) -> dict:
    doc = frappe.get_doc("Motor Vehicle", vehicle) if isinstance(vehicle, str) else vehicle
    item = ensure_vehicle_item(doc)
    asset = ensure_vehicle_asset(doc)
    return {"item": item, "asset": asset}


def _ensure_asset_category(company: str, settings: dict) -> str:
    configured = settings.get("vehicle_asset_category")
    if configured and frappe.db.exists("Asset Category", configured):
        return configured

    category_name = "Motor Vehicles"
    fixed_asset_account = frappe.db.get_value(
        "Account",
        {"company": company, "is_group": 0, "account_type": "Fixed Asset"},
        "name",
    )
    if not fixed_asset_account:
        candidates = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "root_type": "Asset"},
            or_filters={"account_name": ["like", "%Fixed%"], "name": ["like", "%Fixed%"]},
            pluck="name",
            limit_page_length=1,
        )
        fixed_asset_account = candidates[0] if candidates else None
    if not fixed_asset_account:
        frappe.throw(
            _("Motors could not auto-create the vehicle Asset because Company {0} has no leaf account with Account Type 'Fixed Asset'. Create/select a Fixed Asset account once, then save the vehicle again.").format(company),
            title=_("Vehicle Asset Setup"),
        )

    if frappe.db.exists("Asset Category", category_name):
        category = frappe.get_doc("Asset Category", category_name)
        if not any(row.company_name == company for row in category.accounts):
            category.append("accounts", {"company_name": company, "fixed_asset_account": fixed_asset_account})
            category.save(ignore_permissions=True)
    else:
        category = frappe.get_doc(
            {
                "doctype": "Asset Category",
                "asset_category_name": category_name,
                "non_depreciable_category": 1,
                "accounts": [{"company_name": company, "fixed_asset_account": fixed_asset_account}],
            }
        )
        category.insert(ignore_permissions=True)

    if frappe.db.exists("DocType", "Dagaar Motors Settings"):
        try:
            frappe.db.set_single_value("Dagaar Motors Settings", "vehicle_asset_category", category.name)
        except Exception:
            pass
    return category.name


def _ensure_asset_location(branch_name: str) -> str:
    branch = frappe.get_doc("Motor Branch", branch_name)
    if branch.get("asset_location") and frappe.db.exists("Location", branch.asset_location):
        return branch.asset_location

    location_name = f"{branch.branch_name} - Vehicles"
    existing = frappe.db.get_value("Location", {"location_name": location_name}, "name")
    if not existing:
        values = {"doctype": "Location", "location_name": location_name}
        meta = frappe.get_meta("Location")
        if meta.has_field("is_group"):
            values["is_group"] = 0
        location = frappe.get_doc(values)
        location.insert(ignore_permissions=True)
        existing = location.name
    frappe.db.set_value("Motor Branch", branch.name, "asset_location", existing, update_modified=False)
    return existing


def validate_vehicle_document(doc):
    if flt(doc.current_odometer) < flt(doc.acquisition_odometer):
        frappe.throw(_("Current odometer cannot be lower than acquisition odometer."))
    if doc.status == "Sold":
        doc.rentable = 0
    if not doc.sellable and doc.status in {"For Sale", "Sold"}:
        frappe.throw(_("Vehicle {0} is not marked Sellable.").format(doc.vehicle_title or doc.name))
    if doc.sellable and not doc.selling_item and doc.status in {"For Sale", "Sold"} and not doc.is_new():
        frappe.throw(_("A sellable vehicle must have a linked Item before it can be marked For Sale or Sold."))
    if doc.branch and doc.company:
        branch_company = frappe.get_cached_value("Motor Branch", doc.branch, "company")
        if branch_company and branch_company != doc.company:
            frappe.throw(_("Branch {0} belongs to company {1}, not {2}.").format(doc.branch, branch_company, doc.company))


def update_mileage(
    vehicle: str,
    odometer: float,
    event_type: str,
    *,
    source_doctype: str | None = None,
    source_name: str | None = None,
    event_datetime=None,
    correction: bool = False,
    reason: str | None = None,
    approved_by: str | None = None,
):
    lock_document("Motor Vehicle", vehicle)
    vehicle_doc = frappe.get_doc("Motor Vehicle", vehicle)
    previous = flt(vehicle_doc.current_odometer)
    odometer = flt(odometer)
    if odometer < previous:
        if not correction:
            frappe.throw(
                _("Odometer cannot decrease from {0} km to {1} km. Use the authorized correction workflow.").format(
                    previous, odometer
                )
            )
        require_any_role("Dagaar Motors Fleet Manager", "Dagaar Motors Administrator")
        if not reason or not approved_by:
            frappe.throw(_("Mileage correction requires a reason and approving user."))

    existing = None
    if source_doctype and source_name:
        existing = frappe.db.get_value(
            "Vehicle Mileage Log",
            {
                "vehicle": vehicle,
                "source_doctype": source_doctype,
                "source_name": source_name,
                "event_type": event_type,
            },
            "name",
        )
    if existing:
        return frappe.get_doc("Vehicle Mileage Log", existing)

    log = frappe.get_doc(
        {
            "doctype": "Vehicle Mileage Log",
            "vehicle": vehicle,
            "event_type": event_type,
            "event_datetime": event_datetime or now_datetime(),
            "odometer": odometer,
            "previous_odometer": previous,
            "distance": odometer - previous,
            "is_correction": int(correction),
            "approved_by": approved_by,
            "source_doctype": source_doctype,
            "source_name": source_name,
            "reason": reason,
        }
    )
    log.insert(ignore_permissions=True)

    values = {"current_odometer": odometer, "mileage_updated_on": log.event_datetime}
    if event_type == "Checkout":
        values["last_checkout_odometer"] = odometer
    elif event_type == "Return":
        values["last_return_odometer"] = odometer
    elif event_type == "Maintenance":
        values["last_service_odometer"] = odometer
        values["last_service_date"] = getdate(log.event_datetime)
    frappe.db.set_value("Motor Vehicle", vehicle, values, update_modified=True)
    return log


def add_mileage_log(
    vehicle: str,
    event_type: str,
    odometer: float,
    **kwargs,
):
    return update_mileage(vehicle, odometer, event_type, **kwargs)


def refresh_vehicle_availability_status(vehicle: str):
    doc = frappe.get_doc("Motor Vehicle", vehicle)
    if doc.status in {"Sold", "Retired"}:
        return doc.status
    active_agreement = frappe.db.get_value(
        "Rental Agreement",
        {"vehicle": vehicle, "docstatus": ["<", 2], "status": ["in", ["Active", "Extended", "Overdue", "Return Processing"]]},
        "name",
    )
    if active_agreement:
        target = "Rented"
    elif frappe.db.exists("Vehicle Maintenance", {"vehicle": vehicle, "docstatus": ["<", 2], "status": ["in", ["Scheduled", "In Progress", "Quality Check"]]}):
        target = "Maintenance"
    elif frappe.db.exists("Vehicle Block", {"vehicle": vehicle, "status": "Active"}):
        target = "Blocked"
    elif frappe.db.exists("Rental Reservation", {"vehicle": vehicle, "status": ["in", ["Confirmed", "Vehicle Assigned"]]}):
        target = "Reserved"
    elif doc.sellable and doc.status == "For Sale":
        target = "For Sale"
    else:
        target = "Available"
    if doc.status != target:
        try:
            transition_vehicle(doc, target, "Automatic status reconciliation")
        except Exception:
            # Reconciliation may cross a deliberately protected state; preserve history and log it.
            frappe.log_error(frappe.get_traceback(), f"Vehicle status reconciliation: {vehicle}")
    return target


def recalculate_vehicle_financials(vehicle: str, from_date=None, to_date=None) -> dict:
    vehicle_doc = frappe.get_doc("Motor Vehicle", vehicle)
    invoice_filters = [
        "si.docstatus = 1",
        "dl.reference_doctype = 'Sales Invoice'",
        "dl.motor_vehicle = %(vehicle)s",
    ]
    params = {"vehicle": vehicle}
    if from_date:
        invoice_filters.append("si.posting_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date:
        invoice_filters.append("si.posting_date <= %(to_date)s")
        params["to_date"] = to_date

    invoices = frappe.db.sql(
        f"""
        select
            sum(case when coalesce(dl.vehicle_sale, '') = '' then si.base_net_total else 0 end) as rental_revenue,
            sum(case when coalesce(dl.rental_extension, '') != '' then si.base_net_total else 0 end) as extension_revenue,
            sum(case when coalesce(dl.vehicle_sale, '') != '' then si.base_net_total else 0 end) as sale_revenue
        from `tabSales Invoice` si
        inner join `tabDagaar Motors ERP Link` dl
            on dl.reference_doctype = 'Sales Invoice' and dl.reference_name = si.name
        where {' and '.join(invoice_filters)}
        """,
        params,
        as_dict=True,
    )[0]
    expense = flt(
        frappe.db.sql(
            "select coalesce(sum(amount), 0) from `tabVehicle Expense` where vehicle = %s and docstatus = 1",
            (vehicle,),
        )[0][0]
    )
    maintenance = flt(
        frappe.db.sql(
            "select coalesce(sum(grand_total), 0) from `tabMaintenance Work Order` where vehicle = %s and docstatus = 1",
            (vehicle,),
        )[0][0]
    )
    rental_days = _calculate_rental_days(vehicle, from_date=from_date, to_date=to_date)
    utilization = frappe.db.sql(
        """
        select coalesce(sum(rented_hours), 0) as rented, coalesce(sum(available_hours), 0) as available,
               coalesce(sum(maintenance_hours), 0) as maintenance
        from `tabUtilization Snapshot`
        where vehicle = %(vehicle)s
          and (%(from_date)s is null or snapshot_date >= %(from_date)s)
          and (%(to_date)s is null or snapshot_date <= %(to_date)s)
        """,
        {"vehicle": vehicle, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )[0]

    rental_revenue = flt(invoices.rental_revenue)
    extension_revenue = flt(invoices.extension_revenue)
    sale_revenue = flt(invoices.sale_revenue)
    total_revenue = rental_revenue + sale_revenue
    acquisition = flt(vehicle_doc.initial_total_cost)
    total_cost = acquisition + expense + maintenance
    profit = total_revenue - total_cost
    distance = max(0, flt(vehicle_doc.current_odometer) - flt(vehicle_doc.acquisition_odometer))
    total_operational = flt(utilization.rented) + flt(utilization.available) + flt(utilization.maintenance)
    utilization_percent = (flt(utilization.rented) / total_operational * 100) if total_operational else 0

    values = {
        "total_rental_revenue": quantize(rental_revenue),
        "total_extension_revenue": quantize(extension_revenue),
        "total_sale_revenue": quantize(sale_revenue),
        "maintenance_cost": quantize(maintenance),
        "operating_cost": quantize(expense),
        "total_cost": quantize(total_cost),
        "profit": quantize(profit),
        "profit_margin": (profit / total_revenue * 100) if total_revenue else 0,
        "roi": (profit / acquisition * 100) if acquisition else 0,
        "rental_days": rental_days,
        "available_days": flt(utilization.available) / 24,
        "idle_days": flt(utilization.available) / 24,
        "maintenance_downtime_days": flt(utilization.maintenance) / 24,
        "utilization_percent": utilization_percent,
        "average_daily_revenue": (rental_revenue / rental_days) if rental_days else 0,
        "revenue_per_km": (rental_revenue / distance) if distance else 0,
        "cost_per_km": ((expense + maintenance) / distance) if distance else 0,
    }
    frappe.db.set_value("Motor Vehicle", vehicle, values, update_modified=False)
    return values


def _calculate_rental_days(vehicle: str, *, from_date=None, to_date=None) -> float:
    """Calculate completed rental time without database-specific date functions."""
    rows = frappe.get_all(
        "Rental Agreement",
        filters={"vehicle": vehicle, "docstatus": 1, "status": ["in", ["Completed", "Closed"]]},
        fields=["pickup_datetime", "actual_return_datetime", "expected_return_datetime"],
        limit_page_length=100000,
    )
    period_start = get_datetime(from_date) if from_date else None
    period_end = get_datetime(getdate(to_date) + timedelta(days=1)) if to_date else None
    seconds = 0.0
    for row in rows:
        start = get_datetime(row.pickup_datetime)
        end = get_datetime(row.actual_return_datetime or row.expected_return_datetime)
        if period_start:
            start = max(start, period_start)
        if period_end:
            end = min(end, period_end)
        if end > start:
            seconds += (end - start).total_seconds()
    return seconds / 86400