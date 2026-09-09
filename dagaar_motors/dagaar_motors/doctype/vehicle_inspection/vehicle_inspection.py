from frappe.model.document import Document

from dagaar_motors.services.operations import populate_inspection_from_template, process_inspection, validate_inspection


class VehicleInspection(Document):
    def before_validate(self):
        populate_inspection_from_template(self)

    def validate(self):
        validate_inspection(self)

    def on_submit(self):
        process_inspection(self)