from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_discount_authority


class DiscountAuthority(Document):
    def validate(self):
        validate_discount_authority(self)