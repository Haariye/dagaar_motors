from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_branch


class MotorBranch(Document):
    def validate(self):
        validate_branch(self)