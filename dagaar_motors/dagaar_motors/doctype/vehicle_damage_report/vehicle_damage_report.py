from frappe.model.document import Document

from dagaar_motors.services.operations import validate_damage_report


class VehicleDamageReport(Document):
    def validate(self):
        validate_damage_report(self)