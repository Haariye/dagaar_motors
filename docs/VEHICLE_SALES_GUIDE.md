# Vehicle Sales Guide

## Preparation

Mark the vehicle sellable, configure its selling Item, asking price, minimum price, and
commission policy, then place it in **For Sale** when operationally appropriate.

## Sale workflow

Create Vehicle Sale with buyer, price, handover date, Item, and commercial details.
Below-minimum sales require approval when configured. Submission creates or links the
ERPNext Sales Invoice through the configured source references.

## Conflict protection

Final sale is blocked when the vehicle conflicts with an active or overlapping rental,
reservation, extension, maintenance event, transfer, block, or prohibited vehicle
status. A warning is not enough; the server rejects the transaction.

## Completion

After the submitted Sales Invoice and configured completion rule, the vehicle becomes
Sold, rental is permanently disabled, future rental assignment is rejected, buyer and
invoice links are stored, and sale profitability is recalculated.

Completed disposal cannot be casually cancelled. Use an authorized accounting and
ownership reversal process.
