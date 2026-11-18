# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestAnnualStatementSocialBalanceSheet(TestPayrollCommon):

    def test_social_balance_sheet_in_the_annual_statement(self):
        """ The annual statement contains the social balance sheet of the fiscal year """
        company = self.create_belgian_company({'name': 'Annual Statement Company'})
        employees = self.create_employee([{
            'name': 'Annual Statement Worker',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'sex': 'female',
        }])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        data = self.env['annual.statement.report.handler'].with_company(company)._get_extra_file_data({
            'xbrl_current_fiscal_date': {'date_from': date(2025, 1, 1), 'date_to': date(2025, 12, 31)},
        })
        self.assertTrue(data.get('with_social_balance_sheet'))
        self.assertEqual(data['BE_SBS_105_FT'], 1)
        self.assertTrue(data['BE_SBS_1023_TOTAL'])
