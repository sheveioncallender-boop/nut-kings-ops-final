"""Native Odoo 19 tests. Requires Odoo/PostgreSQL; no browser automation."""
import json
import uuid

from lxml import html
from odoo import Command
from odoo.tests import HttpCase, tagged

from ..workspace_policy import WORKSPACES


@tagged('post_install', '-at_install')
class TestWorkspaceUpgrade(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'NkStageTest123!'
        cls.accounts = {}
        for entry, definition in WORKSPACES.items():
            cls.accounts[entry] = cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': definition['label'], 'login': 'nk.patch.' + definition['role'],
                'password': cls.password,
                'company_id': cls.env.company.id,
                'company_ids': [Command.set(cls.env.company.ids)],
                'group_ids': [Command.set([
                    cls.env.ref('base.group_portal').id,
                    cls.env.ref('nut_kings_ops.group_nutkings_' + definition['role']).id,
                ])],
            })
        cls.second_office = cls.accounts['raw-materials/receiving'].copy({
            'name': 'Second Office', 'login': 'nk.patch.second.office', 'password': cls.password,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Nut Kings access test raw product', 'type': 'consu', 'is_storable': True,
            'nk_enabled': True, 'nk_inventory_type': 'raw_material',
        })
        cls.supplier = cls.env['res.partner'].create({'name': 'Nut Kings access test supplier'})

    def setUp(self):
        super().setUp()
        self.authenticate(None, None)

    def login(self, entry, user=None, password=None):
        self.authenticate(None, None)
        url = '/nutkings/' + entry + '/login'
        page = self.url_open(url)
        token = html.fromstring(page.text).xpath('//input[@name="csrf_token"]/@value')[0]
        return self.url_open(url, data={
            'csrf_token': token, 'login': (user or self.accounts[entry]).login,
            'password': password or self.password,
        }, allow_redirects=False)

    def post(self, path, payload, entry='raw-materials/receiving'):
        ping = self.url_open('/nutkings/api/ping').json()
        return self.url_open(path, data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'X-NutKings-CSRF': ping['csrf_token'],
            'X-NutKings-Workspace': entry,
        })

    def test_four_password_entrances_and_wrong_workspace(self):
        for entry in WORKSPACES:
            response = self.login(entry)
            self.assertEqual(response.status_code, 303)
            self.assertIn('/nutkings/' + entry, response.headers['Location'])
            self.assertEqual(self.url_open('/nutkings/' + entry).status_code, 200)
        response = self.login('raw-materials/receiving', user=self.accounts['raw-materials/issuing'])
        self.assertEqual(response.status_code, 403)

    def test_bad_password_and_staff_backend_denial(self):
        self.assertEqual(self.login('raw-materials/receiving', password='wrong').status_code, 401)
        self.login('raw-materials/receiving')
        self.assertEqual(self.url_open('/nutkings/backend').status_code, 403)
        self.assertEqual(self.url_open('/nutkings/api/workspace-users').status_code, 403)
        user = self.accounts['raw-materials/receiving']
        self.assertFalse(user.has_group('base.group_user'))
        self.assertFalse(user.has_group('stock.group_stock_user'))

    def test_backend_root_is_a_native_action(self):
        root = self.env.ref('nut_kings_ops.menu_nk_root')
        self.assertEqual(root.action, self.env.ref('nut_kings_ops.action_nk_open_backend_dashboard'))
        self.assertEqual(root.action._name, 'ir.actions.server')
        menus = self.env['ir.ui.menu'].with_user(self.env.ref('base.user_admin')).load_web_menus(False)
        self.assertEqual(menus[root.id]['actionModel'], 'ir.actions.server')
        self.assertEqual(self.env.ref('nut_kings_ops.menu_nk_workspace').action._name, 'ir.actions.act_url')
        response = self.url_open('/web/login', allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('nk-workspace-login-page', response.text)

    def test_native_receipt_and_actual_validator_attribution(self):
        office = self.accounts['raw-materials/receiving']
        self.login('raw-materials/receiving')
        item = {
            'external_uid': str(uuid.uuid4()), 'kind': 'create_transfer',
            'owner_user_id': office.id, 'operation_type': 'raw_receipt',
            'partner_id': self.supplier.id,
            'lines': [{'product_id': self.product.id, 'quantity': 2}],
            'nk_workspace_user_id': self.env.ref('base.user_admin').id,
        }
        response = self.post('/nutkings/api/sync', {'transactions': [item]})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['results'][0]
        self.assertEqual(result['status'], 'processed', result)
        picking = self.env['stock.picking'].browse(result['picking_id'])
        self.assertEqual(picking.state, 'draft')
        self.assertEqual(picking.nk_workspace_user_id, office)
        self.assertEqual(picking.create_uid, office)

        self.login('raw-materials/receiving', user=self.second_office)
        action = {
            'external_uid': str(uuid.uuid4()), 'kind': 'picking_action',
            'owner_user_id': self.second_office.id, 'picking_id': picking.id,
            'action': 'validate', 'backorder': 'create',
            'nk_actor_user_id': self.env.ref('base.user_admin').id,
        }
        result = self.post('/nutkings/api/sync', {'transactions': [action]}).json()['results'][0]
        self.assertEqual(result['status'], 'processed', result)
        self.env.invalidate_all()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.nk_workspace_user_id, self.second_office)
        self.assertEqual(picking.create_uid, office)
        self.assertEqual(sum(picking.move_ids.mapped('quantity')), 2)
        self.assertTrue(picking.move_ids.mapped('move_line_ids'))

    def test_offline_owner_mismatch_creates_no_transfer(self):
        self.login('raw-materials/receiving')
        uid = str(uuid.uuid4())
        response = self.post('/nutkings/api/sync', {'transactions': [{
            'external_uid': uid, 'kind': 'create_transfer',
            'owner_user_id': self.accounts['raw-materials/issuing'].id,
        }]})
        self.assertEqual(response.json()['results'][0]['status'], 'error')
        self.assertFalse(self.env['nutkings.sync.event'].search([('external_uid', '=', uid)]))
