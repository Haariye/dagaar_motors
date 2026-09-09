from frappe.model.document import Document

from dagaar_motors.services.naming import apply_configured_naming_series
from dagaar_motors.services.rental import on_reservation_update, validate_reservation


class RentalReservation(Document):
    def before_naming(self):
        apply_configured_naming_series(self)

    def validate(self):
        validate_reservation(self)

    def on_update(self):
        on_reservation_update(self)