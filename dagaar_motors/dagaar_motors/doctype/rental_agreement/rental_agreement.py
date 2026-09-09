from frappe.model.document import Document

from dagaar_motors.services.naming import apply_configured_naming_series
from dagaar_motors.services.rental import activate_agreement, cancel_agreement, validate_agreement, validate_checkout


class RentalAgreement(Document):
    def before_naming(self):
        apply_configured_naming_series(self)

    def validate(self):
        validate_agreement(self)

    def before_submit(self):
        validate_checkout(self)

    def on_submit(self):
        activate_agreement(self)

    def before_cancel(self):
        cancel_agreement(self)