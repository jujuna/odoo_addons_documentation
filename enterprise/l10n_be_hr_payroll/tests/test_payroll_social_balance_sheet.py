from datetime import date

from odoo.tests import tagged
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'social_balance_sheet')
class TestPayrollSocialBalanceSheet(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_include_child_branches_in_report(self):
        companies = self.belgian_company | self.multibranch_company
        # company 0 -> root / no child
        # company 1 (is parent of) company 2 (is parent of) company 3
        target_company = companies[1]

        sexes = ['male'] + ['female'] * 3
        employees = self.create_employee([
            {
                'name': f'Employee {company.name}',
                'company_id': company.id,
                'contract_date_start': date(2025, 1, 1),
                # relevant for social balance sheet
                'certificate': 'master',
                'sex': emp_sex,
                'work_time_rate': 1.,
            } for company, emp_sex in zip(companies, sexes)
        ])

        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(target_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 1, 1),
        })._get_report_data()

        self.assertEqual(balance_sheet_data['1003_female'], .25, "Total full time employement for women should equal 3 payslips x 1 month / 12 month = 0.25")
        self.assertEqual(balance_sheet_data['1003_male'], 0., "Total full time employement for men should equal 0")

    def test_full_and_part_time_workers(self):
        """ Each worker is counted as full or part time according to its own version. """
        employees = self.create_employee([{
            'name': 'Full Time Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Part Time Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': self.resource_calendar_mid_time.id,
            'certificate': 'master',
            'sex': 'female',
        }])
        self.assertEqual(employees.version_id.mapped('work_time_rate'), [1.0, 0.5])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()

        self.assertFalse(balance_sheet_data['102']['total_gross']['male']['part'])
        self.assertTrue(balance_sheet_data['102']['total_gross']['male']['full'])
        self.assertFalse(balance_sheet_data['102']['total_gross']['female']['full'])
        self.assertTrue(balance_sheet_data['102']['total_gross']['female']['part'])
        self.assertEqual(balance_sheet_data['105'], {'full': 1, 'part': 1, 'fte': 1.5})
        self.assertEqual(balance_sheet_data['205'], {'full': 1, 'part': 1, 'fte': 1.5})
