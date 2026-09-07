from odoo import fields, models


class NutKingsMovementReason(models.Model):
    _name = 'nutkings.movement.reason'
    _description = 'Nut Kings Movement Reason'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    applies_to = fields.Selection(
        [('raw', 'Raw Materials'), ('finished', 'Finished Goods'), ('distribution', 'Distribution'), ('all', 'All')],
        default='all', required=True,
    )
    requires_note = fields.Boolean(default=False)

    _code_unique = models.Constraint('unique(code)', 'Movement reason code must be unique.')
