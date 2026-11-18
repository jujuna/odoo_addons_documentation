import json
import logging

from requests.exceptions import RequestException

from odoo import SUPERUSER_ID, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import consteq
from odoo.tools.image import image_process
from odoo.tools.misc import hmac as hmac_tool

from odoo.addons.pos_platform_order_wolt.utils import const

_logger = logging.getLogger(__name__)


class WoltController(http.Controller):

    @http.route(const.WEBHOOK_ROUTE, type='http', auth='public', methods=['POST'], csrf=False)
    def wolt_webhook(self):
        """Wolt order and venue notifications, signed with HMAC-SHA256 in WOLT-SIGNATURE.
        Any answer other than 200 makes Wolt retry three times, 5 seconds apart."""
        raw_body = request.httprequest.get_data()
        # superuser: the caller is Wolt, authenticated below by the store's signature; OdooBot, not the public user, owns the import
        Store = request.env['platform.order.entity'].with_user(SUPERUSER_ID)
        try:
            data = json.loads(raw_body)
            stores = Store._find_store_from_data(const.PROVIDER_CODE, data)
        except (ValueError, AttributeError, ValidationError):
            stores = Store
        signature = request.httprequest.headers.get('WOLT-SIGNATURE')
        store = stores.filtered(lambda s: s.provider_id._wolt_check_signature(raw_body, signature))[:1]
        if not store:
            _logger.warning("Wolt: refused a notification (unknown venue or invalid signature)")
            return http.Response(status=403)
        if store.with_company(store.company_id)._wolt_handle_notification(data):
            return http.Response(status=503)
        return http.Response("OK", status=200)

    @http.route(const.OAUTH_CALLBACK_ROUTE, type='http', auth='user', methods=['GET'])
    def wolt_oauth_callback(self, code=None, state=None, **kwargs):
        if not code or not state:
            raise request.not_found()
        # sudo: the state is only readable by admins; the user's own write access is checked right after
        store = request.env['platform.order.entity'].sudo().search([('wolt_oauth_state', '=', state)], limit=1)
        if not store or not consteq(store.wolt_oauth_state, state):
            raise request.not_found()
        if store.company_id not in request.env.user.company_ids:
            raise request.not_found()
        store.with_env(request.env).with_company(store.company_id).check_access('write')
        try:
            store._wolt_handle_oauth_callback(code)
        except (RequestException, UserError) as error:
            _logger.warning("Wolt: onboarding failed for store %s: %s", store.id, error)
            return http.Response(request.env._("Connecting to Wolt failed: %s", error), status=400, content_type='text/plain')
        return request.redirect(f'/odoo/action-pos_platform_order.action_platform_order_entity/{store.id}')

    @http.route(f'{const.MENU_IMAGE_ROUTE}/<int:template_id>/<string:token>.jpg', type='http', auth='public', methods=['GET'])
    def wolt_menu_image(self, template_id, token):
        """Product photo for Wolt's menu import, signed so only menu products are exposed."""
        # sudo: hmac() reads the database secret, a system parameter
        if not consteq(token, hmac_tool(request.env(su=True), 'wolt-menu-image', str(template_id))):
            raise request.not_found()
        # sudo: public route for Wolt; the signed token checked above limits it to menu products
        template = request.env['product.template'].sudo().browse(template_id).exists()
        image = template.image_1024
        if not image:
            raise request.not_found()
        jpeg = image_process(image.content, output_format='JPEG')
        return request.make_response(jpeg, [('Content-Type', 'image/jpeg'), ('Content-Length', len(jpeg))])
