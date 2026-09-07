from odoo import fields, models


class NutKingsSyncEvent(models.Model):
    _name = 'nutkings.sync.event'
    _description = 'Nut Kings Offline Synchronization Event'
    _order = 'received_at desc, id desc'

    external_uid = fields.Char(required=True, index=True, copy=False)
    transaction_kind = fields.Char(required=True, index=True)
    state = fields.Selection(
        [('pending', 'Pending'), ('processed', 'Processed'), ('needs_action', 'Needs Action'), ('error', 'Error')],
        default='pending', required=True, index=True,
    )
    device_name = fields.Char(index=True)
    created_on_device = fields.Datetime()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    processed_at = fields.Datetime()
    user_id = fields.Many2one('res.users', string='Done by', default=lambda self: self.env.user, required=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    payload = fields.Text()
    error_message = fields.Text()
    result_reference = fields.Char()
    picking_id = fields.Many2one('stock.picking', ondelete='set null', index=True)
    partner_id = fields.Many2one('res.partner', ondelete='set null', index=True)
    truck_id = fields.Many2one('nutkings.truck', string='Van', ondelete='set null', index=True)
    trip_id = fields.Many2one('nutkings.trip', ondelete='set null', index=True)

    _external_uid_unique = models.Constraint('unique(external_uid)', 'This offline transaction has already been received.')
