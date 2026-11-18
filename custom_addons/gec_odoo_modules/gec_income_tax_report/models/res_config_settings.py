from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rs_form30_pension_account_ids = fields.Many2many(related='company_id.rs_form30_pension_account_ids', readonly=False)
    rs_form30_employer_pension_account_ids = fields.Many2many(related='company_id.rs_form30_employer_pension_account_ids', readonly=False)
