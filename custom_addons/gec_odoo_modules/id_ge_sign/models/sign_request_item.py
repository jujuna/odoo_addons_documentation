import base64
import hashlib
import secrets

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.business_data import split_vat

from odoo.addons.id_ge_sign.tools import protocol
from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError, verify_pdf_signature
from odoo.addons.id_ge_sign.tools.pdf_update import check_signature_update

GEOEID_TOKEN_TTL = 600


class SignRequestItem(models.Model):
    _inherit = 'sign.request.item'

    geoeid_state = fields.Selection(selection=[
        ('idle', 'Not started'),
        ('launched', 'App launched'),
        ('signed', 'Signed by card'),
        ('failed', 'Failed'),
    ], default='idle', readonly=True, copy=False)
    geoeid_token = fields.Char(readonly=True, copy=False, index='btree_not_null', groups='base.group_system')
    geoeid_token_expiry = fields.Datetime(readonly=True, copy=False)
    geoeid_signed_digest = fields.Char(readonly=True, copy=False, groups='base.group_system')
    geoeid_cert_subject = fields.Char(readonly=True, copy=False)
    geoeid_cert_common_name = fields.Char(readonly=True, copy=False)
    geoeid_cert_personal_number = fields.Char(readonly=True, copy=False, index='btree_not_null')
    geoeid_cert_serial = fields.Char(readonly=True, copy=False)
    geoeid_cert_not_after = fields.Date(readonly=True, copy=False)
    geoeid_cert_trusted = fields.Boolean(readonly=True, copy=False,
        help="The signing certificate chained to a configured trust anchor. Only then is the signature a Qualified Electronic Signature.")
    geoeid_error = fields.Char(readonly=True, copy=False)
    geoeid_signed_on = fields.Datetime(readonly=True, copy=False, index='btree_not_null')

    @api.model_create_multi
    def create(self, vals_list):
        items = super().create(vals_list)
        # The card seals the document, so card signers must sign last.
        for request in items.sign_request_id:
            all_items = request.request_item_ids
            geoeid = all_items.filtered(lambda item: item.role_id.auth_method == 'geoeid')
            if not geoeid:
                continue
            if len(request.template_id.document_ids) != 1:
                raise UserError(self.env._("Georgian ID Card signing supports a single document per request."))
            # Card signers go after the regular ones; core then numbers every signer strictly.
            regular = all_items - geoeid
            if regular:
                last_regular_order = max(order or 1 for order in regular.mapped('mail_sent_order'))
                geoeid.mail_sent_order = last_regular_order + 1
        return items

    def write(self, vals):
        reassigned = self.filtered(lambda item: vals.get('partner_id') and item.partner_id and item.partner_id.id != vals['partner_id'])
        res = super().write(vals)
        # sudo: the card session fields are for administrators; core has just allowed this signer change.
        for item in reassigned.sudo().filtered(lambda item: item.geoeid_state != 'idle'):
            item._geoeid_cancel()
        return res

    def _get_external_signature_url(self, documents=None):
        """Core would open a session at Odoo's signature host; the card app is launched locally instead."""
        if self.role_id.auth_method != 'geoeid':
            return super()._get_external_signature_url(documents)
        if not documents:
            return {}
        if not self._geoeid_settings()['trust_anchor']:
            return {'message': self.env._("Signing with the Georgian ID Card is not set up yet. Please contact the sender of this document.")}
        token = secrets.token_urlsafe(32)
        self.write({
            'geoeid_token': token,
            'geoeid_token_expiry': fields.Datetime.add(fields.Datetime.now(), seconds=GEOEID_TOKEN_TTL),
            'geoeid_state': 'launched',
            'geoeid_error': False,
            'geoeid_signed_digest': False,
        })
        return {'url': protocol.launch_url(self.get_base_url(), token)}

    def _freeze_documents_for_external_signature(self):
        if self.role_id.auth_method == 'geoeid' and len(self.sign_request_id.template_id.document_ids) != 1:
            raise UserError(self.env._("Georgian ID Card signing supports a single document per request."))
        return super()._freeze_documents_for_external_signature()

    def _geoeid_submit_document(self, signed_pdf, expected_token=None):
        """Verify the signed PDF the card app returned and add its signature to the request."""
        self.ensure_one()
        # Lock, then re-read state: a retry after success is a no-op.
        self.sign_request_id.lock_for_update(allow_referencing=True)
        self.lock_for_update(allow_referencing=True)
        self.sign_request_id.invalidate_recordset()
        self.invalidate_recordset()
        if expected_token is not None and (
                self.geoeid_token != expected_token or not self.geoeid_token_expiry
                or self.geoeid_token_expiry < fields.Datetime.now()):
            raise CmsVerificationError(self.env._("This signing session is no longer active."))
        digest = hashlib.sha256(signed_pdf).hexdigest()
        if self.geoeid_state == 'signed':
            if digest != self.geoeid_signed_digest:
                raise CmsVerificationError(self.env._("This signing attempt already completed with another PDF."))
            return
        documents = self._get_documents_awaiting_external_signature()
        validity = self.sign_request_id.validity
        if (self.geoeid_state != 'launched' or self.state != 'sent' or self.sign_request_id.state != 'sent'
                or (validity and validity < fields.Date.context_today(self)) or len(documents) != 1):
            raise CmsVerificationError(self.env._("This signing session is no longer active."))
        if not signed_pdf:
            raise CmsVerificationError(self.env._("No signed document was returned."))
        frozen = bytes(documents.frozen_file)
        if len(signed_pdf) <= len(frozen):
            raise CmsVerificationError(self.env._("The returned PDF must contain a new signature."))
        if len(signed_pdf) > len(frozen) + self._geoeid_signature_increment_limit():
            raise CmsVerificationError(self.env._("The signed PDF exceeds the allowed signature size."))

        settings = self._geoeid_settings()
        anchors = [settings['trust_anchor']] if settings['trust_anchor'] else []
        info = verify_pdf_signature(signed_pdf, trust_anchor_pems=anchors, expected_prefix=frozen)
        if not info['trusted']:
            raise CmsVerificationError(self.env._("A trusted certificate chain is required for this signature."))
        params = self.env['ir.config_parameter'].sudo()
        check_signature_update(frozen, signed_pdf,
            params.get_float('id_ge_sign.max_signature_area_percent', protocol.GEOEID_MAX_SIGNATURE_AREA_PERCENT))
        info['personal_number'] = (info['personal_number'] or '').removeprefix(protocol.GEOEID_PERSONAL_NUMBER_PREFIX)
        self._geoeid_check_identity(info)

        # The request completes inside _apply_external_signatures (certificate of completion, mail),
        # so our data must be written first and undone together with it.
        with self.env.cr.savepoint():
            self.write({
                'geoeid_cert_subject': info['subject'],
                'geoeid_cert_common_name': info['common_name'],
                'geoeid_cert_personal_number': info['personal_number'],
                'geoeid_cert_serial': info['serial'],
                'geoeid_cert_not_after': info['not_after'],
                'geoeid_cert_trusted': info['trusted'],
                'geoeid_state': 'signed',
                'geoeid_signed_on': fields.Datetime.now(),
                'geoeid_signed_digest': digest,
                'geoeid_error': False,
            })
            self._geoeid_update_placeholder(info)
            # Complete as the signer's own user so the audit log names them, not the public user.
            signer = self
            sign_user = self.env['res.users'].sudo().search([('partner_id', '=', self.partner_id.id)], limit=1)
            if sign_user:
                signer = self.with_user(sign_user).sudo()
            signer.sign_request_id.message_post(body=signer._geoeid_audit_body(info), author_id=signer.partner_id.id)
            signer._apply_external_signatures([{
                'document_id': documents.id,
                'signature_increment': base64.b64encode(signed_pdf[len(frozen):]).decode(),
                'hash': digest,
            }])
            if signer.state != 'completed':
                raise CmsVerificationError(self.env._("The signed document could not be added to the request."))

    def _geoeid_check_identity(self, info):
        """A contact person inherits its company's Tax ID: only a signer's own 11-digit personal number is compared."""
        personal_id = split_vat(self.partner_id.vat or '')[1]
        is_own = self.partner_id == self.partner_id.commercial_partner_id
        number = info['personal_number'].strip()
        if is_own and len(personal_id) == 11 and personal_id.isdigit() and number != personal_id:
            raise CmsVerificationError(self.env._("The certificate personal number does not match the signer."))

    def _geoeid_update_placeholder(self, info):
        """Only trusted signatures reach here: the number is proven, so it is written and the contact shown unless another active contact has it."""
        # sudo: the signer of a public link is the public user; the placeholder contact was created by this module.
        partner = self.partner_id.sudo()
        if not (partner.email or '').lower().endswith('@' + protocol.GEOEID_PLACEHOLDER_EMAIL_DOMAIN):
            return
        vals = {'name': info['common_name']} if info['common_name'] else {}
        number = info['personal_number']
        duplicate = False
        if len(number) == 11 and number.isdigit():
            vals['vat'] = number
            duplicate = partner.search([
                ('vat', 'in', [number, 'GE' + number]),
                ('company_id', 'in', [False, self.communication_company_id.id]),
                ('id', '!=', partner.id),
            ], limit=1)
        if not duplicate:
            vals['active'] = True
        partner.write(vals)

    def _geoeid_fail(self, message, expected_token=None):
        """Runs in a rejection handler: when another request holds the rows, leave the state to it, do not raise."""
        self.ensure_one()
        if not all(record.try_lock_for_update(allow_referencing=True) for record in (self.sign_request_id, self)):
            return
        self.invalidate_recordset()
        if self.geoeid_state != 'launched' or (expected_token is not None and self.geoeid_token != expected_token):
            return
        self.write({
            'geoeid_state': 'failed',
            'geoeid_token': False,
            'geoeid_token_expiry': False,
            'geoeid_error': message[:512],
        })
        partner = self.partner_id.display_name
        body = self.env._("The Georgian ID Card signature of %(partner)s was refused: %(reason)s", partner=partner, reason=self.geoeid_error)
        self.sign_request_id.message_post(body=body, subtype_xmlid='mail.mt_note', author_id=self.partner_id.id)

    def _geoeid_cancel(self):
        self.ensure_one()
        self.sign_request_id.lock_for_update(allow_referencing=True)
        self.lock_for_update(allow_referencing=True)
        self.invalidate_recordset(['geoeid_state'])
        if self.geoeid_state in ('launched', 'failed'):
            self._cancel_external_signature()
            self.write({
                'geoeid_state': 'idle',
                'geoeid_token': False,
                'geoeid_token_expiry': False,
                'geoeid_error': False,
            })

    @api.model
    def _geoeid_find_by_token(self, token):
        # sudo: the one-time token is the authorisation; the caller is a public client.
        if not token:
            return self.browse()
        item = self.sudo().search([('geoeid_token', '=', token)], limit=1)
        if not item or not item.geoeid_token_expiry or item.geoeid_token_expiry < fields.Datetime.now():
            return self.browse()
        return item

    def _geoeid_settings(self):
        """Georgian ID system parameters; defaults must match the res.config.settings fields."""
        params = self.env['ir.config_parameter'].sudo()
        return {
            'language': params.get_str('id_ge_sign.language', 'ka'),
            'trust_anchor': params.get_str('id_ge_sign.trust_anchor', ''),
        }

    @api.model
    def _geoeid_signature_increment_limit(self):
        params = self.env['ir.config_parameter'].sudo()
        return max(0, params.get_int('id_ge_sign.max_signature_increment', protocol.GEOEID_MAX_SIGNATURE_INCREMENT))

    def _send_signature_access_message(self):
        signers = self.filtered(lambda item: not protocol.is_placeholder_email(item.signer_email))
        return super(SignRequestItem, signers)._send_signature_access_message()

    def _geoeid_audit_body(self, info):
        holder = info['common_name'] or self.partner_id.display_name
        if info['common_name'] and info['common_name'].casefold() != (self.partner_id.name or '').casefold():
            headline = self.env._("%(holder)s signed with a Georgian ID Card on the link sent to %(partner)s "
                "(certificate chain verified, revocation not checked).")
        else:
            headline = self.env._("%(holder)s signed with a Georgian ID Card (certificate chain verified, revocation not checked).")
        headline = Markup(headline) % {'holder': holder, 'partner': self.partner_id.display_name}
        certificate = Markup(self.env._("Certificate: %(subject)s<br/>Personal number: %(pn)s<br/>Serial: %(serial)s, valid until %(until)s")) % {
            'subject': info['subject'],
            'pn': info['personal_number'] or self.env._("n/a"),
            'serial': info['serial'],
            'until': info['not_after'],
        }
        return headline + Markup('<br/>') + certificate
