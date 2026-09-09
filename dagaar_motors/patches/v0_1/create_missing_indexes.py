import frappe


INDEXES = {
    "Motor Vehicle": [("company", "branch", "status"), ("license_plate",), ("vin",)],
    "Rental Reservation": [("vehicle", "pickup_datetime", "return_datetime", "status")],
    "Rental Agreement": [("vehicle", "pickup_datetime", "expected_return_datetime", "status")],
    "Rental Extension": [("rental_agreement", "new_end_datetime", "docstatus")],
    "Vehicle Maintenance": [("vehicle", "status", "planned_start")],
    "Vehicle Block": [("vehicle", "from_datetime", "to_datetime", "status")],
}


def execute():
    for doctype, indexes in INDEXES.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        table = f"tab{doctype}"
        for fields in indexes:
            try:
                frappe.db.add_index(doctype, list(fields), index_name=_index_name(table, fields))
            except Exception:
                # Existing indexes and database-specific limits are safe to ignore here.
                frappe.log_error(frappe.get_traceback(), f"Dagaar Motors index: {doctype} {fields}")


def _index_name(table, fields):
    base = "dm_" + "_".join(field[:12] for field in fields)
    return base[:60]