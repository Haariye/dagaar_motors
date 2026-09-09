import frappe


def execute():
    """Remove the legacy 'Reservation Pipeline' report.

    Reservations are no longer part of the workflow; the pipeline report has
    been repointed to Rental Agreement and re-registered as 'Rental Pipeline'.
    Any stale standard report left over from an earlier install would otherwise
    fail to load because its source folder no longer exists.
    """
    if frappe.db.exists("Report", "Reservation Pipeline"):
        try:
            frappe.delete_doc("Report", "Reservation Pipeline", force=True, ignore_permissions=True)
        except Exception:
            frappe.db.set_value("Report", "Reservation Pipeline", "disabled", 1)

    # Drop the legacy report link from any saved workspaces so navigation
    # never points at the removed report.
    for name in frappe.get_all(
        "Workspace Link",
        filters={"link_type": "Report", "link_to": "Reservation Pipeline"},
        pluck="name",
    ):
        try:
            frappe.delete_doc("Workspace Link", name, force=True, ignore_permissions=True)
        except Exception:
            pass
