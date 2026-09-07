from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _


class NutKingsBackendDashboard(models.Model):
    _name = 'nutkings.backend.dashboard'
    _description = 'Nut Kings Ops Backend Dashboard'
    _order = 'company_id, id'

    name = fields.Char(default='Backend Dashboard', required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )

    raw_stock_qty = fields.Float(string='Raw Stock on Hand', compute='_compute_dashboard')
    finished_stock_qty = fields.Float(string='Finished Stock on Hand', compute='_compute_dashboard')
    truck_stock_qty = fields.Float(string='Stock on Vans', compute='_compute_dashboard')
    low_stock_count = fields.Integer(string='Low Stock Products', compute='_compute_dashboard')

    open_operations_count = fields.Integer(string='Open Operations', compute='_compute_dashboard')
    draft_operations_count = fields.Integer(string='Draft', compute='_compute_dashboard')
    waiting_operations_count = fields.Integer(string='Waiting', compute='_compute_dashboard')
    ready_operations_count = fields.Integer(string='Ready', compute='_compute_dashboard')
    overdue_operations_count = fields.Integer(string='Overdue', compute='_compute_dashboard')
    done_today_count = fields.Integer(string='Completed Today', compute='_compute_dashboard')

    active_trip_count = fields.Integer(string='Active Trips', compute='_compute_dashboard')
    reconciliation_trip_count = fields.Integer(string='Trips to Reconcile', compute='_compute_dashboard')
    available_truck_count = fields.Integer(string='Available Vans', compute='_compute_dashboard')
    loading_truck_count = fields.Integer(string='Loading Vans', compute='_compute_dashboard')
    on_route_truck_count = fields.Integer(string='Vans on Route', compute='_compute_dashboard')

    pending_sync_count = fields.Integer(string='Pending Sync', compute='_compute_dashboard')
    sync_attention_count = fields.Integer(string='Sync Needs Attention', compute='_compute_dashboard')
    sync_error_count = fields.Integer(string='Sync Errors', compute='_compute_dashboard')

    recent_picking_ids = fields.Many2many(
        'stock.picking',
        string='Recent Operations',
        compute='_compute_dashboard',
        readonly=True,
    )
    active_trip_ids = fields.Many2many(
        'nutkings.trip',
        string='Active Distribution Trips',
        compute='_compute_dashboard',
        readonly=True,
    )
    low_stock_product_ids = fields.Many2many(
        'product.product',
        string='Low Stock Products',
        compute='_compute_dashboard',
        readonly=True,
    )

    _company_unique = models.Constraint(
        'unique(company_id)',
        'Only one Nut Kings Ops backend dashboard can exist per company.',
    )

    @api.model
    def _get_company_dashboard(self, company=None):
        company = company or self.env.company
        dashboard = self.sudo().search([('company_id', '=', company.id)], limit=1)
        if not dashboard:
            dashboard = self.sudo().create({
                'name': _('Backend Dashboard'),
                'company_id': company.id,
            })
        return dashboard.with_user(self.env.user)

    @api.model
    def action_open_dashboard(self):
        dashboard = self._get_company_dashboard()
        action = self.env.ref('nut_kings_ops.action_nk_backend_dashboard').sudo().read()[0]
        action.update({
            'res_id': dashboard.id,
            'views': [(self.env.ref('nut_kings_ops.view_nk_backend_dashboard_form').id, 'form')],
            'view_mode': 'form',
            'target': 'current',
        })
        return action

    def action_refresh(self):
        return self.action_open_dashboard()

    def _today_utc_bounds(self):
        today = fields.Date.context_today(self)
        user_timezone = pytz.timezone(self.env.user.tz or 'UTC')
        local_start = user_timezone.localize(datetime.combine(today, time.min))
        local_end = local_start + timedelta(days=1)
        utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
        return utc_start, utc_end

    @api.depends('company_id')
    def _compute_dashboard(self):
        Picking = self.env['stock.picking'].sudo()
        Trip = self.env['nutkings.trip'].sudo()
        Truck = self.env['nutkings.truck'].sudo()
        Sync = self.env['nutkings.sync.event'].sudo()
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.product'].sudo()
        Location = self.env['stock.location'].sudo()

        for dashboard in self:
            company = dashboard.company_id or self.env.company
            company_domain = [('company_id', '=', company.id)]
            picking_domain = company_domain + [('nk_is_operation', '=', True)]

            raw_location = Location.search([
                ('company_id', '=', company.id), ('nk_code', '=', 'RM_STOCK')
            ], limit=1)
            finished_location = Location.search([
                ('company_id', '=', company.id), ('nk_code', '=', 'FG_STOCK')
            ], limit=1)
            truck_locations = Location.search([
                ('company_id', '=', company.id),
                ('nk_location', '=', True),
                ('nk_code', '=like', 'TRUCK_%'),
                ('usage', '=', 'internal'),
            ])

            raw_quants = Quant.search([
                ('company_id', '=', company.id),
                ('location_id', 'child_of', raw_location.id),
                ('product_id.nk_inventory_type', '=', 'raw_material'),
            ]) if raw_location else Quant.browse()
            finished_quants = Quant.search([
                ('company_id', '=', company.id),
                ('location_id', 'child_of', finished_location.id),
                ('product_id.nk_inventory_type', '=', 'finished_good'),
            ]) if finished_location else Quant.browse()
            truck_quants = Quant.search([
                ('company_id', '=', company.id),
                ('location_id', 'child_of', truck_locations.ids),
                ('product_id.nk_inventory_type', '=', 'finished_good'),
            ]) if truck_locations else Quant.browse()

            raw_qty_by_product = {}
            finished_qty_by_product = {}
            for quant in raw_quants:
                raw_qty_by_product[quant.product_id.id] = raw_qty_by_product.get(quant.product_id.id, 0.0) + quant.available_quantity
            for quant in finished_quants:
                finished_qty_by_product[quant.product_id.id] = finished_qty_by_product.get(quant.product_id.id, 0.0) + quant.available_quantity

            monitored_products = Product.search([
                ('company_id', 'in', (False, company.id)),
                ('active', '=', True),
                ('nk_enabled', '=', True),
                ('nk_inventory_type', 'in', ('raw_material', 'finished_good')),
                ('nk_minimum_qty', '>', 0),
            ])
            low_stock_products = monitored_products.filtered(
                lambda product: (
                    raw_qty_by_product.get(product.id, 0.0)
                    if product.nk_inventory_type == 'raw_material'
                    else finished_qty_by_product.get(product.id, 0.0)
                ) <= product.nk_minimum_qty
            )

            now = fields.Datetime.now()
            today_start, tomorrow_start = dashboard._today_utc_bounds()

            dashboard.raw_stock_qty = sum(raw_quants.mapped('quantity'))
            dashboard.finished_stock_qty = sum(finished_quants.mapped('quantity'))
            dashboard.truck_stock_qty = sum(truck_quants.mapped('quantity'))
            dashboard.low_stock_count = len(low_stock_products)
            dashboard.low_stock_product_ids = [(6, 0, low_stock_products.ids)]

            dashboard.draft_operations_count = Picking.search_count(picking_domain + [('state', '=', 'draft')])
            dashboard.waiting_operations_count = Picking.search_count(picking_domain + [
                ('state', 'in', ('confirmed', 'waiting', 'partially_available'))
            ])
            dashboard.ready_operations_count = Picking.search_count(picking_domain + [('state', '=', 'assigned')])
            dashboard.open_operations_count = Picking.search_count(picking_domain + [
                ('state', 'not in', ('done', 'cancel'))
            ])
            dashboard.overdue_operations_count = Picking.search_count(picking_domain + [
                ('state', 'not in', ('done', 'cancel')),
                ('scheduled_date', '<', now),
            ])
            dashboard.done_today_count = Picking.search_count(picking_domain + [
                ('state', '=', 'done'),
                ('date_done', '>=', fields.Datetime.to_string(today_start)),
                ('date_done', '<', fields.Datetime.to_string(tomorrow_start)),
            ])

            active_trip_domain = company_domain + [
                ('state', 'in', ('planned', 'loading', 'in_progress', 'reconciliation'))
            ]
            active_trips = Trip.search(active_trip_domain, order='planned_departure asc, id desc', limit=8)
            dashboard.active_trip_count = Trip.search_count(active_trip_domain)
            dashboard.reconciliation_trip_count = Trip.search_count(company_domain + [('state', '=', 'reconciliation')])
            dashboard.active_trip_ids = [(6, 0, active_trips.ids)]

            dashboard.available_truck_count = Truck.search_count(company_domain + [('active', '=', True), ('status', '=', 'available')])
            dashboard.loading_truck_count = Truck.search_count(company_domain + [('active', '=', True), ('status', '=', 'loading')])
            dashboard.on_route_truck_count = Truck.search_count(company_domain + [('active', '=', True), ('status', '=', 'on_route')])

            dashboard.pending_sync_count = Sync.search_count(company_domain + [('state', '=', 'pending')])
            dashboard.sync_attention_count = Sync.search_count(company_domain + [('state', '=', 'needs_action')])
            dashboard.sync_error_count = Sync.search_count(company_domain + [('state', '=', 'error')])

            recent_pickings = Picking.search(
                picking_domain,
                order='scheduled_date desc, id desc',
                limit=10,
            )
            dashboard.recent_picking_ids = [(6, 0, recent_pickings.ids)]

    def _stock_operation_action(self, name, extra_domain=None):
        self.ensure_one()
        action = self.env.ref('nut_kings_ops.action_nk_stock_transfers').sudo().read()[0]
        action['name'] = name
        action['domain'] = [
            ('company_id', '=', self.company_id.id),
            ('nk_is_operation', '=', True),
        ] + (extra_domain or [])
        return action

    def action_open_all_operations(self):
        self.ensure_one()
        return self._stock_operation_action(_('All Stock Operations'))

    def action_open_open_operations(self):
        self.ensure_one()
        return self._stock_operation_action(_('Open Stock Operations'), [('state', 'not in', ('done', 'cancel'))])

    def action_open_draft_operations(self):
        self.ensure_one()
        return self._stock_operation_action(_('Draft Stock Operations'), [('state', '=', 'draft')])

    def action_open_waiting_operations(self):
        self.ensure_one()
        return self._stock_operation_action(
            _('Waiting Stock Operations'),
            [('state', 'in', ('confirmed', 'waiting', 'partially_available'))],
        )

    def action_open_ready_operations(self):
        self.ensure_one()
        return self._stock_operation_action(_('Ready Stock Operations'), [('state', '=', 'assigned')])

    def action_open_overdue_operations(self):
        self.ensure_one()
        return self._stock_operation_action(
            _('Overdue Stock Operations'),
            [('state', 'not in', ('done', 'cancel')), ('scheduled_date', '<', fields.Datetime.now())],
        )

    def action_open_done_today(self):
        self.ensure_one()
        today_start, tomorrow_start = self._today_utc_bounds()
        return self._stock_operation_action(
            _('Operations Completed Today'),
            [
                ('state', '=', 'done'),
                ('date_done', '>=', fields.Datetime.to_string(today_start)),
                ('date_done', '<', fields.Datetime.to_string(tomorrow_start)),
            ],
        )

    def _inventory_action(self, name, inventory_type, location_code):
        self.ensure_one()
        location = self.env['stock.location'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('nk_code', '=', location_code),
        ], limit=1)
        action = self.env.ref('nut_kings_ops.action_nk_inventory_levels').sudo().read()[0]
        action['name'] = name
        if not location:
            action['domain'] = [('id', '=', 0)]
            return action
        action['domain'] = [
            ('company_id', '=', self.company_id.id),
            ('location_id', 'child_of', location.id),
            ('product_id.nk_inventory_type', '=', inventory_type),
        ]
        return action

    def action_open_raw_inventory(self):
        return self._inventory_action(_('Raw Materials Inventory'), 'raw_material', 'RM_STOCK')

    def action_open_finished_inventory(self):
        return self._inventory_action(_('Finished Goods Inventory'), 'finished_good', 'FG_STOCK')

    def action_open_truck_inventory(self):
        self.ensure_one()
        truck_locations = self.env['stock.location'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('nk_location', '=', True),
            ('nk_code', '=like', 'TRUCK_%'),
            ('usage', '=', 'internal'),
        ])
        action = self.env.ref('nut_kings_ops.action_nk_inventory_levels').sudo().read()[0]
        action['name'] = _('Stock on Distribution Vans')
        if not truck_locations:
            action['domain'] = [('id', '=', 0)]
            return action
        action['domain'] = [
            ('company_id', '=', self.company_id.id),
            ('location_id', 'child_of', truck_locations.ids),
            ('product_id.nk_inventory_type', '=', 'finished_good'),
        ]
        return action

    def action_open_low_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Low Stock Products'),
            'res_model': 'product.product',
            'view_mode': 'list,kanban,form',
            'target': 'current',
            'domain': [('id', 'in', self.low_stock_product_ids.ids)],
            'context': {'create': False},
        }

    def _trip_action(self, name, domain=None):
        self.ensure_one()
        action = self.env.ref('nut_kings_ops.action_nk_trips').sudo().read()[0]
        action['name'] = name
        action['domain'] = [('company_id', '=', self.company_id.id)] + (domain or [])
        return action

    def action_open_active_trips(self):
        return self._trip_action(
            _('Active Distribution Trips'),
            [('state', 'in', ('planned', 'loading', 'in_progress', 'reconciliation'))],
        )

    def action_open_reconciliation_trips(self):
        return self._trip_action(_('Trips Awaiting Reconciliation'), [('state', '=', 'reconciliation')])

    def action_open_all_trips(self):
        return self._trip_action(_('Distribution Trips'))

    def action_open_trucks(self):
        self.ensure_one()
        action = self.env.ref('nut_kings_ops.action_nk_trucks').sudo().read()[0]
        action['domain'] = [('company_id', '=', self.company_id.id)]
        return action

    def action_open_available_trucks(self):
        self.ensure_one()
        action = self.action_open_trucks()
        action['name'] = _('Available Vans')
        action['domain'] += [('active', '=', True), ('status', '=', 'available')]
        return action

    def action_open_loading_trucks(self):
        self.ensure_one()
        action = self.action_open_trucks()
        action['name'] = _('Loading Vans')
        action['domain'] += [('active', '=', True), ('status', '=', 'loading')]
        return action

    def action_open_on_route_trucks(self):
        self.ensure_one()
        action = self.action_open_trucks()
        action['name'] = _('Vans on Route')
        action['domain'] += [('active', '=', True), ('status', '=', 'on_route')]
        return action

    def _sync_action(self, name, states):
        self.ensure_one()
        action = self.env.ref('nut_kings_ops.action_nk_sync_events').sudo().read()[0]
        action['name'] = name
        action['domain'] = [('company_id', '=', self.company_id.id), ('state', 'in', states)]
        return action

    def action_open_pending_sync(self):
        return self._sync_action(_('Pending Synchronization'), ['pending'])

    def action_open_sync_attention(self):
        return self._sync_action(_('Synchronization Needs Attention'), ['needs_action'])

    def action_open_sync_errors(self):
        return self._sync_action(_('Synchronization Errors'), ['error'])

    def action_open_sync_log(self):
        return self._sync_action(_('Synchronization Log'), ['pending', 'processed', 'needs_action', 'error'])

    def action_open_workspace(self):
        return {
            'type': 'ir.actions.act_url',
            'name': _('Operations Workspace'),
            'url': '/nutkings/',
            'target': 'self',
        }

    def action_open_rapid_scan(self):
        return {
            'type': 'ir.actions.act_url',
            'name': _('Rapid Scan'),
            'url': '/nutkings/#rapid',
            'target': 'self',
        }

    def _new_operation_action(self, operation_kind):
        self.ensure_one()
        labels = dict(self.env['stock.picking']._fields['nk_operation_kind'].selection)
        return {
            'type': 'ir.actions.act_url',
            'name': labels.get(operation_kind, _('New Stock Operation')),
            'url': f'/nutkings/#scan/{operation_kind}',
            'target': 'self',
        }

    def action_new_raw_receipt(self):
        return self._new_operation_action('raw_receipt')

    def action_new_raw_issue(self):
        return self._new_operation_action('raw_issue')

    def action_new_finished_receipt(self):
        return self._new_operation_action('finished_receipt')

    def action_new_truck_load(self):
        return self._new_operation_action('finished_to_truck')

    def action_new_customer_delivery(self):
        return self._new_operation_action('customer_delivery')

    def action_new_truck_return(self):
        return self._new_operation_action('truck_return')

    def action_new_trip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Distribution Trip'),
            'res_model': 'nutkings.trip',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_company_id': self.company_id.id},
        }

    def action_raw_physical_inventory(self):
        self.ensure_one()
        return self.env['stock.quant'].with_company(self.company_id).action_nk_raw_physical_inventory()

    def action_finished_physical_inventory(self):
        self.ensure_one()
        return self.env['stock.quant'].with_company(self.company_id).action_nk_finished_physical_inventory()
