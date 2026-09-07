import json
import uuid
from collections import defaultdict

from odoo import SUPERUSER_ID, fields, http
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.http import request
from odoo.tools.float_utils import float_compare
from ..workspace_policy import scoped_permissions


class NutKingsApi(http.Controller):
    VERSION = '1.4.2'
    MAX_BATCH = 250
    MAX_LINES = 500
    WORKSPACE_ROLES = {
        'office_receiving': ('nut_kings_ops.group_nutkings_office_receiving', 'Raw Materials — Receiving (Office)'),
        'raw_material_issue': ('nut_kings_ops.group_nutkings_raw_material_issue', 'Raw Materials — Issuing (Employee)'),
        'finished_goods_entry': ('nut_kings_ops.group_nutkings_finished_goods_entry', 'Finished Goods — Receiving (Employee)'),
        'dispatcher': ('nut_kings_ops.group_nutkings_dispatcher', 'Finished Goods — Issued (Office)'),
        'manager': ('nut_kings_ops.group_nutkings_manager', 'Nut Kings Manager'),
    }

    @staticmethod
    def _body():
        if not request.validate_csrf(request.httprequest.headers.get('X-NutKings-CSRF')):
            raise AccessError('Your session has changed. Sign in again before saving.')
        return request.httprequest.get_json(silent=True) or {}

    @staticmethod
    def _safe_int(value):
        try:
            return int(value) if value not in (None, False, '') else False
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _device_datetime(value):
        if not value:
            return fields.Datetime.now()
        normalized = str(value).replace('T', ' ').replace('Z', '')[:19]
        try:
            return fields.Datetime.to_datetime(normalized)
        except (TypeError, ValueError):
            return fields.Datetime.now()

    @staticmethod
    def _date(value):
        try:
            return fields.Date.to_date(value) if value else fields.Date.today()
        except (TypeError, ValueError):
            return fields.Date.today()

    @staticmethod
    def _dt(value):
        return value.isoformat() if value else ''

    @classmethod
    def _setup(cls):
        return request.env['stock.picking.type'].sudo().nk_ensure_company_setup(request.env.company)[request.env.company.id]

    @classmethod
    def _permissions(cls):
        try:
            return scoped_permissions(
                request.env.user.nk_ops_permissions(),
                request.httprequest.headers.get('X-NutKings-Workspace', ''),
            )
        except PermissionError as error:
            raise AccessError(str(error)) from error

    @classmethod
    def _require(cls, permission):
        permissions = cls._permissions()
        if not (permissions.get(permission) or permission in permissions['capabilities']):
            raise AccessError('Your workspace does not allow this operation.')

    @classmethod
    def _workspace_role_groups(cls):
        return {
            code: request.env.ref(xmlid).sudo()
            for code, (xmlid, _label) in cls.WORKSPACE_ROLES.items()
        }

    @classmethod
    def _workspace_user_payload(cls, user, role_groups=None):
        role_groups = role_groups or cls._workspace_role_groups()
        explicit_group_ids = set(user.group_ids.ids)
        return {
            'id': user.id,
            'name': user.name,
            'login': user.login,
            'email': user.email or '',
            'active': user.active,
            'roles': [code for code, group in role_groups.items() if group.id in explicit_group_ids],
            'service_area_ids': user.nk_service_area_ids.filtered(
                lambda area: area.company_id == request.env.company
            ).ids,
            'is_self': user.id == request.env.user.id,
            'locked': user.id == SUPERUSER_ID or user.has_group('base.group_system'),
        }

    @classmethod
    def _workspace_user_admin_required(cls):
        if not request.env.user.nk_ops_permissions()['system']:
            raise AccessError('Only an administrator can manage workspace users.')

    @classmethod
    def _workspace_user_error(cls, message, status=400):
        return request.make_json_response({'error': str(message)}, status=status)

    @classmethod
    def _restricted_service_area_ids(cls):
        permissions = cls._permissions()
        if permissions['manager'] or not request.env.user.sudo().nk_service_area_ids:
            return False
        return request.env.user.nk_ops_allowed_service_area_ids()

    @classmethod
    def _area_allowed(cls, area):
        restricted_ids = cls._restricted_service_area_ids()
        return restricted_ids is False or not area or area.id in restricted_ids

    @classmethod
    def _picking_allowed(cls, picking):
        restricted_ids = cls._restricted_service_area_ids()
        if restricted_ids is False:
            return True
        if not cls._area_allowed(picking.nk_trip_id.service_area_id):
            return False
        return not picking.nk_truck_id.service_area_ids or bool(
            set(picking.nk_truck_id.service_area_ids.ids) & set(restricted_ids)
        )

    @classmethod
    def _products(cls):
        return request.env['product.product'].sudo().search([
            ('active', '=', True),
            ('company_id', 'in', (False, request.env.company.id)),
            ('product_tmpl_id.nk_enabled', '=', True),
            ('nk_inventory_type', 'in', ('raw_material', 'finished_good')),
        ], order='name, default_code')

    @classmethod
    def _location_balances(cls, products, locations):
        Quant = request.env['stock.quant'].sudo()
        result = defaultdict(lambda: defaultdict(lambda: {'quantity': 0.0, 'reserved': 0.0, 'available': 0.0}))
        quants = Quant.search([
            ('product_id', 'in', products.ids),
            ('location_id', 'child_of', locations.ids),
            ('location_id.usage', '=', 'internal'),
            ('company_id', 'in', (False, request.env.company.id)),
        ])
        location_ids = set(locations.ids)
        for quant in quants:
            root = next((location for location in locations if quant.location_id == location or (quant.location_id.parent_path or '').startswith(location.parent_path or f'{location.id}/')), None)
            if not root:
                continue
            row = result[root.id][quant.product_id.id]
            row['quantity'] += quant.quantity
            row['reserved'] += quant.reserved_quantity
            row['available'] += quant.available_quantity
        return result

    @classmethod
    def _product_details(cls, products, all_locations, allowed_picking_ids, include_backend_urls=False):
        Move = request.env['stock.move'].sudo()
        Quant = request.env['stock.quant'].sudo()
        details = []
        for product in products:
            product_company = product.with_company(request.env.company)
            quants = Quant.search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', all_locations.ids),
                ('location_id.usage', '=', 'internal'),
                ('company_id', 'in', (False, request.env.company.id)),
            ])
            grouped = {}
            for quant in quants:
                key = (quant.location_id.id, quant.location_id.display_name, quant.lot_id.id or False, quant.lot_id.name or '')
                row = grouped.setdefault(key, {'quantity': 0.0, 'reserved': 0.0, 'available': 0.0})
                row['quantity'] += quant.quantity
                row['reserved'] += quant.reserved_quantity
                row['available'] += quant.available_quantity
            move_domain = [
                ('product_id', '=', product.id),
                ('picking_id', 'in', allowed_picking_ids or [0]),
                ('company_id', '=', request.env.company.id),
            ]
            open_moves = Move.search(
                move_domain + [('state', 'not in', ('done', 'cancel', 'draft'))],
                order='date, id',
                limit=100,
            )
            recent_moves = Move.search(move_domain, order='date desc, id desc', limit=50)
            details.append({
                'product_id': product.id,
                'name': product.display_name,
                'default_code': product.default_code or '',
                'barcode': product.barcode or '',
                'uom': product.uom_id.name,
                'tracking': product.tracking,
                'on_hand': product_company.qty_available,
                'free_qty': product_company.free_qty,
                'incoming_qty': product_company.incoming_qty,
                'outgoing_qty': product_company.outgoing_qty,
                'forecasted_qty': product_company.virtual_available,
                'backend_url': product.nk_backend_url() if include_backend_urls else '',
                'locations': [
                    {'location_id': key[0], 'location': key[1], 'lot_id': key[2], 'lot': key[3], **amounts}
                    for key, amounts in grouped.items()
                ],
                'reservations': [{
                    'move_id': move.id,
                    'reference': move.picking_id.name or move.reference or '',
                    'picking_id': move.picking_id.id or False,
                    'partner': move.picking_id.partner_id.display_name or '',
                    'truck': move.picking_id.nk_truck_id.name or '',
                    'trip': move.picking_id.nk_trip_id.name or '',
                    'demand': move.product_uom_qty,
                    'reserved': move.quantity,
                    'state': move.picking_id.nk_state_label() if move.picking_id.nk_is_operation else move.state,
                    'scheduled_date': cls._dt(move.picking_id.scheduled_date),
                } for move in open_moves if move.quantity > 0],
                'moves': [{
                    'move_id': move.id,
                    'date': cls._dt(move.date),
                    'reference': move.picking_id.name or move.reference or '',
                    'source': move.location_id.display_name,
                    'destination': move.location_dest_id.display_name,
                    'demand': move.product_uom_qty,
                    'quantity': move.quantity,
                    'state': move.state,
                    'partner': move.picking_id.partner_id.display_name or '',
                } for move in recent_moves],
            })
        return details

    @classmethod
    def _serialize_move(cls, move):
        return {
            'id': move.id,
            'product_id': move.product_id.id,
            'product': move.product_id.display_name,
            'barcode': move.product_id.barcode or '',
            'demand': move.product_uom_qty,
            'quantity': move.quantity,
            'uom': move.product_uom.name,
            'source_id': move.location_id.id,
            'source': move.location_id.display_name,
            'destination_id': move.location_dest_id.id,
            'destination': move.location_dest_id.display_name,
            'lot_reference': move.nk_lot_reference or '',
            'expiration_date': str(move.nk_expiration_date or ''),
            'state': move.state,
            'move_lines': [{
                'id': line.id,
                'location_id': line.location_id.id,
                'location': line.location_id.display_name,
                'location_dest_id': line.location_dest_id.id,
                'location_dest': line.location_dest_id.display_name,
                'lot_id': line.lot_id.id or False,
                'lot': line.lot_id.name or line.lot_name or '',
                'package_id': line.package_id.id or False,
                'package': line.package_id.name or '',
                'quantity': line.quantity,
                'picked': line.picked,
            } for line in move.move_line_ids],
        }

    @classmethod
    def _serialize_picking(cls, picking, include_backend_url=False):
        return {
            'id': picking.id,
            'name': picking.name,
            'operation_type': picking.nk_operation_kind,
            'operation_label': dict(picking._fields['nk_operation_kind'].selection).get(picking.nk_operation_kind, picking.picking_type_id.name),
            'picking_type': picking.picking_type_id.name,
            'picking_type_code': picking.picking_type_code,
            'state': picking.state,
            'state_label': picking.nk_state_label(),
            'native_stage': 'draft' if picking.state == 'draft' else 'ready' if picking.state == 'assigned' else 'done' if picking.state == 'done' else 'cancel' if picking.state == 'cancel' else 'waiting',
            'available_actions': picking.nk_available_actions(),
            'scheduled_date': cls._dt(picking.scheduled_date),
            'date_done': cls._dt(picking.date_done),
            'partner_id': picking.partner_id.id or False,
            'partner': picking.partner_id.display_name or '',
            'truck_id': picking.nk_truck_id.id or False,
            'truck': picking.nk_truck_id.name or '',
            'trip_id': picking.nk_trip_id.id or False,
            'trip': picking.nk_trip_id.name or '',
            'reason': picking.nk_reason_id.name or '',
            'reference': picking.nk_reference or picking.origin or '',
            'source_id': picking.location_id.id,
            'source': picking.location_id.display_name,
            'destination_id': picking.location_dest_id.id,
            'destination': picking.location_dest_id.display_name,
            'created_offline': picking.nk_created_offline,
            'device': picking.nk_device_name or '',
            'user_id': picking.nk_workspace_user_id.id or False,
            'user': picking.nk_workspace_user_id.name or picking.create_uid.name or '',
            'moves': [cls._serialize_move(move) for move in picking.move_ids],
            'backend_url': f'/web#id={picking.id}&model=stock.picking&view_type=form' if include_backend_url else '',
            'print_url': f'/nutkings/transfer/{picking.id}/print',
        }

    @classmethod
    def _inventory_rows(cls, products, location):
        Quant = request.env['stock.quant'].sudo()
        quants = Quant.search([
            ('location_id', 'child_of', location.id),
            ('location_id.usage', '=', 'internal'),
            ('product_id', 'in', products.ids),
            ('company_id', 'in', (False, request.env.company.id)),
        ], order='product_id, location_id, lot_id, id')
        rows = []
        seen = set()
        for quant in quants:
            seen.add(quant.product_id.id)
            rows.append({
                'row_key': f'quant-{quant.id}',
                'quant_id': quant.id,
                'product_id': quant.product_id.id,
                'product': quant.product_id.display_name,
                'barcode': quant.product_id.barcode or '',
                'default_code': quant.product_id.default_code or '',
                'uom': quant.product_id.uom_id.name,
                'tracking': quant.product_id.tracking,
                'lot_id': quant.lot_id.id or False,
                'lot_name': quant.lot_id.name or '',
                'quantity': quant.quantity,
                'reserved_quantity': quant.reserved_quantity,
                'available_quantity': quant.available_quantity,
                'location_id': quant.location_id.id,
                'location': quant.location_id.display_name,
            })
        for product in products.filtered(lambda p: p.id not in seen):
            rows.append({
                'row_key': f'product-{product.id}', 'quant_id': False,
                'product_id': product.id, 'product': product.display_name,
                'barcode': product.barcode or '', 'default_code': product.default_code or '',
                'uom': product.uom_id.name, 'tracking': product.tracking,
                'lot_id': False, 'lot_name': '', 'quantity': 0.0,
                'reserved_quantity': 0.0, 'available_quantity': 0.0,
                'location_id': location.id, 'location': location.display_name,
            })
        return rows

    @http.route('/nutkings/api/ping', type='http', auth='user', methods=['GET'], csrf=False)
    def ping(self, **kwargs):
        return request.make_json_response({
            'ok': True,
            'version': self.VERSION,
            'server_time': fields.Datetime.now().isoformat(),
            'user': {'id': request.env.user.id, 'name': request.env.user.name},
            'csrf_token': request.csrf_token(),
        })

    @http.route('/nutkings/api/bootstrap', type='http', auth='user', methods=['GET'], csrf=False)
    def bootstrap(self, **kwargs):
        permissions = self._permissions()
        if not permissions['has_nutkings_access']:
            return request.make_json_response({'error': 'Your user does not have a Nut Kings operational role.'}, status=403)
        setup = self._setup()
        products = self._products()
        allowed_product_types = []
        if permissions['raw']:
            allowed_product_types.append('raw_material')
        if permissions['finished']:
            allowed_product_types.append('finished_good')
        products = products.filtered(lambda product: product.nk_inventory_type in allowed_product_types)
        raw_products = products.filtered(lambda p: p.nk_inventory_type == 'raw_material')
        finished_products = products.filtered(lambda p: p.nk_inventory_type == 'finished_good')
        locations = setup['locations']
        restricted_area_ids = self._restricted_service_area_ids()
        truck_domain = [('company_id', '=', request.env.company.id), ('active', '=', True)]
        trip_domain = [('company_id', '=', request.env.company.id)]
        if restricted_area_ids is not False:
            truck_domain += ['|', ('service_area_ids', '=', False), ('service_area_ids', 'in', restricted_area_ids)]
            trip_domain += ['|', ('service_area_id', '=', False), ('service_area_id', 'in', restricted_area_ids)]
        trucks = request.env['nutkings.truck'].sudo().search(truck_domain, order='name') if permissions['distribution'] else request.env['nutkings.truck']
        trips = request.env['nutkings.trip'].sudo().search(
            trip_domain, order='planned_departure desc, id desc', limit=250,
        ) if permissions['distribution'] else request.env['nutkings.trip']
        picking_domain = [
            ('nk_is_operation', '=', True),
            ('company_id', '=', request.env.company.id),
            ('nk_operation_kind', 'in', permissions['capabilities']),
        ]
        pickings = request.env['stock.picking'].sudo().search(
            picking_domain, order='scheduled_date desc, id desc', limit=300,
        )
        if restricted_area_ids is not False:
            pickings = pickings.filtered(
                lambda picking: self._area_allowed(picking.nk_trip_id.service_area_id)
                and (
                    not picking.nk_truck_id.service_area_ids
                    or bool(set(picking.nk_truck_id.service_area_ids.ids) & set(restricted_area_ids))
                )
            )
        Partner = request.env['res.partner'].sudo()
        # Match Odoo's natural Contact field: any active top-level contact can
        # be selected. Nut Kings flags/ranks are still retained for menus and
        # prioritisation, but the offline selector never becomes a second
        # disconnected contact directory.
        contact_domain = [
            ('active', '=', True),
            ('type', 'in', (False, 'contact')),
            ('company_id', 'in', (False, request.env.company.id)),
        ]
        customer_domain = list(contact_domain)
        if restricted_area_ids is not False:
            customer_domain += ['|', ('nk_service_area_id', '=', False), ('nk_service_area_id', 'in', restricted_area_ids)]
        customers = Partner.search(customer_domain, order='nk_is_customer desc, name') if permissions['distribution'] else Partner
        suppliers = Partner.search(contact_domain, order='nk_is_supplier desc, name') if permissions['office_receiving'] else Partner
        staff = request.env['nutkings.staff'].sudo().search([
            ('company_id', '=', request.env.company.id), ('active', '=', True),
        ], order='name') if permissions['distribution'] else request.env['nutkings.staff']
        reasons = request.env['nutkings.movement.reason'].sudo().search([
            ('active', '=', True),
        ], order='sequence, name')
        all_nk_locations = request.env['stock.location'].sudo().search([
            ('company_id', '=', request.env.company.id), ('nk_location', '=', True),
        ])
        if permissions['manager']:
            visible_nk_locations = all_nk_locations
        else:
            visible_nk_locations = request.env['stock.location'].sudo().browse()
            if permissions['raw']:
                visible_nk_locations |= locations['rm_stock']
            if permissions['finished_goods_entry'] or permissions['distribution']:
                visible_nk_locations |= locations['fg_stock']
            if permissions['distribution']:
                visible_nk_locations |= trucks.mapped('stock_location_id')
        balance_roots = locations['rm_stock'] | locations['fg_stock'] | trucks.mapped('stock_location_id')
        balances_by_location = self._location_balances(products, balance_roots)
        balances = {'raw': {}, 'finished': {}, 'trucks': {}}
        on_hand = {'raw': {}, 'finished': {}, 'trucks': {}}
        product_rows = []
        for product in products:
            root = locations['rm_stock'] if product.nk_inventory_type == 'raw_material' else locations['fg_stock']
            amount = balances_by_location[root.id][product.id]
            key = str(product.id)
            bucket = 'raw' if product.nk_inventory_type == 'raw_material' else 'finished'
            balances[bucket][key] = amount['available']
            on_hand[bucket][key] = amount['quantity']
            product_rows.append({
                'id': product.id,
                'name': product.display_name,
                'default_code': product.default_code or '',
                'barcode': product.barcode or '',
                'type': product.nk_inventory_type,
                'uom': product.uom_id.name,
                'uom_rounding': product.uom_id.rounding,
                'tracking': product.tracking,
                'minimum': product.nk_minimum_qty,
                'minimum_qty': product.nk_minimum_qty,
                'pack_size': product.product_tmpl_id.nk_pack_size or '',
                'units_per_case': product.product_tmpl_id.nk_units_per_case,
                'quantity': amount['quantity'],
                'reserved': amount['reserved'],
                'available': amount['available'],
                'backend_url': product.nk_backend_url() if permissions['system'] else '',
            })
        truck_stock = []
        for truck in trucks:
            truck_key = str(truck.id)
            balances['trucks'][truck_key] = {}
            on_hand['trucks'][truck_key] = {}
            for product in finished_products:
                amount = balances_by_location[truck.stock_location_id.id][product.id]
                product_key = str(product.id)
                balances['trucks'][truck_key][product_key] = amount['available']
                on_hand['trucks'][truck_key][product_key] = amount['quantity']
                if amount['quantity'] or amount['reserved']:
                    truck_stock.append({
                        'truck_id': truck.id, 'truck': truck.name,
                        'product_id': product.id, 'product': product.display_name,
                        **amount,
                    })
        serialized_transfers = [
            self._serialize_picking(picking, include_backend_url=permissions['system'])
            for picking in pickings
        ]
        recent_operations = []
        movement_summary = defaultdict(float)
        for transfer in serialized_transfers:
            total = sum(float(line.get('demand') or 0.0) for line in transfer['moves'])
            workflow_state = (
                'draft' if transfer['state'] == 'draft'
                else 'ready' if transfer['state'] == 'assigned'
                else 'done' if transfer['state'] == 'done'
                else 'cancelled' if transfer['state'] == 'cancel'
                else 'waiting'
            )
            lines = [{
                'product_id': line['product_id'], 'product': line['product'],
                'barcode': line['barcode'], 'quantity': line['demand'],
                'uom': line['uom'], 'lot_reference': line['lot_reference'],
                'expiration_date': line['expiration_date'],
            } for line in transfer['moves']]
            recent_operations.append({
                **transfer,
                'operation_type': transfer['operation_type'],
                'operation_label': transfer['operation_label'],
                'date': transfer['scheduled_date'],
                'quantity': total,
                'workflow_state': workflow_state,
                'partner': transfer['partner'],
                'user': transfer['user'],
                'lines': lines,
                'web_url': transfer['backend_url'],
            })
            if transfer['state'] == 'done':
                movement_summary[transfer['operation_type']] += total
        trip_rows = [{
            'id': trip.id,
            'name': trip.name,
            'truck_id': trip.truck_id.id,
            'truck': trip.truck_id.name,
            'truck_name': trip.truck_id.name,
            'driver_id': trip.driver_id.id or False,
            'driver': trip.driver_id.name or '',
            'driver_name': trip.driver_id.name or '',
            'team_ids': trip.team_ids.ids,
            'customer_ids': trip.customer_ids.ids,
            'route': trip.route_name,
            'route_name': trip.route_name,
            'planned_departure': self._dt(trip.planned_departure),
            'actual_departure': self._dt(trip.actual_departure),
            'actual_return': self._dt(trip.actual_return),
            'state': trip.state,
            'state_label': dict(trip._fields['state'].selection).get(trip.state, trip.state),
            'loaded': trip.total_loaded,
            'delivered': trip.total_delivered,
            'returned': trip.total_returned,
            'damaged': trip.total_damaged,
            'variance': trip.total_variance,
            'total_loaded': trip.total_loaded,
            'total_delivered': trip.total_delivered,
            'total_returned': trip.total_returned,
            'total_damaged': trip.total_damaged,
            'total_variance': trip.total_variance,
            'variance_explanation': trip.variance_explanation or '',
            'variance_approved': trip.variance_approved,
            'reconciliation_lines': [{
                'product_id': line.product_id.id,
                'product': line.product_id.display_name,
                'loaded': line.qty_loaded,
                'delivered': line.qty_delivered,
                'returned': line.qty_returned,
                'damaged': line.qty_damaged,
                'variance': line.variance,
            } for line in trip.line_ids],
            'service_area_id': trip.service_area_id.id or False,
            'service_area': trip.service_area_id.name or '',
            'backend_url': f'/web#id={trip.id}&model=nutkings.trip&view_type=form' if permissions['system'] else '',
        } for trip in trips]
        low_stock = [{
            'product_id': item['id'], 'product': item['name'],
            'inventory_type': item['type'], 'quantity': item['available'],
            'minimum_qty': item['minimum_qty'],
        } for item in product_rows if item['minimum_qty'] > 0 and item['available'] <= item['minimum_qty']]
        stock_on_trucks = sum(item['quantity'] for item in truck_stock)
        open_trips = trips.filtered(lambda t: t.state not in ('done', 'cancelled'))
        pending_pickings = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
        return request.make_json_response({
            'app_version': self.VERSION,
            'workspace': request.httprequest.headers.get('X-NutKings-Workspace', ''),
            'user': {
                'id': request.env.user.id,
                'name': request.env.user.name,
                'login': request.env.user.login,
                'roles': sorted(request.env.user.nk_ops_role_codes()),
            },
            'company': {'id': request.env.company.id, 'name': request.env.company.name},
            'permissions': {key: value for key, value in permissions.items() if key != 'capabilities'},
            'capabilities': permissions['capabilities'],
            'native_actions': {
                'raw_inventory': request.env.ref('nut_kings_ops.action_nk_raw_physical_inventory').id,
                'finished_inventory': request.env.ref('nut_kings_ops.action_nk_finished_physical_inventory').id,
            } if permissions['system'] else {},
            'balances': balances,
            'on_hand': on_hand,
            'products': product_rows,
            'product_details': self._product_details(
                products,
                visible_nk_locations,
                pickings.ids,
                include_backend_urls=permissions['system'],
            ),
            'inventory_rows': {
                'raw': self._inventory_rows(raw_products, locations['rm_stock']) if permissions['raw_count'] else [],
                'finished': self._inventory_rows(finished_products, locations['fg_stock']) if permissions['finished_count'] else [],
            },
            'locations': [{
                'id': loc.id, 'name': loc.display_name, 'usage': loc.usage,
                'parent_id': loc.location_id.id or False, 'barcode': loc.barcode or '',
            } for loc in visible_nk_locations.filtered(lambda l: l.usage != 'view')],
            'trucks': [{
                'id': truck.id, 'name': truck.name,
                'registration': truck.registration_number,
                'barcode': truck.barcode or '',
                'make': truck.make or '', 'model': truck.model or '',
                'capacity': truck.capacity_note or '',
                'driver_id': truck.default_driver_id.id or False,
                'driver': truck.default_driver_id.name or '',
                'team_ids': truck.default_team_ids.ids,
                'location_id': truck.stock_location_id.id,
                'stock_location_id': truck.stock_location_id.id,
                'stock_location': truck.stock_location_id.display_name,
                'status': truck.status,
                'service_area_ids': truck.service_area_ids.ids,
            } for truck in trucks],
            'customers': [{
                'id': partner.id, 'name': partner.display_name,
                'code': partner.nk_customer_code or '',
                'phone': partner.phone or partner.nk_mobile or '',
                'email': partner.email or '', 'route': partner.nk_route or '',
                'address': partner.contact_address or '',
                'notes': partner.nk_delivery_notes or '',
                'service_area_id': partner.nk_service_area_id.id or False,
            } for partner in customers],
            'suppliers': [{
                'id': partner.id, 'name': partner.display_name, 'code': '',
                'phone': partner.phone or partner.nk_mobile or '',
                'email': partner.email or '', 'address': partner.contact_address or '',
            } for partner in suppliers],
            'staff': [{
                'id': member.id, 'name': member.name, 'employee_code': '',
                'role': member.role, 'phone': member.phone or '', 'email': member.email or '',
            } for member in staff],
            'trips': trip_rows,
            'service_areas': [{
                'id': area.id, 'name': area.name, 'code': area.code,
            } for area in request.env['nutkings.service.area'].sudo().browse(
                request.env.user.nk_ops_allowed_service_area_ids()
            )],
            'reasons': [{
                'id': reason.id, 'name': reason.name, 'code': reason.code,
                'applies_to': reason.applies_to, 'requires_note': reason.requires_note,
                'requires_supervisor': False,
            } for reason in reasons],
            'transfers': serialized_transfers,
            'recent_operations': recent_operations,
            'truck_stock': truck_stock,
            'dashboard': {
                'raw_quantity': sum(item['quantity'] for item in product_rows if item['type'] == 'raw_material'),
                'finished_quantity': sum(item['quantity'] for item in product_rows if item['type'] == 'finished_good'),
                'stock_on_trucks': stock_on_trucks,
                'low_stock': len(low_stock),
                'open_trips': len(open_trips),
                'pending_operations': len(pending_pickings),
                'raw_product_count': len(raw_products),
                'finished_product_count': len(finished_products),
                'truck_count': len(trucks),
                'open_trip_count': len(open_trips),
                'pending_operation_count': len(pending_pickings),
                'offline_exception_count': request.env['nutkings.sync.event'].sudo().search_count([('company_id', '=', request.env.company.id), ('state', '=', 'error')]),
                'low_stock_count': len(low_stock),
                'stock_on_trucks_qty': stock_on_trucks,
            },
            'reports': {
                'low_stock': low_stock,
                'movement_summary': dict(movement_summary),
                'truck_stock': [{'truck_id': truck.id, 'truck': truck.name, 'quantity': sum(on_hand['trucks'].get(str(truck.id), {}).values())} for truck in trucks],
                'trip_summary': trip_rows,
            },
            'server_time': fields.Datetime.now().isoformat(),
        })

    @http.route('/nutkings/api/workspace-users', type='http', auth='user', methods=['GET'], csrf=False)
    def workspace_users(self, **kwargs):
        try:
            self._workspace_user_admin_required()
            role_groups = self._workspace_role_groups()
            role_group_ids = [group.id for group in role_groups.values()]
            users = request.env['res.users'].with_context(active_test=False).sudo().search([
                ('id', '!=', SUPERUSER_ID),
                ('company_ids', 'in', request.env.company.id),
                ('group_ids', 'in', role_group_ids),
            ], order='active desc, name, login')
            areas = request.env['nutkings.service.area'].sudo().search([
                ('company_id', '=', request.env.company.id),
                ('active', '=', True),
            ], order='name, code')
            return request.make_json_response({
                'users': [self._workspace_user_payload(user, role_groups) for user in users],
                'roles': [
                    {'code': code, 'label': label}
                    for code, (_xmlid, label) in self.WORKSPACE_ROLES.items()
                ],
                'service_areas': [
                    {'id': area.id, 'name': area.name, 'code': area.code}
                    for area in areas
                ],
            })
        except AccessError as error:
            return self._workspace_user_error(error, status=403)

    @http.route('/nutkings/api/workspace-users/save', type='http', auth='user', methods=['POST'], csrf=False)
    def workspace_user_save(self, **kwargs):
        try:
            with request.env.cr.savepoint():
                self._workspace_user_admin_required()
                data = self._body()
                role_groups = self._workspace_role_groups()
                requested_roles = set(data.get('roles') or [])
                if not requested_roles or not requested_roles.issubset(role_groups):
                    raise ValidationError('Select at least one valid Nut Kings workspace role.')

                name = str(data.get('name') or '').strip()
                login = str(data.get('login') or '').strip()
                email = str(data.get('email') or '').strip()
                password = str(data.get('password') or '')
                user_id = self._safe_int(data.get('id'))
                if not name or not login:
                    raise ValidationError('Name and login are required.')
                if password and len(password) < 8:
                    raise ValidationError('The password must contain at least 8 characters.')
                if not user_id and not password:
                    raise ValidationError('Enter an initial password for the new workspace user.')

                Users = request.env['res.users'].with_context(active_test=False).sudo()
                duplicate = Users.search([
                    ('login', '=ilike', login),
                    ('id', '!=', user_id or 0),
                ], limit=1)
                if duplicate:
                    raise ValidationError('That login is already used by another Odoo account.')

                requested_area_ids = {
                    self._safe_int(area_id) for area_id in (data.get('service_area_ids') or [])
                    if self._safe_int(area_id)
                }
                valid_areas = request.env['nutkings.service.area'].sudo().search([
                    ('id', 'in', list(requested_area_ids)),
                    ('company_id', '=', request.env.company.id),
                    ('active', '=', True),
                ])
                if len(valid_areas) != len(requested_area_ids):
                    raise ValidationError('One or more selected service areas are not available for this company.')

                selected_group_ids = {role_groups[code].id for code in requested_roles}
                all_role_group_ids = {group.id for group in role_groups.values()}
                portal_group = request.env.ref('base.group_portal').sudo()
                internal_group = request.env.ref('base.group_user').sudo()
                stock_user_group = request.env.ref('stock.group_stock_user').sudo()
                stock_manager_group = request.env.ref('stock.group_stock_manager').sudo()
                active = bool(data.get('active', True))
                values = {
                    'name': name,
                    'login': login,
                    'email': email,
                    'active': active,
                    'nk_service_area_ids': [Command.set(valid_areas.ids)],
                }
                if password:
                    values['password'] = password

                if user_id:
                    user = Users.browse(user_id).exists()
                    if not user or user.company_ids != request.env.company or not (set(user.group_ids.ids) & all_role_group_ids):
                        raise ValidationError('The selected workspace user was not found for this company.')
                    if user.id == SUPERUSER_ID or user.has_group('base.group_system'):
                        raise AccessError('Odoo administrator accounts can only be changed in the Odoo backend.')
                    removable_group_ids = all_role_group_ids | {
                        portal_group.id,
                        internal_group.id,
                        stock_user_group.id,
                        stock_manager_group.id,
                    }
                    preserved_backend_groups = user.group_ids.filtered(
                        lambda group: group.id not in removable_group_ids
                        and internal_group in group.all_implied_ids
                    )
                    if preserved_backend_groups:
                        raise ValidationError(
                            'This account has other Odoo backend access groups and cannot be converted safely in the workspace. '
                            'Use a separate workspace account or ask an Odoo administrator to remove those backend groups first.'
                        )
                    values['group_ids'] = (
                        [Command.unlink(group_id) for group_id in all_role_group_ids]
                        + [Command.unlink(internal_group.id), Command.unlink(stock_user_group.id), Command.unlink(stock_manager_group.id)]
                        + [Command.link(group_id) for group_id in selected_group_ids | {portal_group.id}]
                    )
                    user.write(values)
                else:
                    values.update({
                        'company_id': request.env.company.id,
                        'company_ids': [Command.set([request.env.company.id])],
                        'group_ids': [Command.set(list(selected_group_ids | {portal_group.id}))],
                    })
                    user = Users.with_context(no_reset_password=True).create(values)

                return request.make_json_response({
                    'ok': True,
                    'user': self._workspace_user_payload(user, role_groups),
                })
        except AccessError as error:
            return self._workspace_user_error(error, status=403)
        except (ValidationError, ValueError) as error:
            return self._workspace_user_error(error, status=400)

    @classmethod
    def _resolve_partner(cls, item, required=False, supplier=False):
        partner_id = cls._safe_int(item.get('partner_id'))
        if not partner_id:
            if required:
                raise ValueError('Select the customer, company, or supplier.')
            return request.env['res.partner']
        partner = request.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner or (partner.company_id and partner.company_id != request.env.company):
            raise ValueError('The selected contact no longer exists.')
        if not supplier and not cls._area_allowed(partner.nk_service_area_id):
            raise ValueError('The selected customer is outside your assigned service areas.')
        return partner

    @classmethod
    def _resolve_truck(cls, item, required=False):
        truck_id = cls._safe_int(item.get('truck_id'))
        if not truck_id:
            if required:
                raise ValueError('Select the van.')
            return request.env['nutkings.truck']
        truck = request.env['nutkings.truck'].sudo().browse(truck_id).exists()
        if not truck or truck.company_id != request.env.company:
            raise ValueError('Select a valid Nut Kings van.')
        restricted_area_ids = cls._restricted_service_area_ids()
        if restricted_area_ids is not False and truck.service_area_ids and not set(truck.service_area_ids.ids) & set(restricted_area_ids):
            raise ValueError('The selected van is outside your assigned service areas.')
        truck._ensure_stock_location()
        return truck

    @classmethod
    def _resolve_trip(cls, item, required=False):
        trip_id = cls._safe_int(item.get('trip_id'))
        trip = request.env['nutkings.trip']
        if trip_id:
            trip = request.env['nutkings.trip'].sudo().browse(trip_id).exists()
        elif item.get('trip_external_uid'):
            event = request.env['nutkings.sync.event'].sudo().search([
                ('external_uid', '=', str(item.get('trip_external_uid'))[:128]),
                ('company_id', '=', request.env.company.id),
                ('state', '=', 'processed'),
                ('trip_id', '!=', False),
            ], limit=1)
            trip = event.trip_id
        if trip and trip.company_id != request.env.company:
            trip = request.env['nutkings.trip']
        if trip and not cls._area_allowed(trip.service_area_id):
            trip = request.env['nutkings.trip']
        if required and not trip:
            raise ValueError('Select a valid trip.')
        return trip

    @classmethod
    def _operation_map(cls, item):
        kind = item.get('operation_type')
        cls._require(kind)
        setup = cls._setup()
        locations = setup['locations']
        picking_types = setup['picking_types']
        truck = cls._resolve_truck(item, required=kind in ('finished_to_truck', 'customer_delivery', 'truck_return'))
        trip = cls._resolve_trip(item)
        partner = request.env['res.partner']
        if kind == 'raw_receipt':
            partner = cls._resolve_partner(item, required=True, supplier=True)
            config = (picking_types['raw_receipt'], picking_types['raw_receipt'].default_location_src_id, locations['rm_stock'], 'raw_material')
        elif kind == 'raw_issue':
            config = (picking_types['raw_issue'], locations['rm_stock'], locations['rm_use'], 'raw_material')
        elif kind == 'finished_receipt':
            config = (picking_types['finished_receipt'], locations['fg_entry'], locations['fg_stock'], 'finished_good')
        elif kind == 'finished_to_truck':
            partner = cls._resolve_partner(item, required=False)
            config = (picking_types['finished_to_truck'], locations['fg_stock'], truck.stock_location_id, 'finished_good')
        elif kind == 'customer_delivery':
            partner = cls._resolve_partner(item, required=True)
            config = (picking_types['customer_delivery'], truck.stock_location_id, picking_types['customer_delivery'].default_location_dest_id, 'finished_good')
        elif kind == 'truck_return':
            partner = cls._resolve_partner(item, required=False)
            config = (picking_types['truck_return'], truck.stock_location_id, locations['fg_stock'], 'finished_good')
        else:
            raise ValueError('Unsupported Nut Kings operation.')
        if trip and truck and trip.truck_id != truck:
            raise ValueError('The selected trip belongs to a different van.')
        if trip and partner and trip.service_area_id and partner.nk_service_area_id and partner.nk_service_area_id != trip.service_area_id:
            raise ValueError('The selected customer is outside the trip service area.')
        if truck and partner and truck.service_area_ids and partner.nk_service_area_id and partner.nk_service_area_id not in truck.service_area_ids:
            raise ValueError('The selected customer is outside the van service areas.')
        if trip and kind == 'finished_to_truck' and trip.state not in ('planned', 'loading'):
            raise ValueError('Van loading is only allowed while the trip is Planned or Loading.')
        if trip and kind in ('customer_delivery', 'truck_return') and trip.state not in ('in_progress', 'reconciliation'):
            raise ValueError('Deliveries and van returns require an in-progress or reconciling trip.')
        return {'kind': kind, 'picking_type': config[0], 'source': config[1], 'destination': config[2], 'product_type': config[3], 'partner': partner, 'truck': truck, 'trip': trip}

    @classmethod
    def _create_transfer(cls, item, sync_event):
        config = cls._operation_map(item)
        if item.get('force_demand'):
            cls._require('manager')
        reason_id = cls._safe_int(item.get('reason_id'))
        reason = request.env['nutkings.movement.reason'].sudo().browse(reason_id).exists() if reason_id else request.env['nutkings.movement.reason']
        if reason:
            reason_scope = 'raw' if config['kind'] in ('raw_receipt', 'raw_issue') else 'distribution' if config['kind'] in ('finished_to_truck', 'customer_delivery', 'truck_return') else 'finished'
            if not reason.active or reason.applies_to not in ('all', reason_scope):
                raise ValueError('Select a movement reason that applies to this operation.')
            if reason.requires_note and not str(item.get('notes') or '').strip():
                raise ValueError('The selected movement reason requires an explanation in Notes.')
        lines = item.get('lines') or []
        if not isinstance(lines, list) or not lines or len(lines) > cls.MAX_LINES:
            raise ValueError(f'Add between 1 and {cls.MAX_LINES} product lines.')
        moves = []
        seen = set()
        for line in lines:
            product = request.env['product.product'].sudo().browse(cls._safe_int(line.get('product_id'))).exists()
            if not product or (product.company_id and product.company_id != request.env.company) or product.nk_inventory_type != config['product_type']:
                raise ValueError('A selected product does not belong to this warehouse.')
            quantity = float(line.get('quantity') or 0.0)
            if float_compare(quantity, 0.0, precision_rounding=product.uom_id.rounding) <= 0:
                raise ValueError(f'Enter a positive quantity for {product.display_name}.')
            identity = (product.id, str(line.get('lot_reference') or ''))
            if identity in seen:
                raise ValueError(f'Combine duplicate lines for {product.display_name}.')
            seen.add(identity)
            moves.append(Command.create({
                'description_picking': product.display_name,
                'product_id': product.id,
                'product_uom_qty': quantity,
                'product_uom': product.uom_id.id,
                'location_id': config['source'].id,
                'location_dest_id': config['destination'].id,
                'nk_lot_reference': str(line.get('lot_reference') or '')[:128] or False,
                'nk_expiration_date': line.get('expiration_date') or False,
            }))
        picking = request.env['stock.picking'].sudo().create({
            'picking_type_id': config['picking_type'].id,
            'location_id': config['source'].id,
            'location_dest_id': config['destination'].id,
            'partner_id': config['partner'].id or False,
            'scheduled_date': cls._device_datetime(item.get('scheduled_date') or item.get('created_on_device')),
            'origin': str(item.get('reference') or '')[:256] or False,
            'note': str(item.get('notes') or '')[:4000] or False,
            'move_ids': moves,
            'nk_is_operation': True,
            'nk_operation_kind': config['kind'],
            'nk_truck_id': config['truck'].id or False,
            'nk_trip_id': config['trip'].id or False,
            'nk_reason_id': reason.id or False,
            'nk_sync_uid': sync_event.external_uid,
            'nk_device_name': sync_event.device_name,
            'nk_created_offline': bool(item.get('created_offline')),
            'nk_reference': str(item.get('reference') or '')[:256] or False,
            'nk_workspace_user_id': request.env.user.id,
            'company_id': request.env.company.id,
        })
        if config['kind'] == 'finished_to_truck' and config['trip'] and config['trip'].state == 'planned':
            config['trip'].action_start_loading()
        sync_event.write({'picking_id': picking.id, 'truck_id': config['truck'].id or False, 'trip_id': config['trip'].id or False, 'result_reference': picking.name})
        for action in item.get('actions') or []:
            result = picking.with_context(nk_actor_user_id=request.env.user.id).nk_execute_action(
                action,
                allocations=item.get('allocations') or [],
                force_demand=bool(item.get('force_demand')),
                backorder=item.get('backorder') or 'ask',
            )
            if result.get('requires_dialog'):
                return picking, result
        return picking, {}

    @classmethod
    def _apply_picking_action(cls, item, sync_event):
        picking = request.env['stock.picking'].sudo().browse(cls._safe_int(item.get('picking_id'))).exists()
        if not picking or not picking.nk_is_operation or picking.company_id != request.env.company:
            raise ValueError('The stock transfer could not be found.')
        cls._require(picking.nk_operation_kind)
        if not cls._picking_allowed(picking):
            raise ValueError('The stock transfer is outside your assigned service areas.')
        if item.get('force_demand'):
            cls._require('manager')
        result = picking.with_context(nk_actor_user_id=request.env.user.id).nk_execute_action(
            item.get('action'),
            allocations=item.get('allocations') or [],
            force_demand=bool(item.get('force_demand')),
            backorder=item.get('backorder') or 'ask',
        )
        sync_event.write({'picking_id': picking.id, 'result_reference': picking.name})
        return picking, result

    @classmethod
    def _apply_inventory_count(cls, item, sync_event):
        warehouse = item.get('warehouse') or item.get('warehouse_type')
        setup = cls._setup()
        if warehouse == 'raw':
            cls._require('raw_count')
            inventory_type, location, label = 'raw_material', setup['locations']['rm_stock'], 'Raw Materials'
        elif warehouse == 'finished':
            cls._require('finished_count')
            inventory_type, location, label = 'finished_good', setup['locations']['fg_stock'], 'Finished Goods'
        else:
            raise ValueError('Choose Raw Materials or Finished Goods.')
        lines = item.get('lines') or []
        if not isinstance(lines, list) or not lines or len(lines) > cls.MAX_LINES:
            raise ValueError(f'Add between 1 and {cls.MAX_LINES} counted lines.')
        reference = str(item.get('reference') or '')[:256] or f'{label} count {fields.Date.today()}'
        Quant = request.env['stock.quant'].sudo().with_context(
            inventory_mode=True,
            default_location_id=location.id,
            inventory_name=reference,
        )
        to_apply = Quant.browse()
        differences = []
        seen = set()
        for line in lines:
            product = request.env['product.product'].sudo().browse(cls._safe_int(line.get('product_id'))).exists()
            if not product or (product.company_id and product.company_id != request.env.company) or product.nk_inventory_type != inventory_type:
                raise ValueError('A counted product does not belong to this warehouse.')
            counted = float(line.get('counted_quantity') or 0.0)
            expected = float(line.get('expected_quantity') or 0.0)
            if float_compare(counted, 0.0, precision_rounding=product.uom_id.rounding) < 0:
                raise ValueError(f'The counted quantity for {product.display_name} cannot be negative.')
            lot_id = cls._safe_int(line.get('lot_id'))
            lot = request.env['stock.lot'].sudo().browse(lot_id).exists() if lot_id else request.env['stock.lot']
            if lot and (lot.product_id != product or (lot.company_id and lot.company_id != request.env.company)):
                raise ValueError(f'The selected lot does not belong to {product.display_name} in this company.')
            lot_reference = str(line.get('lot_reference') or '').strip()[:128]
            if product.tracking != 'none' and not lot:
                if not lot_reference:
                    raise ValueError(f'{product.display_name} requires a lot or serial number.')
                lot = request.env['stock.lot'].sudo().search([
                    ('name', '=', lot_reference),
                    ('product_id', '=', product.id),
                    ('company_id', 'in', (False, request.env.company.id)),
                ], limit=1)
                if not lot:
                    lot = request.env['stock.lot'].sudo().create({
                        'name': lot_reference,
                        'product_id': product.id,
                        'company_id': request.env.company.id,
                    })
            quant = Quant.browse(cls._safe_int(line.get('quant_id'))).exists() if cls._safe_int(line.get('quant_id')) else Quant
            if quant:
                location_path = location.parent_path or f'{location.id}/'
                if (
                    quant.product_id != product
                    or (quant.company_id and quant.company_id != request.env.company)
                    or (
                        quant.location_id != location
                        and not (quant.location_id.parent_path or '').startswith(location_path)
                    )
                    or (lot and quant.lot_id != lot)
                ):
                    raise ValueError('A counted stock row no longer matches this warehouse, product, or lot.')
            if not quant:
                quant = Quant.search([
                    ('product_id', '=', product.id), ('location_id', '=', location.id),
                    ('lot_id', '=', lot.id or False),
                    ('company_id', 'in', (False, request.env.company.id)),
                ], limit=1)
            identity = ('quant', quant.id) if quant else ('new', product.id, lot.id or False, location.id)
            if identity in seen:
                raise ValueError(f'Combine duplicate count rows for {product.display_name}.')
            seen.add(identity)
            current = quant.quantity if quant else 0.0
            if not item.get('force_conflicts') and float_compare(current, expected, precision_rounding=product.uom_id.rounding) != 0:
                raise ValueError(f'{product.display_name} changed from {expected} to {current}. Synchronize and recount.')
            if not quant:
                quant = Quant.create({'product_id': product.id, 'location_id': location.id, 'lot_id': lot.id or False, 'inventory_quantity': counted})
            else:
                quant.write({'inventory_quantity': counted, 'inventory_date': cls._date(item.get('count_date')), 'user_id': request.env.user.id})
            to_apply |= quant
            differences.append({'product': product.display_name, 'expected': current, 'counted': counted, 'difference': counted - current})
        result = to_apply.with_context(inventory_mode=True, inventory_name=reference).action_apply_inventory(
            date=cls._date(item.get('count_date')),
        )
        if isinstance(result, dict):
            raise ValueError('Odoo detected an inventory-count conflict. Review it in the backend.')
        sync_event.result_reference = reference
        return {'reference': reference, 'differences': differences}

    @classmethod
    def _create_contact(cls, item, sync_event):
        cls._require('contacts')
        name = str(item.get('name') or '').strip()[:256]
        if not name:
            raise ValueError('Enter the contact name.')
        customer = item.get('contact_role') != 'supplier'
        service_area_id = cls._safe_int(item.get('service_area_id'))
        service_area = request.env['nutkings.service.area'].sudo().browse(service_area_id).exists() if service_area_id else request.env['nutkings.service.area']
        if service_area and (service_area.company_id != request.env.company or not cls._area_allowed(service_area)):
            raise ValueError('Select a valid service area.')
        values = {
            'name': name,
            'company_id': request.env.company.id,
            'company_type': 'company' if item.get('company_type') == 'company' else 'person',
            'is_company': item.get('company_type') == 'company',
            'phone': str(item.get('phone') or '')[:64] or False,
            'nk_mobile': str(item.get('mobile') or '')[:64] or False,
            'email': str(item.get('email') or '')[:256] or False,
            'street': str(item.get('street') or '')[:256] or False,
            'street2': str(item.get('street2') or '')[:256] or False,
            'city': str(item.get('city') or '')[:128] or False,
            'nk_customer_code': str(item.get('customer_code') or '')[:64] or False,
            'nk_route': str(item.get('route') or '')[:128] or False,
            'nk_delivery_notes': str(item.get('notes') or '')[:2000] or False,
            'nk_service_area_id': service_area.id or False,
            'nk_is_customer': customer,
            'nk_is_supplier': not customer,
        }
        Partner = request.env['res.partner'].sudo()
        if customer and 'customer_rank' in Partner._fields:
            values['customer_rank'] = 1
        if not customer and 'supplier_rank' in Partner._fields:
            values['supplier_rank'] = 1
        partner = Partner.create(values)
        sync_event.write({'partner_id': partner.id, 'result_reference': partner.display_name})
        return {'reference': partner.display_name, 'partner_id': partner.id}

    @classmethod
    def _create_trip(cls, item, sync_event):
        cls._require('distribution')
        truck = cls._resolve_truck(item, required=True)
        service_area_id = cls._safe_int(item.get('service_area_id'))
        service_area = request.env['nutkings.service.area'].sudo().browse(service_area_id).exists() if service_area_id else request.env['nutkings.service.area']
        if service_area and (service_area.company_id != request.env.company or not cls._area_allowed(service_area)):
            raise ValueError('Select a valid service area.')
        driver_id = cls._safe_int(item.get('driver_id'))
        driver = request.env['nutkings.staff'].sudo().browse(driver_id).exists() if driver_id else request.env['nutkings.staff']
        if not driver or driver.company_id != request.env.company or driver.role != 'driver':
            raise ValueError('Select a valid driver for this company.')
        try:
            team_ids = [int(value) for value in item.get('team_ids') or []]
            customer_ids = [int(value) for value in item.get('customer_ids') or []]
        except (TypeError, ValueError):
            raise ValueError('The selected trip team or customer list is invalid.')
        team = request.env['nutkings.staff'].sudo().browse(team_ids).exists()
        if len(team) != len(set(team_ids)) or any(member.company_id != request.env.company for member in team):
            raise ValueError('A selected team member is invalid for this company.')
        customers = request.env['res.partner'].sudo().browse(customer_ids).exists()
        if len(customers) != len(set(customer_ids)):
            raise ValueError('A selected customer no longer exists.')
        if any(
            (partner.company_id and partner.company_id != request.env.company)
            or not cls._area_allowed(partner.nk_service_area_id)
            or (service_area and partner.nk_service_area_id and partner.nk_service_area_id != service_area)
            for partner in customers
        ):
            raise ValueError('A selected customer is outside this company or service area.')
        trip = request.env['nutkings.trip'].sudo().create({
            'truck_id': truck.id,
            'driver_id': driver.id,
            'team_ids': [Command.set(team.ids)],
            'customer_ids': [Command.set(customers.ids)],
            'route_name': str(item.get('route') or item.get('route_name') or '').strip()[:256] or 'Unspecified Route',
            'service_area_id': service_area.id or False,
            'planned_departure': cls._device_datetime(item.get('planned_departure')),
            'notes': str(item.get('notes') or '')[:4000] or False,
            'company_id': request.env.company.id,
        })
        sync_event.write({'trip_id': trip.id, 'truck_id': truck.id, 'result_reference': trip.name})
        return {'reference': trip.name, 'trip_id': trip.id}

    @classmethod
    def _trip_action(cls, item, sync_event):
        cls._require('distribution')
        trip = cls._resolve_trip(item, required=True)
        action = item.get('action')
        if action == 'close':
            cls._require('manager')
            trip._refresh_lines()
            if float_compare(trip.total_variance, 0.0, precision_digits=2) != 0:
                explanation = str(item.get('variance_explanation') or '').strip()[:4000]
                if not explanation:
                    raise ValueError('Enter the variance explanation before closing this trip.')
                trip.write({
                    'variance_explanation': explanation,
                    'variance_approved': True,
                })
        elif item.get('variance_approved'):
            cls._require('manager')
        method = {
            'start_loading': trip.action_start_loading,
            'depart': trip.action_depart,
            'return': trip.action_return,
            'close': trip.action_close,
            'cancel': trip.action_cancel,
        }.get(action)
        if not method:
            raise ValueError('Unsupported trip action.')
        if action != 'close' and item.get('variance_explanation'):
            trip.variance_explanation = str(item.get('variance_explanation'))[:4000]
        if action != 'close' and item.get('variance_approved'):
            trip.variance_approved = True
        method()
        sync_event.write({'trip_id': trip.id, 'truck_id': trip.truck_id.id, 'result_reference': trip.name})
        return {'reference': trip.name, 'trip_id': trip.id}

    @classmethod
    def _process(cls, item, sync_event):
        kind = item.get('kind')
        if kind == 'create_transfer':
            picking, result = cls._create_transfer(item, sync_event)
            return {'reference': picking.name, 'picking_id': picking.id, 'transfer': cls._serialize_picking(picking), **result}
        if kind == 'picking_action':
            picking, result = cls._apply_picking_action(item, sync_event)
            return {'reference': picking.name, 'picking_id': picking.id, 'transfer': cls._serialize_picking(picking), **result}
        if kind == 'physical_inventory':
            return cls._apply_inventory_count(item, sync_event)
        if kind == 'contact_create':
            return cls._create_contact(item, sync_event)
        if kind == 'trip_create':
            return cls._create_trip(item, sync_event)
        if kind == 'trip_action':
            return cls._trip_action(item, sync_event)
        raise ValueError('Unsupported Nut Kings transaction type.')

    @http.route('/nutkings/api/operation-action', type='http', auth='user', methods=['POST'], csrf=False)
    def operation_action(self, **kwargs):
        item = self._body()
        picking = request.env['stock.picking'].sudo().browse(self._safe_int(item.get('operation_id'))).exists()
        if not picking or not picking.nk_is_operation or picking.company_id != request.env.company:
            return request.make_json_response({'error': 'The stock transfer could not be found.'}, status=404)
        action = item.get('action')
        action = {'confirm': 'mark_todo', 'process': 'validate'}.get(action, action)
        try:
            with request.env.cr.savepoint():
                self._require(picking.nk_operation_kind)
                if not self._picking_allowed(picking):
                    raise ValueError('The stock transfer is outside your assigned service areas.')
                if item.get('force_demand'):
                    self._require('manager')
                result = picking.with_context(nk_actor_user_id=request.env.user.id).nk_execute_action(
                    action,
                    allocations=item.get('allocations') or [],
                    force_demand=bool(item.get('force_demand')),
                    backorder=item.get('backorder') or 'ask',
                )
                picking.invalidate_recordset()
                return request.make_json_response({
                    'operation': self._serialize_picking(picking),
                    'requires_dialog': bool(result.get('requires_dialog')),
                    'result': result,
                })
        except Exception as exc:
            return request.make_json_response({'error': str(exc)}, status=400)

    @http.route('/nutkings/api/sync', type='http', auth='user', methods=['POST'], csrf=False)
    def sync(self, **kwargs):
        payload = self._body()
        transactions = payload.get('transactions') or []
        if not isinstance(transactions, list) or len(transactions) > self.MAX_BATCH:
            return request.make_json_response({'error': 'Invalid transaction batch.'}, status=400)
        priority = {'contact_create': 0, 'trip_create': 5, 'create_transfer': 10, 'picking_action': 20, 'physical_inventory': 30, 'trip_action': 40}
        transactions = sorted(transactions, key=lambda item: (priority.get(item.get('kind'), 99), str(item.get('created_on_device') or '')))
        Event = request.env['nutkings.sync.event'].sudo()
        results = []
        for item in transactions:
            external_uid = str(item.get('external_uid') or uuid.uuid4())[:128]
            owner = self._safe_int(item.get('owner_user_id'))
            if owner and owner != request.env.uid:
                results.append({'external_uid': external_uid, 'kind': item.get('kind'), 'status': 'error', 'error': 'This saved action belongs to another user. Sign in as its owner to synchronize.'})
                continue
            existing = Event.search([
                ('external_uid', '=', external_uid),
                ('company_id', '=', request.env.company.id),
            ], limit=1)
            if existing and existing.user_id.id != request.env.uid:
                results.append({'external_uid': external_uid, 'kind': item.get('kind'), 'status': 'error', 'error': 'This saved action belongs to another user.'})
                continue
            if existing and existing.state == 'processed':
                results.append({'external_uid': external_uid, 'kind': existing.transaction_kind, 'status': 'processed', 'reference': existing.result_reference or '', 'picking_id': existing.picking_id.id or False, 'partner_id': existing.partner_id.id or False, 'trip_id': existing.trip_id.id or False})
                continue
            values = {
                'transaction_kind': str(item.get('kind') or '')[:64],
                'device_name': str(item.get('device_name') or '')[:128],
                'created_on_device': self._device_datetime(item.get('created_on_device')),
                'received_at': fields.Datetime.now(),
                'user_id': request.env.user.id,
                'company_id': request.env.company.id,
                'payload': json.dumps(item),
                'state': 'pending',
                'error_message': False,
            }
            event = existing or Event.create({'external_uid': external_uid, **values})
            if existing:
                existing.write(values)
            try:
                with request.env.cr.savepoint():
                    result = self._process(item, event)
                if result.get('requires_dialog'):
                    event.write({'state': 'needs_action', 'processed_at': fields.Datetime.now()})
                    results.append({'external_uid': external_uid, 'kind': item.get('kind'), 'status': 'needs_action', **result})
                else:
                    event.write({'state': 'processed', 'processed_at': fields.Datetime.now(), 'error_message': False})
                    results.append({'external_uid': external_uid, 'kind': item.get('kind'), 'status': 'processed', **result})
            except Exception as exc:
                event.write({'state': 'error', 'error_message': str(exc)[:2000]})
                results.append({'external_uid': external_uid, 'kind': item.get('kind'), 'status': 'error', 'error': str(exc)})
        return request.make_json_response({'results': results, 'server_time': fields.Datetime.now().isoformat()})

    @http.route('/nutkings/transfer/<int:picking_id>/print', type='http', auth='user', methods=['GET'])
    def print_transfer(self, picking_id, **kwargs):
        picking = request.env['stock.picking'].sudo().browse(picking_id).exists()
        if not picking or not picking.nk_is_operation or picking.company_id != request.env.company:
            return request.not_found()
        try:
            self._require(picking.nk_operation_kind)
            if not self._picking_allowed(picking):
                return request.not_found()
            pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
                'nut_kings_ops.action_report_nk_transfer',
                res_ids=[picking.id],
            )
        except Exception as exc:
            return request.make_response(f'Unable to print this transfer: {exc}', status=500)
        filename = f'Nut-Kings-{picking.name}'.replace('/', '-').replace('\\', '-')
        return request.make_response(pdf, headers=[('Content-Type', 'application/pdf'), ('Content-Disposition', f'inline; filename="{filename}.pdf"'), ('Cache-Control', 'no-store, max-age=0')])
