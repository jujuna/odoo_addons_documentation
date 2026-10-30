# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from lxml import etree

from odoo import Command
from odoo.tests import Form, tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBe28118(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.create_employee([{
            'name': 'Replacement Employee',
            'company_id': cls.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'niss': '85010100115',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Replacement',
            'l10n_be_legal_last_name': 'Employee',
        }])
        cls.income_rule = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_replacement_revenue')
        cls.withholding_rule = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_replacement_revenue_withholding_tax')

    def _mapping(self, field):
        return self.env.ref(f'l10n_be_hr_payroll.l10n_be_281_mapping_281_18_{field}')

    def _274_mapping(self, field):
        return self.env.ref(f'l10n_be_hr_payroll.l10n_be_281_mapping_274_18_{field}')

    def _extra_rule(self):
        return self.income_rule.copy({'name': 'Custom replacement income', 'code': 'REPLACEMENT.CUSTOM'})

    def _payslip(self, amounts):
        payslip = self.env['hr.payslip'].create({
            'name': 'Replacement income',
            'employee_id': self.employee.id,
            'company_id': self.employee.company_id.id,
            'version_id': self.employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'state': 'validated',
        })
        self.env['hr.payslip.line'].create([{
            'name': rule.name,
            'slip_id': payslip.id,
            'salary_rule_id': rule.id,
            'total': amount,
        } for rule, amount in amounts])
        return payslip

    def _annual(self, year=2026):
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': str(year),
            'company_id': self.belgian_company.id,
            'include_281_10': False,
            'include_281_20': False,
            'include_281_45': False,
        })
        sheet = declaration.l10n_be_281_18_ids[:1]
        sheet.action_generate_declarations()
        return sheet

    def _monthly(self, year=2026):
        report = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({
            'year': year,
            'month': '1',
            'company_id': self.belgian_company.id,
        })
        return report.line_274_18_ids.filtered(lambda line: line.employee_id == self.employee)

    def _values(self, sheet):
        self.assertIn(self.employee, sheet.line_ids.employee_id)
        return sheet._get_rendering_data(self.employee)['employees_data'][0]

    def test_default_payroll_and_exports_are_preserved(self):
        leave = self.env['hr.leave'].sudo().create({
            'name': 'Illness',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_incapacity_worker_second_week').id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 1, 31),
            'employee_id': self.employee.id,
        })
        leave.action_approve()
        payslip = self.create_and_validate_payslips(employees=self.employee, year=2025, months=[1])
        income = sum(payslip.line_ids.filtered(lambda line: line.code == 'REPLACEMENT_REVENUE').mapped('total'))
        withholding = -sum(payslip.line_ids.filtered(lambda line: line.code == 'REPLACEMENT_REVENUE.P.P').mapped('total'))
        days = sum(payslip.worked_days_line_ids.filtered(
            lambda line: line.code in ('082.00', '072.00', '072.01'),
        ).mapped('number_of_days'))
        self.assertGreater(income, 0)
        self.assertGreater(days, 0)
        sheet = self._annual(2025)
        values = self._values(sheet)
        self.assertAlmostEqual(values['f18_2064_ziekteofinvaliditeit'], income, 2)
        self.assertEqual(values['f18_2065_beroepsziekte'], 0)
        self.assertEqual(values['f18_2090_dagen'], days)
        self.assertEqual(values['f18_2091_dagen'], 0)
        self.assertAlmostEqual(values['f18_2070_bedrijfsvoorheffing'], withholding, 2)
        self.assertAlmostEqual(values['f18_2059_totaalcontrole'], round(income, 2) + round(withholding, 2), 2)
        monthly = self._monthly(2025)
        self.assertAlmostEqual(monthly.taxable_amount, income, 2)
        self.assertAlmostEqual(monthly.withholding_amount, withholding, 2)

        sheet.declaration_id.action_generate_xml()
        self.assertEqual(sheet.declaration_id.state, 'ready', sheet.declaration_id.error_message)
        fiche = etree.fromstring(bytes(sheet.declaration_id.xml_file)).find('.//Fiche28118')
        self.assertIsNotNone(fiche)
        rounded_values = sheet.with_context(round_281=True)._get_rendering_data(self.employee)['employees_data'][0]
        for tag, value in rounded_values.items():
            if tag.startswith('f18_'):
                self.assertEqual(fiche.findtext(tag), str(value))
        self.assertEqual(fiche.findtext('f18_2064_ziekteofinvaliditeit'), str(int(round(income, 2) * 100)))
        self.assertEqual(fiche.findtext('f18_2070_bedrijfsvoorheffing'), str(int(round(withholding, 2) * 100)))
        self.assertEqual(
            fiche.findtext('f18_2059_totaalcontrole'),
            str(int(round(income, 2) * 100) + int(round(withholding, 2) * 100)),
        )
        self.assertEqual(fiche.findtext('f18_2090_dagen'), str(round(days)))
        report_data = sheet._post_process_rendering_data_pdf(sheet._get_rendering_data(self.employee))[self.employee]
        self.env['ir.actions.report']._render_qweb_html(
            sheet._get_pdf_report().id, self.employee.ids, data={
                'report_data': report_data,
                'employee': self.employee,
                'company_id': self.employee.company_id,
                'payroll_config_id': self.employee.company_id.current_payroll_config_id,
            },
        )

    def test_no_withholding_tax_for_cross_border_workers(self):
        self.employee.version_id.l10n_be_resident_situation = 'cross_border'
        self.assertTrue(self.employee.version_id.no_withholding_taxes)
        leave = self.env['hr.leave'].sudo().create({
            'name': 'Illness',
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_work_incapacity_worker_second_week').id,
            'request_date_from': date(2026, 1, 1),
            'request_date_to': date(2026, 1, 31),
            'employee_id': self.employee.id,
        })
        leave.action_approve()
        payslip = self.create_and_validate_payslips(employees=self.employee, year=2026, months=[1])
        self.assertTrue(payslip.line_ids.filtered(lambda line: line.code == 'REPLACEMENT_REVENUE').total)
        self.assertFalse(payslip.line_ids.filtered(lambda line: line.code == 'REPLACEMENT_REVENUE.P.P').total)

    def test_day_count_follows_mapping(self):
        payslip = self._payslip([(self.income_rule, 100)])
        payslip.worked_days_line_ids = [Command.create({
            'version_id': payslip.version_id.id,
            'work_entry_type_id': self.env['hr.work.entry.type'].search([('code', '=', '082.00')], limit=1).id,
            'number_of_days': 3,
        })]
        self._mapping('2090').evaluation_value = "result = worked_days['082.00'] * 2"
        self.assertEqual(self._values(self._annual())['f18_2090_dagen'], 6)

    def test_281_18_mapping_does_not_feed_274_18(self):
        rule = self._extra_rule()
        self._mapping('2064').salary_rule_ids += rule
        self._payslip([(rule, 40)])
        values = self._values(self._annual())
        self.assertEqual(values['f18_2064_ziekteofinvaliditeit'], 40)
        self.assertFalse(self._monthly())

    def test_274_18_mapping_does_not_feed_281_18(self):
        rule = self._extra_rule()
        custom_tax = self.withholding_rule.copy({
            'name': 'Custom replacement withholding',
            'code': 'REPLACEMENT.CUSTOM.PP',
        })
        self._274_mapping('taxable').salary_rule_ids += rule
        self._274_mapping('withholding').evaluation_value = "result = -mapped_total['REPLACEMENT.CUSTOM.PP']"
        self._payslip([(rule, 40), (custom_tax, -8)])
        monthly = self._monthly()
        self.assertEqual(monthly.taxable_amount, 40)
        self.assertEqual(monthly.withholding_amount, 8)
        self.assertNotIn(self.employee, self._annual().line_ids.employee_id)

    def test_mappings_cover_older_declarations(self):
        self.employee.version_id.contract_date_start = date(2019, 1, 1)
        self._payslip([(self.income_rule, 50)]).write({'date_from': date(2019, 1, 1), 'date_to': date(2019, 1, 31)})
        self.assertEqual(self._monthly(2019).taxable_amount, 50)
        values = self._values(self._annual(2019))
        self.assertEqual(values['f18_2064_ziekteofinvaliditeit'], 50)
        self.assertEqual(values['f18_2059_totaalcontrole'], 50)

    def test_new_274_opens_before_its_period_is_chosen(self):
        report = Form(self.env['l10n_be.274_xx'].with_company(self.belgian_company))
        self.assertEqual(len(report.line_274_18_ids), 0)

    def test_274_18_rows_can_be_formulas(self):
        rule = self._extra_rule()
        self._274_mapping('taxable').write({
            'evaluation_type': 'python',
            'salary_rule_ids': [Command.clear()],
            'is_monetary': True,
            'evaluation_value': "result = mapped_total['REPLACEMENT_REVENUE'] - mapped_total['REPLACEMENT.CUSTOM']",
        })
        self._payslip([(self.income_rule, 100), (rule, 30), (self.withholding_rule, -20)])
        self._payslip([(self.income_rule, 10), (rule, 30), (self.withholding_rule, -2)])
        # As for the other 274 forms, the amounts of all the payslips are added up
        monthly = self._monthly()
        self.assertEqual(monthly.taxable_amount, 50)
        self.assertEqual(monthly.withholding_amount, 22)

    def test_274_18_rows_can_be_control_rows(self):
        self._274_mapping('withholding').write({
            'evaluation_type': 'control',
            'evaluation_value': False,
            'control_mapping_ids': [Command.set(self._274_mapping('taxable').ids)],
        })
        self._payslip([(self.income_rule, 100), (self.withholding_rule, -20)])
        monthly = self._monthly()
        self.assertEqual(monthly.taxable_amount, 100)
        self.assertEqual(monthly.withholding_amount, 100)

    def test_withholding_only_preserves_annual_eligibility(self):
        self._payslip([(self.withholding_rule, -8)])
        values = self._values(self._annual())
        self.assertEqual(values['f18_2064_ziekteofinvaliditeit'], 0)
        self.assertEqual(values['f18_2070_bedrijfsvoorheffing'], 8)
        # The withholding tax is declared, even without taxable amount
        monthly = self._monthly()
        self.assertEqual(monthly.taxable_amount, 0)
        self.assertEqual(monthly.withholding_amount, 8)

    def test_offsetting_slips_leave_no_annual_fiche(self):
        self._payslip([(self.income_rule, 100), (self.withholding_rule, -20)])
        self._payslip([(self.income_rule, -100), (self.withholding_rule, 20)])
        self.assertNotIn(self.employee, self._annual().line_ids.employee_id)
        # As on the 281.18, the correction cancels the payslip
        self.assertFalse(self._monthly())

    def _check_274_18_refund(self):
        # A refund carries the negation of the payslip it reverses: it is kept with it and cancels it, as when the
        # payslip is corrected
        payslip = self._payslip([(self.income_rule, 100), (self.withholding_rule, -20)])
        self._payslip([(self.income_rule, -100), (self.withholding_rule, 20)]).write({
            'credit_note': True,
            'is_refund_payslip': True,
            'origin_payslip_id': payslip.id,
        })
        self._payslip([(self.income_rule, 80), (self.withholding_rule, -16)]).origin_payslip_id = payslip
        monthly = self._monthly()
        self.assertEqual(sum(monthly.mapped('taxable_amount')), 80)
        self.assertEqual(sum(monthly.mapped('withholding_amount')), 16)

    def test_274_18_refund(self):
        self._check_274_18_refund()

    def test_274_18_refund_formula(self):
        self._274_mapping('taxable').write({
            'evaluation_type': 'python',
            'salary_rule_ids': [Command.clear()],
            'is_monetary': True,
            'evaluation_value': "result = mapped_total['REPLACEMENT_REVENUE']",
        })
        self._check_274_18_refund()

    def test_mapping_year_and_fiscal_date(self):
        rule = self._extra_rule()
        for mapping in self._mapping('2064') | self._274_mapping('taxable'):
            mapping.date_to = date(2026, 12, 31)
            mapping.copy({
                'date_from': date(2027, 1, 1),
                'date_to': False,
                'salary_rule_ids': [Command.set(rule.ids)],
            })
        payslip = self._payslip([(rule, 60)])
        self.assertNotIn(self.employee, self._annual().line_ids.employee_id)
        self.assertFalse(self._monthly())
        payslip.l10n_be_fiscal_date = date(2027, 1, 31)
        self.assertEqual(self._values(self._annual(2027))['f18_2064_ziekteofinvaliditeit'], 60)
        self.assertEqual(self._monthly(2027).taxable_amount, 60)
        certificate_sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).new({
            'company_id': self.belgian_company.id,
            'date_start': date(2027, 1, 1),
            'date_end': date(2027, 1, 31),
        })
        self.assertEqual(certificate_sheet.line_274_18_ids.filtered(lambda line: line.employee_id == self.employee).taxable_amount, 60)
