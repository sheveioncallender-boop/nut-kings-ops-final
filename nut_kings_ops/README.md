# Nut Kings Ops 19.0.1.4.2 — Odoo 19 Community

This is a focused update of the exact uploaded v1.4.1 module. The original dashboard CSS, login CSS, branding, scanner, stock locations, and inventory workflows are retained. Read **UPGRADE_1_4_2.md** for current entrances, permissions, upgrade steps, and validation limits. The older release and validation files remain historical records.

Nut Kings Ops is a simplified operations workspace backed by native Odoo inventory records.

## Workspace and administration entrances

- **Nut Kings Workspace:** `/nutkings/login`
- **Odoo administration:** `/web/login`

The branded login includes a workspace selector. Dedicated entrances are `/nutkings/raw-materials/receiving/login`, `/nutkings/raw-materials/issuing/login`, `/nutkings/finished-goods/receiving/login`, and `/nutkings/finished-goods/issued/login`. Administrator workspace: `/nutkings/admin/login`.

The module does not inherit, replace, or style Odoo's default login. Operational staff use the branded workspace login; Odoo administrators continue to use the standard backend login. The workspace login is served from module-owned HTML and does not depend on a database QWeb template.

After a workspace login, the account's Odoo security groups determine the visible pages and allowed server actions. There is no role selector that can be used to bypass permissions.

## Operational roles

| Workspace role | Main workflow |
| --- | --- |
| Raw Materials — Receiving | Office: receive into Raw Materials |
| Raw Materials — Issuing | Employee: issue from Raw Materials |
| Finished Goods — Receiving | Employee: receive into Finished Goods |
| Finished Goods — Issued | Office: original dispatch workflow, including its existing van requirements |
| Administrator | Original full dashboard, counts, reports, Workspace Users, and Odoo backend |

Only Odoo Settings administrators can open **Workspace Users** to create, activate/deactivate, reset passwords, assign operational roles, and limit dispatchers to service areas. These remain real `res.users` accounts and Odoo groups; workspace-created accounts are external users without Odoo backend access. The screen cannot grant Odoo Settings administrator rights. Existing operational-manager membership does not grant account administration or physical inventory adjustments.

## Odoo remains the stock engine

- Raw Materials and Finished Goods use separate native stock locations.
- Receipts, issues, van loads, deliveries, and returns create native `stock.picking` and `stock.move` records, with the originating workspace employee recorded on each transfer.
- Each van has its own internal Odoo stock location, so its products and quantities remain separate.
- Reservations, availability, lots, detailed operations, validation, backorders, returns, forecasting, and physical inventory remain Odoo-native.
- The workspace provides a simplified role-based interface and an offline queue; it does not replace Odoo's stock rules.

## Manual van issue and rotation

Each van remains separate and shows its assigned service areas plus an itemized product balance. The dispatcher decides what to load or rotate manually:

1. Open a van under **Stock on Vans** to see every product currently assigned to it.
2. Choose **Issue More Products**, select any products and quantities, and complete the normal transfer.
3. The same product can be issued to that van again on a later load.
4. Every issue is another native Odoo transfer, so the quantity, employee, van, trip, service area, and time remain traceable.

There is no automatic sales-based rotation recommendation in the workspace.

## Offline operation and shared devices

Operational snapshots and pending actions are stored in IndexedDB and bound to the workspace employee who created them. Signing out is blocked while unsynchronized actions remain, and a successful sign-out clears the downloaded snapshot, local count drafts, and history. If another employee signs in before the previous employee safely signs out, the earlier work stays hidden and cannot synchronize under the new account.

Workspace-user administration requires a live server connection. Supported stock capture and manual van issues continue to use the existing offline queue.

## Deployment or upgrade

1. Replace the complete `nut_kings_ops` add-on folder with this package.
2. Restart/redeploy Odoo and update the Apps list.
3. Click **Upgrade** on Nut Kings Ops. Do not uninstall a working installation.
4. Open `/nutkings/login` and sign in with an Odoo Settings administrator for the initial setup.
5. Create the Nut Kings manager and staff accounts under **Workspace Users**.
6. Confirm `/web/login` is still the standard Odoo administrator login.
7. Confirm a frontend-created workspace account can use `/nutkings/login` but cannot enter the Odoo backend.

If a device retains an older workspace shell, open `/nutkings/reset` while signed in, clear the saved workspace, then reload `/nutkings/`.

## Mobile scanning

Rapid Scan and Physical Inventory can use a phone/tablet camera. Supported browsers use their multi-format barcode detector; the workspace also contains an offline EAN-13/EAN-8/UPC-A fallback. Hardware scanners and manual entry remain available.
