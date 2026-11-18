import logging
from datetime import datetime, timezone

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.business_data import split_vat

from ..tools.signify_api import SIGNATURE_HEIGHT, SIGNATURE_WIDTH, SignifyAPI

_logger = logging.getLogger(__name__)

SYNC_FIELDS = frozenset({'signify_ref', 'status', 'action_time'})


class SignifyRecipient(models.Model):
    _name = 'signify.recipient'
    _description = 'Signify Recipient'
    _order = 'sequence, id'
    _check_company_auto = True

    document_id = fields.Many2one('signify.document', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='document_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', string="Recipient", required=True, check_company=True)
    personal_id = fields.Char(string="Personal Number", compute='_compute_personal_id', store=True, readonly=False, precompute=True,
        help="11-digit personal number for the Georgian ID card and remote ID; taken from the contact's Tax ID when it is one")
    role = fields.Selection([('signer', "Signer"), ('approver', "Approver"), ('receive_signed_copy', "CC"), ('auto_signer', "Automatic Signer")],
        required=True, default='signer')
    contact_type = fields.Selection([('email', "Email"), ('mobile', "SMS"), ('link', "Link")], string="Send Invitation By", required=True,
        default='email')
    auth_type = fields.Selection([
        ('basic', "Basic"),
        ('sms_otp', "SMS Code"),
        ('qualified', "Qualified"),
        ('sign_pad', "Signature Pad"),
        ('remote_id', "Remote ID"),
    ], string="Signing Method", required=True, default='basic', compute='_compute_auth_type', store=True, readonly=False)
    qualified_type = fields.Selection([
        ('geo_id_card', "Georgian ID Card"),
        ('geo_stamp', "Georgian Company Stamp"),
        ('eu', "EU Qualified"),
        ('eu_allow_os', "EU Qualified, One-Shot Allowed"),
    ], string="Certificate")
    auto_sign_type = fields.Selection([('geo_qualified', "Georgian Qualified"), ('company_seal', "Company Seal")], string="Automatic Signature")
    placement_keyword = fields.Char(string="Signature Keyword", help="A word printed in the document where the signature goes, e.g. Director")
    signify_ref = fields.Char(string="Signify ID", readonly=True, copy=False)
    status = fields.Selection([
        ('pending', "Waiting"),
        ('pending_on_user', "To Act"),
        ('finished', "Done"),
        ('rejected', "Rejected"),
        ('no_action_required', "Not Needed"),
        ('no_action_required_interrupted', "Interrupted"),
    ], readonly=True, copy=False)
    action_time = fields.Datetime(readonly=True, copy=False)

    @api.depends('partner_id')
    def _compute_personal_id(self):
        for recipient in self:
            number = split_vat(recipient.partner_id.vat or '')[1]
            recipient.personal_id = number if len(number) == 11 and number.isdigit() else False

    @api.depends('contact_type')
    def _compute_auth_type(self):
        """Signify keeps no proof of who signed a Link page with Basic, so a Link line asks for an SMS code."""
        self.filtered(lambda recipient: recipient.contact_type == 'link' and recipient.auth_type == 'basic').auth_type = 'sms_otp'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            if any(SYNC_FIELDS.intersection(vals) for vals in vals_list):
                raise AccessError(self.env._("Only Signify can change the status of a recipient."))
            # explicit values keep a context default_* or an ir.default row from filling the sync fields
            vals_list = [dict.fromkeys(SYNC_FIELDS, False) | vals for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and SYNC_FIELDS.intersection(vals):
            raise AccessError(self.env._("Only Signify can change the status of a recipient."))
        if not self.env.su and 'document_id' in vals and any(recipient.document_id.id != vals['document_id'] for recipient in self):
            raise AccessError(self.env._("A recipient cannot be moved to another document: delete it and add it there."))
        return super().write(vals)

    def _signify_payload(self, order_number):
        """The recipient part of set-document-details; keys without a value are left out."""
        self.ensure_one()
        partner = self.partner_id
        payload = {
            'recipientCode': str(self.id),
            'name': partner.name,
            'email': partner.email,
            'mobileNumber': partner._phone_format(fname='phone') or partner.phone,
            'role': self.role.upper(),
            'recipientContactType': self.contact_type.upper(),
        }
        if self.document_id.workflow_type == 'serial':
            payload['orderNumber'] = order_number
        qualified = self.role == 'signer' and self.auth_type == 'qualified'
        if self.role == 'signer':
            payload['possibleSignatureTypes'] = [self.auth_type.upper()]
            if qualified and self.qualified_type:
                payload['qualifiedSignatureType'] = self.qualified_type.upper()
        elif self.role == 'approver':
            payload['possibleApprovalTypes'] = [self.auth_type.upper()]
        elif self.role == 'auto_signer' and self.auto_sign_type:
            payload['autoSignType'] = self.auto_sign_type.upper()
        if (qualified and self.qualified_type == 'geo_id_card') or (self.role in ('signer', 'approver') and self.auth_type == 'remote_id'):
            payload['personalId'] = self.personal_id
        if qualified and self.qualified_type == 'geo_stamp':
            payload['taxCode'] = split_vat(partner.commercial_partner_id.vat or '')[1]
        if self.role in ('signer', 'auto_signer') and self.placement_keyword:
            payload['fields'] = [{
                'type': 'SIGNATURE',
                'autoPlacementText': self.placement_keyword,
                'width': SIGNATURE_WIDTH,
                'height': SIGNATURE_HEIGHT,
            }]
        return {key: value for key, value in payload.items() if value}

    def _signify_sync_vals(self, item):
        """An unknown Signify status is logged and gives no values."""
        self.ensure_one()
        status = (item.get('status') or '').lower()
        if status not in dict(self._fields['status'].selection):
            _logger.warning("Signify: unknown status %s on recipient %s, skipped", item.get('status'), self.id)
            return {}
        action_time = item.get('actionTime')
        if action_time:
            action_time = datetime.fromisoformat(action_time).astimezone(timezone.utc).replace(tzinfo=None)
        return {'status': status, 'action_time': action_time or False}

    def action_open_signing_page(self):
        self.ensure_one()
        if self.contact_type != 'link':
            raise UserError(self.env._("Only link recipients have a signing page."))
        document = self.document_id
        document.check_access('read')
        data = SignifyAPI(document.sudo().connection_id).call('generate-document-link',
            {'documentId': int(document.signify_ref), 'recipientId': int(self.signify_ref)})
        return {'type': 'ir.actions.act_url', 'url': data['url'], 'target': 'new'}
