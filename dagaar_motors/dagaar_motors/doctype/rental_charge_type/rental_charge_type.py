from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_charge_type


class RentalChargeType(Document):
    def validate(self):
        validate_charge_type(self)