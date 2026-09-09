from frappe.model.document import Document

from dagaar_motors.services.extensions import apply_extension, cancel_extension, validate_extension
from dagaar_motors.services.naming import apply_configured_naming_series


class RentalExtension(Document):
    def before_naming(self):
        apply_configured_naming_series(self)

    def validate(self):
        validate_extension(self)

    def before_submit(self):
        if self.status not in {"Approved", "Invoiced"}:
            self.status = "Approved"

    def on_submit(self):
        apply_extension(self)

    def before_cancel(self):
        cancel_extension(self)