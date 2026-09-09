from frappe.model.document import Document

from dagaar_motors.services.rental import validate_quotation


class RentalQuotation(Document):
    def validate(self):
        validate_quotation(self)