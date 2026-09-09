from frappe.model.document import Document

from dagaar_motors.services.maintenance import (
    cancel_maintenance,
    process_completed_maintenance,
    validate_maintenance,
    validate_maintenance_submission,
)


class VehicleMaintenance(Document):
    def validate(self):
        validate_maintenance(self)

    def before_submit(self):
        validate_maintenance_submission(self)

    def on_submit(self):
        process_completed_maintenance(self)

    def before_cancel(self):
        cancel_maintenance(self)