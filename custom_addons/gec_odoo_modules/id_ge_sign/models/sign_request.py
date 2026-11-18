from odoo import fields, models

from odoo.addons.id_ge_sign.tools import protocol


class SignRequest(models.Model):
    _inherit = 'sign.request'

    geoeid_public_attempt = fields.Char(readonly=True, copy=False, index='btree_not_null', groups='base.group_system')

    def _get_final_recipients(self):
        return {email for email in super()._get_final_recipients() if not protocol.is_placeholder_email(email)}

    def _send_completed_documents_message(
            self, signers, request_edited, partner, access_token=None,
            with_message_cc=True, force_send=False, sign_request_item=None):
        email = sign_request_item.signer_email if sign_request_item else partner.email
        if protocol.is_placeholder_email(email):
            return False
        return super()._send_completed_documents_message(signers, request_edited, partner, access_token=access_token, with_message_cc=with_message_cc,
            force_send=force_send, sign_request_item=sign_request_item)

    def _send_refused_message(self, refuser, refusal_reason, partner, access_token=None, force_send=False, sign_request_item=None):
        email = sign_request_item.signer_email if sign_request_item else partner.email
        if protocol.is_placeholder_email(email):
            return False
        return super()._send_refused_message(refuser, refusal_reason, partner, access_token=access_token, force_send=force_send,
            sign_request_item=sign_request_item)
