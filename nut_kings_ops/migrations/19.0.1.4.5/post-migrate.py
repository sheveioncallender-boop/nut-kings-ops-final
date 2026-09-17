from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Safe both after a rolled-back 1.4.4 upgrade and on an existing setup.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['stock.picking.type'].sudo().nk_ensure_company_setup()
