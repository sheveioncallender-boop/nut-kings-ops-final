"""Regression tests for receipts that were absent from Odoo stock totals.

Run with Odoo 19/PostgreSQL using --test-tags /nut_kings_ops:TestNativeWarehouses.
"""
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestNativeWarehouses(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'NK warehouse regression'})
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))
        cls.PickingType = cls.env['stock.picking.type'].sudo()
        cls.Warehouse = cls.env['stock.warehouse'].sudo()
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')

        # Reproduce 1.4.2: stock locations exist outside every native warehouse.
        cls.root = cls.PickingType._nk_location(cls.company, 'ROOT', 'Nut Kings Operations', 'view')
        cls.raw_root = cls.PickingType._nk_location(cls.company, 'RM_ROOT', 'Raw Materials Warehouse', 'view', cls.root)
        cls.raw_stock = cls.PickingType._nk_location(cls.company, 'RM_STOCK', 'Available Raw Materials', 'internal', cls.raw_root, 'NK-RM-STOCK')
        cls.raw_use = cls.PickingType._nk_location(cls.company, 'RM_USE', 'Issued / Operational Use', 'production', cls.raw_root, 'NK-RM-USE')
        cls.raw_receipt_type = cls.PickingType._nk_picking_type(cls.company, 'RM_RECEIPT', {
            'name': 'Nut Kings: Receive Raw Materials', 'sequence_code': 'NK-RMR',
            'code': 'incoming', 'default_location_src_id': cls.supplier.id,
            'default_location_dest_id': cls.raw_stock.id,
        })
        cls.raw_product = cls.env['product.product'].create({
            'name': 'Peanuts migration regression', 'type': 'consu',
            'nk_inventory_type': 'raw_material', 'company_id': cls.company.id,
        })

    def _transfer(self, product, operation, source, destination, quantity, kind):
        return self.env['stock.picking'].create({
            'picking_type_id': operation.id, 'company_id': self.company.id,
            'location_id': source.id, 'location_dest_id': destination.id,
            'nk_is_operation': True, 'nk_operation_kind': kind,
            'move_ids': [Command.create({
                'description_picking': product.display_name, 'product_id': product.id,
                'product_uom': product.uom_id.id, 'product_uom_qty': quantity,
                'location_id': source.id, 'location_dest_id': destination.id,
                'company_id': self.company.id,
            })],
        })

    def _complete(self, picking):
        result = picking.nk_execute_action('validate', backorder='create')
        self.assertFalse(result.get('requires_dialog'), result)
        self.assertEqual(picking.state, 'done')

    def _repair(self):
        setup = self.PickingType.nk_ensure_company_setup(self.company)[self.company.id]
        self.env.invalidate_all()
        return setup

    def test_existing_done_receipt_becomes_visible_without_replay(self):
        receipt = self._transfer(self.raw_product, self.raw_receipt_type, self.supplier, self.raw_stock, 1, 'raw_receipt')
        self._complete(receipt)
        self.env.invalidate_all()
        self.assertEqual(self.raw_product.qty_available, 0)
        self.assertEqual(self.raw_product.with_context(location=self.raw_stock.id).qty_available, 1)
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.raw_product.id), ('location_id', '=', self.raw_stock.id),
        ])
        before = (receipt.id, receipt.name, receipt.move_ids.ids, receipt.move_line_ids.ids,
                  receipt.nk_workspace_user_id.id, quant.ids, quant.quantity,
                  self.raw_receipt_type.sequence_id.id)
        setup = self._repair()
        raw_wh = setup['warehouses']['raw']
        self.assertEqual(raw_wh.lot_stock_id, self.raw_stock)
        self.assertEqual(self.raw_stock.warehouse_id, raw_wh)
        self.assertEqual(self.raw_receipt_type.warehouse_id, raw_wh)
        self.assertEqual(self.raw_product.qty_available, 1)
        self.assertEqual(self.raw_product.with_context(warehouse_id=raw_wh.id).qty_available, 1)
        self.assertEqual(before, (
            receipt.id, receipt.name, receipt.move_ids.ids, receipt.move_line_ids.ids,
            receipt.nk_workspace_user_id.id, quant.ids, quant.quantity,
            self.raw_receipt_type.sequence_id.id,
        ))
        self.assertEqual(receipt.state, 'done')
        self.assertEqual(self.raw_stock.barcode, 'NK-RM-STOCK')

        # The real native report and both product buttons use the corrected WH.
        for record, method in (
            (self.raw_product, 'action_product_forecast_report'),
            (self.raw_product.product_tmpl_id, 'action_product_tmpl_forecast_report'),
        ):
            action = getattr(record, method)()
            self.assertEqual(action['context']['warehouse_id'], raw_wh.id)
            self.assertEqual(action['context']['active_model'], record._name)
        docs = self.env['stock.forecasted_product_product'].with_context(
            warehouse_id=raw_wh.id,
        ).get_report_values(self.raw_product.ids)['docs']
        self.assertEqual(docs['product'][self.raw_product.id]['quantity_on_hand'], 1)
        self.assertEqual(docs['product'][self.raw_product.id]['virtual_available'], 1)

    def test_native_forecast_receiving_reservations_and_issuing(self):
        setup = self._repair()
        raw_wh = setup['warehouses']['raw']
        receipt = self._transfer(self.raw_product, self.raw_receipt_type, self.supplier, self.raw_stock, 3, 'raw_receipt')
        receipt.action_confirm()
        self.env.invalidate_all()
        product = self.raw_product.with_context(warehouse_id=raw_wh.id)
        self.assertEqual(product.qty_available, 0)
        self.assertEqual(product.incoming_qty, 3)
        self.assertEqual(product.virtual_available, 3)
        self._complete(receipt)
        issue = self._transfer(self.raw_product, setup['picking_types']['raw_issue'], self.raw_stock, self.raw_use, 1, 'raw_issue')
        issue.action_confirm()
        issue.action_assign()
        self.env.invalidate_all()
        self.assertEqual(product.qty_available, 3)
        self.assertEqual(product.free_qty, 2)
        self.assertEqual(product.outgoing_qty, 1)
        self.assertEqual(product.virtual_available, 2)
        self.assertFalse(self.raw_use.warehouse_id)
        self._complete(issue)
        self.env.invalidate_all()
        self.assertEqual(product.qty_available, 2)
        self.assertEqual(product.free_qty, 2)
        self.assertEqual(product.outgoing_qty, 0)
        self.assertEqual(self.raw_product.qty_available, 2)

    def test_finished_receipt_and_native_defaults(self):
        setup = self._repair()
        finished_wh = setup['warehouses']['finished']
        entry = setup['locations']['fg_entry']
        stock = setup['locations']['fg_stock']
        product = self.env['product.product'].create({
            'name': 'Finished stock regression', 'nk_inventory_type': 'finished_good',
            'company_id': self.company.id,
        })
        receipt = self._transfer(product, setup['picking_types']['finished_receipt'], entry, stock, 2, 'finished_receipt')
        receipt.action_confirm()
        self.env.invalidate_all()
        self.assertEqual(product.with_context(warehouse_id=finished_wh.id).incoming_qty, 2)
        self._complete(receipt)
        self.env.invalidate_all()
        self.assertEqual(product.qty_available, 2)
        self.assertEqual(product.with_context(warehouse_id=finished_wh.id).qty_available, 2)
        self.assertEqual(product.with_context(warehouse_id=setup['warehouses']['raw'].id).qty_available, 0)
        self.assertFalse(entry.warehouse_id)
        self.assertEqual(product.action_product_forecast_report()['context']['warehouse_id'], finished_wh.id)
        for warehouse in setup['warehouses'].values():
            self.assertEqual(warehouse.in_type_id.default_location_dest_id, warehouse.lot_stock_id)
            self.assertEqual(warehouse.out_type_id.default_location_src_id, warehouse.lot_stock_id)
            rules = self.env['stock.rule'].search([('warehouse_id', '=', warehouse.id)])
            self.assertTrue(rules)
            self.assertTrue(all((not r.location_src_id or r.location_src_id.active) and r.location_dest_id.active for r in rules))

    def test_setup_is_repeatable_and_recovers_by_existing_location(self):
        setup = self._repair()
        warehouses = self.Warehouse.search([('company_id', '=', self.company.id)])
        locations = self.env['stock.location'].with_context(active_test=False).search([('company_id', '=', self.company.id)])
        raw_wh = setup['warehouses']['raw']
        raw_wh.nk_inventory_type = False  # simulate markers lost on reinstall
        recovered = self._repair()
        again = self._repair()
        self.assertEqual(recovered['warehouses']['raw'], raw_wh)
        self.assertEqual(again['warehouses']['raw'], raw_wh)
        self.assertEqual(self.Warehouse.search([('company_id', '=', self.company.id)]), warehouses)
        self.assertEqual(self.env['stock.location'].with_context(active_test=False).search([('company_id', '=', self.company.id)]), locations)
        self.assertEqual(self.raw_stock.location_id, raw_wh.view_location_id)
        self.assertEqual(self.raw_use.location_id, self.raw_root)
        explicit = self.raw_product.with_context(warehouse_id=setup['warehouses']['finished'].id)
        action = explicit.action_product_forecast_report()
        # Without injecting a default, native action handling retains caller context.
        action_context = action.get('context') or {}
        if isinstance(action_context, str):
            action_context = safe_eval(action_context)
        effective_context = dict(explicit.env.context, **action_context)
        self.assertEqual(effective_context['warehouse_id'], setup['warehouses']['finished'].id)

    def test_unrelated_warehouse_is_never_repurposed(self):
        unrelated = self.Warehouse.create({
            'name': 'Existing customer warehouse', 'code': 'NKRM', 'company_id': self.company.id,
        })
        location = unrelated.lot_stock_id
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._repair()
        self.assertEqual(unrelated.lot_stock_id, location)
        self.assertFalse(unrelated.nk_inventory_type)
        self.assertEqual(self.raw_stock.location_id, self.raw_root)

    def test_company_isolation(self):
        setup = self._repair()
        other = self.env['res.company'].create({'name': 'NK independent company'})
        other_setup = self.PickingType.nk_ensure_company_setup(other)[other.id]
        self.assertNotEqual(setup['warehouses']['raw'], other_setup['warehouses']['raw'])
        self.assertNotEqual(setup['locations']['rm_stock'], other_setup['locations']['rm_stock'])
        for warehouse in other_setup['warehouses'].values():
            self.assertEqual(warehouse.company_id, other)
            self.assertEqual(warehouse.lot_stock_id.company_id, other)
