from odoo import api, models


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    @api.depends('is_paid', 'number_of_hours', 'payslip_id', 'version_id.wage', 'version_id.hourly_wage', 'payslip_id.sum_worked_hours',
        'work_entry_type_id.amount_rate', 'work_entry_type_id.is_extra_hours', 'version_id.wage_type', 'version_id.pay_scheme',
        'version_id.hourly_source')
    def _compute_amount(self):
        zero_base = self.filtered(lambda wd: wd.payslip_id.wage_type in ('daily',
            'unit') or (wd.payslip_id and wd.payslip_id.gec_uses_timesheet_hourly_base()))
        super(HrPayslipWorkedDays, self - zero_base)._compute_amount()
        for worked_days in zero_base:
            if worked_days.payslip_id.edited or worked_days.payslip_id.state != 'draft':
                continue
            worked_days.amount = 0.0
