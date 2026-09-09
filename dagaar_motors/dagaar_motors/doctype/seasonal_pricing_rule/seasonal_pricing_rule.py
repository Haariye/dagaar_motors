from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_seasonal_rule


class SeasonalPricingRule(Document):
    def validate(self):
        validate_seasonal_rule(self)