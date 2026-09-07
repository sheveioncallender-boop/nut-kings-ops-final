def post_init_hook(env):
    """Create the Nut Kings locations and operation types for every company."""
    env['stock.picking.type'].sudo().nk_ensure_company_setup()
