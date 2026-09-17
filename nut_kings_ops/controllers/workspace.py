from html import escape
from pathlib import Path
import re

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.addons.web.controllers.utils import _get_login_redirect_url, ensure_db
from odoo.http import request
from ..workspace_policy import WORKSPACES, workspace_allowed


class NutKingsWorkspace(http.Controller):
    MODULE_PATH = Path(__file__).resolve().parents[1]

    @staticmethod
    def _landing_url(user, entry=''):
        permissions = user.nk_ops_permissions()
        if entry and workspace_allowed(permissions, entry):
            page = WORKSPACES[entry]['page'] if entry in WORKSPACES else 'dashboard'
            return f'/nutkings/{entry}#{page}'
        if permissions['system']:
            return '/nutkings/admin#dashboard'
        for candidate in WORKSPACES:
            if workspace_allowed(permissions, candidate):
                return NutKingsWorkspace._landing_url(user, candidate)
        return '/nutkings/login'

    @staticmethod
    def _entry(kwargs=None):
        path = request.httprequest.path.removeprefix('/nutkings/').removesuffix('/login')
        if path in (*WORKSPACES, 'admin'):
            return path
        return str((kwargs or {}).get('workspace') or '')

    @staticmethod
    def _has_workspace_access():
        return bool(request.session.uid and request.env.user.nk_ops_permissions()['has_nutkings_access'])

    @staticmethod
    def _login_response(error=None, login=None, status=200, entry=''):
        # Keep this page independent from ir.ui.view/QWeb data.  The controller
        # is available as soon as the addon code is loaded, while a QWeb view
        # can be absent when a hosted deployment restarts before the database
        # module upgrade has imported its XML.  Serving the module-owned HTML
        # prevents that timing mismatch and does not touch Odoo's /web/login.
        content = (
            NutKingsWorkspace.MODULE_PATH / 'static' / 'workspace' / 'login.html'
        ).read_text(encoding='utf-8')
        login_value = str(login or request.session.get('auth_login') or '')
        error_block = ''
        if error:
            error_block = f'<div class="nk-login-alert" role="alert">{escape(str(error))}</div>'
        options = '<option value="">Select your workspace</option>'
        for code, definition in {**WORKSPACES, 'admin': {'label': 'Administrator', 'team': 'Administrator'}}.items():
            selected = ' selected' if code == entry else ''
            options += f'<option value="{escape(code, quote=True)}"{selected}>{escape(definition["label"])} · {escape(definition["team"])}</option>'
        values = {
            'CSRF_TOKEN': escape(str(request.csrf_token()), quote=True),
            'LOGIN_VALUE': escape(login_value, quote=True),
            'ERROR_BLOCK': error_block,
            'WORKSPACE_OPTIONS': options,
            'LOGIN_ACTION': escape(request.httprequest.path, quote=True),
            'WORKSPACE_DISABLED': 'disabled' if request.httprequest.path != '/nutkings/login' else '',
        }
        # One pass: user-entered text cannot become another template token.
        content = re.sub(r'__NK_([A-Z_]+)__', lambda match: values[match[1]], content)
        return request.make_response(content, status=status, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store, max-age=0'),
            ('X-Frame-Options', 'DENY'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
        ])

    @staticmethod
    def _forbidden():
        return request.make_response(
            'This account is not assigned to this workspace. Ask your administrator to update Workspace Users.',
            status=403,
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
        )

    @http.route(['/nutkings/login'] + [f'/nutkings/{entry}/login' for entry in (*WORKSPACES, 'admin')], type='http', auth='none', methods=['GET', 'POST'], readonly=False)
    def workspace_login(self, **kwargs):
        ensure_db()
        if request.env.uid is None:
            if request.session.uid is None:
                request.env['ir.http']._auth_method_public()
            else:
                request.update_env(user=request.session.uid)

        entry = self._entry(kwargs)
        login = str(kwargs.get('login') or '').strip()
        if request.httprequest.method == 'POST':
            if entry not in (*WORKSPACES, 'admin'):
                return self._login_response('Select your workspace.', login, status=400)
            password = kwargs.get('password') or ''
            if not login or not password:
                return self._login_response('Enter your workspace username and password.', login, entry=entry)
            try:
                credential = {
                    'login': login,
                    'password': password,
                    'type': 'password',
                }
                if request.env['res.users']._should_captcha_login(credential):
                    return request.redirect(f'/web/login?redirect=/nutkings/{entry}', 303)
                auth_info = request.session.authenticate(request.env, credential)
                user = request.env(user=auth_info['uid']).user
                if not workspace_allowed(user.nk_ops_permissions(), entry):
                    request.session.logout(keep_db=True)
                    request.env['ir.http']._auth_method_public()
                    return self._login_response(
                        'This account is not assigned to this workspace. Contact your administrator.',
                        login,
                        status=403,
                        entry=entry,
                    )
                redirect = self._landing_url(user, entry)
                return request.redirect(_get_login_redirect_url(auth_info['uid'], redirect=redirect), 303)
            except AccessDenied:
                return self._login_response('The username or password is incorrect.', login, status=401, entry=entry)
        return self._login_response(login=login, entry=entry)

    @http.route('/nutkings/logout', type='http', auth='none', methods=['GET'], csrf=False)
    def workspace_logout(self, **kwargs):
        request.session.logout(keep_db=True)
        return request.redirect('/nutkings/login', 303)

    @http.route('/nutkings', type='http', auth='public', methods=['GET'])
    def workspace_redirect(self, **kwargs):
        if not request.session.uid:
            return request.redirect('/nutkings/login', 303)
        if not self._has_workspace_access():
            return self._forbidden()
        return request.redirect('/nutkings/')

    @http.route(['/nutkings/', '/nutkings/offline', '/nutkings/rapid-scan'] + [f'/nutkings/{entry}' for entry in (*WORKSPACES, 'admin')], type='http', auth='public', methods=['GET'])
    def workspace(self, **kwargs):
        entry = self._entry()
        if not request.session.uid:
            login = f'/nutkings/{entry}/login' if entry in (*WORKSPACES, 'admin') else '/nutkings/login'
            return request.redirect(login, 303)
        if not self._has_workspace_access():
            return self._forbidden()
        if entry in (*WORKSPACES, 'admin') and not workspace_allowed(request.env.user.nk_ops_permissions(), entry):
            return self._forbidden()
        if entry not in (*WORKSPACES, 'admin') and not request.env.user.nk_ops_permissions()['system']:
            return request.redirect(self._landing_url(request.env.user), 303)
        content = (self.MODULE_PATH / 'static' / 'workspace' / 'index.html').read_text(encoding='utf-8')
        return request.make_response(content, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-cache, must-revalidate'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/nutkings/reset', type='http', auth='public', methods=['GET'])
    def reset(self, **kwargs):
        if not request.session.uid:
            return request.redirect('/nutkings/login', 303)
        if not self._has_workspace_access():
            return self._forbidden()
        content = (self.MODULE_PATH / 'static' / 'workspace' / 'reset.html').read_text(encoding='utf-8')
        return request.make_response(content, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store, max-age=0'),
        ])

    @http.route('/nutkings/sw.js', type='http', auth='public', methods=['GET'], csrf=False)
    def service_worker(self, **kwargs):
        content = (self.MODULE_PATH / 'static' / 'workspace' / 'sw.js').read_text(encoding='utf-8')
        return request.make_response(content, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Service-Worker-Allowed', '/nutkings/'),
            ('Cache-Control', 'no-cache, must-revalidate'),
        ])

    @http.route('/nutkings/scanner-worker.js', type='http', auth='public', methods=['GET'], csrf=False)
    def scanner_worker(self, **kwargs):
        # Keep the dedicated worker inside the PWA scope. Its decoder and WASM
        # requests must be controlled by the service worker when offline.
        content = (self.MODULE_PATH / 'static' / 'workspace' / 'scanner-worker-v1.4.6.js').read_text(encoding='utf-8')
        return request.make_response(content, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Cache-Control', 'no-cache, must-revalidate'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/nutkings/manifest.webmanifest', type='http', auth='public', methods=['GET'], csrf=False)
    def manifest(self, **kwargs):
        content = (self.MODULE_PATH / 'static' / 'workspace' / 'manifest.webmanifest').read_text(encoding='utf-8')
        return request.make_response(content, headers=[
            ('Content-Type', 'application/manifest+json'),
            ('Cache-Control', 'no-cache, must-revalidate'),
        ])

    @http.route('/nutkings/backend', type='http', auth='user', methods=['GET'])
    def backend(self, **kwargs):
        if not request.env.user.nk_ops_permissions()['system']:
            return self._forbidden()
        dashboard = request.env['nutkings.backend.dashboard']._get_company_dashboard()
        action = request.env.ref('nut_kings_ops.action_nk_backend_dashboard')
        menu = request.env.ref('nut_kings_ops.menu_nk_backend_dashboard')
        return request.redirect(f'/web#action={action.id}&id={dashboard.id}&model=nutkings.backend.dashboard&view_type=form&menu_id={menu.id}')
