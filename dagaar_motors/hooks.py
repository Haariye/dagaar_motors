from . import __version__ as app_version

app_name = "dagaar_motors"
app_title = "Motors"
app_publisher = "Dagaar Technology"
app_description = "Enterprise vehicle rental, fleet, maintenance and vehicle sales for ERPNext"
app_email = "support@dagaar.com"
app_license = "MIT"
required_apps = ["erpnext"]

app_logo_url = "/assets/dagaar_motors/images/dagaar-motors-logo.svg"
app_home = "/app/dagaar-motors-dashboard"

add_to_apps_screen = [
    {
        "name": "dagaar_motors",
        "logo": "/assets/dagaar_motors/images/dagaar-motors-logo.svg",
        "title": "Motors",
        "route": app_home,
        "has_permission": "dagaar_motors.api.permissions.can_access_app",
    }
]

app_include_css = "dagaar_motors.bundle.css"
app_include_js = "dagaar_motors.bundle.js"

doctype_js = {
    "Dagaar Motors Settings": "public/js/dagaar_motors_settings.js",
    "Motor Vehicle": "public/js/motor_vehicle.js",
    "Rental Reservation": "public/js/rental_reservation.js",
    "Rental Agreement": "public/js/rental_agreement.js",
    "Rental Extension": "public/js/rental_extension.js",
    "Rental Return": "public/js/rental_return.js",
    "Vehicle Maintenance": "public/js/vehicle_maintenance.js",
    "Vehicle Sale": "public/js/vehicle_sale.js",
    "Vehicle Expense": "public/js/vehicle_context.js",
    "Vehicle Transfer": "public/js/vehicle_context.js",
    "Vehicle Damage Report": "public/js/vehicle_context.js",
    "Traffic Fine": "public/js/vehicle_context.js",
    "Vehicle Accident": "public/js/vehicle_context.js",
}

doctype_list_js = {
    "Motor Vehicle": "public/js/motor_vehicle_list.js",
    "Rental Agreement": "public/js/rental_agreement_list.js",
}

before_migrate = "dagaar_motors.setup.install.before_migrate"
after_install = "dagaar_motors.setup.install.after_install"
after_migrate = "dagaar_motors.setup.install.after_migrate"
before_tests = "dagaar_motors.setup.install.before_tests"

permission_query_conditions = {
    "Motor Vehicle": "dagaar_motors.api.permissions.vehicle_query_conditions",
    "Rental Reservation": "dagaar_motors.api.permissions.reservation_query_conditions",
    "Rental Agreement": "dagaar_motors.api.permissions.agreement_query_conditions",
    "Rental Return": "dagaar_motors.api.permissions.return_query_conditions",
    "Vehicle Maintenance": "dagaar_motors.api.permissions.maintenance_query_conditions",
    "Vehicle Sale": "dagaar_motors.api.permissions.sale_query_conditions",
}

has_permission = {
    "Motor Vehicle": "dagaar_motors.api.permissions.has_branch_permission",
    "Rental Reservation": "dagaar_motors.api.permissions.has_branch_permission",
    "Rental Agreement": "dagaar_motors.api.permissions.has_branch_permission",
    "Rental Return": "dagaar_motors.api.permissions.has_branch_permission",
    "Vehicle Maintenance": "dagaar_motors.api.permissions.has_branch_permission",
    "Vehicle Sale": "dagaar_motors.api.permissions.has_branch_permission",
}

doc_events = {
    "Sales Invoice": {
        "validate": "dagaar_motors.services.integrations.validate_sales_invoice",
        "on_submit": "dagaar_motors.services.integrations.on_sales_invoice_submit",
        "on_cancel": "dagaar_motors.services.integrations.on_sales_invoice_cancel",
        "on_trash": "dagaar_motors.services.erp_links.remove_erp_link",
    },
    "Payment Entry": {
        "validate": "dagaar_motors.services.integrations.validate_payment_entry",
        "on_submit": "dagaar_motors.services.integrations.on_payment_entry_submit",
        "on_cancel": "dagaar_motors.services.integrations.on_payment_entry_cancel",
    },
    "Journal Entry": {
        "on_trash": "dagaar_motors.services.erp_links.remove_erp_link",
    },
}

scheduler_events = {
    "hourly": [
        "dagaar_motors.services.scheduler.mark_overdue_rentals",
        "dagaar_motors.services.scheduler.refresh_operational_alerts",
    ],
    "daily": [
        "dagaar_motors.services.scheduler.generate_maintenance_due",
        "dagaar_motors.services.scheduler.send_expiry_notifications",
        "dagaar_motors.services.scheduler.create_utilization_snapshot",
    ],
}

notification_config = "dagaar_motors.notifications.get_notification_config"

fixtures = [
    {"dt": "Role", "filters": [["name", "like", "Dagaar Motors%"]]},
]