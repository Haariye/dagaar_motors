# Motors Release Manifest

## Package

- Technical app: `dagaar_motors`
- User-facing title: Motors
- Version: `0.2.1`
- License: MIT
- Publisher: Dagaar Technology

## Functional inventory

| Component | Count |
| --- | ---: |
| Normalized DocTypes | 49 |
| Simplified workspaces | 7 |
| Script Reports | 34 |
| Customer print formats | 8 |
| Motors home pages | 1 |

## Primary modules

- Rental quotation, reservation, agreement, inline drivers, checkout, extension, return, and reconciliation
- Fleet identity, automatic Item/Asset linkage, availability, mileage, inspections, transfers, blocks, insurance, accidents, and expenses
- Preventive maintenance, due generation, work orders, parts, labor, downtime, and workshop operations
- Security-deposit liability, collection, allocation, refund, forfeiture, waiver, and immutable transaction history
- Vehicle sales restricted to explicitly sellable vehicles, minimum-price approval, invoice integration, conflict prevention, and final disposal
- Pricing, seasonal rules, duration tiers, extras, mileage, discounts, source-linked accounting through `Dagaar Motors ERP Link`, and profitability
- Simple Motors home screen, operational workspaces, reports, print formats, alerts, and search

## Installation entry points

- Hooks: `dagaar_motors/hooks.py`
- Install and migrate setup: `dagaar_motors/setup/install.py`
- Compatibility layer: `dagaar_motors/compat/`
- Server commands: `dagaar_motors/api/`
- Domain services: `dagaar_motors/services/`
- Source release gate: `tools/validate_repository.py`
