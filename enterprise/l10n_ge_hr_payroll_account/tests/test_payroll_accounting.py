# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon


@tagged('post_install', 'post_install_l10n', '-at_install', 'payslips_validation')
class TestL10nGePayrollAccounting(TestPayslipValidationCommon):

    @classmethod
    @TestPayslipValidationCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_common(
            country=cls.env.ref('base.ge'),
            structure=cls.env.ref('l10n_ge_hr_payroll.hr_payroll_structure_ge_employee_salary'),
            structure_type=cls.env.ref('l10n_ge_hr_payroll.structure_type_employee_ge'),
            version_fields={
                'date_version': date(2019, 1, 1),
                'contract_date_start': date(2019, 1, 1),
                'wage': 5_200.0,
            },
            tz='Asia/Tbilisi',
        )

    def _amounts_by_account(self, move):
        amounts = {}
        for line in move.line_ids:
            debit, credit = amounts.get(line.account_id.code, (0.0, 0.0))
            amounts[line.account_id.code] = (debit + line.debit, credit + line.credit)
        return amounts

    def _payslip_with_inputs(self, inputs):
        payslip = self._generate_payslip(date(2027, 1, 1), date(2027, 1, 31))
        payslip.input_line_ids = [
            Command.create({'salary_rule_id': self.env.ref(f'l10n_ge_hr_payroll.{xml_id}').id, 'amount': amount})
            for xml_id, amount in inputs
        ]
        payslip.compute_sheet()
        return payslip

    def test_payroll_accounts_configuration(self):
        # The chart template loading configured the salary journal and the accounts of the rules
        rule = self.env.ref
        self.assertEqual(self.env.company.currency_id, self.env.ref('base.GEL'))
        self.assertEqual(self.structure.journal_id.code, 'SLR')
        self.assertEqual(self.structure.journal_id.default_account_id.code, '720100')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_basic').account_debit.code, '720100')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_bonus').account_debit.code, '720110')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_commission').account_debit.code, '720200')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_severance').account_debit.code, '720700')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_net').account_credit.code, '310310')
        self.assertTrue(rule('l10n_ge_hr_payroll.l10n_ge_rule_net').employee_move_line)
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_pension_employee').account_debit.code, '332010')
        self.assertEqual(rule('l10n_ge_hr_payroll.l10n_ge_rule_income_tax').account_debit.code, '331310')
        employer_rule = rule('l10n_ge_hr_payroll.l10n_ge_rule_pension_employer')
        self.assertEqual((employer_rule.account_debit.code, employer_rule.account_credit.code), ('721000', '332010'))

    def test_payslip_journal_entry(self):
        # GEL 5,200 in January 2027 and 3 days of per diem:
        #   salaries and wages      720100  5,200
        #   personnel cost others   720900  90
        #   pension cost            721000  2% x 5,200 = 104
        #   pension accrued         332010  104 withheld + 104 employer = 208
        #   PIT accrued             331310  (5,200 - 104) x 20% = 1,019.20
        #   salaries payable        310310  5,200 + 90 - 104 - 1,019.20 = 4,166.80
        payslip = self._payslip_with_inputs([('l10n_ge_rule_per_diem', 90)])
        self._validate_payslip(payslip, {
            'BASIC': 5_200,
            'PER_DIEM': 90,
            'PENSION_EE': -104,
            'PIT': -1_019.20,
            'NET': 4_166.80,
        }, skip_lines=True)

        payslip.action_payslip_done()

        move = payslip.move_id
        self.assertTrue(move, "The validated payslip must generate a journal entry")
        self.assertEqual(move.journal_id, self.structure.journal_id)
        self.assertEqual(move.date, date(2027, 1, 31))
        self.assertEqual(self._amounts_by_account(move), {
            '720100': (5_200.0, 0.0),
            '720900': (90.0, 0.0),
            '721000': (104.0, 0.0),
            '332010': (0.0, 208.0),
            '331310': (0.0, 1_019.2),
            '310310': (0.0, 4_166.8),
        })
        self.assertFalse(move.line_ids.filtered(lambda line: line.name == 'Adjustment Entry'),
                         "Every payslip line reaching the net must have its accounts")
        net_line = move.line_ids.filtered(lambda line: line.account_id.code == '310310')
        self.assertEqual(net_line.partner_id, self.employee.work_contact_id)

    def test_termination_journal_entry(self):
        # One month of severance on a redundancy with 30 days' notice, and the salary advance credited back to the
        # payroll advances: taxable 10,400, pension 208, tax 2,038.40, net 10,400 - 208 - 2,038.40 - 1,000 = 7,153.60
        self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref('l10n_ge_hr_payroll.l10n_ge_departure_redundancy').id,
            'dismissal_date': date(2027, 1, 1),
            'l10n_ge_notice_period': 30,
        })
        payslip = self._payslip_with_inputs([('l10n_ge_rule_advance_recovery', 1_000)])
        payslip.action_payslip_done()
        amounts = self._amounts_by_account(payslip.move_id)
        self.assertEqual(amounts['720700'], (5_200.0, 0.0))
        self.assertEqual(amounts['150310'], (0.0, 1_000.0))
        self.assertEqual(amounts['331310'], (0.0, 2_038.4))
        self.assertEqual(amounts['310310'], (0.0, 7_153.6))
        self.assertEqual(sum(payslip.move_id.line_ids.mapped('debit')), sum(payslip.move_id.line_ids.mapped('credit')))
