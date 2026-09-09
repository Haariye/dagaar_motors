# Release Notes

## 0.2.1 - Install compatibility fix

- Fixed installation on servers that still contain the removed v0.1 `Rental Driver` controller after an overlay upgrade.
- Restored only the legacy `validate_driver` callable required by that stale controller; the active v0.2 design still uses editable inline Rental Agreement driver rows and does not restore the Driver master to the source tree.

## 0.2.0 - Simplified Motors experience

- Renamed the visible application to **Motors** while keeping the technical app name `dagaar_motors`.
- Replaced company-prefixed workspace names with seven simple workspaces: Motors, Rental, Fleet, Maintenance, Sales, Reports, and Settings.
- Added migration cleanup for the old `Dagaar ...` workspaces.
- Rebuilt the Motors home page around four daily actions and four operational KPIs instead of a crowded executive dashboard.
- Added dynamic Customer -> Contact, Branch -> Company/Currency/Locations, Vehicle -> Company/Branch/Category/Odometer, and Rental Agreement -> return/extension context fetching.
- Added live server-side pricing previews as rental inputs change.
- Removed the permanent Rental Driver master from the active product. Drivers now live directly on Rental Agreement rows, default from the customer/contact, and remain editable.
- Added inline driver license/passport/ID attachment support and moved driver-expiry reporting/alerts to Rental Agreement driver rows.
- Vehicle documents now use the human **Vehicle Name** as the actual document name; vehicle naming series was removed.
- Vehicle save now automatically creates/links the ERPNext fixed-asset Item and Asset. Purchase Date and Purchase Price are required for a valid Asset value.
- ERPNext Item `is_sales_item` now follows the Vehicle **Available for Sale** checkbox.
- Vehicle Sale selection and server validation reject any vehicle not explicitly marked sellable.
- Preserved the v0.1.2 wide-table fix: no Dagaar Motors columns are added to Sales Invoice, Payment Entry, Journal Entry, or Purchase Invoice.

## 0.1.2 - Wide ERPNext table compatibility

- Removed all Dagaar Motors Custom Fields from Sales Invoice, Payment Entry, Journal Entry, and Purchase Invoice.
- Added `Dagaar Motors ERP Link`, an app-owned reference DocType that preserves traceability without widening ERPNext transaction tables.
- Added automatic cleanup of v0.1.0/v0.1.1 legacy Custom Field metadata before migrate/install.
- Refactored accounting, deposits, payment updates, dashboards, returns, fleet profitability, and reports to use the new ERP link table.
- Fixes MariaDB error 1118 (`Row size too large`) on mature/customized ERPNext sites.

## 0.1.1 - Installation compatibility fix

- Custom-field installation tolerates unrelated invalid legacy/custom Link fields on existing ERPNext DocTypes.

## 0.1.0 - Initial production foundation

- Centralized rental, pricing, availability, maintenance, deposits, accounting, sales, reporting, permissions, and audit architecture.
- No ERPNext core modifications.
