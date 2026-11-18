# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.tools import file_open


class BscGuide(http.Controller):
    """Serves the user guide in the language of the person reading it."""

    @http.route('/bsc_strategy/guide', type='http', auth='user', methods=['GET'])
    def guide(self, lang=None, **kwargs):
        lang = lang or request.env.user.lang or 'en_US'
        name = 'guide_ka.html' if lang.startswith('ka') else 'guide_en.html'
        with file_open('bsc_strategy/static/guide/%s' % name, 'r') as handle:
            body = handle.read()
        return request.make_response(body, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-cache'),
        ])
