from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NutKingsServiceArea(models.Model):
    _name = 'nutkings.service.area'
    _description = 'Nut Kings Service Area'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True, index=True)
    code = fields.Char(required=True, tracking=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
        required=True, index=True,
    )
    customer_ids = fields.One2many('res.partner', 'nk_service_area_id', string='Customers')
    truck_ids = fields.Many2many(
        'nutkings.truck',
        'nutkings_truck_service_area_rel',
        'service_area_id',
        'truck_id',
        string='Assigned Vans',
    )
    user_ids = fields.Many2many(
        'res.users',
        'nutkings_service_area_user_rel',
        'service_area_id',
        'user_id',
        string='Assigned Users',
    )
    notes = fields.Text()

    _code_company_unique = models.Constraint(
        'unique(code, company_id)',
        'The service-area code must be unique per company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('code'):
                values['code'] = str(values['code']).strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        values = dict(vals)
        if values.get('code'):
            values['code'] = str(values['code']).strip().upper()
        return super().write(values)

    def action_view_customers(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('nut_kings_ops.action_nk_customers')
        action['domain'] = [('nk_service_area_id', '=', self.id)]
        action['context'] = {
            'default_nk_is_customer': True,
            'default_nk_service_area_id': self.id,
        }
        return action


class ResPartner(models.Model):
    _inherit = 'res.partner'

    nk_service_area_id = fields.Many2one(
        'nutkings.service.area',
        string='Nut Kings Service Area',
        domain="[('company_id', '=', company_id)]",
        index=True,
    )


class NutKingsTruck(models.Model):
    _inherit = 'nutkings.truck'

    service_area_ids = fields.Many2many(
        'nutkings.service.area',
        'nutkings_truck_service_area_rel',
        'truck_id',
        'service_area_id',
        string='Service Areas',
    )


class NutKingsTrip(models.Model):
    _inherit = 'nutkings.trip'

    service_area_id = fields.Many2one(
        'nutkings.service.area', string='Service Area',
        tracking=True, index=True,
        domain="[('company_id', '=', company_id)]",
    )
    @api.onchange('truck_id')
    def _onchange_truck_service_area(self):
        for trip in self:
            if trip.truck_id and len(trip.truck_id.service_area_ids) == 1 and not trip.service_area_id:
                trip.service_area_id = trip.truck_id.service_area_ids

    @api.model_create_multi
    def create(self, vals_list):
        Area = self.env['nutkings.service.area']
        for values in vals_list:
            if not values.get('service_area_id') and values.get('route_name'):
                company_id = values.get('company_id') or self.env.company.id
                area = Area.search([
                    ('company_id', '=', company_id),
                    ('name', '=ilike', str(values['route_name']).strip()),
                ], limit=1)
                values['service_area_id'] = area.id or False
            if values.get('service_area_id') and not values.get('route_name'):
                values['route_name'] = Area.browse(values['service_area_id']).name
        return super().create(vals_list)

    @api.constrains('company_id', 'truck_id', 'driver_id', 'team_ids', 'customer_ids', 'service_area_id')
    def _check_truck_service_area(self):
        for trip in self:
            if trip.truck_id.company_id != trip.company_id:
                raise ValidationError(_('The van must belong to the trip company.'))
            if trip.service_area_id and trip.service_area_id.company_id != trip.company_id:
                raise ValidationError(_('The service area must belong to the trip company.'))
            if trip.driver_id and trip.driver_id.company_id != trip.company_id:
                raise ValidationError(_('The driver must belong to the trip company.'))
            if any(member.company_id != trip.company_id for member in trip.team_ids):
                raise ValidationError(_('Every distribution-team member must belong to the trip company.'))
            if any(partner.company_id and partner.company_id != trip.company_id for partner in trip.customer_ids):
                raise ValidationError(_('Every customer must be shared or belong to the trip company.'))
            if trip.service_area_id and any(
                partner.nk_service_area_id and partner.nk_service_area_id != trip.service_area_id
                for partner in trip.customer_ids
            ):
                raise ValidationError(_('Every assigned customer must belong to the trip service area.'))
            assigned = trip.truck_id.service_area_ids
            if trip.service_area_id and assigned and trip.service_area_id not in assigned:
                raise ValidationError(_(
                    '%(truck)s is not assigned to the %(area)s service area.',
                    truck=trip.truck_id.display_name,
                    area=trip.service_area_id.display_name,
                ))
