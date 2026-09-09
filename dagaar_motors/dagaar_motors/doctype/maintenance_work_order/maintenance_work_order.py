from frappe.model.document import Document

from dagaar_motors.services.maintenance import (
    process_completed_work_order,
    validate_work_order,
    validate_work_order_submission,
)


class MaintenanceWorkOrder(Document):
    def validate(self):
        validate_work_order(self)

    def before_submit(self):
        validate_work_order_submission(self)

    def on_submit(self):
        process_completed_work_order(self)