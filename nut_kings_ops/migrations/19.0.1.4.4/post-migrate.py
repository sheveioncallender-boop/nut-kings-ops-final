from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Reuse the existing locations, quants and transfers. No receipt replay,
    # inventory adjustment, quant write or replacement stock move is required.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['stock.picking.type'].sudo().nk_ensure_company_setup()
