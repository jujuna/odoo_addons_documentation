import mimetypes

from odoo import http
from odoo.http import request
from odoo.tools import file_open
from odoo.tools.image import image_process

from odoo.addons.web.controllers.webmanifest import WebManifest

from ..models.gec_brand_kit import FONT_STYLES

FONT_MIMETYPES = {'woff2': 'font/woff2', 'woff': 'font/woff', 'ttf': 'font/ttf'}


class GecBrandKitController(http.Controller):
    """Public routes for the few brand files the login page and browser need without a session."""

    @http.route('/gec_brand_kit/favicon', type='http', auth='public', methods=['GET'], readonly=True)
    def favicon(self):
        kit = request.env['gec.brand.kit']._get_applied()
        if not kit.favicon:
            with file_open('web/static/img/favicon.ico', 'rb') as f:
                return request.make_response(f.read(), [('Content-Type', 'image/x-icon')])
        return request.env['ir.binary']._get_image_stream_from(
            kit.with_context(bin_size=False), 'favicon', width=64, height=64,
        ).get_response(max_age=3600)

    @http.route('/gec_brand_kit/login_background', type='http', auth='public', methods=['GET'], readonly=True)
    def login_background(self, **kw):
        """Kit login background (or its home background) for the login page, where /web/image is not
        readable without a session."""
        kit = request.env['gec.brand.kit']._get_applied()
        field = 'login_background' if kit.login_background else 'home_background'
        if not kit[field]:
            return request.not_found()
        return request.env['ir.binary']._get_image_stream_from(
            kit.with_context(bin_size=False), field,
        ).get_response(max_age=3600)

    @http.route('/gec_brand_kit/icon/<int:size>', type='http', auth='public', methods=['GET'], readonly=True)
    def icon(self, size):
        """Square PNG app icon (192 or 512) built from the kit favicon, for the web-app manifest."""
        kit = request.env['gec.brand.kit']._get_applied()
        size = 512 if size >= 512 else 192
        if not kit.favicon:
            return request.redirect(f'/web/static/img/odoo-icon-{size}x{size}.png')
        data = image_process(kit.with_context(bin_size=False).favicon.content, size=(size, size), expand=True, output_format='PNG')
        return request.make_response(data, [('Content-Type', 'image/png'), ('Cache-Control', 'public, max-age=3600')])

    @http.route('/gec_brand_kit/font/<string:style>', type='http', auth='public', methods=['GET'], readonly=True)
    def font(self, style, **kw):
        """Kit font file; the URL carries a `unique` value, so it can be cached for a year."""
        kit = request.env['gec.brand.kit']._get_applied()
        if style not in FONT_STYLES or not kit[f'font_{style}']:
            raise request.not_found()
        kit = kit.with_context(bin_size=False)
        name = kit[f'font_{style}_name'] or ''
        mimetype = FONT_MIMETYPES.get(name.rsplit('.', 1)[-1].lower(), 'application/octet-stream')
        return request.make_response(kit[f'font_{style}'].content, [
            ('Content-Type', mimetype),
            ('Cache-Control', 'public, max-age=31536000, immutable'),
        ])


class GecBrandKitWebManifest(WebManifest):

    def _get_webmanifest(self):
        """Brand the installed web app: name (from web.web_app_name, set by Apply), colors and icons."""
        manifest = super()._get_webmanifest()
        kit = request.env['gec.brand.kit']._get_applied()
        if kit:
            manifest['theme_color'] = kit.color_primary
            manifest['background_color'] = kit.color_background
            if kit.favicon:
                manifest['icons'] = [{
                    'src': f'/gec_brand_kit/icon/{size}',
                    'sizes': f'{size}x{size}',
                    'type': 'image/png',
                } for size in (192, 512)]
        return manifest
