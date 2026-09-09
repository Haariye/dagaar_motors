from __future__ import annotations

from dagaar_motors.services.settings import get_settings_dict


SERIES_SETTING_BY_DOCTYPE = {
    "Rental Reservation": "reservation_series",
    "Rental Agreement": "agreement_series",
    "Rental Extension": "extension_series",
    "Rental Return": "return_series",
    "Vehicle Sale": "sale_series",
}


def apply_configured_naming_series(doc) -> None:
    """Apply the administrator-selected series before Frappe names a new document."""
    fieldname = SERIES_SETTING_BY_DOCTYPE.get(doc.doctype)
    if not fieldname or not doc.meta.has_field("naming_series"):
        return

    configured = (get_settings_dict().get(fieldname) or "").strip()
    if not configured:
        return

    field = doc.meta.get_field("naming_series")
    configured_options = [
        value.strip()
        for value in str(field.options or "").splitlines()
        if value.strip()
    ]
    if configured not in configured_options:
        field.options = "\n".join([*configured_options, configured])
    doc.naming_series = configured
