# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'payroll_281_withholding_check')
class TestL10nBe281WithholdingCheck(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.create_employee({
            'name': 'Withholding Check Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'niss': '/',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
        })
        cls.payslips = cls.create_and_validate_payslips(employees=cls.employee, year=2025, months=[1, 2, 3])
        cls.sheets_274 = cls.env['l10n_be.274_xx'].with_company(cls.belgian_company).create([
            {'year': 2025, 'month': str(month)} for month in (1, 2, 3)
        ])
        cls.declaration = cls.env['l10n_be.281_xx'].with_company(cls.belgian_company).create({
            'year': '2025',
            'company_id': cls.belgian_company.id,
        })
        cls.declaration.l10n_be_281_10_ids.action_generate_declarations()

    def _get_check_lines(self):
        action = self.declaration.action_open_withholding_check()
        return self.env[action['res_model']].search(action['domain'])

    def test_withholding_check_missing_274(self):
        # Only January and February are filed: March is missing from the 274 declarations.
        self.sheets_274[:2].write({'state': 'done'})

        lines = self._get_check_lines().filtered(lambda line: line.report == '281.10' and line.employee_id == self.employee)
        annual_line = lines.filtered(lambda line: line.origin == '281')
        declared_lines = lines.filtered(lambda line: line.origin == 'declared')
        undeclared_line = lines.filtered(lambda line: line.origin == 'undeclared')

        self.assertEqual(len(annual_line), 1)
        self.assertEqual(declared_lines.mapped('document'), list(self.sheets_274[:2]))
        self.assertTrue(all(lines.mapped('is_inconsistent')))
        self.assertAlmostEqual(
            sum(lines.mapped('difference')),
            sum(self.sheets_274[2].line_274_10_ids.mapped('withholding_amount')), 2,
            msg="The difference must be the withholding taxes of the unfiled March declaration",
        )
        self.assertEqual(len(undeclared_line), 1)
        self.assertIn(self.payslips[2].name, undeclared_line.note)

    def test_withholding_check_consistent(self):
        self.sheets_274.write({'state': 'done'})

        lines = self._get_check_lines().filtered(lambda line: line.report == '281.10' and line.employee_id == self.employee)
        self.assertEqual(len(lines.filtered(lambda line: line.origin == 'declared')), 3)
        self.assertFalse(lines.filtered('is_inconsistent'))
        self.assertFalse(lines.filtered(lambda line: line.origin == 'undeclared'))
        self.assertAlmostEqual(sum(lines.mapped('difference')), 0, 2)
        self.assertAlmostEqual(
            sum(lines.mapped('amount_281')),
            self.declaration.l10n_be_281_10_ids._get_withholding_amount(), 2,
        )

    def test_withholding_check_employee_not_on_281(self):
        self.sheets_274.write({'state': 'done'})
        self.declaration.l10n_be_281_10_ids.line_ids.filtered(lambda line: line.employee_id == self.employee).unlink()

        lines = self._get_check_lines().filtered(lambda line: line.report == '281.10' and line.employee_id == self.employee)
        self.assertFalse(lines.filtered(lambda line: line.origin == '281'))
        self.assertTrue(all(lines.mapped('is_inconsistent')))
        self.assertTrue(all('not on the 281.10 form' in line.note for line in lines))
