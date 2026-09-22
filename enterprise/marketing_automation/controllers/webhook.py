from ast import literal_eval

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request, route
from odoo.tools.misc import consteq


def get_webhook_request_payload():
    if not request:
        return None
    try:
        payload = request.get_json_data()
    except ValueError:
        payload = {
            'search_domain': literal_eval(request.httprequest.args.get('search_domain', '{}')),
            'create_values': literal_eval(request.httprequest.args.get('create_values', '{}')),
        }
    return payload


class MarketingCampaignController(http.Controller):

    @route('/mkauto/webhook/<int:id>/<string:webhook_uuid>', type='http', auth='public', methods=['GET', 'POST'], csrf=False, save_session=False)
    def call_mkauto_webhook_http(self, id, webhook_uuid, **kwargs):
        campaign = request.env['marketing.campaign'].sudo().browse(id)
        if not campaign.exists() or not consteq(campaign.webhook_uuid, webhook_uuid) or not campaign._is_webhook_enabled():
            return request.make_json_response({'status': 'error'}, status=404)

        payload = get_webhook_request_payload()
        try:
            campaign._process_webhook_payload(payload.get('search_domain'), payload.get('create_values'))
        except (UserError, ValidationError):
            return request.make_json_response({'status': 'error'}, status=500)
        return request.make_json_response({'status': 'ok'}, status=200)

    @route('/mkauto/webhook/<int:id>/<string:webhook_uuid>/test', type='http', auth='public', methods=['GET', 'POST'], csrf=False, save_session=False)
    def call_mkauto_webhook_http_test(self, id, webhook_uuid, **kwargs):
        """
            The test route evaluates the payload the same way as the standard route.
            However, it will always raise an UserError on a successful evaluation to rollback any changes.
            Certain errors are also made more explicit.
        """
        campaign = request.env['marketing.campaign'].sudo().browse([id])
        if not campaign.exists() or not consteq(campaign.webhook_uuid, webhook_uuid):
            return request.make_json_response({'status': 'error'}, status=404)

        payload = get_webhook_request_payload()
        try:
            campaign._process_webhook_payload(payload.get('search_domain'), payload.get('create_values'), webhook_test=True)
        except UserError as e:
            return request.make_json_response({'status': 'ok', 'msg': e.args[0]}, status=200)
        except ValidationError:
            return request.make_json_response({'status': 'error'}, status=500)
