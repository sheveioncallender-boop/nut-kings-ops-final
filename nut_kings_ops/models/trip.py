from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class NutKingsTrip(models.Model):
    _name = 'nutkings.trip'
    _description = 'Nut Kings Distribution Trip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_departure desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    truck_id = fields.Many2one('nutkings.truck', string='Van', required=True, tracking=True, index=True)
    driver_id = fields.Many2one('nutkings.staff', domain=[('role', '=', 'driver')], tracking=True)
    team_ids = fields.Many2many('nutkings.staff', 'nk_trip_staff_rel', string='Distribution Team')
    customer_ids = fields.Many2many('res.partner', 'nk_trip_customer_rel', string='Planned Customers')
    route_name = fields.Char(required=True, tracking=True)
    planned_departure = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    actual_departure = fields.Datetime(readonly=True, tracking=True)
    actual_return = fields.Datetime(readonly=True, tracking=True)
    state = fields.Selection(
        [('planned', 'Planned'), ('loading', 'Loading'), ('in_progress', 'In Progress'), ('reconciliation', 'Reconciliation'), ('done', 'Closed'), ('cancelled', 'Cancelled')],
        default='planned', required=True, tracking=True, index=True,
    )
    picking_ids = fields.One2many('stock.picking', 'nk_trip_id', string='Stock Transfers')
    line_ids = fields.One2many('nutkings.trip.line', 'trip_id', string='Reconciliation', readonly=True)
    total_loaded = fields.Float(compute='_compute_totals', store=True)
    total_delivered = fields.Float(compute='_compute_totals', store=True)
    total_returned = fields.Float(compute='_compute_totals', store=True)
    total_damaged = fields.Float(compute='_compute_totals', store=True)
    total_variance = fields.Float(compute='_compute_totals', store=True)
    variance_explanation = fields.Text(tracking=True)
    variance_approved = fields.Boolean(
        tracking=True,
        groups='nut_kings_ops.group_nutkings_manager,base.group_system',
    )
    notes = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nutkings.trip') or 'New'
        trips = super().create(vals_list)
        trips._check_open_trip()
        return trips

    @api.constrains('truck_id', 'state')
    def _check_open_trip(self):
        open_states = ('planned', 'loading', 'in_progress', 'reconciliation')
        for trip in self.filtered(lambda rec: rec.truck_id and rec.state in open_states):
            if self.search_count([
                ('id', '!=', trip.id),
                ('truck_id', '=', trip.truck_id.id),
                ('state', 'in', open_states),
            ]):
                raise ValidationError(_('This van is already assigned to another open trip.'))

    def _done_quantity(self, kinds):
        self.ensure_one()
        total = 0.0
        pickings = self.picking_ids.filtered(lambda p: p.state == 'done' and p.nk_operation_kind in kinds)
        for move in pickings.move_ids.filtered(lambda m: m.state == 'done'):
            total += move.quantity
        return total

    @api.depends('picking_ids.state', 'picking_ids.nk_operation_kind', 'picking_ids.move_ids.quantity')
    def _compute_totals(self):
        for trip in self:
            trip.total_loaded = trip._done_quantity({'finished_to_truck'})
            trip.total_delivered = trip._done_quantity({'customer_delivery'})
            trip.total_returned = trip._done_quantity({'truck_return'})
            trip.total_damaged = trip._done_quantity({'damage'})
            trip.total_variance = trip.total_loaded - trip.total_delivered - trip.total_returned - trip.total_damaged

    def action_start_loading(self):
        for trip in self:
            if trip.state != 'planned':
                raise UserError(_('Only a planned trip can start loading.'))
            trip.state = 'loading'
            trip.truck_id.status = 'loading'
        return True

    def action_depart(self):
        for trip in self:
            if trip.state != 'loading':
                raise UserError(_('Only a loading trip can depart.'))
            trip.state = 'in_progress'
            trip.actual_departure = fields.Datetime.now()
            trip.truck_id.status = 'on_route'
        return True

    def action_return(self):
        for trip in self:
            if trip.state != 'in_progress':
                raise UserError(_('Only an in-progress trip can start reconciliation.'))
            trip.state = 'reconciliation'
            trip.actual_return = fields.Datetime.now()
            trip.truck_id.status = 'loading'
            trip._refresh_lines()
        return True

    def _refresh_lines(self):
        Line = self.env['nutkings.trip.line'].sudo()
        for trip in self:
            values = {}
            for picking in trip.picking_ids.filtered(lambda p: p.state == 'done'):
                bucket = {
                    'finished_to_truck': 'qty_loaded',
                    'customer_delivery': 'qty_delivered',
                    'truck_return': 'qty_returned',
                    'damage': 'qty_damaged',
                }.get(picking.nk_operation_kind)
                if not bucket:
                    continue
                for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                    row = values.setdefault(move.product_id.id, {
                        'trip_id': trip.id,
                        'product_id': move.product_id.id,
                        'qty_loaded': 0.0,
                        'qty_delivered': 0.0,
                        'qty_returned': 0.0,
                        'qty_damaged': 0.0,
                    })
                    row[bucket] += move.quantity
            trip.line_ids.unlink()
            if values:
                Line.create(list(values.values()))
        return True

    def action_close(self):
        self.env.user.nk_ops_assert('manager')
        for trip in self:
            trip._refresh_lines()
            if trip.state != 'reconciliation':
                raise UserError(_('The trip must be in Reconciliation before it can be closed.'))
            if not float_is_zero(trip.total_variance, precision_digits=2) and not trip.variance_approved:
                raise UserError(_('Explain and approve the trip variance before closing.'))
            trip.state = 'done'
            trip.truck_id.status = 'available'
        return True

    def action_cancel(self):
        for trip in self:
            if trip.state not in ('planned', 'loading'):
                raise UserError(_('Only a planned or loading trip can be cancelled.'))
            if trip.picking_ids.filtered(lambda p: p.state == 'done'):
                raise UserError(_('A trip with completed stock transfers cannot be cancelled.'))
            trip.state = 'cancelled'
            trip.truck_id.status = 'available'
        return True


class NutKingsTripLine(models.Model):
    _name = 'nutkings.trip.line'
    _description = 'Nut Kings Trip Reconciliation Line'

    trip_id = fields.Many2one('nutkings.trip', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    qty_loaded = fields.Float(readonly=True)
    qty_delivered = fields.Float(readonly=True)
    qty_returned = fields.Float(readonly=True)
    qty_damaged = fields.Float(readonly=True)
    variance = fields.Float(compute='_compute_variance')

    @api.depends('qty_loaded', 'qty_delivered', 'qty_returned', 'qty_damaged')
    def _compute_variance(self):
        for line in self:
            line.variance = line.qty_loaded - line.qty_delivered - line.qty_returned - line.qty_damaged
