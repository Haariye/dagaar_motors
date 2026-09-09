# Testing and Release Gate

## Source-only gate

Run from the app repository before installation:

```bash
python3 tools/validate_repository.py
```

It validates Python compilation, JavaScript syntax, DocType field/order and permission
metadata, child links, hooks, reports, workspaces, custom SQL fields, print Jinja,
required documents, and prohibited placeholder/source patterns.

## Live staging gate

```bash
cd ~/frappe-bench
bench --site staging.example.com backup --with-files
bench --site staging.example.com migrate
bench build --app dagaar_motors
bench --site staging.example.com run-tests --app dagaar_motors
```

Also test with the actual production database engine, ERPNext minor version, tax setup,
chart of accounts, stock settings, and User Permissions.

## Mandatory business scenarios

1. Two agents attempt to reserve the same vehicle for overlapping time.
2. Original rental is billed at one rate; extension uses a new rate without changing the original invoice.
3. Checkout 50,000 km, return 50,650 km, included 500 km; bill 150 excess km.
4. Maintenance becomes due at the configured date/kilometer trigger and blocks availability.
5. Vehicle sale fails during active rental, succeeds after close, then future rental fails.
6. Two users attempt the same deposit refund or automatic invoice command.
7. Branch-restricted users test lists, dashboards, reports, global search, and direct API calls.
8. All generated ERPNext accounting documents balance and belong to the correct Company.
9. Fresh install, upgrade migration, scheduler jobs, print formats, and rollback from backup.

## Acceptance evidence

Capture test results, source record names, generated accounting document names, and any
Error Log entries. Do not describe a release as bug-free; approve it from reproducible
evidence on the target environment.
