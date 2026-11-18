import hashlib
import io
import logging
import uuid

from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.formparser import MultiPartParser

from odoo import Command, fields, http
from odoo.exceptions import LockError, UserError
from odoo.http import request
from odoo.http.session import STORED_SESSION_BYTES
from odoo.tools import consteq

from odoo.addons.id_ge_sign.tools import protocol
from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError
from odoo.addons.id_ge_sign.models.sign_request_item import GEOEID_TOKEN_TTL
from odoo.addons.sign.models.sign_request import MAX_EXTERNAL_SIGNATURE_UPLOAD_SIZE
from odoo.addons.sign.controllers.main import Sign

_logger = logging.getLogger(__name__)


class GeoeidController(Sign):
    """Endpoints for the Georgian ID Card signing flow (document mode): ``cancel`` and ``status`` from the
    signing page (JSON-RPC, signer token); ``init``, ``document``, ``submit`` from the desktop app (plain
    HTTP, one-time token, no CSRF)."""

    def _signer_item(self, sign_request_id, token):
        return request.env['sign.request.item'].sudo().search([('sign_request_id', '=', sign_request_id), ('access_token', '=', token)], limit=1)

    @http.route('/sign/geoeid/cancel/<int:sign_request_id>/<token>', type='jsonrpc', auth='public')
    def cancel(self, sign_request_id, token, **kwargs):
        item = self._signer_item(sign_request_id, token)
        if not item or item.role_id.auth_method != 'geoeid':
            return {'success': False}
        item._geoeid_cancel()
        return {'success': True}

    @http.route('/sign/geoeid/status/<int:sign_request_id>/<token>', type='jsonrpc', auth='public')
    def status(self, sign_request_id, token, **kwargs):
        item = self._signer_item(sign_request_id, token)
        if not item:
            return {'state': 'failed'}
        return {'state': item.geoeid_state}

    @http.route()
    def make_public_user(self, request_id, token, name=None, mail=None, attempt_id=None):
        sign_request = self._get_sign_request(request_id, token)
        if (sign_request and len(sign_request.request_item_ids) == 1 and sign_request.request_item_ids.role_id.auth_method == 'geoeid'):
            return self.public_user(request_id, token, attempt_id=attempt_id)
        return super().make_public_user(request_id, token, name=name, mail=mail)

    @http.route('/sign/geoeid/public/<int:request_id>/<token>', type='jsonrpc', auth='public')
    def public_user(self, request_id, token, attempt_id=None, **kwargs):
        if not isinstance(attempt_id, str):
            return False
        try:
            attempt_id = str(uuid.UUID(attempt_id))
        except ValueError:
            return False
        sign_request = request.env['sign.request'].sudo().search([('id', '=', request_id), ('access_token', '=', token)])
        if not sign_request:
            return False
        if (not consteq(sign_request.access_token, token) or sign_request.state != 'shared'
                or len(sign_request.request_item_ids) != 1
                or sign_request.request_item_ids.partner_id
                or sign_request.request_item_ids.role_id.auth_method != 'geoeid'
                or (sign_request.validity and sign_request.validity < fields.Date.context_today(sign_request))):
            return False
        request.session['geoeid_public'] = True
        session_id = request.session.sid[:STORED_SESSION_BYTES]
        session_hash = hashlib.sha256(session_id.encode()).hexdigest()
        attempt_prefix = '%s:%s:' % (session_hash, sign_request.id)
        attempt_key = attempt_prefix + attempt_id
        requests = request.env['sign.request'].sudo().with_context(active_test=False)
        new_request = requests.search([('geoeid_public_attempt', '=', attempt_key)], limit=1)
        since = fields.Datetime.subtract(fields.Datetime.now(), seconds=GEOEID_TOKEN_TTL)
        if new_request and (
                new_request.state not in ('sent', 'signed') or not new_request.active or new_request.create_date < since
                or (new_request.validity and new_request.validity < fields.Date.context_today(new_request))):
            return False
        if not new_request:
            partner = request.env['res.partner'].sudo().create({
                'name': request.env._("Georgian ID Card signer"),
                'active': False,
                'email': 'geoeid-%s@%s' % (uuid.uuid4().hex, protocol.GEOEID_PLACEHOLDER_EMAIL_DOMAIN),
            })
            new_request = sign_request.with_user(sign_request.create_uid).with_context(no_sign_mail=True).sudo().copy({
                'reference': sign_request.reference.replace('-%s' % request.env._("Shared"), ''),
                'request_item_ids': [Command.create({'partner_id': partner.id, 'role_id': sign_request.request_item_ids.role_id.id})],
                'state': 'sent',
                'geoeid_public_attempt': attempt_key,
            })
        return {'requestID': new_request.id, 'requestToken': new_request.access_token, 'accessToken': new_request.request_item_ids[0].access_token}

    @http.route('/sign/geoeid/init/<token>', type='http', auth='public', methods=['GET'], csrf=False)
    def init(self, token, **kwargs):
        item = request.env['sign.request.item']._geoeid_find_by_token(token)
        if not item or item.geoeid_state != 'launched':
            return request.make_json_response({'error': 'invalid or expired token'}, status=404)
        settings = item._geoeid_settings()
        spec = protocol.build_init_document_json(item.get_base_url(), token,
            description=item.sign_request_id.reference or item.sign_request_id.subject or '', language=settings['language'])
        return request.make_json_response(spec, headers=[('Cache-Control', 'no-store')])

    @http.route('/sign/geoeid/document/<token>', type='http', auth='public', methods=['GET'], csrf=False)
    def document(self, token, **kwargs):
        item = request.env['sign.request.item']._geoeid_find_by_token(token)
        documents = item._get_documents_awaiting_external_signature() if item else []
        if not item or item.geoeid_state != 'launched' or len(documents) != 1:
            return request.make_json_response({'error': 'invalid or expired token'}, status=404)
        pdf = bytes(documents.frozen_file)
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', 'inline; filename="document.pdf"'),
            ('Cache-Control', 'no-store'),
        ])

    def _submit_content_length(self):
        increment = request.env['sign.request.item']._geoeid_signature_increment_limit()
        return MAX_EXTERNAL_SIGNATURE_UPLOAD_SIZE + increment + protocol.GEOEID_MULTIPART_OVERHEAD

    @http.route('/sign/geoeid/submit/<token>', type='http', auth='public', methods=['POST'], csrf=False, max_content_length=_submit_content_length)
    def submit(self, token, **kwargs):
        item = request.env['sign.request.item']._geoeid_find_by_token(token)
        if not item or item.geoeid_state not in ('launched', 'signed'):
            return request.make_json_response({'error': 'invalid or expired token'}, status=404)
        try:
            signed_pdf = self._read_signed_file()
            if not signed_pdf:
                return request.make_json_response({'error': 'no signedFile in the submission'}, status=400)
            item._geoeid_submit_document(signed_pdf, expected_token=token)
        except LockError as exc:
            _logger.info("Concurrent Georgian ID submit for item %s: %s", item.id, exc)
            return request.make_json_response({'error': str(exc)}, status=409, headers=[('Retry-After', '1')])
        except (ValueError, CmsVerificationError, UserError) as exc:
            _logger.warning("Georgian ID signature rejected for item %s: %s", item.id, exc)
            item._geoeid_fail(str(exc), expected_token=token)
            return request.make_json_response({'error': str(exc)}, status=400)
        return request.make_json_response({'success': True})

    def _read_signed_file(self):
        """Return the uploaded signed-PDF bytes. The app's unquoted boundary containing '='
        (``boundary====1780578020325===``) breaks werkzeug and leaves ``files`` empty, so the raw body is
        re-parsed with the header boundary."""
        files = request.httprequest.files
        upload = files.get('signedFile') or next(iter(files.values()), None)
        if upload is None:
            ctype = request.httprequest.content_type or ''
            raw = request.httprequest.get_data()
            if raw and 'boundary=' in ctype:
                boundary = ctype.split('boundary=', 1)[1].split(';', 1)[0].strip().strip('"').encode('ascii')
                if boundary:
                    __, files = MultiPartParser().parse(io.BytesIO(raw), boundary, len(raw))
                    upload = files.get('signedFile') or next(iter(files.values()), None)
        if upload is None:
            return None
        limit = self._submit_content_length() - protocol.GEOEID_MULTIPART_OVERHEAD
        signed_pdf = upload.read(limit + 1)
        if len(signed_pdf) > limit:
            raise RequestEntityTooLarge()
        return signed_pdf
