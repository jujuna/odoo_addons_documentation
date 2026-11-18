# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class L10n_Bg_SaftFileAttachmentErrorWizard(models.TransientModel):
    _name = 'l10n_bg_saft.file.attachment.error.wizard'
    _description = "Wizard to display the SAF-T generation errors and control whether to proceed with the attachment and the validation anyway."

    actionable_errors = fields.Json(required=True)
    file_name = fields.Char()
    file_content = fields.Binary()
    account_return_id = fields.Many2one(comodel_name='account.return')
    options = fields.Json()

    def button_proceed_with_errors(self):
        self.ensure_one()

        if self.env['ir.config_parameter'].sudo().get_bool("l10n_bg_saft.create_on_validate"):
            self.account_return_id.add_attachments_and_validate(
                self.file_content.content if self.file_content else False,
                self.file_name,
                self.options,
            )
        else:
            self.account_return_id.add_attachments_and_submit(
                self.file_content.content if self.file_content else False,
                self.file_name,
                self.options,
            )
