import logging

from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.action import Action

from ..models.gec_access_preview import preview_of_request, preview_refused


_logger = logging.getLogger(__name__)


class ActionAccess(Action):

    @staticmethod
    def _resolve_action_id(action_id):
        """ Mirror the resolution /web/action/load does, without raising. """
        try:
            return int(action_id)
        except (TypeError, ValueError):
            pass
        if not isinstance(action_id, str):
            return None
        if '.' in action_id:
            record = request.env.ref(action_id, raise_if_not_found=False)
            if record and record._name.startswith('ir.actions.'):
                return record.id
            return None
        record = request.env['ir.actions.actions'].sudo().search([('path', '=', action_id)], limit=1)
        return record.id or None

    @http.route()
    def load(self, action_id, context=None):
        """ Refuse an action a profile hides, or whose menus it all hides: neither the URL of a hidden menu nor a button
        that opens only that action opens it. run and server actions are left as they were; /json checks the same
        (json.py). """
        resolved_id = self._resolve_action_id(action_id)
        request.env['gec.access.profile']._check_action(resolved_id)
        request.env['gec.access.profile']._check_hidden_menu_action(resolved_id)
        result = super().load(action_id, context=context)
        # filtered here: the action is built under sudo, where this module steps aside
        return request.env['gec.access.profile']._filter_action_views(result)

    @staticmethod
    def _preview_may_run(action_id):
        """ Whether a preview may run a server action: only one a menu opens (it picks a view), not one bound to the
        Action menu of a model or scheduled: those run code, whatever a read only transaction refuses to save. """
        env = request.env
        action = env['ir.actions.server'].sudo().browse(action_id).exists()
        return bool(
            action and not action.binding_model_id
            and env['ir.ui.menu'].sudo().search_count([('action', '=', f'ir.actions.server,{action.id}')], limit=1)
            and not env['ir.cron'].sudo().with_context(active_test=False).search_count(
                [('ir_actions_server_id', '=', action.id)], limit=1))

    @http.route()
    def run(self, action_id, context=None):
        """ Refuse an action a profile hides, and in a preview a server action no menu opens (_preview_may_run). """
        resolved_id = self._resolve_action_id(action_id)
        request.env['gec.access.profile']._check_action(resolved_id)
        if preview_of_request() and not self._preview_may_run(resolved_id):
            raise preview_refused()
        return super().run(action_id, context=context)

    @http.route()
    def load_breadcrumbs(self, actions):
        """ Core runs a server action that has a path to restore its breadcrumb. In a preview the ones _preview_may_run
        refuses are not run: they answer an error, and a stub keeps their place so core gives one answer each. """
        if not preview_of_request():
            return super().load_breadcrumbs(actions)
        stub = {'model': 'ir.actions.server', 'resId': 'new'}
        refused = set()
        kept = []
        for idx, action in enumerate(actions):
            action_id = self._resolve_action_id(action.get('action')) if action.get('action') else None
            server = request.env['ir.actions.server'].sudo().browse(action_id).exists() if action_id else None
            if server and server.path and not self._preview_may_run(server.id):
                refused.add(idx)
                kept.append(stub)
            else:
                kept.append(action)
        results = super().load_breadcrumbs(kept)
        for idx in refused:
            results[idx] = {'error': str(preview_refused())}
        return results
