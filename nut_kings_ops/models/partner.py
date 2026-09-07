from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    nk_is_customer = fields.Boolean(string='Nut Kings Customer / Company', index=True)
    nk_is_supplier = fields.Boolean(string='Nut Kings Supplier', index=True)
    nk_customer_code = fields.Char(string='Customer Code', index=True)
    nk_route = fields.Char(string='Route / Region', index=True)
    nk_mobile = fields.Char(string='Mobile')
    nk_delivery_notes = fields.Text(string='Delivery Instructions')

    def nk_is_available_customer(self):
        self.ensure_one()
        return bool(self.nk_is_customer or ('customer_rank' in self._fields and self.customer_rank > 0))

    def nk_is_available_supplier(self):
        self.ensure_one()
        return bool(self.nk_is_supplier or ('supplier_rank' in self._fields and self.supplier_rank > 0))
