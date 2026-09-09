from frappe.model.document import Document

from dagaar_motors.services.naming import apply_configured_naming_series
from dagaar_motors.services.vehicle_sales import (
    cancel_vehicle_sale,
    process_vehicle_sale,
    validate_vehicle_sale,
    validate_vehicle_sale_submission,
)


class VehicleSale(Document):
    def before_naming(self):
        apply_configured_naming_series(self)

    def validate(self):
        validate_vehicle_sale(self)

    def before_submit(self):
        validate_vehicle_sale_submission(self)

    def on_submit(self):
        process_vehicle_sale(self)

    def before_cancel(self):
        cancel_vehicle_sale(self)