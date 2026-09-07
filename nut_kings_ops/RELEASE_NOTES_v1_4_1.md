# Nut Kings Ops 19.0.1.4.1

This is a complete replacement package for Odoo 19 Community, not a hotfix overlay.

## 1.4.1 login hotfix

- Replaced the database-loaded workspace QWeb login template with a standalone module-owned HTML page.
- Eliminated the `Template not found: 'nut_kings_ops.workspace_login_page'` failure when hosted code restarts before or without a successful XML view import.
- Kept Odoo's standard `/web/login` completely unchanged.
- Updated application, API, static asset URLs, and service-worker cache to `1.4.1`.

## Workspace authentication

- Added a dedicated branded login at `/nutkings/login`.
- Left Odoo's standard `/web/login` template and assets untouched.
- Added role-aware landing pages and rejected accounts without a Nut Kings operational role.
- Added a separate workspace sign-out that protects unsynchronized actions and clears shared-device data.
- Bound offline queues and count drafts to their workspace owner so a later employee cannot view or synchronize another employee's saved device work.
- Restricted the workspace Backend link and `/nutkings/backend` helper to Odoo Settings administrators.

## Frontend user administration

- Added a manager-only **Workspace Users** page.
- Managers can create real Odoo users, set/reset passwords, activate or deactivate accounts, assign Nut Kings roles, and limit dispatcher service areas.
- Frontend-created staff are external workspace users: they authenticate through Odoo but do not receive Odoo backend-user or Inventory groups.
- Restricted Nut Kings backend menus and direct custom-model access to Odoo Settings administrators; operational roles work only through the controlled workspace APIs.
- The endpoint cannot edit Odoo administrator accounts or grant Settings access. When an existing operational account is edited, obsolete Nut Kings, backend-user, and Inventory group assignments are removed while unrelated groups are preserved. Accounts with other backend-granting groups are rejected rather than changed unsafely.
- Managers cannot deactivate their own account or remove their own manager role.

## Van inventory and manual rotation

- Added an itemized frontend stock view for every van, including its service areas and separate Odoo stock location.
- Added **Issue More Products** directly from a van's stock view.
- Products can be manually issued to the same van again; every issue creates another native Odoo Finished Goods-to-van transfer.
- Removed the automated dispatch-plan and rotation-recommendation workflow to keep the client process manual and easy to operate.
- Added itemized trip reconciliation rows to the workspace API.
- Added the originating Workspace User to native transfers, returns, frontend history, and printed transfer documents.
- Updated the operational frontend terminology from truck to van while retaining stable internal model and API field names for upgrade compatibility.

## Reliability and compatibility

- Corrected the Odoo 19 search-view and group-privilege definitions from earlier builds.
- Updated frontend workspace-user administration to Odoo 19's `res.users.group_ids` field.
- Removed all obsolete default-login inheritance and login asset files.
- Updated the application, API, and service-worker cache to `1.4.1`.
- Versioned the main workspace JavaScript and stylesheet URLs as `1.4.1` so browsers and proxies cannot reuse the previous frontend after upgrade.
- Changed workspace navigation caching to network-first so a signed-out user reaches the workspace login instead of a cached shell.
- Corrected workspace-session expiry handling to return users to `/nutkings/login`.
