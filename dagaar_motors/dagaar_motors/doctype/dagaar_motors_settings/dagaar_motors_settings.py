from frappe.model.document import Document

from dagaar_motors.services.master_data import settings_updated, validate_settings


class DagaarMotorsSettings(Document):
    def validate(self):
        validate_settings(self)

    def on_update(self):
        settings_updated(self)