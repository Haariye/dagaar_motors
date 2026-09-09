from frappe.model.document import Document

from dagaar_motors.services.naming import apply_configured_naming_series
from dagaar_motors.services.returns import cancel_return, process_return, validate_return


class RentalReturn(Document):
    def before_naming(self):
        apply_configured_naming_series(self)

    def validate(self):
        validate_return(self)

    def before_submit(self):
        if self.status != "Completed":
            self.status = "Completed"

    def on_submit(self):
        process_return(self)

    def before_cancel(self):
        cancel_return(self)