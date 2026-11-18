# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestScientificResearchExemption(TestPayrollCommon):

    _minimal_payroll_setup = True

    @classmethod
    def _create_274xx_sheet(cls, profiles, period_start):
        """ Create payslips for researcher profiles and return a 274.XX sheet for that month. """
        period_end = period_start + relativedelta(day=31)
        struct = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        slip_vals = []
        for i, (cert, wage, rd) in enumerate(profiles, 1):
            emp = cls.create_employee({
                'name': f'R{i}', 'certificate': cert, 'wage': wage,
                'date_version': period_start, 'contract_date_start': period_start, 'contract_date_end': False,
            })
            emp.version_id.write({'rd_percentage': rd})
            emp.version_id.generate_work_entries(period_start, period_end)
            slip_vals.append({
                'name': f'R{i}', 'employee_id': emp.id, 'struct_id': struct.id,
                'version_id': emp.version_id.id, 'date_from': period_start, 'date_to': period_end,
            })
        slips = cls.env['hr.payslip'].create(slip_vals)
        slips.compute_sheet()
        slips.action_payslip_done()
        return cls.env['l10n_be.274_xx'].create({
            'year': period_start.year, 'month': str(period_start.month), 'company_id': cls.belgian_company.id,
        })

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.belgian_company.current_payroll_config_id.onss_importance_code = '1'
        cls.sheet_jan_2026 = cls._create_274xx_sheet([
            ('doctor',   100000.0, 0.50), ('master',   100000.0, 0.50),
            ('doctor',   100000.0, 0.70), ('doctor',   100000.0, 1.00),
            ('bachelor', 100000.0, 0.20), ('bachelor', 100000.0, 0.50),
            ('bachelor', 100000.0, 0.50), ('bachelor', 100000.0, 0.80),
            ('bachelor', 100000.0, 1.00),
        ], date(2026, 1, 1))

    def test_doctor_master_not_capped_bachelor_capped_proportionally(self):
        """ Verify bachelor exemption is capped at 50% of the doctor/master total (small company). """
        sheet = self.sheet_jan_2026
        raw_dm = sheet.deducted_amount_32 + sheet.deducted_amount_33
        expected_cap = raw_dm * 0.50
        self.assertGreater(sheet.deducted_amount_34, expected_cap, 'Raw bachelor must exceed the 50% cap.')
        self.assertAlmostEqual(sheet.capped_amount_34, expected_cap, places=2, msg='capped_amount_34 must equal 50% of doctor/master total.')
        self.assertAlmostEqual(sum(line.amount for line in sheet.line_274_34_ids), sheet.capped_amount_34, places=1, msg='Bachelor line amounts must sum to the granted (capped) total.')
        self.assertAlmostEqual(sheet.deducted_amount, raw_dm + expected_cap, places=2, msg='Total deducted must be doctor/master plus capped bachelor.')
        self.assertAlmostEqual(sheet.amount_to_pay, sheet.total_pp_amount - raw_dm - expected_cap, delta=0.01, msg='Amount to pay must be total PP minus granted exemption.')

    def test_bachelor_rate_derived_limit_is_binding(self):
        """ Verify the 25% rate cap applies for large companies (50+ employees). """
        self.belgian_company.current_payroll_config_id.write({'onss_importance_code': '6'})
        sheet = self._create_274xx_sheet([
            ('doctor', 3000.0, 1.0), ('master', 3000.0, 1.0), ('bachelor', 5000.0, 1.0),
        ], date(2026, 3, 1))
        raw_dm = sheet.deducted_amount_32 + sheet.deducted_amount_33
        self.assertGreater(sheet.deducted_amount_34, raw_dm * 0.25, 'Raw bachelor must exceed the 25% cap.')
        self.assertAlmostEqual(sheet.capped_amount_34, raw_dm * 0.25, places=2, msg='capped_amount_34 must equal 25% of doctor/master total for a large company.')

    def test_bachelor_rate_defaults_to_25_percent_when_company_size_undefined(self):
        """ Verify the 25% rate applies when the company size is not configured. """
        self.belgian_company.current_payroll_config_id.write({'onss_importance_code': False})
        sheet = self._create_274xx_sheet([
            ('doctor', 3000.0, 1.0), ('master', 3000.0, 1.0), ('bachelor', 5000.0, 1.0),
        ], date(2026, 4, 1))
        raw_dm = sheet.deducted_amount_32 + sheet.deducted_amount_33
        self.assertGreater(sheet.deducted_amount_34, raw_dm * 0.25, 'Raw bachelor must exceed the 25% cap.')
        self.assertAlmostEqual(sheet.capped_amount_34, raw_dm * 0.25, places=2, msg='capped_amount_34 must default to 25% of doctor/master total when company size is undefined.')

    def test_bachelor_without_doctors_gets_zero_exemption(self):
        """ Verify a bachelor with no doctor/master peers gets zero exemption. """
        sheet = self._create_274xx_sheet([('bachelor', 100000.0, 1.0)], date(2026, 2, 1))
        self.assertGreater(sheet.deducted_amount_34, 0.0, 'Raw bachelor must be positive before the cap is applied.')
        self.assertAlmostEqual(sheet.capped_amount_34, 0.0, places=2, msg='capped_amount_34 must be zero when no doctors or masters are present.')
        self.assertAlmostEqual(sum(line.amount for line in sheet.line_274_34_ids), 0.0, places=2, msg='Bachelor line amounts must also be zero when the exemption is fully denied.')
        self.assertAlmostEqual(sheet.deducted_amount, 0.0, places=2, msg='Total deducted must be zero when bachelor exemption is fully denied.')

    def test_bachelor_amounts_scaled_proportionally_per_employee(self):
        """ Verify each employee's exempted amount is scaled by the same ratio as the aggregate cap,
        proportional to their own uncapped share, not split equally or by headcount. """
        self.belgian_company.current_payroll_config_id.write({'onss_importance_code': '6'})
        bachelor_profiles = [('bachelor', 8000.0, 1.0), ('bachelor', 4000.0, 1.0)]

        # Large doctor/master pool so the cap never binds here: line amounts stay at their raw value.
        uncapped_sheet = self._create_274xx_sheet(
            [('doctor', 100000.0, 1.0), ('master', 100000.0, 1.0)] + bachelor_profiles, date(2026, 5, 1))
        raw_amounts = sorted(uncapped_sheet.line_274_34_ids.mapped('amount'))

        # Same bachelor profiles, but a small doctor/master pool so the 25% cap is now binding.
        capped_sheet = self._create_274xx_sheet(
            [('doctor', 3000.0, 1.0), ('master', 3000.0, 1.0)] + bachelor_profiles, date(2026, 6, 1))
        capped_amounts = sorted(capped_sheet.line_274_34_ids.mapped('amount'))

        self.assertLess(capped_sheet.capped_amount_34, capped_sheet.deducted_amount_34, 'Cap must actually bind for this scenario.')
        ratio = capped_sheet.capped_amount_34 / capped_sheet.deducted_amount_34
        for raw, capped in zip(raw_amounts, capped_amounts):
            self.assertAlmostEqual(capped, raw * ratio, places=1, msg='Each employee amount must scale by the same ratio as the aggregate cap.')
        self.assertAlmostEqual(sum(capped_amounts), capped_sheet.capped_amount_34, places=1, msg='Bachelor line amounts must sum to the granted (capped) total.')

    def test_research_exemption_on_warrant_payslip(self):
        """ The withholding tax on a researcher's warrants is exempted like the one on the salary (art. 275/3 CIR
        92), at the average research share of the year (a bonus). """
        period_start = date(2026, 7, 1)
        sheet = self._create_274xx_sheet([('master', 4000.0, 0.5)], period_start)
        employee = sheet.line_274_33_ids.employee_id
        monthly_withholding = sheet.line_274_33_ids.withholding_amount

        warrant = self.env['hr.payslip'].create({
            'name': 'Warrant',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant').id,
            'date_from': period_start,
            'date_to': period_start + relativedelta(day=31),
        })
        warrant._set_input_value('WARRANT_WITHOUT_ONSS', 10000.0)
        warrant.compute_sheet()
        warrant.action_payslip_done()
        warrant_withholding = warrant._get_line_values(['PPTOTAL'])['PPTOTAL'][warrant.id]['total']
        self.assertGreater(warrant_withholding, 0.0)

        sheet._compute_line_ids()
        line = sheet.line_274_33_ids
        self.assertAlmostEqual(line.withholding_amount, monthly_withholding + warrant_withholding, places=2)
        self.assertAlmostEqual(line.amount, 0.8 * 0.5 * line.withholding_amount, places=2)

    def test_research_exemption_on_bonus_of_the_monthly_payslip(self):
        """ The withholding tax of a bonus paid with the salary (exceptional withholding tax) is part of the base of
        the research exemption, at the average research share of the year (the one of a bonus), the withholding tax
        of the salary at the share of the month. """
        employee = self.create_employee({
            'name': 'Researcher With A Bonus', 'certificate': 'master', 'wage': 4000.0,
            'date_version': date(2026, 1, 1), 'contract_date_start': date(2026, 1, 1), 'contract_date_end': False,
        })
        employee.version_id.write({'rd_percentage': 0.5})
        employee.create_version({'date_version': date(2026, 7, 1), 'rd_percentage': 1.0})
        period_start, period_end = date(2026, 3, 1), date(2026, 3, 31)
        payslip = self.env['hr.payslip'].create({
            'name': 'Bonus', 'employee_id': employee.id, 'version_id': employee.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': period_start, 'date_to': period_end,
        })
        payslip._set_input_value('BONUS', 5000.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        values = payslip._get_line_values(['PPTOTAL', 'BONUS_PP', 'WITHHOLDING_TAX_EX_274_33'])
        bonus_withholding = -values['BONUS_PP'][payslip.id]['total']
        salary_withholding = values['PPTOTAL'][payslip.id]['total'] - bonus_withholding
        self.assertGreater(bonus_withholding, 0.0)
        year_share = (181 * 0.5 + 184 * 1.0) / 365
        expected = 0.8 * (0.5 * salary_withholding + year_share * bonus_withholding)
        self.assertAlmostEqual(values['WITHHOLDING_TAX_EX_274_33'][payslip.id]['total'], round(expected, 1), delta=0.06)

        sheet = self.env['l10n_be.274_xx'].create({'year': 2026, 'month': '3', 'company_id': self.belgian_company.id})
        line = sheet.line_274_33_ids.filtered(lambda l: l.employee_id == employee)
        self.assertAlmostEqual(line.withholding_amount, salary_withholding + bonus_withholding, places=2)
        self.assertAlmostEqual(line.amount, expected, places=2)

    def test_average_research_share_of_the_pay_types(self):
        """ The research share of a pay type (Partena's table): the bonuses and the exit holiday pay of the year at
        the average of the year (of the occupation), the double holiday pay and the exit holiday pay of the previous
        year at the average of the previous year (of the period worked in it, none without service in it), the
        termination indemnity at the average of the twelve months before the departure, the salary at the share of
        the month. """
        employee = self.create_employee({
            'name': 'Researcher Entered In A-1', 'certificate': 'master',
            'date_version': date(2025, 4, 1), 'contract_date_start': date(2025, 4, 1), 'contract_date_end': False,
        })
        employee.version_id.write({'rd_percentage': 0.4})
        employee.create_version({'date_version': date(2026, 1, 1), 'rd_percentage': 0.6})
        employee.create_version({'date_version': date(2026, 7, 1), 'rd_percentage': 0.8})
        on = date(2026, 3, 1)
        year_share = (181 * 0.6 + 184 * 0.8) / 365
        for structure_code, share in (
            ('BEMONTHLY', 0.6),
            ('BETHIRTEEN', year_share),
            ('BEWARRANT', year_share),
            ('BEHOLN', year_share),
            # the period worked in the previous year only (from April)
            ('BEDOUBLE', 0.4),
            ('BEHOLN1', 0.4),
        ):
            with self.subTest(structure_code=structure_code):
                self.assertAlmostEqual(employee._get_average_rd_percentage(structure_code, on), share, places=6)

        # termination: the twelve months before the departure, 01/10/2025 - 30/09/2026
        employee.departure_date = date(2026, 9, 30)
        self.assertAlmostEqual(
            employee._get_average_rd_percentage('BETERM', date(2026, 9, 1)),
            (92 * 0.4 + 181 * 0.6 + 92 * 0.8) / 365, places=6)
        # a departure during the year: the bonus at the average of the occupation of the year
        self.assertAlmostEqual(
            employee._get_average_rd_percentage('BETHIRTEEN', date(2026, 9, 1)), (181 * 0.6 + 92 * 0.8) / 273, places=6)

        # no service in the previous year: no exemption on the double holiday pay
        newcomer = self.create_employee({
            'name': 'Researcher Hired In A', 'certificate': 'master',
            'date_version': date(2026, 2, 1), 'contract_date_start': date(2026, 2, 1), 'contract_date_end': False,
        })
        newcomer.version_id.write({'rd_percentage': 0.5})
        self.assertEqual(newcomer._get_average_rd_percentage('BEDOUBLE', date(2026, 5, 1)), 0.0)
        self.assertEqual(newcomer._get_average_rd_percentage('BETHIRTEEN', date(2026, 5, 1)), 0.5)
