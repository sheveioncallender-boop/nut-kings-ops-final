from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


OPERATION_KINDS = [
    ('raw_receipt', 'Raw Materials — Receiving'),
    ('raw_issue', 'Raw Materials — Issuing'),
    ('finished_receipt', 'Finished Goods — Receiving'),
    ('finished_to_truck', 'Finished Goods — Issued'),
    ('customer_delivery', 'Customer Delivery'),
    ('truck_return', 'Return Van Stock'),
    ('damage', 'Damaged / Write-Off'),
]


class StockMove(models.Model):
    _inherit = 'stock.move'

    nk_lot_reference = fields.Char(string='Requested Batch / Lot', copy=False)
    nk_expiration_date = fields.Date(string='Requested Expiration Date', copy=False)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    nk_is_operation = fields.Boolean(string='Nut Kings Transfer', default=False, index=True, copy=False)
    nk_operation_kind = fields.Selection(OPERATION_KINDS, string='Nut Kings Operation', index=True, copy=False)
    nk_truck_id = fields.Many2one('nutkings.truck', string='Van', index=True, copy=False, tracking=True)
    nk_trip_id = fields.Many2one('nutkings.trip', string='Distribution Trip', index=True, copy=False, tracking=True, ondelete='set null')
    nk_reason_id = fields.Many2one('nutkings.movement.reason', string='Movement Reason', copy=False, tracking=True)
    nk_sync_uid = fields.Char(string='Offline Transaction ID', index=True, copy=False, readonly=True)
    nk_device_name = fields.Char(string='Originating Device', copy=False, readonly=True)
    nk_created_offline = fields.Boolean(string='Created Offline', default=False, copy=False, readonly=True)
    nk_reference = fields.Char(string='Nut Kings Reference', copy=False, tracking=True)
    nk_workspace_user_id = fields.Many2one(
        'res.users',
        string='Done by',
        copy=False,
        readonly=True,
        index=True,
        help='Authenticated workspace creator until validation; the authenticated person who completes the transfer after validation. Native Created by remains available separately.',
    )

    _nk_sync_uid_unique = models.Constraint('unique(nk_sync_uid)', 'This offline transfer has already been synchronized.')

    def _action_done(self):
        # sudo() retains the authenticated uid in Odoo. Never take attribution
        # from a browser payload or from a caller-supplied context actor id.
        pending = self.filtered(lambda p: p.nk_is_operation and p.state != 'done')
        actor_id = self.env.uid
        result = super()._action_done()
        pending.filtered(lambda p: p.state == 'done').write({'nk_workspace_user_id': actor_id})
        return result

    def nk_state_label(self):
        self.ensure_one()
        return {
            'draft': 'Draft',
            'confirmed': 'Waiting',
            'waiting': 'Waiting',
            'partially_available': 'Waiting',
            'assigned': 'Ready',
            'done': 'Done',
            'cancel': 'Cancelled',
        }.get(self.state, self.state or '')

    def nk_available_actions(self):
        self.ensure_one()
        actions = []
        if self.state == 'draft':
            actions += ['mark_todo', 'validate', 'cancel']
        elif self.state in ('confirmed', 'waiting', 'partially_available'):
            if self.show_check_availability:
                actions.append('check_availability')
            actions += ['validate', 'cancel']
        elif self.state == 'assigned':
            actions += ['validate', 'print', 'cancel']
        elif self.state == 'done':
            actions += ['return', 'print']
        return actions

    def _nk_find_or_create_lot(self, move):
        reference = (move.nk_lot_reference or '').strip()
        if not reference or move.product_id.tracking == 'none':
            return self.env['stock.lot']
        lot = self.env['stock.lot'].sudo().search([
            ('name', '=', reference),
            ('product_id', '=', move.product_id.id),
            ('company_id', 'in', (False, move.company_id.id)),
        ], limit=1)
        if not lot:
            values = {
                'name': reference,
                'product_id': move.product_id.id,
                'company_id': move.company_id.id,
            }
            if move.nk_expiration_date and 'expiration_date' in self.env['stock.lot']._fields:
                values['expiration_date'] = move.nk_expiration_date
            lot = self.env['stock.lot'].sudo().create(values)
        return lot

    def _nk_prepare_quantities(self, allocations=None, force_demand=False):
        self.ensure_one()
        allocations = allocations or []
        by_product = {}
        for item in allocations:
            product_id = int(item.get('product_id') or 0)
            if product_id:
                by_product.setdefault(product_id, []).append(item)

        moves = self.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
        if allocations:
            if self.state == 'draft':
                self.action_confirm()
            if self.state in ('assigned', 'partially_available'):
                self.do_unreserve()
            self.move_line_ids.filtered(lambda line: line.state not in ('done', 'cancel')).unlink()
            MoveLine = self.env['stock.move.line'].sudo()
            for move in moves:
                total = 0.0
                for item in by_product.get(move.product_id.id, []):
                    location = self.env['stock.location'].sudo().browse(int(item.get('location_id') or move.location_id.id)).exists()
                    if not location or location.usage == 'view':
                        raise ValidationError(_('Select a valid source location.'))
                    source_path = move.location_id.parent_path or f'{move.location_id.id}/'
                    if location != move.location_id and not (location.parent_path or '').startswith(source_path):
                        raise ValidationError(_('%s is outside the transfer source location.') % location.display_name)
                    quantity = float(item.get('quantity') or 0.0)
                    if float_compare(quantity, 0.0, precision_rounding=move.product_uom.rounding) <= 0:
                        continue
                    lot = self.env['stock.lot']
                    lot_id = int(item.get('lot_id') or 0)
                    if lot_id:
                        lot = self.env['stock.lot'].sudo().browse(lot_id).exists()
                        if not lot or lot.product_id != move.product_id or (lot.company_id and lot.company_id != move.company_id):
                            raise ValidationError(_('The selected lot does not match the product.'))
                    elif item.get('lot_name'):
                        move.nk_lot_reference = str(item.get('lot_name'))[:128]
                        lot = self._nk_find_or_create_lot(move)
                    values = {
                        'move_id': move.id,
                        'picking_id': self.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': location.id,
                        'location_dest_id': move.location_dest_id.id,
                        'lot_id': lot.id or False,
                        'quantity': quantity,
                        'picked': True,
                        'company_id': move.company_id.id,
                    }
                    MoveLine.create(values)
                    total += quantity
                if force_demand and float_compare(total, move.product_uom_qty, precision_rounding=move.product_uom.rounding) < 0:
                    missing = move.product_uom_qty - total
                    MoveLine.create({
                        'move_id': move.id,
                        'picking_id': self.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'lot_id': self._nk_find_or_create_lot(move).id or False,
                        'quantity': missing,
                        'picked': True,
                        'company_id': move.company_id.id,
                    })
            return

        for move in moves:
            lot = self._nk_find_or_create_lot(move)
            if move.move_line_ids:
                remaining = move.product_uom_qty
                for line in move.move_line_ids:
                    if float_compare(line.quantity, 0.0, precision_rounding=move.product_uom.rounding) <= 0:
                        line.quantity = min(remaining, move.product_uom_qty)
                    if lot and not line.lot_id:
                        line.lot_id = lot.id
                    line.picked = True
                    remaining -= line.quantity
                if force_demand and float_compare(remaining, 0.0, precision_rounding=move.product_uom.rounding) > 0:
                    self.env['stock.move.line'].sudo().create({
                        'move_id': move.id,
                        'picking_id': self.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'lot_id': lot.id or False,
                        'quantity': remaining,
                        'picked': True,
                        'company_id': move.company_id.id,
                    })
            elif move.location_id.should_bypass_reservation() or force_demand:
                self.env['stock.move.line'].sudo().create({
                    'move_id': move.id,
                    'picking_id': self.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'lot_id': lot.id or False,
                    'quantity': move.product_uom_qty,
                    'picked': True,
                    'company_id': move.company_id.id,
                })

    def nk_execute_action(self, action, allocations=None, force_demand=False, backorder='ask'):
        self.ensure_one()
        if not self.nk_is_operation:
            raise UserError(_('This is not a Nut Kings Ops transfer.'))
        if force_demand:
            self.env.user.nk_ops_assert('manager')
        if action == 'mark_todo':
            if self.state == 'draft':
                self.action_confirm()
        elif action == 'check_availability':
            if self.state == 'draft':
                self.action_confirm()
            self.action_assign()
        elif action == 'validate':
            if self.state == 'draft':
                self.action_confirm()
            self._nk_prepare_quantities(allocations=allocations, force_demand=force_demand)
            context = {}
            if backorder == 'cancel':
                context['picking_ids_not_to_backorder'] = self.ids
            if backorder in ('create', 'cancel'):
                context['skip_backorder'] = True
            result = self.with_context(**context).button_validate()
            if isinstance(result, dict):
                return {'requires_dialog': True, 'action': result, 'dialog': result.get('res_model') or result.get('tag') or 'odoo_action'}
        elif action == 'cancel':
            if self.state not in ('done', 'cancel'):
                self.action_cancel()
        elif action == 'return':
            if self.state != 'done':
                raise UserError(_('Only a completed transfer can be returned.'))
            wizard = self.env['stock.return.picking'].sudo().with_context(
                active_model='stock.picking', active_id=self.id, active_ids=self.ids,
            ).create({'picking_id': self.id})
            return_action = wizard.action_create_returns_all()
            return_picking = self.env['stock.picking'].sudo().browse(return_action.get('res_id')).exists()
            if return_picking:
                actor_user_id = self.env.uid
                return_picking.write({
                    'nk_is_operation': True,
                    'nk_operation_kind': 'truck_return' if self.nk_truck_id else self.nk_operation_kind,
                    'nk_truck_id': self.nk_truck_id.id or False,
                    'nk_trip_id': self.nk_trip_id.id or False,
                    'nk_reference': f'Return of {self.name}',
                    'nk_workspace_user_id': actor_user_id,
                })
            return {'return_picking_id': return_picking.id or False, 'return_reference': return_picking.name or ''}
        else:
            raise UserError(_('Unsupported transfer action.'))
        return {}
