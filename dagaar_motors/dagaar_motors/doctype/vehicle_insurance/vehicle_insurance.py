from frappe.model.document import Document

from dagaar_motors.services.master_data import validate_vehicle_insurance


class VehicleInsurance(Document):
    def validate(self):
        validate_vehicle_insurance(self)