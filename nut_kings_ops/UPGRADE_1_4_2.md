# Nut Kings Ops — original module, access update

**Version:** 19.0.1.4.2 · **Target:** Odoo 19 Community · **Status:** ready for staging verification; not installed or tested on a live Odoo database here.

This package updates the exact uploaded `nut_kings_ops-19.0.1.4.1(1).zip`. It keeps the same addon name, model names, XML IDs, original dashboard and login CSS, branding, screen structure, scanner, native stock locations, and offline database identity. It is not a replacement frontend or a new stock application.

## This update

| Workspace wording | Account assignment | Password entrance |
| --- | --- | --- |
| Raw Materials — Receiving | Office | `/nutkings/raw-materials/receiving/login` |
| Raw Materials — Issuing | Employee | `/nutkings/raw-materials/issuing/login` |
| Finished Goods — Receiving | Employee | `/nutkings/finished-goods/receiving/login` |
| Finished Goods — Issued | Office | `/nutkings/finished-goods/issued/login` |
| Administrator | Odoo Settings administrator | `/nutkings/admin/login` |

The original branded `/nutkings/login` now has a workspace selector. Each person uses their own Odoo username and password. An administrator can assign more than one workspace to the same personal account; that account uses the same password for its assigned workspaces. An already authenticated Odoo session can enter an assigned workspace directly. Login pages still request credentials.

The selected workspace shows its relevant warehouse and permitted actions. Server checks enforce the user's current role assignments. Staff cannot administer accounts, create products, set opening balances, or apply physical inventory adjustments through these workspaces. Administrators retain the original full dashboard and native Odoo product and inventory tools.

Only a Settings administrator can create, edit, reset passwords, activate, or deactivate workspace accounts. The existing Workspace Users screen creates real Odoo users with external workspace access. Existing administrator and unrelated backend accounts must be managed in the Odoo backend.

**Done by** appears on the transfer form, operation history, review, printout, and synchronization audit. Before validation it identifies the authenticated creator; after successful validation it identifies the authenticated person who completed that transfer. Native Odoo Created by preserves the original creator. Browser-supplied actor IDs are ignored. Completed records from the earlier release retain their existing stored attribution; this patch does not invent missing historical validator information.

The Nut Kings root backend menu now opens its native dashboard action. **`/web/login`, `/web`, and `/odoo` are not overridden.** Opening Operations Workspace remains an explicit menu choice.

The receipt API uses Odoo 19's `description_picking` field instead of the removed `stock.move.name` field. Failed account edits and direct transfer actions roll back within database savepoints. These changes retain the native receipt and transfer workflow.

## Preserved features and staged rollout

The existing receiving, issuing, native reservations, stock availability, forecast, detailed operations, returns, backorders, physical inventory, product details, reports, printing, scanner, responsive screens, offline capture, and automatic retry code remain in the module. This patch does not recreate those workflows. The two original warehouse location trees remain separate; no balances or locations are migrated or recreated by the patch.

Start staging with Raw Materials — Receiving, then Raw Materials — Issuing and Finished Goods — Receiving. Test stock taking and administrator stock tools as part of the stock stage. Purchasing is not added.

**Vans remain the last development and acceptance stage.** Existing van models, screens, and workflows are retained so the imported module is not stripped down. No new van functionality is implemented here. In the original module, Finished Goods — Issued is a dispatch to a selected van; that existing requirement is preserved. This access patch does not introduce a different, van-independent issue operation or finish van acceptance testing.

The existing offline queue and automatic synchronization are retained. A different authenticated user cannot submit another person's saved action or take over an existing synchronization event. A queue can synchronize the current user's work from multiple assigned workspaces; every action is authorized again against current Odoo roles. Server stock remains authoritative, and rejected actions remain visible for correction.

The original single-snapshot storage design is retained. Opening another entrance replaces the downloaded view when online; if the saved snapshot belongs to a different entrance, its data is not displayed. Open the intended entrance online before using it offline. New authentication and password changes require an internet connection. This release has not been certified for unattended or background synchronization while the app is closed.

## Upgrade on staging

1. Back up the Odoo database and filestore. Finish synchronizing existing device work before upgrading; do not reset browser storage to troubleshoot an unsynchronized queue.
2. Extract the package. Replace the existing `nut_kings_ops` addon directory with the included folder, preserving the same addon name. This package does not require `nut_kings_access` or `nut_kings_stock`.
3. Restart Odoo and upgrade **Nut Kings Ops** through Apps, or use your deployment's usual `-u nut_kings_ops --stop-after-init` process against the staging database. Copying Python files without upgrading the module is insufficient for the menu and field-label changes.
4. Sign in through the standard `/web/login`. Verify the normal backend stays open, then explicitly open the Operations Workspace.
5. Reload the workspace online to obtain v1.4.2 assets and its updated service worker. The existing IndexedDB name and version are unchanged.
6. Using an administrator account, assign the four workspace roles and test each entrance with its assigned personal account.

This ZIP is an Odoo addon, not a standalone SiteGround PHP application. Install it in the Odoo server's addons path. This update makes no hosting or deployment changes.

## Verification completed and remaining

Completed here: 12 focused Python tests, covering all 16 role/entrance combinations, native-authentication delegation and MFA redirect handling with doubles, bad passwords, forged entrance selection, administrator-only management, selected-workspace permissions, CSRF rejection, and offline-owner rejection. Python, JavaScript, XML, manifest, local references, screen structure, and original asset preservation are checked separately. These are source and isolated logic checks, not a live Odoo test result.

Five native Odoo HTTP/database tests are included in `tests/test_workspace_upgrade.py`. They cover password entrances, staff restrictions, native backend menu routing, a real receipt completed by a second Office user, and offline owner mismatch. Run these on an Odoo 19 test database using the normal module test runner, for example with `--test-enable --test-tags /nut_kings_ops --stop-after-init` during installation or upgrade.

Before daily use, verify on staging: native backend entry without a redirect loop; all four passwords and wrong-role denials; account creation/edit/password reset/deactivation; product and count restrictions; receipt/issue quantities and Done by on native records and printouts; offline disconnect/reconnect, retry without duplicate posting, shared-device ownership, and existing backorders/returns. Visual checks on phone, tablet, and desktop and end-to-end offline tests are still required. Vans follow after stock acceptance.

The package includes `SOURCE_COMPARISON.json` and `CHANGES_FROM_1_4_1.patch` so the changes can be compared against the uploaded source.
