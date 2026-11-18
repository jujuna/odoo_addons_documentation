# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from lxml import etree

from odoo import Command
from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_281_13')
class TestL10nBe28113(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.create_employee([{
            'name': 'Unemployment Employee',
            'company_id': cls.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'niss': '85010100115',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Unemployment',
            'l10n_be_legal_last_name': 'Employee',
        }])
        cls.unemployment_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment')
        cls.rules = {
            code: cls.env['hr.salary.rule'].search([('code', '=', code), ('country_id.code', '=', 'BE')], limit=1)
            for code in ('EUC', 'EUC_CP200', 'EUB', 'ECONOMIC_UNEMPLOYMENT.P.P')
        }

    def _payslip(self, amounts, unemployment_days=0, arrears=False, month=1, other_days=None):
        payslip = self.env['hr.payslip'].create({
            'name': 'Economic unemployment',
            'employee_id': self.employee.id,
            'company_id': self.employee.company_id.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 28),
            'l10n_be_arrear_salary': arrears,
            'state': 'validated',
            'worked_days_line_ids': ([Command.create({
                'version_id': self.employee.version_id.id,
                'work_entry_type_id': self.unemployment_type.id,
                'number_of_days': unemployment_days,
                'number_of_hours': unemployment_days * 7.6,
            })] if unemployment_days else []) + [Command.create({
                'version_id': self.employee.version_id.id,
                'work_entry_type_id': self.env.ref(f'hr_work_entry.{xmlid}').id,
                'number_of_days': days,
                'number_of_hours': days * 7.6,
            }) for xmlid, days in (other_days or {}).items()],
        })
        self.env['hr.payslip.line'].create([{
            'name': code,
            'slip_id': payslip.id,
            'salary_rule_id': self.rules[code].id,
            'total': amount,
        } for code, amount in amounts.items()])
        return payslip

    def _values(self, round_281=False):
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        sheet = declaration.l10n_be_281_13_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(self.employee, sheet.line_ids.employee_id)
        return sheet.with_context(round_281=round_281)._get_rendering_data(self.employee)['employees_data'][0]

    def _monthly(self, month=1):
        report = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({
            'year': 2025,
            'month': str(month),
            'company_id': self.belgian_company.id,
        })
        return report.line_274_13_ids.filtered(lambda line: line.employee_id == self.employee)

    def test_complements_arrears_and_withholding(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        self._payslip({'EUC_CP200': 100.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -26.75}, unemployment_days=2, arrears=True, month=2)

        values = self._values()
        self.assertEqual(values['f13_2060_bedrag'], 350.0)
        self.assertEqual(values['f13_2072_werkloosheidzonder'], 350.0)
        self.assertEqual(values['f13_2066_bedrag'], 100.0)
        self.assertEqual(values['f13_2075_werkloosheidzonder'], 100.0)
        self.assertEqual(values['f13_2078_bedrijfsvoorheffing'], 120.38)
        # The days of the arrears belong to their own year
        self.assertEqual(values['f13_2089_werkloosheidzonder'], 5)
        self.assertAlmostEqual(values['f13_2059_totaalcontrole'], 350 * 2 + 100 * 2 + 120.38, 2)

        rounded_values = self._values(round_281=True)
        self.assertEqual(rounded_values['f13_2060_bedrag'], 35000)
        self.assertEqual(rounded_values['f13_2078_bedrijfsvoorheffing'], 12038)
        self.assertEqual(rounded_values['f13_2059_totaalcontrole'], 35000 * 2 + 10000 * 2 + 12038)

    def test_cross_border_workers(self):
        # The complements of a cross-border worker, without withholding tax, are declared too, with the supporting
        # documents of the exemption (zone 2035)
        self.employee.version_id.l10n_be_resident_situation = 'cross_border'
        self.assertTrue(self.employee.version_id.no_withholding_taxes)
        self._payslip({'EUC': 300.0, 'EUB': 50.0}, unemployment_days=5)
        values = self._values()
        self.assertEqual(values['f13_2060_bedrag'], 350.0)
        self.assertEqual(values['f13_2078_bedrijfsvoorheffing'], 0)
        self.assertEqual(values['f13_2035_verantwoordingsstukken'], 1)

    def test_days_without_complement(self):
        # The days of temporary unemployment the employer pays no complement for are not declared: the days paid as
        # salary (refused by the ONEM, public holiday) and the collective closures
        self._payslip({'EUB': 26.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -6.96}, unemployment_days=5, other_days={
            'l10n_be_work_entry_type_economic_unemployment_refused_by_administration': 2,
            'l10n_be_work_entry_type_public_holiday_temporary_unemployment': 1,
            'l10n_be_work_entry_type_temporary_unemployment_collective_closure': 3,
        })
        self.assertEqual(self._values()['f13_2089_werkloosheidzonder'], 5)

    def test_negative_amounts(self):
        # A correction in 2025 of a complement of 2024: Belcotax refuses the negative amounts, they are set to 0
        # with their days, and the recovery is to be declared by hand
        self._payslip({'EUC': -300.0, 'ECONOMIC_UNEMPLOYMENT.P.P': 80.25}, unemployment_days=5)
        self._payslip({'EUC': 100.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -26.75}, unemployment_days=2, arrears=True, month=2)
        values = self._values()
        self.assertEqual(values['f13_2060_bedrag'], 0)
        self.assertEqual(values['f13_2072_werkloosheidzonder'], 0)
        self.assertEqual(values['f13_2089_werkloosheidzonder'], 0)
        self.assertEqual(values['f13_2066_bedrag'], 100)
        self.assertEqual(values['f13_2078_bedrijfsvoorheffing'], 0)
        self.assertEqual(values['f13_2059_totaalcontrole'], 200)
        declaration = self.env['l10n_be.281_xx'].search([], order='id desc', limit=1)
        declaration.action_generate_xml()
        self.assertIn('2060, 2078', declaration.declaration_warning)

    def test_only_negative_amounts(self):
        # Only the correction of a complement of a previous year: no form, the employee is reported on the
        # declaration to declare the recovery by hand
        self._payslip({'EUC': -300.0, 'ECONOMIC_UNEMPLOYMENT.P.P': 80.25}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        sheet = declaration.l10n_be_281_13_ids[:1]
        sheet.action_generate_declarations()
        self.assertNotIn(self.employee, sheet.line_ids.employee_id)
        warnings = sheet._get_declaration_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn('Unemployment Employee: only negative amounts', warnings[0])

    def test_half_days(self):
        # Python rounds 2.5 to 2, a half day is rounded up
        self._payslip({'EUC': 100.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -26.75}, unemployment_days=2.5)
        self.assertEqual(self._values()['f13_2089_werkloosheidzonder'], 3)

    def _render_pdf_html(self, sheet, employee):
        report_data = sheet._post_process_rendering_data_pdf(sheet._get_rendering_data(employee))[employee]
        html = self.env['ir.actions.report']._render_qweb_html(
            sheet._get_pdf_report().id, employee.ids, data={
                'report_data': report_data,
                'employee': employee,
                'company_id': employee.company_id,
                'payroll_config_id': employee.company_id.current_payroll_config_id,
            },
        )[0].decode()
        return ' '.join(html.split())

    def test_pdf_year(self):
        self._payslip({'EUC': 300.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -80.25}, unemployment_days=5)
        self.env['hr.payslip'].search([('employee_id', '=', self.employee.id)]).write({
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 28)})
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2026',
            'company_id': self.belgian_company.id,
        })
        sheet = declaration.l10n_be_281_13_ids[:1]
        sheet.action_generate_declarations()
        html = self._render_pdf_html(sheet, self.employee)
        self.assertIn('Amount paid or attributed in <span>2026</span>', html)
        self.assertIn('Amount recovered in <span>2026</span>', html)
        # the text of the page only: the logo, the asset urls... could contain the digits
        self.assertNotIn('2025', etree.fromstring(html, etree.HTMLParser()).xpath('string(//body)'))

    def test_274_13(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        monthly = self._monthly()
        self.assertAlmostEqual(monthly.taxable_amount, 350.0, 2)
        self.assertAlmostEqual(monthly.withholding_amount, 93.63, 2)

    def test_no_economic_unemployment_no_declaration(self):
        self._payslip({'EUC': 300.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -80.25})
        self.assertFalse(self._monthly())
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        sheet = declaration.l10n_be_281_13_ids[:1]
        sheet.action_generate_declarations()
        self.assertNotIn(self.employee, sheet.line_ids.employee_id)

    def test_days_without_amount_no_declaration(self):
        # Temporary unemployment without any complement paid: no form with days only
        self._payslip({}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        sheet = declaration.l10n_be_281_13_ids[:1]
        sheet.action_generate_declarations()
        self.assertNotIn(self.employee, sheet.line_ids.employee_id)

    def test_274_13_follows_the_taxable_category(self):
        # The 274.13 and the 281.13 declare the taxable amount of the nature 13 (category TAXABLE_13)
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        self.rules['EUB'].category_ids -= self.env.ref('l10n_be_hr_payroll.ECONOMIC_UNEMPLOYMENT_BASE')
        self.assertAlmostEqual(self._monthly().taxable_amount, 300.0, 2)
        self.assertEqual(self._values()['f13_2060_bedrag'], 300.0)

    def test_complement_of_the_employer_in_281_13(self):
        # A complement of the employer's own (a rule of the category TAXABLE_13) is declared with the legal ones, in
        # box 10, and in box 11 when paid as arrears, as in the 274.13
        self.rules['EUC_OWN'] = self.rules['EUC'].copy({
            'name': "Economic unemployment complement of the employer", 'code': 'EUC_OWN'})
        self.assertIn(self.env.ref('l10n_be_hr_payroll.ECONOMIC_UNEMPLOYMENT_BASE'), self.rules['EUC_OWN'].category_ids)
        self._payslip({'EUC': 300.0, 'EUC_OWN': 52.36, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        self._payslip({'EUC_OWN': 20.0}, unemployment_days=1, arrears=True, month=2)
        self.assertAlmostEqual(self._monthly().taxable_amount, 352.36, 2)
        values = self._values()
        self.assertAlmostEqual(values['f13_2060_bedrag'], 352.36, 2)
        self.assertAlmostEqual(values['f13_2066_bedrag'], 20.0, 2)

    def test_correction_of_281_13_only(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
            **{f'include_281_{form}': False for form in ('10', '18', '20', '30', '45')},
        })
        declaration.action_generate_xml()
        declaration.reference = 'BOW-1'
        declaration.with_context(skip_validation=True).action_mark_as_done()

        correction = declaration.browse(declaration.action_correct_declaration()['res_id'])
        correction.action_generate_xml()
        self.assertEqual(correction.state, 'ready', correction.error_message)
        self.assertIn(self.employee, correction.l10n_be_281_13_ids.line_ids.employee_id)

    def test_mark_as_done_only_targets_its_own_declarations(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
            **{f'include_281_{form}': False for form in ('10', '18', '20', '30', '45')},
        })
        sheet = declaration.l10n_be_281_13_ids
        sheet.action_generate_declarations()
        own_declarations = sheet.line_ids
        self.assertTrue(own_declarations)
        # A declaration of another sheet sharing the same id
        other_declaration = self.env['hr.payroll.employee.declaration'].create({
            'employee_id': self.employee.id,
            'res_model': 'l10n_be.281_10',
            'res_id': sheet.id,
        })
        self.assertEqual(declaration._get_target_declarations(), own_declarations)
        declaration.reference = 'BOW-1'
        declaration.action_mark_as_done()
        self.assertTrue(own_declarations.pdf_to_generate)
        self.assertFalse(other_declaration.pdf_to_generate)

    def test_generate_pdf_of_sheet_without_declaration(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        sheet_281_13 = declaration.l10n_be_281_13_ids
        sheet_281_13.action_generate_declarations()
        self.assertEqual(sheet_281_13.line_ids.state, 'draft')
        # Nothing to generate on the 281.10: the declarations of the other sheets are left untouched
        sheet_281_10 = declaration.l10n_be_281_10_ids
        self.assertFalse(sheet_281_10.line_ids)
        sheet_281_10.action_generate_pdf()
        self.assertEqual(sheet_281_13.line_ids.state, 'draft')

    def test_xml(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
        })
        declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
        fiche = etree.fromstring(bytes(declaration.xml_file)).find('.//Fiche28113')
        self.assertIsNotNone(fiche, "The 281.13 forms must be part of the file")
        self.assertEqual(fiche.findtext('f13_2060_bedrag'), '35000')
        self.assertEqual(fiche.findtext('f13_2078_bedrijfsvoorheffing'), '9363')
        self.assertEqual(fiche.findtext('f13_2089_werkloosheidzonder'), '5')
        self.assertEqual(fiche.findtext('f2017_gemeente'), 'Brussels')
        self.assertIsNone(fiche.find('f13_2079_werkloosheidzonder'), "Belcotax refuses a 0 in zone 2079")
        self.assertIsNone(fiche.find('f13_2081_werkloosheidmetancienniteit'), "Belcotax refuses a 0 in zone 2081")
        for tag in ('f13_2099_referentienummerui', 'f13_2102_kas', 'f13_2103_kasvrijaanvullendpensioen', 'f13_2109_fiscaalidentificat'):
            self.assertIsNone(fiche.find(tag), "Optional zones are left out when empty")
