from __future__ import annotations


def get_notification_config():
    return {
        "for_doctype": {
            "Rental Agreement": {"status": ("in", ["Overdue", "Extension Requested", "Return Processing"])},
            "Rental Extension": {"status": ("in", ["Draft", "Awaiting Approval"])},
            "Security Deposit": {"status": ("in", ["Pending", "Partially Collected", "Refund Pending"])},
            "Vehicle Maintenance": {"status": ("in", ["Due", "Scheduled", "In Progress", "Quality Check"])},
            "Vehicle Sale": {"status": ("in", ["Awaiting Approval", "Approved", "Invoiced", "Delivered"])},
        },
        "for_module_doctypes": {
            "Dagaar Motors": [
                "Rental Agreement",
                "Rental Extension",
                "Security Deposit",
                "Vehicle Maintenance",
                "Vehicle Sale",
            ]
        },
    }