# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon


@tagged('post_install', 'post_install_l10n', '-at_install', 'payslips_validation')
class TestL10nLbPayrollAccounting(TestPayslipValidationCommon):

    @classmethod
    @TestPayslipValidationCommon.setup_country('lb')
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_common(
            country=cls.env.ref('base.lb'),
            structure=cls.env.ref('l10n_lb_hr_payroll.hr_payroll_structure_lb_employee_salary'),
            structure_type=cls.env.ref('l10n_lb_hr_payroll.structure_type_employee_lb'),
            version_fields={
                'date_version': date(2019, 1, 1),
                'contract_date_start': date(2019, 1, 1),
                'wage': 104_000_000.0,
                'marital': 'married',
                'children': 2,
            },
            tz='Asia/Beirut',
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
            Command.create({'salary_rule_id': self.env.ref(f'l10n_lb_hr_payroll.{xml_id}').id, 'amount': amount})
            for xml_id, amount in inputs
        ]
        payslip.compute_sheet()
        return payslip

    def test_payroll_accounts_configuration(self):
        # The chart template loading configured the salary journal and the accounts of the rules
        rule = self.env.ref
        self.assertEqual(self.env.company.currency_id, self.env.ref('base.LBP'))
        self.assertEqual(self.structure.journal_id.code, 'SLR')
        self.assertEqual(self.structure.journal_id.default_account_id.code, '631200')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_basic').account_debit.code, '631200')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_transport_allowance').account_debit.code, '631910')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_bonus').account_debit.code, '631101')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_end_of_service').account_debit.code, '631990')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_family_allowance').account_debit.code, '431101')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_net').account_credit.code, '421101')
        self.assertTrue(rule('l10n_lb_hr_payroll.l10n_lb_rule_net').employee_move_line)
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_nssf_sm_employee').account_debit.code, '431102')
        self.assertEqual(rule('l10n_lb_hr_payroll.l10n_lb_rule_income_tax').account_debit.code, '441101')
        for xml_id, payable in (
            ('l10n_lb_rule_nssf_sm_employer', '431102'),
            ('l10n_lb_rule_nssf_fa_employer', '431101'),
            ('l10n_lb_rule_nssf_eos_employer', '431103'),
        ):
            employer_rule = rule(f'l10n_lb_hr_payroll.{xml_id}')
            self.assertEqual((employer_rule.account_debit.code, employer_rule.account_credit.code), ('635100', payable))

    def test_payslip_journal_entry(self):
        # Married with 2 children, LBP 104,000,000 in January 2027, transport allowance of the contract:
        #   wages                     631200  104,000,000
        #   personnel transportation  631910  21 days x 450,000 = 9,450,000
        #   NSSF family allowances    431101  4,410,000 paid for the Fund, 6% x 28,000,000 = 1,680,000 due
        #   NSSF cost                 635100  8% + 8.5% of 104,000,000 + 1,680,000 = 18,840,000
        #   NSSF sickness, maternity  431102  3% + 8% of 104,000,000 = 11,440,000
        #   NSSF end-of-service       431103  8.5% of 104,000,000 = 8,840,000
        #   taxes due on salaries     441101  104M - 63.75M = 40.25M -> 600,000 + 410,000 = 1,010,000
        #   due to personnel          421101  104M + 9.45M + 4.41M - 3.12M - 1.01M = 113,730,000
        self.version._set_property_input_value('TRANSPORT_ALW', 9_450_000)
        payslip = self._payslip_with_inputs([])
        self._validate_payslip(payslip, {
            'BASIC': 104_000_000,
            'TRANSPORT_ALW': 9_450_000,
            'FAMILY_ALW': 4_410_000,
            'NSSF_SM_EMP': -3_120_000,
            'ITS': -1_010_000,
            'NET': 113_730_000,
        }, skip_lines=True)

        payslip.action_payslip_done()

        move = payslip.move_id
        self.assertTrue(move, "The validated payslip must generate a journal entry")
        self.assertEqual(move.journal_id, self.structure.journal_id)
        self.assertEqual(move.date, date(2027, 1, 31))
        self.assertEqual(self._amounts_by_account(move), {
            '631200': (104_000_000.0, 0.0),
            '631910': (9_450_000.0, 0.0),
            '431101': (4_410_000.0, 1_680_000.0),
            '635100': (18_840_000.0, 0.0),
            '431102': (0.0, 11_440_000.0),
            '431103': (0.0, 8_840_000.0),
            '441101': (0.0, 1_010_000.0),
            '421101': (0.0, 113_730_000.0),
        })
        self.assertFalse(move.line_ids.filtered(lambda line: line.name == 'Adjustment Entry'),
                         "Every payslip line reaching the net must have its accounts")
        net_line = move.line_ids.filtered(lambda line: line.account_id.code == '421101')
        self.assertEqual(net_line.partner_id, self.employee.work_contact_id)

    def test_termination_journal_entry(self):
        # The end-of-service settlement notified by the NSSF is an employer cost owed to the Fund, the end-of-service
        # indemnity paid by the employer a personnel charge not taxable, the salary advance is credited back to the
        # personnel receivable
        self.version.contract_date_end = date(2027, 1, 31)
        payslip = self._payslip_with_inputs([
            ('l10n_lb_rule_eos_settlement', 300_000_000),
            ('l10n_lb_rule_end_of_service', 20_000_000),
            ('l10n_lb_rule_advance_recovery', 50_000_000),
        ])
        payslip.action_payslip_done()
        amounts = self._amounts_by_account(payslip.move_id)
        self.assertEqual(amounts['635500'], (300_000_000.0, 0.0))
        self.assertEqual(amounts['431103'], (0.0, 308_840_000.0))
        self.assertEqual(amounts['631990'], (20_000_000.0, 0.0))
        self.assertEqual(amounts['428001'], (0.0, 50_000_000.0))
        self.assertEqual(amounts['421101'], (0.0, 74_280_000.0))
        self.assertEqual(sum(payslip.move_id.line_ids.mapped('debit')), sum(payslip.move_id.line_ids.mapped('credit')))
