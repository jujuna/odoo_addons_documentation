from odoo import models
from odoo.exceptions import UserError

SIGNIFY_MIMETYPES = ('application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')


class DocumentsDocument(models.Model):
    _inherit = 'documents.document'

    def action_signify_send(self):
        if len(self) != 1:
            raise UserError(self.env._("Select one file to send with Signify."))
        if self.type != 'binary' or self.shortcut_document_id or self.mimetype not in SIGNIFY_MIMETYPES:
            raise UserError(self.env._("Send with Signify works on PDF and Word files only."))
        return self.env['signify.document'].action_new_from_attachment(self.attachment_id.id)
