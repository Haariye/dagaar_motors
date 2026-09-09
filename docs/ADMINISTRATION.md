# Administrator Guide

## Daily controls

Use the **Motors** home screen for fleet status, pickups, returns, overdue
rentals, deposits, maintenance, revenue, and utilization. KPI cards and operations rows
open the underlying records or reports.

## Master-data governance

Only authorized administrators and managers should change pricing, account mappings,
deposit policy, discount limits, document requirements, or status masters. Test policy
changes with a future-dated quotation before applying them to live bookings.

## User setup

Assign the narrowest role required. Add Company and Motor Branch User Permissions for
branch users. Re-run permission tests after changing roles or User Permissions.

## Data import

Use Frappe Data Import for Vehicle Category, Rental Type, Motor Branch, Motor Vehicle,
Rental Pricing Rule, inline rental-driver data, historical mileage, and maintenance rules. Import
masters before transactions. Always test mappings on staging and keep unique VIN,
plate, code, and external reference values.

## Audit and corrections

Commercial history is append-oriented. Use dedicated extension, return, deposit,
mileage-correction, and reversal processes. Do not edit submitted documents directly
or delete linked source records.

## Period close

Before month-end close:

1. Resolve overdue/return-processing agreements.
2. Reconcile deposits held to the configured liability account.
3. Confirm rental, extension, return-charge, damage, fine, and vehicle-sale invoices.
4. Review unposted vehicle expenses and incomplete maintenance work orders.
5. Validate Vehicle Profitability against ERPNext General Ledger and project reports.
6. Export the operational and financial reports required by management.
