from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    documents_signify_folder_id = fields.Many2one(
        'documents.document', check_company=True, related='company_id.documents_signify_folder_id', readonly=False)
