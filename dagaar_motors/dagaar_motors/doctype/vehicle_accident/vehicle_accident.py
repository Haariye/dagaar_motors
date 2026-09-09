from frappe.model.document import Document

from dagaar_motors.services.operations import validate_accident


class VehicleAccident(Document):
    def validate(self):
        validate_accident(self)