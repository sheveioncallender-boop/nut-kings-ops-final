from odoo import fields, models


class NutKingsStaff(models.Model):
    _name = 'nutkings.staff'
    _description = 'Nut Kings Staff Member'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    role = fields.Selection(
        [
            ('driver', 'Driver'),
            ('warehouse', 'Warehouse'),
            ('distribution', 'Distribution'),
            ('supervisor', 'Supervisor'),
            ('manager', 'Manager'),
            ('other', 'Other'),
        ],
        default='other', required=True, index=True,
    )
    phone = fields.Char()
    email = fields.Char()
    notes = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
