from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_driver


class RentalDriver(Document):
    def validate(self):
        validate_driver(self)