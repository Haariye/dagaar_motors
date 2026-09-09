from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_extra


class RentalExtra(Document):
    def validate(self):
        validate_extra(self)