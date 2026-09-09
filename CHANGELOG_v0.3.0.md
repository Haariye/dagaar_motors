# Motors (dagaar_motors) — v0.3.0 change summary

This release addresses the ten issues raised and keeps installation/migration smooth.

## 1. Reservation removed from the workflow
- Rental Agreement is now the single entry point. The home screen primary action
  is **New Rental**; reservation shortcuts were removed from the home screen and
  every workspace.
- The only reservation-based report was repointed to Rental Agreement and renamed
  **Rental Pipeline**. All 34 reports now key off Rental Agreement / operational data.
- The `reservation` field on Rental Agreement is hidden, and the Rental Reservation
  DocType is hidden from navigation. The DocType file is kept (dormant) so existing
  data and migrations never break. A migration patch removes the stale
  "Reservation Pipeline" report on upgrade.

## 2. Charges child table calculates amount and adds to Grand Total
- Each Charges row now computes `Amount = Quantity × Rate` (server + live in the grid).
- The charges total is folded into Net Amount, Tax and **Grand Total** (charged,
  not discounted).

## 3. Discount Amount field now works
- `Discount %` and `Discount Amount` now both work and are mutually exclusive:
  entering a percentage computes the amount; entering an amount is honoured directly.
  Both update the live pricing preview and the saved totals.

## 4. Checkout bug fixed (Draft → Active)
- "Check Out Vehicle" moved a Draft agreement straight to Active, which the state
  machine rejected. The transition table now allows Draft/Awaiting Approval → Active,
  so checkout works in one click.

## 5. Early return, deposit-first billing, daily revenue
- A security deposit is now **always requested** (falls back to a configurable
  **Default Deposit Percentage**, 20% by default, of the rental total).
- Default **Original Invoice Timing** is now **On Return** for fresh installs: the
  deposit is collected at checkout and the rental is billed at return for the
  **actual days used** (each started 24 hours = one day).
- Early returns recompute the base rental for the actual period. The final invoice
  is created and **deducted from the security deposit automatically**, and the
  remaining balance is refunded. New read-only fields on Rental Return show
  Actual Billable Days/Units, Actual Rental Amount and Early Return Credit.

## 6. "Available for Sale" visibility fixed
- The checkbox used to live inside a tab that only appeared once it was already
  ticked (impossible to enable). It now sits next to **Rentable** and appears when
  the vehicle is available and not rentable.

## 7. Friendlier steps
- One-click New Rental from the home screen and from a vehicle; live amount/total
  updates in the Charges grids; guided "mark for sale" hint when a vehicle is set
  non-rentable.

## 8. Dynamic linked fields
- Status and link fields continue to derive their options from the shared
  option/enum sources; no new hard-coded lists were introduced.

## 9. "ERPNext" labels renamed to "ERP …"
- ERP Links, ERP Records, ERP Documents, ERP; and related descriptions/headlines.

## 10. Calculations seed from the beginning odometer
- New vehicles seed current, last-service, last-checkout and last-return odometers
  from the acquisition (beginning) odometer, so mileage, service-due and
  profitability calculate correctly from day one.

---

## Please verify on a staging bench (accounting-sensitive path)
A live ERPNext bench is required to confirm runtime accounting/permission behaviour.
After `bench --site <site> migrate` and `bench build --app dagaar_motors`, please check:
1. Motors Settings shows **Default Deposit Percentage** and **Original Invoice Timing**
   (set to **On Return** to use the deposit-first model on an existing site; new
   installs default to it).
2. Create a Rental Agreement, collect the deposit, check out (Draft → Active in one click).
3. Process an **early** return: confirm Actual Rental Amount/Early Return Credit,
   the final invoice for actual days, deposit deduction, and refund of the remainder.
4. Confirm Charges rows add into Grand Total and both discount fields work.

Static release gate: `python3 tools/validate_repository.py` — PASSED.
