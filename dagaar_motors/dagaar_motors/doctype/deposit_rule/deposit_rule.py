from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_deposit_rule


class DepositRule(Document):
    def validate(self):
        validate_deposit_rule(self)