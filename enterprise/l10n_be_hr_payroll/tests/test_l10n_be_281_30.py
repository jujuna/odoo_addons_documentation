# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_281_30')
class TestL10nBe28130(TestPayrollCommon):

    def _beneficiary(self, **values):
        if values.get('lang'):
            self.env['res.lang']._activate_lang(values['lang'])
        return self.create_employee([{
            'name': 'Board Member',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'niss': '85010100115',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Board',
            'l10n_be_legal_last_name': 'Member',
            'l10n_be_include_employee_in_281_30': True,
            **values,
        }])

    def _payslip(self, employee, amounts, version=None, month=1):
        payslip = self.env['hr.payslip'].create({
            'name': 'Presence Tokens',
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'version_id': (version or employee.version_id).id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 28),
            'state': 'validated',
        })
        self.env['hr.payslip.line'].create([{
            'name': xmlid,
            'slip_id': payslip.id,
            'salary_rule_id': self.env.ref(f'l10n_be_hr_payroll.{xmlid}').id,
            'total': amount,
        } for xmlid, amount in amounts.items()])
        return payslip

    def _values(self, employee):
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        sheet = declaration.l10n_be_281_30_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(employee, sheet.line_ids.employee_id)
        return sheet._get_rendering_data(employee)['employees_data'][0]

    def test_reimbursed_expenses(self):
        # The reimbursed expenses are part of the taxable income (box 6a) and repeated in box 9 with their nature
        beneficiary = self._beneficiary(lang='fr_FR')
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 2000.0,
            'cp200_employees_salary_company_car': 150.0,
            'cp200_employees_salary_representation_fees': 100.0,
            'cp200_employees_salary_expense_refund': 60.0,
            'cp200_employees_salary_withholding_taxes_total': 545.0,
        })
        values = self._values(beneficiary)
        self.assertAlmostEqual(values['f30_2064_presentiegelden'], 2000.0 + 150.0 + 100.0 + 60.0, 2)
        self.assertEqual(values['f30_2081_retributies'], 0)
        self.assertAlmostEqual(values['f30_2086_bedrag'], 160.0, 2)
        self.assertEqual(values['f30_2099_aard'], 'divers')
        # Belcotax-on-web: the reimbursed expenses are part of the taxable income
        self.assertGreaterEqual(
            values['f30_2064_presentiegelden'] + values['f30_2062_bedrag'] + values['f30_2067_bedrag']
            + values['f30_2068_zonderberoepskarak'] + values['f30_2087_bedrag'],
            values['f30_2086_bedrag'])
        # The control total adds up the zones 2060 to 2088: the expenses are counted in 2064 and in 2086
        self.assertAlmostEqual(values['f30_2059_totaalcontrole'], 545.0 + 2310.0 + 160.0, 2)

    def test_reimbursed_expenses_non_resident(self):
        # A non-resident beneficiary: the income in box 7f, the nature in the language of the beneficiary
        beneficiary = self._beneficiary(lang='nl_BE', l10n_be_resident_situation='non_resident')
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 2000.0,
            'cp200_employees_salary_homeworking_fees': 20.0,
            'cp200_employees_salary_withholding_taxes_total': 545.0,
        })
        values = self._values(beneficiary)
        self.assertEqual(values['f30_2064_presentiegelden'], 0)
        self.assertAlmostEqual(values['f30_2081_retributies'], 2020.0, 2)
        self.assertAlmostEqual(values['f30_2086_bedrag'], 20.0, 2)
        self.assertEqual(values['f30_2099_aard'], 'diversen')

    def test_no_reimbursed_expenses(self):
        beneficiary = self._beneficiary()
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 2000.0,
            'cp200_employees_salary_withholding_taxes_total': 545.0,
        })
        values = self._values(beneficiary)
        self.assertAlmostEqual(values['f30_2064_presentiegelden'], 2000.0, 2)
        self.assertEqual(values['f30_2086_bedrag'], 0)
        self.assertEqual(values['f30_2099_aard'], '')

    def test_taxable_remuneration(self):
        # The beneficiary is left out of the 281.10 and the 281.20: its whole taxable remuneration is declared with the
        # presence tokens, benefits in kind included
        beneficiary = self._beneficiary()
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 2000.0,
            'cp200_employees_salary_rep_fees_regul': 300.0,
            'cp200_employees_salary_company_car': 150.0,
            'cp200_employees_salary_withholding_taxes_total': 600.0,
        })
        values = self._values(beneficiary)
        self.assertAlmostEqual(values['f30_2064_presentiegelden'], 2000.0 + 300.0 + 150.0, 2)
        self.assertEqual(values['f30_2086_bedrag'], 0)

    def test_residence_of_each_payslip(self):
        # The residence is the one of the version of each payslip: the presence tokens paid while the beneficiary was
        # a resident are declared in box 6a, the following ones in box 7f
        beneficiary = self._beneficiary(l10n_be_resident_situation='resident')
        resident_version = beneficiary.version_id
        non_resident_version = beneficiary.create_version({
            'date_version': date(2025, 2, 1),
            'l10n_be_resident_situation': 'non_resident',
        })
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 2000.0,
            'cp200_employees_salary_representation_fees': 100.0,
            'cp200_employees_salary_withholding_taxes_total': 545.0,
        }, version=resident_version, month=1)
        self._payslip(beneficiary, {
            'l10n_be_presence_token_salary_rule': 1500.0,
            'cp200_employees_salary_withholding_taxes_total': 400.0,
        }, version=non_resident_version, month=2)
        values = self._values(beneficiary)
        self.assertAlmostEqual(values['f30_2064_presentiegelden'], 2100.0, 2)
        self.assertAlmostEqual(values['f30_2081_retributies'], 1500.0, 2)
        self.assertAlmostEqual(values['f30_2086_bedrag'], 100.0, 2)

    def test_pdf_sequence_number(self):
        # Box 1 of the PDF shows the sequence number of the form in the XML file (zone 2009), even when the PDF of
        # an employee is rendered alone: the forms of the declaration follow each other (281.20 before 281.30)
        directors = self.create_employee([{
            'name': f'Director {i}',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'niss': niss,
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Director',
            'l10n_be_legal_last_name': f'Test {i}',
        } for i, niss in enumerate(['85010100214', '85010100313'])])
        for director in directors:
            self._payslip(director, {
                'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
                'cp200_employees_salary_withholding_taxes_total': 1500.0,
            })
        beneficiaries = self._beneficiary(niss='85010100412') | self._beneficiary(niss='85010100511')
        for beneficiary in beneficiaries:
            self._payslip(beneficiary, {
                'l10n_be_presence_token_salary_rule': 2000.0,
                'cp200_employees_salary_withholding_taxes_total': 545.0,
            })
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        declaration.l10n_be_281_20_ids.action_generate_declarations()
        declaration.l10n_be_281_30_ids.action_generate_declarations()
        sheet = declaration.l10n_be_281_30_ids
        self.assertEqual(sheet.line_ids.employee_id, beneficiaries)

        xml_data = declaration._get_xml_rendering_data()
        xml_numbers = {data['employee']: data['f2009_volgnummer'] for data in xml_data['employees_data_30']}
        self.assertEqual(sorted(xml_numbers.values()), [3, 4])
        last_beneficiary = beneficiaries.sorted('id')[-1]
        self.assertEqual(xml_numbers[last_beneficiary], 4)
        # The PDF of the last beneficiary, alone in its batch
        pdf_data = sheet._post_process_rendering_data_pdf(sheet._get_rendering_data(last_beneficiary))
        self.assertEqual(pdf_data[last_beneficiary]['f2009_volgnummer'], 4)
        html = self.env['ir.actions.report']._render_qweb_html(
            sheet._get_pdf_report().id, last_beneficiary.ids, data={
                'report_data': pdf_data[last_beneficiary],
                'employee': last_beneficiary,
                'company_id': last_beneficiary.company_id,
                'payroll_config_id': last_beneficiary.company_id.current_payroll_config_id,
            })[0].decode()
        self.assertRegex(html, r'1\. Nr\.</strong>\s*<span>4</span>')
