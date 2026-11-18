from dateutil.relativedelta import relativedelta

from odoo import models


class HrPayrollWarning(models.Model):
    _inherit = 'hr.payroll.warning'

    def action_l10n_be_onss_payment_warning(self):
        report_ids = self.env.context.get('report_ids', False)
        if len(report_ids) == 1:
            report = self.env['l10n_be.dmfa'].browse(report_ids[0])
            company = report.company_id
            onss_account_id = self.env['account.account'].with_company(company).search([
                *self.env['account.account']._check_company_domain(company),
                ('code', '=', '454000'),
            ], limit=1).id
            onss_bank_accounts = self.env['hr.salary.rule'].search([
                ('struct_ids', 'in', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id),
                ('code', '=', 'ONSS'),
            ]).partner_id.bank_ids.filtered(lambda b: b.allow_out_payment)
            # The provisions of the quarter are paid by the 5th of the months following each of its
            # months, and the balance by the end of the month following the quarter: keep the
            # payments to the ONSS account in that period, not the contributions booked by the
            # payslips nor the payments of the other quarters.
            paid_amount = self.env['account.move.line']._read_group(
                domain=[
                    ('company_id', '=', company.id),
                    ('account_id', '=', onss_account_id),
                    ('parent_state', '=', 'posted'),
                    ('move_id.payslip_ids', '=', False),
                    ('debit', '>', 0),
                    ('date', '>=', report.quarter_start + relativedelta(months=1)),
                    ('date', '<=', report.quarter_end + relativedelta(months=1, day=31)),
                ],
                aggregates=['debit:sum'],
            )[0][0] or 0
            return {
                'type': 'ir.actions.client',
                'tag': 'l10n_be_hr_payroll_account.onss_payment_warning_action',
                'target': 'new',
                'params': {
                    'report_id': report_ids[0],
                    'payment_id': report.payment_id.id,
                    'onss_account_id': onss_account_id,
                    'onss_bank_account_id': onss_bank_accounts[0].id if onss_bank_accounts else False,
                    'onss_bank_account_number': onss_bank_accounts[0].account_number if onss_bank_accounts else '',
                    'onss_balance': int(report._get_rendering_data()['global_contribution']) / 100,
                    'paid_amount': paid_amount,
                },
            }
        else:
            return {
                'name': self.env._("Unpaid DMFA Reports"),
                'res_model': 'l10n_be.dmfa',
                'type': 'ir.actions.act_window',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', report_ids)],
            }

    def _get_payroll_translation(self, text, **kwargs):
        if text == "ONSS Payment %(year)s Q%(quarter)s":
            return self.env._("ONSS Payment %(year)s Q%(quarter)s", **kwargs)
        return super()._get_payroll_translation(text, **kwargs)
