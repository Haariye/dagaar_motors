# Configuration Guide

## 1. Run the setup health check

Open **Dagaar Motors Settings** and select **Setup > Run Setup Health Check**. The
readiness panel separates critical configuration from recommended operational setup.
The system is not operationally ready until every critical check passes.

## 2. Organization

Select the default Company, Currency, and Motor Branch. Every Motor Branch must belong
to one Company and should carry its Warehouse, Cost Center, location, and any branch
account overrides.

Use Frappe **User Permission** records for both Company and Motor Branch. Users without
explicit restrictions may see every branch allowed by their roles.

## 3. Accounting and stock

Configure the rental, extension, mileage, fuel, damage, cleaning, deposit liability,
deposit clearing, expense, and vehicle-sale gain/loss accounts. Accounts, Cost Centers,
and Warehouses are validated against the selected Company.

Create non-stock service Items for rental charges and optional stock/service Items for
other charges. Vehicle sale Items may be created per vehicle when that setting is
enabled.

## 4. Pricing

Create at least one active **Rental Pricing Rule**. Rules may be filtered by Company,
Branch, vehicle, category, rental type, customer, dates, route, currency, booking
channel, promo code, and duration. Lower-level exact matches win through deterministic
priority and specificity; equal conflicting rules are rejected.

Use child **Duration Pricing Tier** rows for slab or whole-duration pricing. Seasonal
rules may use date ranges, recurring annual periods, weekdays, weekends, or events.
Every calculated quote stores a pricing snapshot and human-readable breakdown.

## 5. Rental policy

Configure deposit requirements, mileage behavior, excess-kilometer rate, fuel policy,
checkout payment threshold, inspection requirements, duration limits, and invoicing
timing. Policy values can be overridden by Category, Branch, Vehicle, or specific rule
where the model supports it.

## 6. Masters

Create or review:

- Motor Branch
- Vehicle Category
- Rental Type
- Rental Pricing Rule
- Deposit Rule
- Discount Authority
- Rental Extra
- Rental Charge Type
- Rental Document Requirement
- Inspection Template
- Vehicle Maintenance Rule

Initial City Rate and Trip Rate masters and common charge types are installed as
editable starting records, not permanent hardcoded policy.

## 7. Vehicles

Create one **Motor Vehicle** record per physical vehicle. Enter VIN/chassis, engine,
plate, acquisition, ownership, category, branch, Item/Asset/Project links, odometer,
rental policy, and sale policy. Duplicate VIN, plate, or conflicting company/branch
configuration must be corrected before operations begin.

## 8. Notifications and automation

Review reminder lead times and invoice automation. Scheduled jobs detect overdue
rentals, maintenance due, document/insurance/registration expiry, operational alerts,
and utilization snapshots. Confirm the site scheduler is enabled in production.
