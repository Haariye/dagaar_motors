# Motors (dagaar_motors) v0.5.0 — Payment Entry–only deposits

## Big change
The custom deposit ledger is gone. **Security Deposit** and **Deposit Transaction**
doctypes are removed. Deposits are now pure ERPNext accounting:

- **Collect Deposit** → Payment Entry (Receive) = a customer advance (shows in the
  customer's balance). Linked on the agreement as *Deposit Payment Entry*.
- **Return** → the final Sales Invoice pulls the deposit advance automatically
  (capped to the invoice), so it reconciles natively on the customer ledger.
- **Refund Deposit** (new button) → Payment Entry (Pay) for the unused balance
  (deposit − amount applied), linked as *Deposit Refund Payment Entry*, and
  reconciled against the deposit advance (best-effort).
- **Waive Deposit** → role-gated via Settings ▸ Deposit Waiver Roles.
- **Account Statement** → daily rent accrual (debit) vs deposit/payments (credit).

Deposit state (required / collected / applied / unallocated / refunded /
refundable) is computed live from the Payment Entries — no separate ledger.

## Removed / rewired
- Deleted doctypes Security Deposit, Deposit Transaction and security_deposit.js.
- Reports **Deposit Liability** and **Deposit Refunds** now read Payment Entries.
- Cleaned hooks, permissions, analytics, notifications, install, erp links,
  form defaults, workspaces. Dropped the `security_deposit` field from Rental
  Agreement / Return / Reservation / ERP Link.
- New agreement fields: Deposit Refund Payment Entry, Deposit Waiver Reason.

## Migration (automatic on `bench migrate`)
Patch `v0_4/drop_deposit_ledger` deletes the old doctypes, their tables and the
old Security Deposit print format. Historical deposits that were posted as
Journal Entries in older versions stay as-is in the GL; only the app objects go.

## Deploy
    bench --site uat.dagaartech.com backup --with-files
    # upload + rsync the new app folder over apps/dagaar_motors, then:
    bench --site uat.dagaartech.com migrate
    bench build --app dagaar_motors
    bench --site uat.dagaartech.com clear-cache && bench restart

## Settings to confirm (Motors Settings)
- Default Deposit Receipt Account (bank/cash) — required
- Default Deposit Refund Account (bank/cash)
- Customer Receivable Account (optional; else customer default)
- Deposit Waiver Roles

## Verify on staging (accounting)
1. Collect deposit → PE (Receive) on customer ledger, linked on agreement.
2. Checkout blocked until collected or waived.
3. Return → invoice for actual usage; deposit auto-applied; customer balance right.
4. Refund Deposit button → PE (Pay) for leftover; balances net to zero.
5. Account Statement and Deposit Liability / Deposit Refunds reports read PEs.

Static gate: `python3 tools/validate_repository.py` — PASSED (49 doctypes, 34 reports).
