from odoo import fields, models

from odoo.addons.gec_bank.models.account_payment_method_line import GEC_BANK_CHANNEL_DOMAIN


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gec_payroll_channel_id = fields.Many2one(related='company_id.gec_payroll_channel_id', string='Default Salary Bank', readonly=False,
        domain=GEC_BANK_CHANNEL_DOMAIN)
