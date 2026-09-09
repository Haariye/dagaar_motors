# Dagaar Motors Technical Architecture

## A. Architecture

Dagaar Motors is a modular Frappe application. ERPNext remains responsible for
general ledger, receivables, payables, stock, assets, taxes, customers, suppliers,
projects, cost centers, warehouses, and payment posting. Dagaar Motors owns the
automotive domain and links every commercial or operational record back to the
appropriate ERPNext document.

### Domain boundaries

| Boundary | Responsibility |
| --- | --- |
| Configuration | Company/branch defaults, accounting maps, numbering, policy and automation settings |
| Fleet | Vehicle identity, acquisition, location, mileage, status, documents, blocks and transfers |
| Pricing | Deterministic rate resolution, duration tiers, seasonal rules, mileage, extras, discounts and explanations |
| Availability | Atomic overlap detection across reservations, rentals, extensions, maintenance, blocks, transfers and sales |
| Rental | Quotation, reservation, agreement, checkout, extension, return, reconciliation and closing |
| Deposits | Liability tracking, collection, allocation, refund, forfeiture and immutable transaction history |
| Maintenance | Preventive rules, due calculation, inspections, work orders, parts/labor, downtime and vehicle blocking |
| Vehicle Sales | Inquiry/profile, price protection, ERPNext selling documents, ownership transfer and disposal |
| Accounting | Mapping hierarchy, invoice/payment creation, source references, project/cost-center propagation |
| Analytics | Operational KPIs, vehicle profitability, utilization, revenue, cost, aging and drill-down reports |

All critical commands execute through server-side services. DocType controllers are
thin orchestration layers. Client scripts improve usability but never serve as the
only validation layer.

### Transaction boundaries

Atomic service commands cover vehicle assignment, rental activation, extension,
return completion, deposit refund and vehicle sale. They acquire row locks where
supported, re-check the invariant inside the transaction, write source references,
and rely on the request transaction for commit/rollback. No controller hook calls
`frappe.db.commit()`.

### Idempotency

Generated invoices, projects, maintenance events, reminders and refunds use source
references and deterministic idempotency keys. Repeating a command returns the
existing linked document instead of creating a duplicate.

## B. Module Tree

```text
dagaar_motors/
├── api/                 # Stable whitelisted endpoints
├── compat/              # Frappe/ERPNext v15-v16 differences
├── config/              # Desktop/navigation integration
├── dagaar_motors/
│   ├── doctype/         # Normalized business documents and child tables
│   ├── page/            # Premium operations dashboard
│   ├── report/          # Script reports
│   └── workspace/       # Desk workspaces
├── public/              # Desk JS, CSS and product identity
├── services/            # Business rules and transaction commands
├── setup/               # Installation, roles, ERP link storage and seed masters
├── templates/           # Portal and print templates
├── tests/               # Unit and integration coverage
└── utils/               # Shared constants, dates, money and validation helpers
```

## C. DocType Map

### Configuration and masters

- **Dagaar Motors Settings** — singleton control center; company defaults, accounts,
  pricing, deposits, mileage, fuel, automation, project and sales behavior.
- **Motor Branch** — company-bound operational branch with warehouse, cost center,
  project and account overrides.
- **Vehicle Category** — category-level rental, deposit, mileage, driver, sale and
  maintenance policy.
- **Rental Type** — configurable city, trip or other billing/mileage behavior.
- **Rental Pricing Rule** — prioritized rule header with date, dimension, rate,
  discount/surcharge, tax and applicability fields.
- **Duration Pricing Tier** — child rows for configurable duration slabs.
- **Seasonal Pricing Rule** — reusable season/event multiplier and date recurrence.
- **Deposit Rule** — risk-, category-, customer-, vehicle- and duration-aware deposit.
- **Discount Authority** — role/user limits and approval thresholds.
- **Rental Extra** — configurable fixed/hour/day/week/month/quantity add-ons.
- **Rental Charge Type** — charge-to-item/account mapping for fuel, late, damage,
  cleaning, mileage, delivery and other charges.
- **Rental Document Requirement** — scenario-aware mandatory-document rule.
- **Vehicle Maintenance Rule** — mileage/date/engine-hour preventive schedule.
- **Inspection Template** / **Inspection Template Item** — reusable checklists.

### Fleet and lifecycle

