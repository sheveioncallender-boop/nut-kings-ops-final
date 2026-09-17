# Nut Kings Ops 19.0.1.4.7

## Physical inventory loading fix

Opening Physical Inventory from the sidebar previously displayed the page
without initializing its count rows. Products could be found by the scanner,
but adding them failed with “This product is not available in the current count
snapshot.” Warehouse shortcuts initialized the rows correctly.

The workspace now loads the selected warehouse's synchronized count rows on
sidebar entry, direct links, and offline reopening. It also populates an empty
count when the first online snapshot arrives. An untouched count refreshes with
the latest snapshot; entered quantities, including zero, and their original
system quantities are preserved during navigation and synchronization. Saved
counts retain their warehouse and original quantities when reopened. The count
warehouse selector respects the user's existing permissions.

The existing design and Odoo stock-count application are unchanged. Opening or
scanning a count does not apply an inventory adjustment. Submit & Apply continues
to queue the counted lines for the existing native Odoo stock-quant workflow,
including its checks for stock changes since the count began.

## Install

1. Pull the latest `main` in Cloudpepper and restart/redeploy Odoo.
2. Upgrade **Nut Kings Ops** to **19.0.1.4.7**.
3. Reopen the workspace online, reload it, and synchronize once on each device.
   The updated service worker caches the new workspace for offline use.

No new database fields or data migration are introduced.

## Verification

`tools/test_inventory_browser.cjs` exercises the real workspace startup and
browser interface against a local API fixture. It checks sidebar entry, barcode
addition, untouched and active count refreshes, saved counts, zero quantities,
warehouse switching, offline reopening, submission payloads, first-snapshot
loading, and permitted warehouse selection at desktop and mobile widths.

Run with Node and Playwright installed:

```sh
node nut_kings_ops/tools/test_inventory_browser.cjs
```

Set `BROWSER_EXECUTABLE` if using a separately installed Chromium binary. These
checks do not connect to a live Odoo database or alter real inventory. Live Odoo
application of an adjustment must be verified on the installed instance.
