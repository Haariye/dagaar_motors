import frappe


def execute():
    """v0.4.x: the custom deposit ledger (Security Deposit / Deposit Transaction)
    is replaced by native Payment Entries. Remove the obsolete doctypes, their
    tables and the old print format."""
    for name in ["Dagaar Motors - Security Deposit Receipt"]:
        if frappe.db.exists("Print Format", name):
            frappe.delete_doc("Print Format", name, force=True, ignore_permissions=True)

    # Deposit Transaction is a child of Security Deposit, so drop it first.
    for doctype in ["Deposit Transaction", "Security Deposit"]:
        if frappe.db.exists("DocType", doctype):
            try:
                frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True, ignore_permissions=True)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"drop_deposit_ledger: {doctype}")
        frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
    frappe.db.commit()
