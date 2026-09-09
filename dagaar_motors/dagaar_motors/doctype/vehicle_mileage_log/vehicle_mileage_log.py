import frappe
from frappe import _
from frappe.model.document import Document

from dagaar_motors.api.permissions import require_any_role


class VehicleMileageLog(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw(_("Vehicle Mileage Log entries are immutable. Create an authorized correction instead."))
        if self.is_correction:
            require_any_role("Dagaar Motors Fleet Manager", "Dagaar Motors Administrator")
            if not self.reason or not self.approved_by:
                frappe.throw(_("Mileage corrections require a reason and approving user."))

    def on_trash(self):
        frappe.throw(_("Vehicle Mileage Log entries cannot be deleted."))