from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_rental_type


class RentalType(Document):
    def validate(self):
        validate_rental_type(self)