from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_pricing_rule


class RentalPricingRule(Document):
    def validate(self):
        validate_pricing_rule(self)