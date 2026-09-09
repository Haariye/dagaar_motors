from frappe.model.document import Document

from dagaar_motors.services.maintenance import validate_vehicle_expense


class VehicleExpense(Document):
    def validate(self):
        validate_vehicle_expense(self)

    def before_submit(self):
        self.status = "Posted"