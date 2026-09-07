from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NutKingsTruck(models.Model):
    _name = 'nutkings.truck'
    _description = 'Nut Kings Distribution Van'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Van Name / Number', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    registration_number = fields.Char(required=True, copy=False, index=True, tracking=True)
    barcode = fields.Char(copy=False, index=True, tracking=True)
    make = fields.Char()
    model = fields.Char()
    capacity_note = fields.Char(string='Carrying Capacity')
    default_driver_id = fields.Many2one('nutkings.staff', domain=[('role', '=', 'driver')], tracking=True)
    default_team_ids = fields.Many2many('nutkings.staff', 'nk_truck_staff_rel', string='Default Distribution Team')
    stock_location_id = fields.Many2one('stock.location', string='Van Inventory Location', readonly=True, copy=False)
    status = fields.Selection(
        [('available', 'Available'), ('loading', 'Loading'), ('on_route', 'On Route'), ('maintenance', 'Maintenance'), ('inactive', 'Inactive')],
        default='available', tracking=True, required=True,
    )
    notes = fields.Text()

    _registration_unique = models.Constraint('unique(registration_number)', 'Van registration number must be unique.')
    _barcode_unique = models.Constraint('unique(barcode)', 'Van barcode must be unique.')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_stock_location()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._ensure_stock_location()
        return result

    def _ensure_stock_location(self):
        setup = self.env['stock.picking.type'].nk_ensure_company_setup(self.mapped('company_id'))
        for truck in self:
            root = setup[truck.company_id.id]['locations']['fg_trucks']
            if not truck.stock_location_id:
                Location = self.env['stock.location'].sudo().with_context(active_test=False)
                location = Location.search([
                    ('company_id', '=', truck.company_id.id),
                    ('nk_code', '=', f'TRUCK_{truck.id}'),
                ], limit=1)

                if not location and truck.barcode:
                    candidate = Location.search([
                        ('company_id', '=', truck.company_id.id),
                        ('barcode', '=', truck.barcode),
                    ], limit=1)
                    if candidate:
                        # A surviving truck location from an earlier install is
                        # safe to reuse only when it belongs to the Trucks tree.
                        # Never hijack an unrelated Odoo location that happens to
                        # use the same barcode.
                        if candidate.location_id != root:
                            raise ValidationError(_(
                                'Van barcode %(barcode)s is already used by stock location %(location)s.',
                                barcode=truck.barcode,
                                location=candidate.display_name,
                            ))
                        location = candidate

                if not location:
                    location = Location.search([
                        ('company_id', '=', truck.company_id.id),
                        ('name', '=', truck.name),
                        ('usage', '=', 'internal'),
                        ('location_id', '=', root.id),
                    ], limit=1)

                values = {
                    'name': truck.name,
                    'location_id': root.id,
                    'usage': 'internal',
                    'company_id': truck.company_id.id,
                    'barcode': truck.barcode or False,
                    'nk_location': True,
                    'nk_code': f'TRUCK_{truck.id}',
                }
                if location:
                    location.write(values)
                else:
                    location = Location.create(values)
                truck.sudo().stock_location_id = location.id
            else:
                if truck.stock_location_id.company_id != truck.company_id:
                    raise ValidationError(_('A van company cannot be changed after its stock location is created.'))
                truck.stock_location_id.sudo().write({
                    'name': truck.name,
                    'barcode': truck.barcode or False,
                    'location_id': root.id,
                    'nk_location': True,
                })
