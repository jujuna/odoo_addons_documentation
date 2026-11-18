import json
import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

from odoo.addons.pos_wolt_drive.models.pos_config import WEBHOOK_ROUTE

_logger = logging.getLogger(__name__)


class WoltDriveController(http.Controller):

    @http.route(f'{WEBHOOK_ROUTE}/<int:config_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def wolt_drive_webhook(self, config_id):
        """Wolt Drive delivery events: {"token": <HS256 JWT signed with the registered secret>}."""
        try:
            token = json.loads(request.httprequest.get_data()).get('token')
        except (ValueError, AttributeError):
            return http.Response("Invalid JSON", status=400)
        # superuser: the caller is Wolt, authenticated by the JWT signature checked right below
        config = request.env['pos.config'].with_user(SUPERUSER_ID).browse(config_id).exists()
        event = config and config._wolt_drive_decode_event(token)
        if not event:
            _logger.warning("Wolt Drive: event with an invalid signature for POS %s", config_id)
            return http.Response(status=403)
        # superuser, not sudo: the chatter notes of the event are authored by OdooBot, not by the public user
        request.env['pos.order'].with_user(SUPERUSER_ID)._wolt_drive_handle_event(event, config)
        return http.Response("OK", status=200)