- **Motor Vehicle** — complete vehicle identity, ownership, acquisition, ERP links,
  rental/sale policy, status, odometer, location and financial summary.
- **Vehicle Mileage Log** — immutable odometer event history and correction audit.
- **Vehicle Document** — registration, license, insurance and other expiry-tracked files.
- **Vehicle Block** — explicit operational, inspection, accident or administrative hold.
- **Vehicle Transfer** — branch/location movement with odometer, fuel, driver and cost.
- **Vehicle Insurance** — policy, premium, coverage, excess and expiry.
- **Vehicle Accident** — accident evidence, liability, insurance and downtime.

### Rental

- **Rental Agreement Driver** — inline child rows on each agreement; defaults from the customer/contact, remains fully editable, and requires no permanent driver master.
- **Rental Quotation** — pre-reservation commercial offer with pricing snapshot.
- **Rental Reservation** — demand, assignment, availability, documents, deposit and status.
- **Rental Agreement** — legal and financial contract; checkout/active lifecycle.
- **Rental Extension** — immutable extension interval and separate pricing/invoice link.
- **Rental Return** — return inspection, mileage, fuel, damage, charges and reconciliation.
- Child tables: quotation/reservation/agreement extras, agreement drivers and charges,
  return charges and pricing breakdown lines.

### Money, condition and maintenance

- **Security Deposit** / **Deposit Transaction** / **Deposit Allocation** — liability
  lifecycle, immutable financial events, and allocation trail.
- **Vehicle Inspection** / **Vehicle Inspection Item** — pre/post-rental, maintenance and sale evidence.
- **Vehicle Damage Report** — before/after damage, estimates, liability, insurance and recovery.
- **Traffic Fine** — violation-time rental/customer resolution and later billing.
- **Vehicle Expense** — vehicle/project-linked cost with ERPNext source document.
- **Vehicle Maintenance** — scheduled/due/completed service event.
- **Maintenance Work Order** / **Maintenance Work Order Item** — workshop execution,
  parts, labor, supplier, cost, invoice and downtime.
- **Vehicle Sale** — controlled sale, price approval, ERPNext sales links, transfer and disposal.

Relationships are Link fields rather than copied identifiers. Independent records use
separate DocTypes; ownership-only line items use child tables. High-volume filters use
`search_index` on vehicle, company, branch, status, date/time and customer fields.

## D. Workflow Map

### Reservation and rental

`Draft → Pending → Confirmed → Vehicle Assigned → Checked Out → Completed`

Cancellation and no-show are terminal branches. Confirmation and assignment re-check
availability. Checkout creates or links the agreement and validates customer, driver,
documents, deposit, payment and vehicle condition.

### Rental agreement

`Draft → Awaiting Approval → Ready for Pickup → Active → Return Processing → Completed → Closed`

`Active → Extension Requested → Extended → Active` is repeatable. `Active → Overdue`
is scheduler-driven. Only controlled commands can move operational states.

### Vehicle

`Preparation → Available → Reserved → Rented → Inspection → Available`

Additional branches are Maintenance, Blocked, Transfer, For Sale, Sold and Retired.
`Sold → Rented` and `Retired → Available` are prohibited without an authorized reversal process.

### Maintenance

`Planned → Due → Scheduled → In Progress → Quality Check → Completed`

In-progress work blocks rental availability. Completion updates service mileage/date and
re-evaluates the vehicle status.

### Vehicle sale

`Draft → Qualified → Reserved → Awaiting Approval → Approved → Invoiced → Delivered → Completed`

Final invoice/delivery is blocked while an overlapping reservation, active rental,
maintenance, transfer or administrative block exists.

## E. Accounting Map

| Event | ERPNext document | Posting principle |
| --- | --- | --- |
| Rental/extension/final charges | Sales Invoice | Configured Item/account, vehicle Project, branch Cost Center, source links |
| Customer receipt | Payment Entry | Allocated to linked invoice; rental and vehicle references retained |
| Security deposit collection | Journal Entry | Debit configured receipt account and credit deposit liability; never rental revenue |
| Deposit use | Journal Entry with invoice allocation | Debit deposit liability and credit receivable or the configured clearing account |
| Deposit refund | Journal Entry | Debit deposit liability and credit the configured refund account; duplicate refund protected |
| Maintenance/expense | Purchase Invoice, Expense Claim or Journal Entry | Vehicle Project and expense account mapping |
| Vehicle acquisition | Purchase Invoice/Asset/Stock | Linked to Motor Vehicle; acquisition cost captured without duplicate GL |
| Vehicle sale | Sales Order/Delivery Note/Sales Invoice | Linked Item/Asset/stock behavior; gain/loss mapping when applicable |

