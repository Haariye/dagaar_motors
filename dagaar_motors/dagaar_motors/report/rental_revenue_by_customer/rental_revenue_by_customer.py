from dagaar_motors.services.reports import execute_report


def execute(filters=None):
    return execute_report('Rental Revenue by Customer', filters)
