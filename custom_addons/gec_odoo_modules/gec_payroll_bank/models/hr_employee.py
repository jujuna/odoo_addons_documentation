from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.gec_bank.models.account_payment_method_line import GEC_BANK_CHANNEL_DOMAIN


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    gec_payroll_channel_id = fields.Many2one('account.payment.method.line', string='Salary Bank', ondelete='set null', domain=GEC_BANK_CHANNEL_DOMAIN,
        groups='hr_payroll.group_hr_payroll_manager', tracking=True,
        help="Bank channel used by default when this employee's salary is paid. Left empty, the company default is used.")

    @api.constrains('gec_payroll_channel_id', 'company_id')
    def _check_gec_payroll_channel_company(self):
        invalid = self.filtered(lambda employee:
            employee.gec_payroll_channel_id.company_id
            and employee.company_id
            and employee.gec_payroll_channel_id.company_id != employee.company_id)
        if invalid:
            raise ValidationError(_("The salary bank must belong to the employee's company: %s", ', '.join(invalid.mapped('display_name'))))
