# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo import Command
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
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
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

    def _director(self, **values):
        return self.create_employee([{
            'name': 'Director',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'niss': '85010100115',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Director',
            'l10n_be_legal_last_name': 'Test',
            **values,
        }])

    def _payslip(self, director, amounts, struct=None):
        payslip = self.env['hr.payslip'].create({
            'name': 'Director',
            'employee_id': director.id,
            'company_id': director.company_id.id,
            'version_id': director.version_id.id,
            'struct_id': (struct or self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')).id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'validated',
        })
        self.env['hr.payslip.line'].create([{
            'name': xmlid,
            'slip_id': payslip.id,
            'salary_rule_id': self.env.ref(f'l10n_be_hr_payroll.{xmlid}').id,
            'total': amount,
        } for xmlid, amount in amounts.items()])
        if gross := amounts.get('l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule'):
            # The taxable salary the GROSS line totals: the remuneration of the worked days
            self._worked_days(payslip, gross)
        return payslip

    def _worked_days(self, payslip, amount):
        payslip.worked_days_line_ids = [Command.clear(), Command.create({
            'version_id': payslip.version_id.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            'number_of_days': 20,
            'amount': amount,
        })]

    def _values(self, director):
        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        sheet = declaration.l10n_be_281_20_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(director, sheet.line_ids.employee_id)
        return sheet._get_rendering_data(director)['employees_data'][0]

    def test_termination_fees(self):
        # Code 431: the termination fees of the director, taxable separately
        director = self._director()
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        self._payslip(director, {
            'cp200_employees_termination_fees_gross': 30000.0,
            'cp200_employees_salary_withholding_taxes_total': 9000.0,
        }, struct=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees'))
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 5000.0, 2)
        self.assertAlmostEqual(values['f20_2065_opzeggingsreclasseringsverg'], 30000.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 10500.0, 2)
        self.assertAlmostEqual(values['f20_2059_totaalcontrole'], 5000.0 * 2 + 30000.0 + 10500.0, 2)

    def test_bonus_of_a_director(self):
        # Box 6b: a bonus of the director paid on a bonus payslip (year-end or exceptional bonus) is a non periodic
        # remuneration, with its withholding tax
        director = self._director()
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_bonus_basic_salary_rule': 10000.0,
            'cp200_employees_salary_withholding_taxes_total': 5000.0,
        }, struct=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month'))
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 5000.0, 2)
        self.assertAlmostEqual(values['f20_2062_anderebezoldiginge'], 10000.0, 2)
        self.assertAlmostEqual(values['f20_2063_totaal'], 15000.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 6500.0, 2)

    def test_holiday_pays_of_a_director(self):
        # The holiday pays of a director under an employment contract: the double holiday pay is a periodic
        # remuneration (box 6a), the holiday pay of the year paid at departure an early holiday pay (box 8a, code 402)
        director = self._director_under_employment_contract()
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_double_holiday_base_salary_rule': 4000.0,
            'cp200_employees_salary_withholding_taxes_total': 1200.0,
        }, struct=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday'))
        self._payslip(director, {
            'cp200_employees_termination_n_pay_simple': 3000.0,
            'cp200_employees_salary_withholding_taxes_total': 900.0,
        }, struct=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays'))
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 9000.0, 2)
        self.assertAlmostEqual(values['f20_2062_anderebezoldiginge'], 0.0, 2)
        self.assertAlmostEqual(values['f20_2063_totaal'], 9000.0, 2)
        self.assertAlmostEqual(values['f20_2064_vervroegdvakantieg'], 3000.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 3600.0, 2)
        # Code 411 repeats the codes 400 and 401, not the early holiday pay (code 402)
        self.assertAlmostEqual(values['f20_2081_bezoldigingen'], 9000.0, 2)

    def test_expenses_of_the_company(self):
        # Box 19 a): the reimbursed expenses of the company, by way of determination, out of the remuneration
        director = self._director()
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
            'cp200_employees_salary_representation_fees': 150.0,
            'cp200_employees_salary_homeworking_fees': 20.0,
            'cp200_employees_salary_representation_fees_volatile': 40.0,
            'cp200_employees_salary_expense_refund': 60.0,
            'cp200_employees_salary_expense_reimbursement_manual': 5.0,
        })
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2200_compensationwithstandards'], 170.0, 2)
        self.assertAlmostEqual(values['f20_2069_compensationamountwithoutstandards'], 40.0, 2)
        self.assertAlmostEqual(values['f20_2201_compensationwithdocuments'], 65.0, 2)
        self.assertAlmostEqual(values['f20_2063_totaal'], 5000.0, 2)
        # The control total adds up the zones 2060 to 2088
        self.assertAlmostEqual(values['f20_2059_totaalcontrole'], 5000.0 * 2 + 1500.0 + 40.0, 2)

    def test_mobility_budget(self):
        # Box 19 b): the mobility budget of the year the director was entitled to, prorated to the calendar days of
        # participation in the year (circular 2024/C/16 n° 61-62): entered in July
        director = self._director(contract_date_start=date(2025, 7, 1))
        director.version_id.write({
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 6000.0,
        })
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        }).write({'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31)})
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2134_totaalbedragmobiliteitsbudget'], round(6000.0 * 184 / 365, 2), 2)

    def test_bike_kilometers(self):
        # The kilometers of the bike reimbursement, the ones of the bike part of the commute only
        director = self._director(distance_home_work=20, bike_transport_employee_kilometer=5)
        payslip = self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        self.env['hr.payslip.line'].create({
            'name': 'CYCLE',
            'slip_id': payslip.id,
            'salary_rule_id': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_cycle_transportation').id,
            'quantity': 10,
            'amount': 2.7,
            'total': 27.0,
        })
        self.assertEqual(director.version_id.km_home_work, 20)
        values = self._values(director)
        self.assertEqual(values['f20_2226_kmzone2207'], '100')

    def test_entry_and_departure_dates(self):
        # Box 2: the entry date of a director under an employment contract who started during the year, as the
        # departure date. Not filled for a director without employment contract (avis aux debiteurs 281.20).
        amounts = {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        }
        director = self._director_under_employment_contract(contract_date_start=date(2025, 3, 1))
        self._payslip(director, amounts)
        values = self._values(director)
        self.assertEqual(values['f20_2055_datumvanindienstt'], '01-03-2025')
        self.assertEqual(values['f20_2056_datumvanvertrek'], '')

        director.version_id.contract_date_start = date(2024, 1, 1)
        self.assertEqual(self._values(director)['f20_2055_datumvanindienstt'], '')

        mandate_director = self._director(contract_date_start=date(2025, 3, 1), niss='85010100709')
        self._payslip(mandate_director, amounts)
        self.assertEqual(self._values(mandate_director)['f20_2055_datumvanindienstt'], '')

    def test_remuneration_of_the_year(self):
        # As on the 281.10, each amount of the taxable salary is declared in the year it is attached to: a December
        # payslip paid in January is declared the next year, its benefits in kind stay in the year of the benefit
        director = self._director()
        payslip = self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5100.0,
            'cp200_employees_salary_atn_internet': 100.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        payslip.write({
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
        })
        payslip.l10n_be_fiscal_date = date(2026, 1, 31)
        payslip.worked_days_line_ids.amount = 5000.0
        payslip.line_ids.filtered(lambda line: line.code == 'ATN.INT').l10n_be_follow_pay_period = True
        payslip.line_ids.filtered(lambda line: line.code != 'ATN.INT').l10n_be_follow_pay_period = False

        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 0.0, 2)
        self.assertAlmostEqual(values['f20_2068_bedrag'], 100.0, 2)

        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2026'})
        sheet = declaration.l10n_be_281_20_ids[:1]
        sheet.action_generate_declarations()
        values = sheet._get_rendering_data(director)['employees_data'][0]
        self.assertAlmostEqual(values['f20_2060_periodieke'], 5000.0, 2)
        self.assertAlmostEqual(values['f20_2068_bedrag'], 0.0, 2)

    def test_taxable_bike_allowance(self):
        # The taxable part of the bike allowance is declared in box 6b, not in box 6a
        director = self._director()
        payslip = self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_cycle_transportation_taxable': 20.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        payslip.worked_days_line_ids.amount = 4980.0
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 4980.0, 2)
        self.assertAlmostEqual(values['f20_2062_anderebezoldiginge'], 20.0, 2)
        self.assertAlmostEqual(values['f20_2063_totaal'], 5000.0, 2)

    def test_negative_remuneration(self):
        # Belcotax refuses a negative amount: a negative box 6a (a correction of the previous year) is deducted from
        # box 6b, what is left is set to 0 and reported on the declaration
        director = self._director()
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': -1000.0,
            'cp200_employees_salary_cycle_transportation_taxable': 300.0,
            'cp200_employees_salary_withholding_taxes_total': -300.0,
        })
        values = self._values(director)
        # Box 6a: -1.000 of taxable salary, the 300 of taxable bike allowance in it go to box 6b: -1.000 in box 6a,
        # 300 in box 6b deducted from it, 700 left
        self.assertEqual(values['f20_2060_periodieke'], 0)
        self.assertEqual(values['f20_2062_anderebezoldiginge'], 0)
        self.assertEqual(values['f20_2063_totaal'], 0)
        self.assertEqual(values['f20_2131_bedrijfsvoorheffingvanwerkgever'], 0)
        self.assertEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 0)
        self.assertEqual(values['f20_2059_totaalcontrole'], 0)
        declaration = self.env['l10n_be.281_xx'].search([], order='id desc', limit=1)
        declaration.action_generate_xml()
        self.assertIn('Director', declaration.declaration_warning)
        self.assertIn('-700.00', declaration.declaration_warning)
        self.assertIn('2131', declaration.declaration_warning)

    def test_presence_tokens_of_a_director(self):
        # The presence tokens of a company director are director remunerations: declared on the 281.20 (box 6b)
        # and the 274.20 with their withholding taxes, even if the director is flagged for the 281.30
        director = self._director(l10n_be_include_employee_in_281_30=True)
        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'l10n_be_presence_token_salary_rule': 1000.0,
            'cp200_employees_salary_withholding_taxes': -1500.0,
            'l10n_be_presence_token_withholding_tax': -272.5,
            'cp200_employees_salary_withholding_taxes_total': 1772.5,
        })
        monthly = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        lines_20 = monthly.line_274_20_ids.filtered(lambda l: l.employee_id == director)
        self.assertAlmostEqual(sum(lines_20.mapped('withholding_amount')), 1772.5, 2)
        self.assertFalse(monthly.line_274_30_ids.filtered(lambda l: l.employee_id == director))

        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        declaration.l10n_be_281_30_ids.action_generate_declarations()
        self.assertNotIn(director, declaration.l10n_be_281_30_ids.line_ids.employee_id)
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 5000.0, 2)
        self.assertAlmostEqual(values['f20_2062_anderebezoldiginge'], 1000.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 1772.5, 2)

    def _director_under_employment_contract(self, **values):
        # A worker under an employment contract who also has a paid mandate of director: an ordinary employee for the
        # social security (CP 200, worker code 495), a company director for the withholding tax
        return self.create_employee([{
            'name': 'Salaried Director',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'employee_type_id': self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_director_employment_contract').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'niss': '85010100610',
            'private_street': 'Rue du Test 1',
            'private_zip': '1000',
            'private_city': 'Brussels',
            'l10n_be_legal_first_name': 'Salaried',
            'l10n_be_legal_last_name': 'Director',
            **values,
        }])

    def test_director_under_employment_contract(self):
        # An employee for the social security, declared on the 274.20 and the 281.20 (attraction principle), its
        # remunerations repeated in box 17 (codes 411 and 420) with the special social security contribution (409)
        # and the work bonus (419) of an employee
        director = self._director_under_employment_contract()
        version = director.version_id
        self.assertEqual(version.l10n_be_joint_committee_id.egov3_code, '200')
        self.assertEqual(version.l10n_be_worker_code_id.dmfa_code, '495')
        self.assertTrue(version._l10n_be_is_company_director())
        self.assertFalse(self._director().version_id._l10n_be_is_director_under_employment_contract())

        self._payslip(director, {
            'l10n_be_hr_payroll_structure_cp200_employee_salary_gross_salary_rule': 5000.0,
            'cp200_employees_salary_cycle_transportation': 30.0,
            'cp200_employees_salary_mis_ex_onss': -50.0,
            'cp200_employees_salary_employment_bonus_volet_A': 20.0,
            'cp200_employees_salary_withholding_taxes': -1500.0,
            'cp200_employees_salary_withholding_taxes_total': 1500.0,
        })
        monthly = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        lines_20 = monthly.line_274_20_ids.filtered(lambda l: l.employee_id == director)
        self.assertAlmostEqual(sum(lines_20.mapped('withholding_amount')), 1500.0, 2)
        self.assertFalse(monthly.line_274_10_ids.filtered(lambda l: l.employee_id == director))

        declaration = self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({'year': '2025'})
        declaration.l10n_be_281_10_ids.action_generate_declarations()
        self.assertNotIn(director, declaration.l10n_be_281_10_ids.line_ids.employee_id)
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2063_totaal'], 5000.0, 2)
        self.assertAlmostEqual(values['f20_2081_bezoldigingen'], values['f20_2063_totaal'] + values['f20_2075_totaal'], 2)
        self.assertAlmostEqual(values['f20_2207_travelbicycleorspeedpedelec'], 30.0, 2)
        self.assertAlmostEqual(values['f20_2087_code420'], 30.0, 2)
        self.assertAlmostEqual(values['f20_2067_bijzonderbijdrage'], 50.0, 2)
        self.assertAlmostEqual(values['f20_2083_bonus'], 20.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], 1500.0, 2)

    def test_director_under_employment_contract_professional_fees(self):
        # The withholding tax of a director under an employment contract deducts the flat-rate professional fees of
        # the company directors (3 %), not the ones of the employees (30 %)
        director = self._director_under_employment_contract(wage=5000.0)
        payslip = self.env['hr.payslip'].create({
            'name': 'Salaried Director',
            'employee_id': director.id,
            'version_id': director.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
        })
        payslip.compute_sheet()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('ONSSTOTAL'), "An employee for the social security")
        fees_rate = payslip._rule_parameter('flat_rate_professional_fees_rate_cp999')
        fees_max = payslip._rule_parameter('flat_rate_professional_fees_max_cp999')
        yearly_taxable = totals['GROSS.Y'] + totals.get('TRANSPORT_TAX_DED', 0)
        self.assertAlmostEqual(totals['F_PROFESSIONAL_FEES'], -min(yearly_taxable * fees_rate, fees_max), 2)

    def test_non_recurring_benefits(self):
        # Code 418: the non recurring benefits linked to results of a director under an employment contract, who pays
        # the ONSS on them, up to the yearly limit (3.622 EUR for 2025), the excess in box 6b
        cct90 = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90')
        director = self._director_under_employment_contract()
        payslip = self.env['hr.payslip'].create({
            'name': 'Director bonus',
            'employee_id': director.id,
            'version_id': director.version_id.id,
            'struct_id': cct90.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'input_line_ids': [Command.create({
                'salary_rule_id': self.env.ref('l10n_be_hr_payroll.l10n_be_hr_payroll_structure_cp200_cct90_amount').id,
                'amount': 5000.0,
            })],
        })
        payslip.compute_sheet()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('ONSS_BONUS'))
        self.assertAlmostEqual(totals['PP_EXEMP'], -3622.0, 2)
        payslip.action_payslip_done()
        values = self._values(director)
        self.assertAlmostEqual(values['f20_2076_nonrecurrentadvantages'], 3622.0, 2)
        self.assertAlmostEqual(values['f20_2062_anderebezoldiginge'], totals['BONUS_GROSS'] - 3622.0, 2)
        self.assertAlmostEqual(values['f20_2060_periodieke'], 0.0, 2)
        self.assertAlmostEqual(values['f20_2066_totaalbedrijfsvoorheffing'], totals['PPTOTAL'], 2)
        self.assertAlmostEqual(values['f20_2081_bezoldigingen'], values['f20_2063_totaal'] + values['f20_2075_totaal'], 2)
