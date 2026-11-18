from odoo import SUPERUSER_ID, api, fields, models
from odoo.fields import Domain


class ResCompany(models.Model):
    _inherit = 'res.company'

    documents_signify_folder_id = fields.Many2one('documents.document', string="Signify Folder",
        domain=[('type', '=', 'folder'), ('shortcut_document_id', '=', False)], check_company=True)

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._signify_create_documents_folders()
        return companies

    def _get_used_folder_ids_domain(self, folder_ids):
        return super()._get_used_folder_ids_domain(folder_ids) | Domain('documents_signify_folder_id', 'in', folder_ids)

    def _signify_create_documents_folders(self):
        """Runs as OdooBot, so the folder has no owner and the pin does not depend on the groups of the user who creates the company."""
        companies = self.with_user(SUPERUSER_ID).filtered(lambda company: not company.documents_signify_folder_id)
        folders = companies.env['documents.document'].create([{
            'name': "Signify",
            'type': 'folder',
            'company_id': company.id,
            'access_internal': 'view',
        } for company in companies])
        for company, folder in zip(companies, folders):
            company.documents_signify_folder_id = folder
        action = self.env.ref('signify_documents.ir_actions_server_signify_send', raise_if_not_found=False)
        if action:
            folders._embed_action(action.id)
