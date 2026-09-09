import frappe
from frappe import _
from frappe.model.document import Document

from dagaar_motors.services.accounting import ensure_vehicle_project
from dagaar_motors.services.fleet import (
    ensure_vehicle_erp_links,
    prepare_vehicle_document,
    validate_vehicle_document,
)
from dagaar_motors.services.state_machine import assert_transition
from dagaar_motors.utils.constants import VEHICLE_TRANSITIONS


class MotorVehicle(Document):
    def before_validate(self):
        prepare_vehicle_document(self)

    def validate(self):
        validate_vehicle_document(self)
        if not self.is_new():
            previous = frappe.db.get_value("Motor Vehicle", self.name, "status")
            if previous and previous != self.status:
                assert_transition(previous, self.status, VEHICLE_TRANSITIONS, _("Vehicle {0}").format(self.name))

        duplicate = frappe.db.get_value(
            "Motor Vehicle",
            {"license_plate": self.license_plate, "name": ["!=", self.name or ""]},
            "name",
        )
        if duplicate:
            frappe.throw(_("License plate {0} is already assigned to {1}.").format(self.license_plate, duplicate))
        if self.vin:
            duplicate_vin = frappe.db.get_value(
                "Motor Vehicle", {"vin": self.vin, "name": ["!=", self.name or ""]}, "name"
            )
            if duplicate_vin:
                frappe.throw(_("VIN {0} is already assigned to {1}.").format(self.vin, duplicate_vin))

    def after_insert(self):
        ensure_vehicle_erp_links(self)
        ensure_vehicle_project(self)

    def on_update(self):
        # Keep ERP links and the Item sales flag synchronized with this vehicle.
        ensure_vehicle_erp_links(self)
        if not self.project:
            ensure_vehicle_project(self)
