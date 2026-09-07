"""Focused tests with doubles; these do not replace the Odoo database tests."""
import importlib.util
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, **values):
    obj = types.ModuleType(name)
    obj.__dict__.update(values)
    sys.modules[name] = obj
    return obj


class AccessError(Exception):
    pass


class RequestProxy:
    current = None

    def __getattr__(self, name):
        return getattr(self.current, name)


request = RequestProxy()
fields = types.SimpleNamespace(**{key: lambda *a, **kw: None for key in ('Many2many', 'Many2one', 'Boolean', 'Char', 'Date', 'Selection')})
fields.Datetime = types.SimpleNamespace(now=datetime.now)
module('odoo', SUPERUSER_ID=1, _=lambda text: text, fields=fields,
       models=types.SimpleNamespace(Model=object, Constraint=lambda *a: None),
       http=types.SimpleNamespace(Controller=object, route=lambda *a, **kw: lambda fn: fn))
module('odoo.fields', Command=types.SimpleNamespace())
module('odoo.exceptions', AccessDenied=AccessError, AccessError=AccessError, ValidationError=ValueError, UserError=ValueError)
module('odoo.http', request=request)
module('odoo.tools.float_utils', float_compare=lambda a, b, **kw: (a > b) - (a < b))
for name in ('odoo.addons', 'odoo.addons.web', 'odoo.addons.web.controllers', 'test_nk', 'test_nk.models', 'test_nk.controllers'):
    module(name, __path__=[])
module('odoo.addons.web.controllers.utils', ensure_db=lambda: None,
       _get_login_redirect_url=lambda uid, redirect: '/mfa?redirect=' + redirect)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


policy = load('test_nk.workspace_policy', 'workspace_policy.py')
users = load('test_nk.models.operations_access', 'models/operations_access.py')
workspace = load('test_nk.controllers.workspace', 'controllers/workspace.py')
api = load('test_nk.controllers.api', 'controllers/api.py')


class User:
    id = 99
    name = 'Office tester'

    def __init__(self, roles=(), admin=False):
        self.groups = {users.ROLE_GROUPS[role] for role in roles}
        if admin:
            self.groups.add('base.group_system')

    def ensure_one(self):
        pass

    def has_group(self, name):
        return name in self.groups

    nk_ops_role_codes = users.ResUsers.nk_ops_role_codes
    nk_ops_permissions = users.ResUsers.nk_ops_permissions


class Env:
    def __init__(self, user):
        self.user, self.uid = user, user.id
        self.company = types.SimpleNamespace(id=3)
        self.model = Mock()
        self.model._should_captcha_login.return_value = False
        self.cr = Mock()

    def __call__(self, **kw):
        return self

    def __getitem__(self, name):
        return self.model


class Request:
    def __init__(self, path, user, method='GET', uid=None, headers=None):
        self.httprequest = types.SimpleNamespace(path=path, method=method, headers=headers or {})
        self.env = Env(user)
        self.session = Mock(uid=uid)
        self.session.authenticate.return_value = {'uid': user.id}
        self.session.get.return_value = ''

    def csrf_token(self):
        return 'test-csrf'

    def validate_csrf(self, token):
        return token == self.csrf_token()

    def make_response(self, content, status=200, headers=()):
        return types.SimpleNamespace(content=content, status=status, headers=dict(headers))

    make_json_response = make_response

    def redirect(self, location, status=303):
        return types.SimpleNamespace(location=location, status=status)


