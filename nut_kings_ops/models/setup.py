from odoo import api, fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    nk_location = fields.Boolean(string='Nut Kings Location', default=False, index=True)
    nk_code = fields.Char(string='Nut Kings Location Code', index=True, copy=False)


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    nk_code = fields.Char(string='Nut Kings Operation Code', index=True, copy=False)

    @api.model
    def _nk_optional_extension_default(self, field_name):
        field = self._fields.get(field_name)
        if not field:
            return None
        default = field.default
        if callable(default):
            try:
                default = default(self)
            except TypeError:
                default = default()
        if field.type == 'boolean':
            return bool(default)
        if field.type == 'selection':
            if default not in (None, False, ''):
                return default
            selection = field._description_selection(self.env)
            keys = [item[0] for item in (selection or [])]
            preferred = ('none', 'not_set', 'no_restriction', 'no_package', 'no')
            return next((item for item in preferred if item in keys), keys[0] if keys else False)
        if default not in (None, False):
            return default
        if field.type in ('integer', 'float', 'monetary'):
            return 0
        if field.type in ('char', 'text', 'html'):
            return ''
        return False

    @api.model_create_multi
    def create(self, vals_list):
        # Some hosted Enterprise databases add this required field. Community
        # does not, so it is supplied only when present.
        if 'restrict_put_in_pack' in self._fields:
            fallback = self._nk_optional_extension_default('restrict_put_in_pack')
            for vals in vals_list:
                if vals.get('restrict_put_in_pack') in (None, ''):
                    vals['restrict_put_in_pack'] = fallback
        return super().create(vals_list)

    @api.model
    def _nk_location(self, company, code, name, usage, parent=False, barcode=False):
        """Return or create the canonical Nut Kings stock location.

        Nut Kings locations are created programmatically rather than from XML data.
        Odoo therefore does not automatically remove them when this addon is
        uninstalled.  On a later reinstall the custom ``nk_code`` field may no
        longer identify those surviving stock locations, while their Odoo barcode
        is still present.  Creating a second location with the same barcode then
        triggers Odoo's per-company barcode uniqueness constraint.

        Recovery order is intentionally conservative:
        1. the current Nut Kings logical code;
        2. the fixed Nut Kings barcode (strong reinstall identifier);
        3. the exact expected name/usage/parent for non-barcoded view locations.

        This makes setup idempotent and adopts the surviving Nut Kings location
        instead of deleting stock data or creating a duplicate location.
        """
        Location = self.env['stock.location'].sudo().with_context(active_test=False)

        location = Location.search([
            ('company_id', '=', company.id),
            ('nk_code', '=', code),
        ], limit=1)

        # A failed uninstall/reinstall can leave the physical stock location but
        # remove/reset our custom marker.  The fixed NK-* barcode is the safest
        # way to recover that existing record before attempting a create/write.
        barcode_location = Location.browse()
        if barcode:
            barcode_location = Location.search([
                ('company_id', '=', company.id),
                ('barcode', '=', barcode),
            ], limit=1)
            if barcode_location and barcode_location != location:
                if location:
                    # Avoid two records claiming the same logical Nut Kings code.
                    location.write({'nk_code': False})
                location = barcode_location

        # View/root locations have no barcode. Recover only an exact structural
        # match so unrelated Odoo locations are never repurposed accidentally.
        if not location:
            recovery_domain = [
                ('company_id', '=', company.id),
                ('name', '=', name),
                ('usage', '=', usage),
                ('location_id', '=', parent.id if parent else False),
            ]
            location = Location.search(recovery_domain, limit=1)

        values = {
            'name': name,
            'usage': usage,
            'company_id': company.id,
            'location_id': parent.id if parent else False,
            'barcode': barcode or False,
            'nk_location': True,
            'nk_code': code,
        }
        writable = {key: value for key, value in values.items() if key in Location._fields}
        if location:
            location.write(writable)
            return location
        return Location.create(writable)

    @api.model
    def _nk_picking_type(self, company, code, values):
        PickingType = self.sudo()
        operation = PickingType.search([
            ('company_id', '=', company.id), ('nk_code', '=', code),
        ], limit=1)
        values = dict(values, company_id=company.id, nk_code=code)
        writable = {key: value for key, value in values.items() if key in PickingType._fields}
        if operation:
            operation.write(writable)
            return operation
        return PickingType.create(writable)

    @api.model
    def nk_ensure_company_setup(self, company=False):
        companies = company or self.env['res.company'].sudo().search([])
        suppliers = self.env.ref('stock.stock_location_suppliers')
        customers = self.env.ref('stock.stock_location_customers')
        result = {}
        for company in companies:
            root = self._nk_location(company, 'ROOT', 'Nut Kings Operations', 'view')
            rm_root = self._nk_location(company, 'RM_ROOT', 'Raw Materials Warehouse', 'view', root)
            rm_stock = self._nk_location(company, 'RM_STOCK', 'Available Raw Materials', 'internal', rm_root, 'NK-RM-STOCK')
            rm_use = self._nk_location(company, 'RM_USE', 'Issued / Operational Use', 'production', rm_root, 'NK-RM-USE')
            fg_root = self._nk_location(company, 'FG_ROOT', 'Finished Goods Warehouse', 'view', root)
            fg_entry = self._nk_location(company, 'FG_ENTRY', 'Finished Goods Entry', 'inventory', fg_root, 'NK-FG-ENTRY')
            fg_stock = self._nk_location(company, 'FG_STOCK', 'Available Finished Goods', 'internal', fg_root, 'NK-FG-STOCK')
            fg_trucks = self._nk_location(company, 'FG_TRUCKS', 'Vans', 'view', fg_root)
            fg_staging = self._nk_location(company, 'FG_STAGING', 'Van Loading Staging', 'internal', fg_root, 'NK-FG-STAGING')
            fg_damage = self._nk_location(company, 'FG_DAMAGE', 'Damaged / Write-Off', 'inventory', fg_root, 'NK-FG-DAMAGE')
            fg_quarantine = self._nk_location(company, 'FG_QUARANTINE', 'Quarantine / Inspection', 'internal', fg_root, 'NK-FG-QUARANTINE')

            common = {
                'show_operations': True,
                'use_existing_lots': True,
                'create_backorder': 'ask',
            }
            raw_receipt = self._nk_picking_type(company, 'RM_RECEIPT', {
                **common,
                'name': 'Nut Kings: Receive Raw Materials',
                'sequence_code': 'NK-RMR',
                'code': 'incoming',
                'default_location_src_id': suppliers.id,
                'default_location_dest_id': rm_stock.id,
                'use_create_lots': True,
            })
            raw_issue = self._nk_picking_type(company, 'RM_ISSUE', {
                **common,
                'name': 'Nut Kings: Issue Raw Materials',
                'sequence_code': 'NK-RMI',
                'code': 'internal',
                'default_location_src_id': rm_stock.id,
                'default_location_dest_id': rm_use.id,
                'reservation_method': 'manual',
            })
            finished_receipt = self._nk_picking_type(company, 'FG_RECEIPT', {
                **common,
                'name': 'Nut Kings: Receive Finished Goods',
                'sequence_code': 'NK-FGR',
                'code': 'incoming',
                'default_location_src_id': fg_entry.id,
                'default_location_dest_id': fg_stock.id,
                'use_create_lots': True,
            })
            finished_truck = self._nk_picking_type(company, 'FG_TRUCK', {
                **common,
                'name': 'Nut Kings: Finished Goods to Van',
                'sequence_code': 'NK-TRK',
                'code': 'internal',
                'default_location_src_id': fg_stock.id,
                'default_location_dest_id': fg_staging.id,
                'reservation_method': 'manual',
            })
            customer_delivery = self._nk_picking_type(company, 'TRUCK_DELIVERY', {
                **common,
                'name': 'Nut Kings: Customer Delivery',
                'sequence_code': 'NK-DEL',
                'code': 'outgoing',
                'default_location_src_id': fg_staging.id,
                'default_location_dest_id': customers.id,
                'reservation_method': 'manual',
            })
            truck_return = self._nk_picking_type(company, 'TRUCK_RETURN', {
                **common,
                'name': 'Nut Kings: Return Van Stock',
                'sequence_code': 'NK-RET',
                'code': 'internal',
                'default_location_src_id': fg_staging.id,
                'default_location_dest_id': fg_stock.id,
                'reservation_method': 'manual',
            })
            result[company.id] = {
                'locations': {
                    'root': root, 'rm_root': rm_root, 'rm_stock': rm_stock, 'rm_use': rm_use,
                    'fg_root': fg_root, 'fg_entry': fg_entry, 'fg_stock': fg_stock,
                    'fg_trucks': fg_trucks, 'fg_staging': fg_staging,
                    'fg_damage': fg_damage, 'fg_quarantine': fg_quarantine,
                },
                'picking_types': {
                    'raw_receipt': raw_receipt,
                    'raw_issue': raw_issue,
                    'finished_receipt': finished_receipt,
                    'finished_to_truck': finished_truck,
                    'customer_delivery': customer_delivery,
                    'truck_return': truck_return,
                },
            }
        return result


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def _nk_physical_inventory_action(self, inventory_type):
        setup = self.env['stock.picking.type'].nk_ensure_company_setup(self.env.company)[self.env.company.id]
        location = setup['locations']['rm_stock' if inventory_type == 'raw_material' else 'fg_stock']
        action = self.with_context(
            inventory_mode=True,
            default_location_id=location.id,
            hide_location=False,
            no_at_date=True,
        ).action_view_inventory()
        action['name'] = 'Raw Materials Physical Inventory' if inventory_type == 'raw_material' else 'Finished Goods Physical Inventory'
        action['domain'] = [
            ('location_id', 'child_of', location.id),
            ('product_id.nk_inventory_type', '=', inventory_type),
        ]
        context = dict(action.get('context') or {})
        context.pop('search_default_my_count', None)
        context.update({
            'inventory_mode': True,
            'default_location_id': location.id,
            'hide_location': False,
            'no_at_date': True,
        })
        action['context'] = context
        return action

    @api.model
    def action_nk_raw_physical_inventory(self):
        return self._nk_physical_inventory_action('raw_material')

    @api.model
    def action_nk_finished_physical_inventory(self):
        return self._nk_physical_inventory_action('finished_good')
