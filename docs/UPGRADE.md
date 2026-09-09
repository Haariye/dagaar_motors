# Upgrade Guide

## Before upgrade

1. Read `RELEASE_NOTES.md`.
2. Back up database and files.
3. Confirm the current site restores successfully on staging.
4. Record the installed Frappe, ERPNext, and Dagaar Motors versions.
5. Complete or document in-progress migrations and commercial transactions.

## Upgrade commands

```bash
cd ~/frappe-bench/apps/dagaar_motors
git pull
cd ~/frappe-bench
bench --site your-site migrate
bench build --app dagaar_motors
bench clear-cache
bench restart
bench --site your-site run-tests --app dagaar_motors
```

`after_migrate` refreshes roles, Dagaar Motors ERP Link records, initial masters, and
app-managed Print Formats idempotently. Schema/data changes must be delivered through
Frappe patches; production data must never be deleted to make an upgrade pass.

## Rollback

Stop writes, restore the pre-upgrade database and files, restore the matching app commit,
rebuild assets, clear cache, and restart. Do not attempt partial manual schema rollback
on a live site.