class AccessPatchTests(unittest.TestCase):
    def use(self, path, roles=(), admin=False, **kw):
        request.current = Request(path, User(roles, admin), **kw)
        return request.current

    def test_all_sixteen_role_entrance_pairs(self):
        for entry, definition in policy.WORKSPACES.items():
            for assigned in policy.WORKSPACES.values():
                with self.subTest(entry=entry, role=assigned['role']):
                    self.use('/nutkings/' + entry, [assigned['role']], uid=99)
                    response = workspace.NutKingsWorkspace().workspace()
                    self.assertEqual(response.status, 200 if definition['role'] == assigned['role'] else 403)

    def test_each_anonymous_entrance_keeps_its_login(self):
        for entry in policy.WORKSPACES:
            self.use('/nutkings/' + entry)
            self.assertEqual(workspace.NutKingsWorkspace().workspace().location, '/nutkings/' + entry + '/login')

    def test_fixed_login_cannot_be_overridden_by_body(self):
        req = self.use('/nutkings/raw-materials/receiving/login', ['raw_material_issue'], method='POST')
        response = workspace.NutKingsWorkspace().workspace_login(login='worker', password='password', workspace='raw-materials/issuing')
        self.assertEqual(response.status, 403)
        req.session.logout.assert_called_once()

    def test_password_and_mfa_use_native_authentication(self):
        for entry, definition in policy.WORKSPACES.items():
            req = self.use('/nutkings/' + entry + '/login', [definition['role']], method='POST')
            response = workspace.NutKingsWorkspace().workspace_login(login='worker', password='password')
            self.assertEqual(req.session.authenticate.call_args.args[1]['type'], 'password')
            self.assertEqual(response.location, '/mfa?redirect=/nutkings/' + entry + '#' + definition['page'])

    def test_wrong_password_is_rejected(self):
        req = self.use('/nutkings/raw-materials/receiving/login', ['office_receiving'], method='POST')
        req.session.authenticate.side_effect = AccessError()
        self.assertEqual(workspace.NutKingsWorkspace().workspace_login(login='worker', password='bad').status, 401)

    def test_login_input_is_escaped_and_not_substituted_twice(self):
        self.use('/nutkings/login')
        response = workspace.NutKingsWorkspace._login_response(login='\"><script>__NK_CSRF_TOKEN__</script>')
        self.assertIn('&lt;script&gt;__NK_CSRF_TOKEN__&lt;/script&gt;', response.content)
        self.assertNotIn('<script>test-csrf', response.content)

    def test_multi_role_selection_is_scoped(self):
        perms = User(['office_receiving', 'raw_material_issue']).nk_ops_permissions()
        self.assertEqual(policy.scoped_permissions(perms, 'raw-materials/receiving')['capabilities'], ['raw_receipt'])
        with self.assertRaises(PermissionError):
            policy.scoped_permissions(perms, 'finished-goods/receiving')

    def test_api_enforces_selection_before_native_mutation(self):
        self.use('/nutkings/api/sync', ['office_receiving', 'raw_material_issue'], headers={'X-NutKings-Workspace': 'raw-materials/receiving'})
        api.NutKingsApi._require('raw_receipt')
        with self.assertRaises(AccessError):
            api.NutKingsApi._require('raw_issue')

    def test_only_system_administrator_manages_accounts(self):
        for role in users.ROLE_GROUPS:
            self.use('/nutkings/api/workspace-users', [role])
            with self.assertRaises(AccessError):
                api.NutKingsApi._workspace_user_admin_required()
        self.use('/nutkings/api/workspace-users', admin=True)
        api.NutKingsApi._workspace_user_admin_required()

    def test_only_administrator_can_apply_counts(self):
        self.assertFalse(User(['manager']).nk_ops_permissions()['raw_count'])
        self.assertTrue(User(admin=True).nk_ops_permissions()['raw_count'])

    def test_post_requires_current_session_csrf(self):
        self.use('/nutkings/api/sync')
        with self.assertRaises(AccessError):
            api.NutKingsApi._body()

    def test_another_users_offline_action_never_reaches_event_search(self):
        req = self.use('/nutkings/api/sync', ['office_receiving'], headers={'X-NutKings-CSRF': 'test-csrf'})
        req.httprequest.get_json = lambda **kw: {'transactions': [{'external_uid': 'saved', 'kind': 'create_transfer', 'owner_user_id': 101}]}
        response = api.NutKingsApi().sync()
        self.assertEqual(response.content['results'][0]['status'], 'error')
        req.env.model.sudo.return_value.search.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
