# Nut Kings Ops 19.0.1.4.4 — native warehouse stock visibility

## Problem

The existing module receives stock into `NK-RM-STOCK` and `NK-FG-STOCK`, but
creates their warehouse names as view locations outside any `stock.warehouse`.
Odoo 19's default product quantity domain includes descendants of registered
warehouse views. Consequently, the workspace can show a successfully received
unit while the native product form and forecast show zero.

## Change

- Register a Raw Materials Warehouse (`NKRM`) and Finished Goods Warehouse
  (`NKFG`) for each company using native Odoo warehouse creation.
- Adopt the **same existing stock-location records** as their main stock
  locations. Update the newly created native operation defaults and route
  endpoints to those locations. Archive only the empty stock locations that
  native warehouse creation generated during this transaction.
- Associate the existing Raw Materials Receiving/Issuing and Finished Goods
  Receiving/Issued operation types with their warehouse.
- Keep production and inventory-loss locations outside warehouse stock trees,
  so issues decrease stock and finished-goods receipts increase it.
- Default the native product/template forecast button to the matching Nut
  Kings warehouse, while retaining an explicitly selected warehouse.
- Run setup on module upgrade as well as installation. Repeated setup reuses
  warehouse and location records; a conflicting unrelated warehouse causes a
  clear validation error rather than being silently repurposed.

There is no receipt replay, inventory adjustment, direct quant write, replacement
move, or deletion of an existing location. Stock-location IDs, completed receipt
numbers, move IDs, lot history and Done by attribution remain intact. The UI,
workspace logins, purchasing scope and van workflow are unchanged.

This is a focused backend patch against the repository's 19.0.1.4.2 baseline,
matching the tested installation's workspace version. It does not replace the
separate login-chooser package. Apply these changed files to any newer deployment
rather than replacing its unrelated frontend files with an older full snapshot.

## Installation and verification

1. Apply this branch to an Odoo 19 staging copy of the current database.
2. Restart Odoo and upgrade **Nut Kings Ops** (`-u nut_kings_ops`). The upgrade
   migration adopts existing locations; do not uninstall the module or receive
   the same goods again.
3. Reopen the Peanuts product: its normal on-hand quantity should include the
   existing receipt. Open its native forecast and confirm **Raw Materials
   Warehouse** is selected.
4. Synchronize the workspace. For the original single-unit test, the workspace,
   product form and Raw Materials forecast should all show 1, assuming no other
   movements. The original receipt must still be Done with its original number.
5. Check a pending receipt, reserve/validate an issue, and receive a finished
   product. Confirm on-hand, incoming, outgoing and forecast quantities agree.

## Automated checks

Native Odoo regression coverage is in `tests/test_native_warehouses.py`:

- Reproduce the legacy completed-receipt mismatch and repair it without changing
  its quants, moves, document identity or Done by.
- Native forecast data and template/variant forecast actions.
- Raw-material incoming, reservations, available stock and completed issuing.
- Finished-goods receipts and warehouse separation.
- Native picking defaults and active route endpoints.
- Repeated setup, marker recovery after reinstall, company isolation and
  refusal to adopt an unrelated warehouse with a conflicting name/code.

Run against a disposable Odoo 19/PostgreSQL database:

```sh
odoo-bin -d nk_warehouse_test -i nut_kings_ops --test-enable \
  --test-tags /nut_kings_ops:TestNativeWarehouses --stop-after-init
```

Python syntax and patch consistency were checked locally. The Odoo integration
tests and database upgrade have **not been run**: this editing environment has no
Odoo server or PostgreSQL. Run the checks above before deploying to production.
