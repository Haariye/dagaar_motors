from frappe.model.document import Document

from dagaar_motors.services.operations import apply_vehicle_block, validate_vehicle_block


class VehicleBlock(Document):
    def validate(self):
        validate_vehicle_block(self)

    def on_update(self):
        apply_vehicle_block(self)

    def on_trash(self):
        self.status = "Cancelled"
        apply_vehicle_block(self)