import logging

import psycopg2

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE

_logger = logging.getLogger(__name__)


class GlovoController(http.Controller):

    @http.route('/glovo/order/dispatched', type='http', auth='public', methods=['POST'], csrf=False)
    def glovo_order_dispatched(self):
        return self._handle_notification('dispatched')

    @http.route('/glovo/order/picked_up', type='http', auth='public', methods=['POST'], csrf=False)
    def glovo_order_picked_up(self):
        return self._handle_notification('picked_up')

    @http.route('/glovo/order/cancelled', type='http', auth='public', methods=['POST'], csrf=False)
    def glovo_order_cancelled(self):
        return self._handle_notification('cancelled')

    def _handle_notification(self, event_type):
        """Authenticate a Glovo notification, store it as a glovo.event and apply it once.

        Errors are stored on the event and answered with 200: Glovo only retries non-2xx.
        """
        try:
            data = request.get_json_data()
            if not (
                isinstance(data, dict)
                and isinstance(data.get('store_id'), str)
                and isinstance(data.get('order_id'), str)
                and '\x00' not in data['order_id']
            ):
                raise ValueError("order_id and store_id must be strings in a JSON object")
        except ValueError as error:
            _logger.warning("Glovo: invalid %s notification: %s", event_type, error)
            return request.make_response("Invalid notification", status=400)

        try:
            # sudo: the webhook is public; the store is authenticated just below with its provider token
            stores_sudo = request.env['platform.order.entity'].sudo()._find_store_from_data(PROVIDER_CODE, data)
        except ValidationError as error:
            # same answer as a wrong token, so the response doesn't tell which store IDs exist
            _logger.warning("Glovo: %s notification refused: %s", event_type, error)
            return request.make_response("Unauthorized", status=401)

        header = request.httprequest.headers.get('Authorization', '').encode()
        stores_sudo = stores_sudo.filtered(lambda store: store.provider_id.glovo_token and consteq(header, store.provider_id.glovo_token.encode()))
        if not stores_sudo:
            _logger.warning("Glovo: %s notification with an invalid token for store %s.", event_type, data['store_id'])
            return request.make_response("Unauthorized", status=401)
        if len(stores_sudo) > 1:
            _logger.error("Glovo: store ID %s with this token exists in companies %s.", data['store_id'], stores_sudo.company_id.mapped('name'))
        store_sudo = stores_sudo.sorted(lambda store: store.provider_id.state == 'disabled')[:1]

        if not data.get('order_id'):
            return request.make_response("Missing order_id", status=400)

        event_sudo = self._get_or_create_event(event_type, store_sudo, data)
        if not event_sudo or event_sudo.state == 'processed':
            return request.make_response("OK")

        event_sudo._process_notification(store_sudo, data)
        return request.make_response("OK")

    @staticmethod
    def _get_or_create_event(event_type, store_sudo, data):
        """Return the inbox row of this notification; Glovo retries each notification up to 3 times.

        Empty when a concurrent request inserted the same notification (that request processes it) or when the existing
        row belongs to another store, which must not apply it.
        """
        Event = request.env['glovo.event'].sudo()
        domain = [('glovo_order_id', '=', str(data['order_id'])), ('event_type', '=', event_type)]
        event = Event.search(domain, limit=1)
        if event:
            if event.company_id != store_sudo.company_id or event.store_external_id != store_sudo.external_id:
                _logger.warning("Glovo: %s of order %s belongs to another store than %s; ignored.", event_type, data['order_id'], store_sudo.name)
                return Event
            return event
        try:
            with request.env.cr.savepoint():
                return Event.create({
                    'event_type': event_type,
                    'glovo_order_id': str(data['order_id']),
                    'store_external_id': data.get('store_id'),
                    'payload': request.httprequest.get_data(as_text=True),
                    'company_id': store_sudo.company_id.id,
                })
        except psycopg2.errors.UniqueViolation:
            return Event
