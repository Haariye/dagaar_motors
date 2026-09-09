# Fleet and Maintenance Guide

## Vehicle control

The Motor Vehicle status is lifecycle-controlled. Availability considers reservations,
active rentals, extensions, maintenance, blocks, transfers, sale status, and retirement.
Do not manually turn a sold, rented, blocked, or maintenance vehicle into Available.

## Mileage

Checkout, return, transfer, and maintenance events create immutable Vehicle Mileage Log
records. Odometer regression requires the correction workflow, reason, approving user,
and Fleet Manager/Administrator authority.

## Preventive maintenance

Create configurable Vehicle Maintenance Rules by vehicle or category. Triggers may use
kilometers, months, engine hours, or whichever occurs first. The scheduler and the
manual generation command create one active due record per vehicle/rule.

## Work orders

Schedule maintenance, then start the Vehicle Maintenance or Maintenance Work Order.
Starting work blocks the vehicle. Record parts, labor, external supplier, planned and
actual dates, odometer, cost, and attachments. Completion moves the vehicle to
Inspection before it returns to normal availability.

## Transfers, incidents, and documents

Use Vehicle Transfer for branch moves. Capture departure/arrival time, odometer, fuel,
driver, cost, and reason. Use Vehicle Block, Vehicle Accident, Vehicle Damage Report,
Vehicle Insurance, Traffic Fine, and Vehicle Document for their dedicated lifecycles so
availability, expiry alerts, costs, and customer recovery remain traceable.
