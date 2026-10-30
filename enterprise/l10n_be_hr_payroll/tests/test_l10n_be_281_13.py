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

    def _payslip(self, amounts, unemployment_days=0, arrears=False, month=1):
        payslip = self.env['hr.payslip'].create({
            'name': 'Economic unemployment',
            'employee_id': self.employee.id,
            'company_id': self.employee.company_id.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(2025, month, 1),
            'date_to': date(2025, month, 28),
            'l10n_be_arrear_salary': arrears,
            'state': 'validated',
            'worked_days_line_ids': [Command.create({
                'version_id': self.employee.version_id.id,
                'work_entry_type_id': self.unemployment_type.id,
                'number_of_days': unemployment_days,
                'number_of_hours': unemployment_days * 7.6,
            })] if unemployment_days else [],
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
        self.assertEqual(values['f13_2089_werkloosheidzonder'], 7)
        self.assertAlmostEqual(values['f13_2059_totaalcontrole'], 350 * 2 + 100 * 2 + 120.38, 2)

        rounded_values = self._values(round_281=True)
        self.assertEqual(rounded_values['f13_2060_bedrag'], 35000)
        self.assertEqual(rounded_values['f13_2078_bedrijfsvoorheffing'], 12038)
        self.assertEqual(rounded_values['f13_2059_totaalcontrole'], 35000 * 2 + 10000 * 2 + 12038)

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

    def test_274_13_mapping_can_be_changed(self):
        self._payslip({'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        self.env.ref('l10n_be_hr_payroll.l10n_be_281_mapping_274_13_taxable').salary_rule_ids -= self.rules['EUB']
        self.assertAlmostEqual(self._monthly().taxable_amount, 300.0, 2)
        # The yearly form keeps its own mapping
        self.assertEqual(self._values()['f13_2060_bedrag'], 350.0)

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
