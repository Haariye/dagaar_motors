from frappe.model.document import Document

from dagaar_motors.services.maintenance import validate_maintenance_rule


class VehicleMaintenanceRule(Document):
    def validate(self):
        validate_maintenance_rule(self)