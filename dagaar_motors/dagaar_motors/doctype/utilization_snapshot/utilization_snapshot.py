import frappe
from frappe import _
from frappe.model.document import Document


class UtilizationSnapshot(Document):
    def validate(self):
        if not self.is_new():
            existing = frappe.db.get_value(
                "Utilization Snapshot", self.name, ["snapshot_date", "vehicle"], as_dict=True
            )
            if existing and (str(existing.snapshot_date) != str(self.snapshot_date) or existing.vehicle != self.vehicle):
                frappe.throw(_("Snapshot date and vehicle are immutable."))
        duplicate = frappe.db.get_value(
            "Utilization Snapshot",
            {"snapshot_date": self.snapshot_date, "vehicle": self.vehicle, "name": ["!=", self.name or ""]},
            "name",
        )
        if duplicate:
            frappe.throw(_("A utilization snapshot already exists for this vehicle and date."))