Mapping fallback is `Vehicle → Category → Branch → Company settings → Global settings`.
Every Account, Cost Center, Warehouse and Project is validated against the selected company.

## F. Pricing Engine

1. Normalize pickup/return times and calculate billable duration using configured grace,
   rounding and minimum-duration rules.
2. Load only enabled rules valid for company, branch, currency, date and booking context.
3. Score exact dimensions: vehicle, contract, customer, customer group, category,
   rental type, route, booking channel, promo, mileage package and one-way status.
4. Apply deterministic priority and reject ambiguous equal-priority conflicting rules.
5. Resolve hourly/daily/weekly/monthly/fixed-trip/kilometer base pricing.
6. Apply whole-duration or slab duration tiers.
7. Apply seasonal/event/weekend/holiday adjustments by configured priority.
8. Add mileage package, insurance, extras, relocation and other surcharges.
9. Apply automatic and user discounts, then enforce server-side authority/approval.
10. Apply tax behavior through the configured ERPNext tax template.
11. Round with currency precision and persist a human-readable price breakdown snapshot.

Extensions price only the new interval. Previously billed periods and invoices are never
recalculated or overwritten.

## G. Compatibility Strategy

`compat/version.py`, `compat/db.py`, `compat/navigation.py` and `compat/accounting.py`
contain version checks and framework differences. The rest of the domain imports only
compatibility functions, never scattered version conditionals. The support boundary is
Frappe/ERPNext 15.x and 16.x; future majors require adapting the compatibility layer and tests.

## H. Security Strategy

- Dedicated administrator, rental, reservation, fleet, maintenance, sales, cashier,
  accountant, branch manager, auditor and read-only roles.
- Role permissions plus company/branch User Permissions.
- Permission query conditions and `has_permission` checks for branch-sensitive records.
- No client-trusted price, discount, availability, mileage or status decisions.
- Parameterized/query-builder database access; no unsafe SQL interpolation.
- Private customer and driver attachments.
- No payment card secrets or credentials stored by this app.
- Approval and status decisions are tracked through Frappe Version and explicit fields.
- User-facing validation messages include the conflicting vehicle/document/date.

## I. Test Strategy

- Unit tests: duration, tier, season, rate priority, discounts, state transitions and mileage.
- Integration tests: reservation, checkout, invoicing, extension, return, deposits,
  maintenance, expenses, sale and ERPNext links.
- Concurrency tests: same-vehicle assignment, sale-versus-extension, maintenance-versus-
  reservation and duplicate refund.
- Permission tests: company, branch, role, API and attachment visibility.
- Accounting tests: source links, balanced documents, company ownership and mapping fallback.
- Migration tests: fresh install, upgrade patches, fixtures and idempotent after-install.

## J. Development Plan

1. Foundation, settings, roles, ERP link storage, compatibility and normalized masters.
2. Pricing engine and automated tests.
3. Availability, reservation and concurrency protection.
4. Agreement, checkout, extensions, return and reconciliation.
5. Accounting, invoices, payments and deposits.
6. Fleet mileage, documents, inspections, damage, fines and transfers.
7. Maintenance, work orders, expenses and downtime.
8. Vehicle sales and rental/sale conflict protection.
9. Reports, profitability, dashboard and workspaces.
10. Portal, print formats, operational hardening, performance and upgrade QA.

## Implementation Inventory

The initial release implements the core foundation through operational UX:

- 49 normalized DocTypes with controllers and role permissions.
- Central pricing, availability, rental, extension, return, deposit, accounting,
  maintenance, vehicle-sale, analytics, reporting, and security services.
- Eight Desk workspaces and a custom management command center.
- 34 Script Reports with company/branch scope and drill-down links.
- Eight app-managed customer-facing Jinja print formats.
- Setup health checks, scheduled tasks, Dagaar Motors ERP Link records, tests, and
  a source-only release gate.

Live bench migration, accounting, permission, and concurrency validation remains a
deployment gate for each target ERPNext site and database engine.