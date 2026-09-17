# Nut Kings Ops 19.0.1.4.5 — Picking Policy upgrade error

## Cause and correction

When the 1.4.4 stock-visibility migration creates a second native warehouse,
Odoo 19 enables Storage Locations through a full `res.config.settings` wizard.
That can fail if an installed app supplies a required setting with no value,
as in the reported `default_picking_policy` error from Sales. Executing the
whole settings wizard during an upgrade also risks unrelated module changes.

Before creating a Nut Kings warehouse, setup now enables only the native
Storage Locations feature, including stock's internal operation types and
location-view transition. Odoo still creates its own warehouses, routes and
operation types, and manages the multi-warehouse feature. Existing Sales
picking policies and unrelated settings are not saved or overwritten.

The 1.4.4 location-adoption repair is retained. The 1.4.5 migration reuses the
same idempotent setup, whether 1.4.4 succeeded or its transaction rolled back.
No receipt is replayed and no inventory adjustment is made.

The subsequent `column stock_warehouse.nk_inventory_type does not exist` error
is consistent with the new Python model being loaded while the failed upgrade
rolled back its database changes. A completed module upgrade creates the field
through Odoo's normal schema update; no manual SQL column or replacement
receiving document is needed.

## Apply in Cloudpepper

1. Update the existing Nut Kings Ops repository to the latest `main` and
   restart/redeploy the Odoo instance so it loads the updated Python code.
2. In Odoo Apps, upgrade **Nut Kings Ops** to **19.0.1.4.5**. Do not uninstall it.
   If the missing-column error prevents using Apps, use Cloudpepper's Odoo
   module-upgrade task for `nut_kings_ops` on the same database instead. A
   restart alone does not perform the database upgrade.
3. Reopen Peanuts and its Raw Materials forecast, then synchronize the
   workspace. With only the original one-unit receipt, all three should show
   one unit. Keep the original completed receipt; do not receive it again.

## Verification

Python syntax and the change against Odoo 19's native warehouse/settings source
were checked locally. Regression coverage checks setup without any settings
wizard, native inventory feature activation, repeatability, and preservation
of a configured Sales policy. When `sale_stock` is installed, it also reproduces
a missing saved Picking Policy default.

The native tests and live upgrade have not been run in this editing environment,
which has no Odoo server or PostgreSQL. Run on a disposable Odoo 19 database:

```sh
odoo-bin -d nk_warehouse_test -i sale_stock,nut_kings_ops --test-enable \
  --test-tags /nut_kings_ops:TestNativeWarehouses --stop-after-init
```

The module continues to depend on Inventory only (plus its existing base app
dependencies); Sales is not added as a runtime dependency.
