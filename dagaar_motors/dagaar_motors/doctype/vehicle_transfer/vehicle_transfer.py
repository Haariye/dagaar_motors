from frappe.model.document import Document

from dagaar_motors.services.operations import process_transfer, validate_transfer


class VehicleTransfer(Document):
    def validate(self):
        validate_transfer(self)

    def on_submit(self):
        process_transfer(self)