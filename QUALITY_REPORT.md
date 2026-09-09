# Motors Quality Report - 0.2.1

## Source release gate

The source package passes `python3 tools/validate_repository.py` with:

- 49 DocTypes
- 48 JavaScript files
- 11 Jinja templates, including eight customer print formats
- 239 Python files
- 34 reports
- 7 simplified workspaces

The gate validates Python and JavaScript syntax, JSON metadata integrity, field ordering, role metadata, hooks, report bundles, workspace links, SQL fields, print-template Jinja, required documentation, database-specific SQL policy, placeholder policy, and the absence of utility-billing source references.

## v0.2 usability controls

- No company-name prefixes in the visible workspace menu.
- Customer, branch, vehicle, and rental-agreement context is auto-fetched into related forms.
- Drivers are inline Rental Agreement child rows; no permanent driver master is required.
- Vehicle Name is the document name; no vehicle series is used.
- ERPNext Item and Asset are automatically created/linked on Vehicle save.
- Item sales eligibility and Vehicle Sale workflow both require the explicit Vehicle `sellable` flag.
- Old wide-table integration remains removed; app-owned ERP Link records preserve transaction traceability.

## Deployment gate still required

This environment does not contain the user's live Frappe/ERPNext bench. Run the documented staging migration, build, automated tests, accounting checks, permissions, browser workflows, scheduler checks, and concurrency tests before production approval.
