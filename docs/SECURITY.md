# Security and Permissions

## Roles

The app defines Administrator, Rental Manager, Rental Agent, Reservation Agent, Fleet
Manager, Maintenance Manager, Workshop User, Vehicle Sales Manager, Vehicle
Salesperson, Accountant, Cashier, Branch Manager, Auditor, and Read Only roles.

## Data scope

Company and Motor Branch User Permissions restrict lists, dashboards, reports, search,
and whitelisted commands. Critical endpoints re-check the target document or vehicle
scope before executing. Administrator and System Manager remain unrestricted.

## Server authority

Prices, discounts, availability, status transitions, mileage, deposit totals, invoice
source links, and sale/rental conflicts are recalculated or validated on the server.
Hidden or disabled browser fields are not security controls.

## Sensitive data

Driver and customer identification documents must use private File attachments and
appropriate Frappe permissions. Do not store payment-card secrets, passwords, API keys,
or credentials in Dagaar Motors fields or source control.

## Deployment controls

- Use TLS and supported Frappe/ERPNext releases.
- Restrict bench/server access and database backups.
- Review Guest and API users; no app endpoint is intended for guest access.
- Enable scheduler and background workers with least-privilege service accounts.
- Test Company/Branch restrictions through Desk and direct API requests.
- Review Error Log and Version records for failed or unusual commercial actions.
