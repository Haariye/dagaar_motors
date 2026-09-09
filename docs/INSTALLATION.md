# Installation and Upgrade Guide

## Supported versions

- Frappe Framework 15.x or 16.x
- ERPNext 15.x or 16.x on the same major version
- MariaDB/PostgreSQL according to the supported Frappe deployment

## Fresh installation

```bash
cd ~/frappe-bench
bench get-app /path/to/dagaar_motors
bench --site your-site install-app dagaar_motors
bench --site your-site migrate
bench build --app dagaar_motors
bench clear-cache
bench restart
```

## Upgrade

```bash
cd ~/frappe-bench/apps/dagaar_motors
git pull
cd ~/frappe-bench
bench --site your-site migrate
bench build --app dagaar_motors
bench clear-cache
bench restart
```

Back up the site before every upgrade. Never delete production records to complete a migration.

## Post-install checklist

1. Open **Dagaar Motors Settings**.
2. Select the default company, branch and currency.
3. Configure all income, expense, deposit, receivable and gain/loss accounts.
4. Select default cost center, project behavior, warehouse and tax templates.
5. Create Vehicle Categories, Rental Types, Pricing Rules and Deposit Rules.
6. Review role assignments and branch/company User Permissions.
7. Import or create vehicles.
8. Run the app tests on a staging site before production use.