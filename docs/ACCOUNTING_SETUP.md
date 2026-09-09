# Accounting Setup Guide

## Source of truth

ERPNext remains the General Ledger, receivable, payable, stock, asset, tax, project,
and payment source of truth. Dagaar Motors creates or links supported ERPNext documents
and stores bidirectional source references.

## Required mappings

At minimum configure:

- Rental and extension income
- Deposit liability and clearing
- Default Cost Center
- Rental and extension Items
- Mileage, fuel, damage, cleaning, and miscellaneous Items/accounts as used
- Maintenance, repair, accident, insurance, registration, fuel, and operating expenses
- Gain/loss on vehicle sale when applicable

Mappings resolve from Vehicle to Category to Branch to Settings. Every Account, Cost
Center, and Warehouse must belong to the transaction Company.

## Security deposits

Deposits are liabilities, not revenue. Collection, use, refund, and forfeiture create
immutable Deposit Transaction records. Allocation identifies damage, fuel, mileage,
fines, outstanding rent, cleaning, or another approved purpose. Never delete historical
deposit transactions.

## Rental billing

The original rental invoice follows the configured timing. Each extension retains its
own interval, pricing snapshot, and invoice. Return charges may create a separate final
invoice. Idempotency keys and source fields prevent duplicate automatic documents.

## Profitability reconciliation

Vehicle Profitability combines linked rental/sale revenue and vehicle operating costs.
Reconcile it to ERPNext Sales Invoice, Purchase Invoice, Expense Claim, Journal Entry,
Project, Cost Center, and General Ledger reports before relying on period-close figures.


## Vehicle sale revenue

Configure **Vehicle Sale Income Account** as the fallback when the linked Item has no company-specific Item Default income account.
