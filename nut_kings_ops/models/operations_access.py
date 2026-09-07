from odoo import SUPERUSER_ID, _, fields, models
from odoo.exceptions import AccessError


ROLE_GROUPS = {
    'office_receiving': 'nut_kings_ops.group_nutkings_office_receiving',
    'raw_material_issue': 'nut_kings_ops.group_nutkings_raw_material_issue',
    'finished_goods_entry': 'nut_kings_ops.group_nutkings_finished_goods_entry',
    'dispatcher': 'nut_kings_ops.group_nutkings_dispatcher',
    'manager': 'nut_kings_ops.group_nutkings_manager',
}

OPERATION_ROLE = {
    'raw_receipt': 'office_receiving',
    'raw_issue': 'raw_material_issue',
    'finished_receipt': 'finished_goods_entry',
    'finished_to_truck': 'dispatcher',
    'customer_delivery': 'dispatcher',
    'truck_return': 'dispatcher',
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    nk_service_area_ids = fields.Many2many(
        'nutkings.service.area',
        'nutkings_service_area_user_rel',
        'user_id',
        'service_area_id',
        string='Nut Kings Service Areas',
        help='Limit a dispatcher to these service areas. Leave empty to allow all service areas.',
    )

    @property
    def SELF_READABLE_FIELDS(self):
        """Let a frontend-only user read their own area restriction.

        Odoo keeps a strict allow-list for fields that external users may read
        from their own ``res.users`` record.  The manager-only workspace API
        writes this field with ``sudo``; staff only need to read their own
        assignment while the server authorizes van, customer, and trip data.
        """
        return [*super().SELF_READABLE_FIELDS, 'nk_service_area_ids']

    def nk_ops_role_codes(self):
        self.ensure_one()
        roles = {
            code for code, xmlid in ROLE_GROUPS.items()
            if self.has_group(xmlid)
        }
        if self.id == SUPERUSER_ID or self.has_group('base.group_system'):
            roles.add('system')
            roles.add('manager')
        return roles

    def nk_ops_permissions(self):
        self.ensure_one()
        roles = self.nk_ops_role_codes()
        manager = bool({'manager', 'system'} & roles)
        office_receiving = manager or 'office_receiving' in roles
        raw_material_issue = manager or 'raw_material_issue' in roles
        finished_goods_entry = manager or 'finished_goods_entry' in roles
        dispatcher = manager or 'dispatcher' in roles
        capabilities = [
            operation for operation, role in OPERATION_ROLE.items()
            if manager or role in roles
        ]
        return {
            'office_receiving': office_receiving,
            'raw_material_issue': raw_material_issue,
            'finished_goods_entry': finished_goods_entry,
            'dispatcher': dispatcher,
            'raw': office_receiving or raw_material_issue,
            'finished': finished_goods_entry or dispatcher,
            'distribution': dispatcher,
            'raw_count': 'system' in roles,
            'finished_count': 'system' in roles,
            'contacts': dispatcher or manager,
            'supervisor': manager,
            'manager': manager,
            'system': 'system' in roles,
            'capabilities': capabilities,
            'has_nutkings_access': bool(capabilities or manager),
        }

    def nk_ops_can(self, permission):
        self.ensure_one()
        permissions = self.nk_ops_permissions()
        if permission in OPERATION_ROLE:
            return permission in permissions['capabilities']
        return bool(permissions.get(permission))

    def nk_ops_assert(self, permission):
        self.ensure_one()
        if not self.nk_ops_can(permission):
            raise AccessError(_('Your Nut Kings role does not allow this operation.'))
        return True

    def nk_ops_allowed_service_area_ids(self):
        self.ensure_one()
        permissions = self.nk_ops_permissions()
        Area = self.env['nutkings.service.area'].sudo()
        company_domain = [('company_id', '=', self.env.company.id), ('active', '=', True)]
        assigned_areas = self.sudo().nk_service_area_ids
        if permissions['manager'] or not assigned_areas:
            return Area.search(company_domain).ids
        return assigned_areas.filtered(
            lambda area: area.active and area.company_id == self.env.company
        ).ids
