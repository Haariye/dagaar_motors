from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_vehicle_document


class VehicleDocument(Document):
    def validate(self):
        validate_vehicle_document(self)