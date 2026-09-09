from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_category


class VehicleCategory(Document):
    def validate(self):
        validate_category(self)