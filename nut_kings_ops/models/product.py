from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nk_inventory_type = fields.Selection(
        [
            ('raw_material', 'Raw Material'),
            ('finished_good', 'Finished Good'),
            ('other', 'Other'),
        ],
        string='Nut Kings Inventory Type',
        default='other',
        required=True,
        index=True,
    )
    nk_minimum_qty = fields.Float(string='Minimum Stock Level', default=0.0)
    nk_units_per_case = fields.Float(string='Units per Case', default=1.0)
    nk_pack_size = fields.Char(string='Pack Size')
    nk_enabled = fields.Boolean(string='Available in Nut Kings Ops', default=True)

    @api.onchange('nk_inventory_type')
    def _onchange_nk_inventory_type(self):
        if self.nk_inventory_type in ('raw_material', 'finished_good'):
            self.is_storable = True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('nk_inventory_type') in ('raw_material', 'finished_good'):
                vals['is_storable'] = True
        return super().create(vals_list)

    def write(self, vals):
        values = dict(vals)
        if values.get('nk_inventory_type') in ('raw_material', 'finished_good'):
            values['is_storable'] = True
        return super().write(values)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    nk_inventory_type = fields.Selection(
        related='product_tmpl_id.nk_inventory_type', store=True, readonly=True,
    )
    nk_minimum_qty = fields.Float(
        related='product_tmpl_id.nk_minimum_qty', store=True, readonly=True,
    )

    def nk_backend_url(self):
        self.ensure_one()
        return f'/web#id={self.id}&model=product.product&view_type=form'
