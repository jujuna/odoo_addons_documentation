from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    gec_payroll_channel_id = fields.Many2one('account.payment.method.line', string='Default Salary Bank', ondelete='set null',
        domain="[('payment_type', '=', 'outbound'), ('journal_id.type', '=', 'bank'), ('journal_id', '!=', False), ('company_id', '=', id)]")
