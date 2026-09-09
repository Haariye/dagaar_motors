# Motors (`dagaar_motors`)

`dagaar_motors` is the technical Frappe app name. The user-facing product is **Motors**: a focused ERPNext application for rental, fleet, maintenance, vehicle sales, deposits, and vehicle profitability.

## v0.2 experience

The app is intentionally simple for daily users:

- **Motors** - clean home screen with New Reservation, Add Vehicle, Process Return, and Vehicle Sale.
- **Rental** - reservations, rental agreements, extensions, returns, and deposits.
- **Fleet** - vehicles, inspections, documents, transfers, blocks, and fleet reports.
- **Maintenance** - maintenance jobs, work orders, expenses, and maintenance rules.
- **Sales** - sellable vehicles, vehicle sales, customers, invoices, and profitability.
- **Reports** - management reports without crowding operational menus.
- **Settings** - configuration only.

No workspace is prefixed with the company name.

## Smart form behavior

- Selecting a **Customer** automatically fetches the linked primary Contact and contact details.
- Rental Agreement drivers are entered **inline**. The customer is suggested as the primary driver automatically and can be replaced or edited; there is no Driver master to create.
- Selecting a **Vehicle**, **Branch**, or **Rental Agreement** fills related company, branch, currency, category, locations, odometer, fuel, and other context automatically where applicable.
- Pricing previews refresh from the server as dates, vehicle/category, rental type, extras, or discount change.
- A vehicle uses the human **Vehicle Name** as its document name; there is no vehicle naming series.
- On first Vehicle save, Motors creates and links its ERPNext **Item** and **Asset** automatically. Purchase Date and Purchase Price are required so the Asset can be created correctly.
- The ERPNext Item's sales flag follows the vehicle's **Available for Sale** checkbox. A vehicle cannot enter the vehicle-sale workflow unless that checkbox is enabled.

## Release inventory

| Area | Included |
| --- | ---: |
| Normalized DocTypes | 49 |
| Simplified workspaces | 7 |
| Script Reports | 34 |
| Customer print formats | 8 |
| Motors home page | 1 |

The source includes centralized pricing, availability, rental, extension, return, deposit, accounting, maintenance, sale, reporting, permission, and audit services. Business rules remain server-validated; browser scripts only improve usability.

## Installation

```bash
cd ~/frappe-bench
bench get-app /path/to/dagaar_motors
bench --site your-site install-app dagaar_motors
bench --site your-site migrate
bench build --app dagaar_motors
bench clear-cache
bench restart
```

Open **Settings > Motors Settings**, run the setup health check, then open **Motors**.

## Quality gates

Source validation:

```bash
python3 tools/validate_repository.py
```

Staging validation:

```bash
bench --site your-site migrate
bench build --app dagaar_motors
bench --site your-site run-tests --app dagaar_motors
```

A live ERPNext bench is still required for final migration, accounting, permission, browser, scheduler, and concurrency validation before production use.

## Documentation

- [Technical architecture](ARCHITECTURE.md)
- [Installation](docs/INSTALLATION.md)
- [Configuration](docs/CONFIGURATION.md)
- [Administration](docs/ADMINISTRATION.md)
- [Rental agent guide](docs/RENTAL_AGENT_GUIDE.md)
- [Fleet and maintenance](docs/FLEET_MAINTENANCE_GUIDE.md)
- [Vehicle sales](docs/VEHICLE_SALES_GUIDE.md)
- [Accounting setup](docs/ACCOUNTING_SETUP.md)
- [Security and permissions](docs/SECURITY.md)
- [API guide](docs/API.md)
- [Testing](docs/TESTING.md)
- [Upgrade guide](docs/UPGRADE.md)
