from odoo.http import request

from odoo.addons.web.controllers.json import WebJsonController
from odoo.addons.web.controllers.utils import get_action_triples


class WebJsonAccess(WebJsonController):

    def _get_action(self, subpath):
        """ Refuse a hidden action, or one whose menus are all hidden, before the parent runs it: the parent turns a
        server action into a new window action, which names no action to check; the action it returns is checked. """
        Profile = request.env['gec.access.profile']
        try:
            requested = list(get_action_triples(request.env, subpath, start_pos=1))[-1][1]
        except (ValueError, IndexError):
            requested = None  # the parent answers a malformed path
        if requested:
            Profile._check_action(requested.id)
            Profile._check_hidden_menu_action(requested.id)
        result = super()._get_action(subpath)
        returned = result[0]._origin
        if returned and returned.id != (requested and requested.id):
            # what a server action returns, judged as /web/action/run judges it
            Profile._check_action(returned.id)
        return result
