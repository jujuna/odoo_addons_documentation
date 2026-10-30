# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_281_20')
class TestL10nBe28120(TestPayrollCommon):

    def test_all_withholding_taxes_declared(self):
        # The withholding tax adjustments are part of the withholding taxes of the director, on the
        # monthly 274.20 as on the yearly 281.20.
        director = self.create_employee([{
            'name': 'Director',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'niss': '85010100115',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Director',
            'l10n_be_legal_last_name': 'Test',
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Director',
            'employee_id': director.id,
            'company_id': director.company_id.id,
            'version_id': director.version_id.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'validated',
        })
        rules = {
            'GROSS': 'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule',
            'P.P': 'cp200_employees_salary_withholding_taxes',
            'P_P_ADJ': 'cp200_employees_salary_withholding_tax_threshold',
            'PPTOTAL': 'cp200_employees_salary_withholding_taxes_total',
        }
        amounts = {'GROSS': 5000.0, 'P.P': -1500.0, 'P_P_ADJ': -100.0, 'PPTOTAL': 1600.0}
        self.env['hr.payslip.line'].create([{
            'name': code,
            'slip_id': payslip.id,
            'salary_rule_id': self.env.ref(f'l10n_be_hr_payroll.{xmlid}').id,
            'total': amounts[code],
        } for code, xmlid in rules.items()])

        monthly = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        self.assertAlmostEqual(sum(monthly.line_274_20_ids.filtered(lambda l: l.employee_id == director).mapped('withholding_amount')), 1600.0, 2)

        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        sheet = declaration.l10n_be_281_20_ids[:1]
        sheet.action_generate_declarations()
        values = sheet._get_rendering_data(director)['employees_data'][0]
        self.assertAlmostEqual(values['f20_2131_bedrijfsvoorheffingvanwerkgever'], 1600.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 1600.0, 2)
