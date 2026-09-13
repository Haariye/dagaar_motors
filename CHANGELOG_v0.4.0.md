# Motors (dagaar_motors) — v0.4.0: financial integration

Focus of this release: make the money side ERPNext-native (Payment Entries on the
customer ledger), add a live account statement, and add a role-gated deposit waiver.

## 1. Deposits & refunds now use Payment Entries (not Journal Entries)
- Collecting a deposit now posts a **Payment Entry (Receive)** against the customer,
  so it appears in the customer's balance/ledger and can be reconciled natively.
  Refunds post a **Payment Entry (Pay)**.
- The Rental Agreement now has a **Deposit Payment Entry** link (and the Deposit
  Transaction has a Payment Entry link) so the voucher is traceable from the rental.
- Existing (historical) Journal-Entry deposits are left untouched.

## 2. Deposit applied to the return invoice natively
- On return, the final invoice pulls the customer's deposit advance automatically
  (native ERPNext advance allocation), so the deposit is deducted against the
  invoice on the customer ledger. Any unused deposit is refunded via a Payment
  Entry; if the invoice exceeds the deposit, the remainder stays as the customer's
  outstanding balance to collect.

## 3. Account Statement button (Rental Agreement → View → Account Statement)
- A live statement: rent accrues one day at a time (each started 24h = one day)
  from pickup to the actual return (or to "now" for ongoing/overdue rentals) as
  debits; charges and tax are debits; deposit and payments are credits; shows the
  running Balance Due.

## 4. Waive Deposit (role-gated)
- New Settings table **Deposit Waiver Roles** (multi-select of Role). Only users
  holding one of those roles see the **Waive Deposit** action (falls back to the
  standard approval roles if the table is empty, and requires "Allow Deposit
  Waiver" to be enabled). Checkout is allowed once a deposit is collected OR waived.

## 5. Checkout
- Still requires a deposit to be collected before checkout, unless it has been
  waived. The Collect Deposit action (added in the previous fix) now posts a
  Payment Entry.

---

## Updating an installed site
This release changes several files plus adds a doctype and fields, so replace the
whole app folder rather than hand-copying:

1. Back up first: `bench --site YOURSITE backup --with-files`.
2. Replace the contents of `apps/dagaar_motors/` with this version
   (keep your `.git` if present).
3. `bench --site YOURSITE migrate`
4. `bench build --app dagaar_motors`
5. `bench --site YOURSITE clear-cache && bench restart`

## Configure once (Motors Settings → Accounting / Security Deposit)
- **Default Deposit Receipt Account** (bank/cash) — required for deposit Payment Entries.
- **Default Deposit Refund Account** (bank/cash) — used for refunds.
- **Customer Receivable Account** — optional; if blank, the customer's default
  receivable is used.
- **Deposit Waiver Roles** — add the roles allowed to waive deposits.

## Please verify on staging (accounting is involved)
A live bench is needed to confirm Payment Entry behaviour on your chart of accounts:
1. Collect a deposit → a Payment Entry (Receive) is created, linked on the
   agreement, and the amount shows on the customer's ledger.
2. Check out (blocked until deposit collected or waived).
3. Return early → final invoice for actual days; deposit advance auto-applied;
   unused deposit refunded via Payment Entry; customer balance is correct.
4. Waive Deposit visible only to the configured roles; checkout works after waiving.
5. Account Statement shows daily accrual, payments and balance.

Static release gate: `python3 tools/validate_repository.py` — PASSED.
