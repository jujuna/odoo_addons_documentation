from odoo import http
from odoo.http import request


class AccessPreview(http.Controller):

    # no identity check: leaving a preview must always work, and it only changes the session
    @http.route('/gec_access_manager/preview/stop', type='jsonrpc', auth='user', check_identity=False)
    def stop(self):
        data = request.env['res.users']._gec_preview_stop()
        if data and data.get('cids'):
            # the web client moved the company cookie to the previewed user's companies
            request.future_response.set_cookie('cids', data['cids'])
        return {'url': (data or {}).get('back') or '/odoo'}
