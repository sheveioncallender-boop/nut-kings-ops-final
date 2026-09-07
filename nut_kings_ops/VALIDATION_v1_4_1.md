# Nut Kings Ops 19.0.1.4.1 Validation

## Architecture review

- `/web/login` is not inherited, replaced, or included in frontend assets.
- `/nutkings/login` is standalone module-owned HTML and has no `ir.ui.view`/QWeb dependency.
- Workspace credentials authenticate through Odoo's session API; role groups control both page visibility and server authorization.
- Workspace-user creation writes normal Odoo external users and Nut Kings group memberships through a narrowly scoped manager-only endpoint; it does not grant the Odoo backend-user group.
- All Nut Kings backend menus and direct custom-model ACLs are limited to `base.group_system`; operational groups use only the role-checked workspace APIs.
- Raw Materials, Finished Goods, and every van remain separate native Odoo stock locations.
- Every supported stock movement continues to create or act on native Odoo transfers.
- Van product rotation is manual: the itemized van view can issue or reissue products without an automated recommendation layer.

## Static validation completed

- Python syntax and byte-compilation passed.
- JavaScript syntax passed for the workspace and service worker.
- All XML files parse successfully.
- All local XML references resolve, all explicit XML IDs are unique, and every backend menu is Settings-administrator-only.
- The manifest references only existing data and asset files.
- The access-control CSV contains only the eight required Settings-administrator ACL rows.
- All HTML element IDs referenced through the workspace `$()` helper exist.
- No duplicate workspace HTML element IDs were found.
- The application, API, sidebar, login assets, and service-worker cache agree on release `1.4.1`.
- The module no longer contains the obsolete `views/login_templates.xml` or default-login stylesheet.
- Compiled Python cache files are excluded from the release archive.

## Required staging acceptance test

A live Odoo 19 server is not present in the build environment. Before production use:

1. Upgrade the complete module on staging and verify the standard `/web/login` still renders unchanged.
2. Sign into `/nutkings/login` as an Odoo Settings administrator and create one account for each Nut Kings role.
3. Verify each account lands on the correct workspace area and sees only its permitted actions.
4. Test create, password reset, deactivate, reactivate, multi-role assignment, and service-area limits from Workspace Users.
5. Verify a frontend-created workspace user is external, can authenticate only through the Nut Kings workspace, and cannot enter the Odoo backend.
6. Complete one raw receipt, raw issue, finished-goods receipt, van load, customer delivery, van return, and trip reconciliation.
7. Confirm every movement appears as a native Odoo transfer and each van's stock is isolated in its own location.
8. Issue the same product to one van twice, verify two traceable Odoo transfers, and confirm another van's itemized balance is unchanged.
9. Test offline capture, later synchronization, blocked sign-out with pending actions, cleared local data after successful sign-out, and the protected-owner screen when a different employee signs in on a device containing unsynchronized work.
