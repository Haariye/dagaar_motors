# API Guide

All endpoints require an authenticated Frappe session or token and the relevant Dagaar
Motors role. Company/branch scope and server validations still apply.

## Pricing and availability

- `dagaar_motors.api.pricing.preview`
- `dagaar_motors.api.availability.available_vehicles`
- `dagaar_motors.api.availability.vehicle_conflicts`

## Rental lifecycle

- `dagaar_motors.api.rental.convert_quotation`
- `dagaar_motors.api.rental.confirm`
- `dagaar_motors.api.rental.assign`
- `dagaar_motors.api.rental.create_agreement`
- `dagaar_motors.api.rental.checkout`
- `dagaar_motors.api.rental.approve_extension`
- `dagaar_motors.api.rental.finalize_return`

## Deposits and fleet

- `dagaar_motors.api.deposits.transact`
- `dagaar_motors.api.fleet.vehicle_summary`
- `dagaar_motors.api.fleet.correct_mileage`
- `dagaar_motors.api.fleet.generate_maintenance`
- maintenance/work-order, block, transfer, fine, and sale commands in
  `dagaar_motors.api.fleet`

## Dashboard, search, and setup

- `dagaar_motors.api.dashboard.get_dashboard`
- `dagaar_motors.api.dashboard.get_operations`
- `dagaar_motors.api.search.global_search`
- `dagaar_motors.api.setup.health_check`

## Example

```bash
curl -X POST "https://erp.example.com/api/method/dagaar_motors.api.availability.available_vehicles" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  --data '{
    "company": "Example Company",
    "branch": "OSLO",
    "start_datetime": "2026-08-10 09:00:00",
    "end_datetime": "2026-08-12 09:00:00",
    "vehicle_category": "SUV"
  }'
```

Treat action endpoints as commands, not editable status shortcuts. Send the record name
and required action values; the server locks and revalidates the current state.
