# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import date

from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.models.l10n_be_281_XX import REPORT_CONFIG

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_274_281_consistency')
class TestL10nBe274281Consistency(TestPayrollCommon):
    """Whatever the monthly declarations (274.XX, 273S) declare during the year must be declared again,
    employee by employee, on the yearly 281 forms."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        address = {
            'niss': '/',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        }
        cls.employees = cls.create_employee({'name': 'Consistency Employee', **address})
        cls.employees |= cls.create_employee_with_benefits({'name': 'Consistency Benefits', **address})
        cls.employees |= cls.create_employee({
            'name': 'Consistency Director',
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'wage': 5000.0,
            **address,
        })
        token_employee = cls.create_employee({
            'name': 'Consistency Board Member',
            'l10n_be_include_employee_in_281_30': True,
            **address,
        })
        cls.employees |= token_employee

        months = [1, 2, 3]
        cls.create_and_validate_payslips(cls.employees - token_employee, 2025, months)
        structure = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        token_payslips = cls.env['hr.payslip'].create([{
            'name': f'Board Fees {month}',
            'employee_id': token_employee.id,
            'version_id': token_employee.version_id.id,
            'struct_id': structure.id,
            'company_id': token_employee.company_id.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month + 1, 1).replace(day=1) - date.resolution,
        } for month in months])
        for payslip in token_payslips:
            payslip._set_input_value('PRESENCE_TOKEN', 2000)
        token_payslips.compute_sheet()
        token_payslips.action_payslip_done()

        cls.sheets_274 = cls.env['l10n_be.274_xx'].with_company(cls.belgian_company).create([
            {'year': 2025, 'month': str(month)} for month in months
        ])
        cls.sheets_274.write({'state': 'done'})
        cls.declaration = cls.env['l10n_be.281_xx'].with_company(cls.belgian_company).create({
            'year': '2025',
            'company_id': cls.belgian_company.id,
        })
        for config in REPORT_CONFIG.values():
            cls.declaration[config['relation_field']].action_generate_declarations()

    def test_monthly_withholding_taxes_declared_on_281(self):
        declared = defaultdict(float)
        for line in self.declaration._get_declared_withholding_lines():
            declared[line['report'], line['employee']] += line['amount']
        self.assertTrue(any(declared.values()), "The monthly declarations should declare withholding taxes")

        reported = defaultdict(float)
        for report_key in self.declaration._get_withholding_sources():
            form = self.declaration[REPORT_CONFIG[report_key]['relation_field']][:1]
            if not form:
                continue
            amounts, errors = form._get_withholding_amounts()
            self.assertFalse(errors, f"No employee may be left out of the {report_key} form")
            for employee, amount in amounts.items():
                reported[report_key, employee] += amount

        for report_key, employee in set(declared) | set(reported):
            with self.subTest(report=report_key, employee=employee.name):
                self.assertAlmostEqual(
                    reported[report_key, employee], declared[report_key, employee], 2,
                    msg=f"The withholding taxes of {employee.name} on the {report_key} form must be the ones "
                        "declared during the year",
                )

    def test_every_declared_nature_has_a_281_form(self):
        sources = set(self.declaration._get_withholding_sources().values())
        natures = set(self.sheets_274.line_ids.filtered('withholding_amount').mapped('nature_code'))
        # The exemptions of withholding taxes (274.32 and further) are not declared on the 281 forms.
        natures = {nature for nature in natures if nature in {'274.10', '274.13', '274.18', '274.20', '274.30'}}
        self.assertTrue(natures)
        self.assertFalse(natures - sources, "Every monthly nature must be declared on a 281 form")
