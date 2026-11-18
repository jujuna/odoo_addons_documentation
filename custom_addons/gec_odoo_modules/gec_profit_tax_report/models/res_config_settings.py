from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gec_cit_company_status = fields.Selection(related='company_id.gec_cit_company_status', readonly=False)
    gec_cit_special_status = fields.Selection(related='company_id.gec_cit_special_status', readonly=False)
    gec_cit_financial = fields.Boolean(related='company_id.gec_cit_financial', readonly=False)
    gec_cit_insurer = fields.Boolean(related='company_id.gec_cit_insurer', readonly=False)
    gec_cit_gambling = fields.Boolean(related='company_id.gec_cit_gambling', readonly=False)
    gec_cit_post_entry = fields.Boolean(related='company_id.gec_cit_post_entry', readonly=False)
    gec_cit_journal_id = fields.Many2one(related='company_id.gec_cit_journal_id', readonly=False)
    gec_cit_expense_account_id = fields.Many2one(related='company_id.gec_cit_expense_account_id', readonly=False)
    gec_cit_payable_account_id = fields.Many2one(related='company_id.gec_cit_payable_account_id', readonly=False)
