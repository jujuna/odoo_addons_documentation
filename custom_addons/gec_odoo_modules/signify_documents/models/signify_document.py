from odoo import models


class SignifyDocument(models.Model):
    _name = 'signify.document'
    _inherit = ['signify.document', 'documents.mixin']

    def _get_document_folder(self):
        return self.company_id.documents_signify_folder_id.filtered('active')

    def _get_document_members(self):
        """The sync runs as OdooBot or under sudo(), so the sender is named here; the current user is not the sender."""
        return [((self.connection_id.user_id or self.create_uid).partner_id, ('view', False))]

    def _get_document_partner(self):
        return self.recipient_ids.filtered(lambda recipient: recipient.role == 'signer')[:1].partner_id
