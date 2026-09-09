from frappe.model.document import Document

from dagaar_motors.services.operations import validate_traffic_fine


class TrafficFine(Document):
    def validate(self):
        validate_traffic_fine(self)