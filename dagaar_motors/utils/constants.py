from __future__ import annotations

APP_ROLES = (
    "Dagaar Motors Administrator",
    "Dagaar Motors Rental Manager",
    "Dagaar Motors Rental Agent",
    "Dagaar Motors Reservation Agent",
    "Dagaar Motors Fleet Manager",
    "Dagaar Motors Maintenance Manager",
    "Dagaar Motors Workshop User",
    "Dagaar Motors Vehicle Sales Manager",
    "Dagaar Motors Vehicle Salesperson",
    "Dagaar Motors Accountant",
    "Dagaar Motors Cashier",
    "Dagaar Motors Branch Manager",
    "Dagaar Motors Auditor",
    "Dagaar Motors Read Only",
)

ADMIN_ROLES = {"Administrator", "System Manager", "Dagaar Motors Administrator"}

VEHICLE_STATUSES = (
    "Preparation",
    "Available",
    "Reserved",
    "Rented",
    "Inspection",
    "Maintenance",
    "Blocked",
    "In Transit",
    "For Sale",
    "Sold",
    "Retired",
)

VEHICLE_TRANSITIONS = {
    "Preparation": {"Available", "Maintenance", "Blocked", "For Sale", "Retired"},
    "Available": {"Reserved", "Rented", "Inspection", "Maintenance", "Blocked", "In Transit", "For Sale", "Retired"},
    "Reserved": {"Available", "Rented", "Blocked", "Maintenance"},
    "Rented": {"Inspection", "Maintenance", "Blocked"},
    "Inspection": {"Available", "Maintenance", "Blocked", "For Sale", "Retired"},
    "Maintenance": {"Inspection", "Available", "Blocked", "For Sale", "Retired"},
    "Blocked": {"Preparation", "Available", "Inspection", "Maintenance", "For Sale", "Retired"},
    "In Transit": {"Available", "Inspection", "Maintenance", "Blocked"},
    "For Sale": {"Available", "Reserved", "Sold", "Maintenance", "Blocked", "Retired"},
    "Sold": set(),
    "Retired": set(),
}

RESERVATION_STATUSES = (
    "Draft",
    "Quotation",
    "Pending",
    "Confirmed",
    "Vehicle Assigned",
    "Checked Out",
    "Completed",
    "Cancelled",
    "No Show",
)

RESERVATION_TRANSITIONS = {
    "Draft": {"Quotation", "Pending", "Confirmed", "Cancelled"},
    "Quotation": {"Pending", "Confirmed", "Cancelled"},
    "Pending": {"Confirmed", "Cancelled", "No Show"},
    "Confirmed": {"Vehicle Assigned", "Checked Out", "Cancelled", "No Show"},
    "Vehicle Assigned": {"Confirmed", "Checked Out", "Cancelled", "No Show"},
    "Checked Out": {"Completed"},
    "Completed": set(),
    "Cancelled": set(),
    "No Show": set(),
}

RESERVATION_BLOCKING_STATUSES = {"Confirmed", "Vehicle Assigned", "Checked Out"}
AGREEMENT_BLOCKING_STATUSES = {
    "Reserved",
    "Ready for Pickup",
    "Active",
    "Extension Requested",
    "Extended",
    "Overdue",
    "Return Processing",
}
MAINTENANCE_BLOCKING_STATUSES = {"Scheduled", "In Progress", "Quality Check"}
TRANSFER_BLOCKING_STATUSES = {"Approved", "In Transit"}
BLOCKING_VEHICLE_STATUSES = {
    "Preparation",
    "Reserved",
    "Rented",
    "Inspection",
    "Maintenance",
    "Blocked",
    "In Transit",
    "Sold",
    "Retired",
}

RENTAL_AGREEMENT_TRANSITIONS = {
    # "Active" is allowed directly from Draft/Awaiting Approval so a single
    # "Check Out Vehicle" action can take a fresh agreement straight to Active
    # without forcing the user through an intermediate "Ready for Pickup" step.
    "Draft": {"Awaiting Approval", "Ready for Pickup", "Active", "Cancelled"},
    "Awaiting Approval": {"Ready for Pickup", "Active", "Cancelled"},
    "Reserved": {"Ready for Pickup", "Active", "Cancelled"},
    "Ready for Pickup": {"Active", "Cancelled"},
    "Active": {"Extension Requested", "Extended", "Overdue", "Return Processing", "Cancelled"},
    "Extension Requested": {"Active", "Extended", "Overdue"},
    "Extended": {"Active", "Extension Requested", "Overdue", "Return Processing"},
    "Overdue": {"Extension Requested", "Extended", "Return Processing"},
    "Return Processing": {"Completed"},
    "Completed": {"Closed"},
    "Closed": set(),
    "Cancelled": set(),
}

DEFAULT_CHARGE_CODES = (
    ("RENTAL", "Rental Charge", "Rental"),
    ("EXTENSION", "Extension Charge", "Extension"),
    ("LATE", "Late Return", "Late Return"),
    ("MILEAGE", "Excess Mileage", "Mileage"),
    ("FUEL", "Fuel Charge", "Fuel"),
    ("DAMAGE", "Damage Recovery", "Damage"),
    ("CLEANING", "Cleaning Charge", "Cleaning"),
    ("FINE", "Traffic Fine", "Fine"),
    ("INSURANCE", "Insurance Charge", "Insurance"),
    ("DELIVERY", "Vehicle Delivery", "Delivery"),
    ("COLLECTION", "Vehicle Collection", "Collection"),
    ("DRIVER", "Driver Service", "Driver"),
    ("OTHER", "Miscellaneous Charge", "Other"),
)
