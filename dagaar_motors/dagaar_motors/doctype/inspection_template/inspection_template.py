from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_inspection_template


class InspectionTemplate(Document):
    def validate(self):
        validate_inspection_template(self)