# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_lb_hr_payroll')
class TestL10nLbPayslip(TestPayrollBase):
    """Lebanon regular pay structure.

    The expected payslip lines live in tests/test_files/payslips/test_payslip_computation/<test>.json,
    regenerate them with the ',SAVE_JSON' pseudo tag (see hr_payroll.tests.common). The figures the
    tests are about are also asserted explicitly.

    The company pays in LBP, the employee works 40 hours a week (Monday to Friday) since 1 January 2019
    for LBP 104,000,000 a month. January 2027 counts 21 working days: an hourly wage of 104,000,000 / 168.
    From 2024 the yearly family deduction is 450,000,000, 225,000,000 for the spouse and 45,000,000 a child,
    and the bands are 2% up to 360,000,000, 4% up to 900,000,000, then 7%, 11%, 15%, 20% and 25%; a whole
    month counts for 30 days of 360, so the monthly bands are 2% up to 30,000,000 and 4% up to 75,000,000.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attendance_type = cls.env.ref('hr_work_entry.lb_work_entry_type_attendance')
        cls.lbp = cls.env.ref('base.LBP')
        cls.lbp.active = True
        # A company of its own: the currency of a company with journal items (demo data) cannot change
        company = cls.env['res.company'].create({
            'name': "Lebanese Company",
            'country_id': cls.env.ref('base.lb').id,
            'currency_id': cls.lbp.id,
        })
        cls.env.user.company_ids |= company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=company.ids))
        calendar = cls.env['resource.calendar'].create({
            'name': "Lebanon 40 Hours/Week",
            'company_id': cls.env.company.id,
            'hours_per_day': 8.0,
            'full_time_required_hours': 40.0,
            'attendance_ids': [(5, 0, 0)] + [Command.create({
                'dayofweek': str(dayofweek),
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': attendance_type.id,
            }) for dayofweek in range(5) for hour_from, hour_to in [(8.0, 12.0), (13.0, 17.0)]],
        })
        cls._setup_common(
            country=cls.env.ref('base.lb'),
            structure=cls.env.ref('l10n_lb_hr_payroll.hr_payroll_structure_lb_employee_salary'),
            structure_type=cls.env.ref('l10n_lb_hr_payroll.structure_type_employee_lb'),
            resource_calendar=calendar,
            version_fields={
                'date_version': date(2019, 1, 1),
                'contract_date_start': date(2019, 1, 1),
                'wage': 104_000_000.0,
            },
            tz='Asia/Beirut',
        )
        cls.attendance_type = attendance_type
        cls.overtime_type = cls.env.ref('hr_work_entry.lb_work_entry_type_overtime')
        cls.holiday_overtime_type = cls.env.ref('hr_work_entry.l10n_lb_work_entry_type_overtime_public_holiday')
        cls.sick_types = {
            'full': cls.env.ref('hr_work_entry.lb_work_entry_type_sick_leave'),
            'half': cls.env.ref('hr_work_entry.l10n_lb_work_entry_type_sick_leave_half'),
            'unpaid': cls.env.ref('hr_work_entry.l10n_lb_work_entry_type_sick_leave_unpaid'),
        }
        cls.rules = {rule.code: rule for rule in cls.structure.rule_ids}
        # The time rules classify the time entries on their own: the tests encode the overtime directly
        cls.env['hr.time.rule'].search([]).write({'active': False})

    def _payslip(self, date_from, date_to, inputs=None):
        # The inputs are added after the creation, next to the allowances of the contract
        payslip = self._generate_payslip(date_from, date_to)
        if inputs:
            payslip.input_line_ids = [
                Command.create({'salary_rule_id': self.rules[code].id, 'amount': amount})
                for code, amount in inputs.items()
            ]
            payslip.compute_sheet()
        return payslip

    def _month_payslip(self, year, month, inputs=None):
        date_from = date(year, month, 1)
        date_to = (date_from + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return self._payslip(date_from, date_to, inputs=inputs)

    def _create_overtime(self, day, hour_from, hour_to, work_entry_type=None):
        return self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': (work_entry_type or self.overtime_type).id,
            'request_date_from': day,
            'request_date_to': day,
            'request_hour_from': hour_from,
            'request_hour_to': hour_to,
        })

    def _create_sick_leave(self, date_from, date_to):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_types['full'].id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        })
        leave._action_validate()
        return leave

    def _get_sick_leaves(self):
        """(type, first day, last day) of the sick leaves of the employee, in order."""
        types = {work_entry_type: key for key, work_entry_type in self.sick_types.items()}
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
            ('work_entry_type_id', 'in', [work_entry_type.id for work_entry_type in types]),
        ], order='request_date_from')
        return [(types[leave.work_entry_type_id], leave.request_date_from, leave.request_date_to) for leave in leaves]

    def _line_total(self, payslip, code):
        return payslip._get_line_values([code])[code][payslip.id]['total']

    def _worked_days_amount(self, payslip, work_entry_type):
        return sum(payslip.worked_days_line_ids.filtered(lambda line: line.work_entry_type_id == work_entry_type).mapped('amount'))

    def _validate_months(self, months, inputs=None):
        """Generate and validate the monthly payslips of the given (year, month)."""
        payslips = self.env['hr.payslip']
        for year, month in months:
            payslip = self._month_payslip(year, month, inputs=inputs)
            payslip.action_validate()
            payslips |= payslip
        return payslips

    def _set_usd_company(self):
        # 89,500 LBP for a USD, the official rate of the Banque du Liban from 1 February 2024
        self.env.company.currency_id = self.env.ref('base.USD')
        self.env['res.currency.rate'].create({
            'currency_id': self.lbp.id,
            'name': date(2024, 2, 1),
            'rate': 89_500,
            'company_id': self.env.company.id,
        })

    # -------------------------------------------------------------------------
    # Worked example of the specification
    # -------------------------------------------------------------------------

    def test_worked_example_january_2027(self):
        # Married, spouse without work, 2 children. 10 hours of overtime at 104,000,000 / 168 x 150%
        # = 9,285,714.29, paid by the overtime time type and included in the basic salary. Transport allowance
        # entered on the contract: 21 x 450,000; family allowance 2,100,000 + 2 x 1,155,000.
        # NSSF earnings 113,285,714.29 (transport and family allowance excluded): 3% employee, 8% + 6% (on the
        # 28M ceiling) + 8.5% employer. Tax: 113,285,714.29 - (450M + 225M + 2 x 45M) / 12 = 49,535,714.29
        # -> 30M x 2% + 19,535,714.29 x 4% = 1,381,428.57 -> 1,390,000
        self.version.write({'marital': 'married', 'children': 2})
        self.version._set_property_input_value('TRANSPORT_ALW', 9_450_000)
        self._create_overtime(date(2027, 1, 4), 17.0, 22.0)
        self._create_overtime(date(2027, 1, 5), 17.0, 22.0)
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertAlmostEqual(self._worked_days_amount(payslip, self.overtime_type), 104_000_000 / 168 * 1.5 * 10, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'BASIC'), 113_285_714.29, places=2)
        self.assertEqual(self._line_total(payslip, 'TRANSPORT_ALW'), 9_450_000)
        self.assertEqual(self._line_total(payslip, 'FAMILY_ALW'), 4_410_000)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_BASE'), 113_285_714.29, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_SM_EMP'), -3_398_571.43, places=2)
        self.assertEqual(self._line_total(payslip, 'NSSF_FA_EMPLR'), 1_680_000)
        self.assertAlmostEqual(self._line_total(payslip, 'TAXABLE'), 113_285_714.29, places=2)
        self.assertEqual(self._line_total(payslip, 'ITS'), -1_390_000)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 122_357_142.86, places=2)

    # -------------------------------------------------------------------------
    # Income tax on salaries and wages
    # -------------------------------------------------------------------------

    def test_income_tax_cumulative(self):
        # February after the January of the worked example: 217,285,714.29 so far, less 765M x 60 / 360 =
        # 127,500,000; 89,785,714.29 on the bands x 2 / 12: 60M x 2% + 29,785,714.29 x 4% = 2,391,428.57, minus the
        # 1,390,000 of January = 1,001,428.57 -> 1,010,000. The year to date comes from the validated payslips.
        self.version.write({'marital': 'married', 'children': 2})
        self._create_overtime(date(2027, 1, 4), 17.0, 22.0)
        self._create_overtime(date(2027, 1, 5), 17.0, 22.0)
        self._validate_months([(2027, 1)])
        february = self._month_payslip(2027, 2)
        self._validate_payslip(february)
        days, taxable, tax = february._l10n_lb_get_tax_year_to_date()
        self.assertEqual(days, 30)
        self.assertAlmostEqual(taxable, 113_285_714.29, places=2)
        self.assertEqual(tax, 1_390_000)
        self.assertEqual(february._l10n_lb_get_tax_days(), 30)
        self.assertEqual(self._line_total(february, 'ITS'), -1_010_000)

    def test_income_tax_family_situations(self):
        # Single: 104M - 37.5M = 66.5M -> 600,000 + 36.5M x 4% = 2,060,000. Married with 2 children and a working
        # spouse: each spouse gets the single deduction and half the children: 104M - 41.25M = 62.75M -> 1,910,000,
        # and no family allowance for the spouse. Other employer: no deduction, 600,000 + 1,800,000 + 29M x 7%
        for values, tax, label in [
            ({}, 2_060_000, 'single'),
            ({'marital': 'married', 'children': 2, 'l10n_lb_spouse_working': True}, 1_910_000, 'spouse_working'),
            ({'l10n_lb_tax_category': 'other'}, 4_430_000, 'other_employer'),
            ({'l10n_lb_tax_category': 'exempt'}, 0, 'exempt'),
        ]:
            self.version.write({
                'marital': 'single', 'children': 0, 'l10n_lb_spouse_working': False, 'l10n_lb_tax_category': 'main',
                **values,
            })
            payslip = self._month_payslip(2027, 1)
            self._validate_payslip(payslip, label=label)
            self.assertEqual(self._line_total(payslip, 'ITS'), -tax, label)
            if label == 'spouse_working':
                self.assertEqual(self._line_total(payslip, 'FAMILY_ALW'), 2 * 1_155_000)
            payslip.unlink()

    def test_income_tax_2023(self):
        # December 2023, before Law No. 324 of 2024: deduction 37,500,000 a year, bands up to 675,000,000 and no
        # rounding. 104M - 3,125,000 = 100,875,000 on the monthly bands of 1.5M, 3.75M, 7.5M, 15M, 30M, 56.25M:
        # 30,000 + 90,000 + 262,500 + 825,000 + 2,250,000 + 5,250,000 + 44,625,000 x 25% = 19,863,750
        self.version.l10n_lb_nssf_coverage = 'none'
        payslip = self._month_payslip(2023, 12)
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'ITS'), -19_863_750)

    def test_income_tax_joiner(self):
        # Hired on 16 March 2027: 12 of the 23 working days paid, 104M x 12 / 23 = 54,260,869.57; 16 days of
        # work for the tax: deduction 450M x 16 / 360 = 20,000,000, bands x 16 / 360 (2% up to 16,000,000, 4% up
        # to 40,000,000): 320,000 + 18,260,869.57 x 4% = 1,050,434.78 -> 1,060,000
        self.version.write({'date_version': date(2027, 3, 16), 'contract_date_start': date(2027, 3, 16)})
        payslip = self._month_payslip(2027, 3)
        self._validate_payslip(payslip)
        self.assertEqual(payslip._l10n_lb_get_tax_days(), 16)
        self.assertAlmostEqual(self._line_total(payslip, 'BASIC'), 54_260_869.57, places=2)
        self.assertEqual(self._line_total(payslip, 'ITS'), -1_060_000)

    def test_income_tax_daily_worker(self):
        # Hourly wage 200,000: 21 days of 8 hours in January 2027 = 33,600,000. Daily deduction 21 x 1,500,000
        # = 31,500,000, 2,100,000 taxed at 2% (up to 21,000,000) = 42,000 -> 50,000
        self.version.write({'wage_type': 'hourly', 'hourly_wage': 200_000})
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'BASIC'), 33_600_000)
        self.assertEqual(payslip._l10n_lb_get_tax_days(), 21)
        self.assertEqual(self._line_total(payslip, 'ITS'), -50_000)

    def test_tax_borne_by_the_employer(self):
        # Single employee with a net salary agreement: the tax is a cash benefit, grossed up until stable:
        # 106,150,000 - 37,500,000 = 68,650,000 -> 600,000 + 38,650,000 x 4% = 2,146,000 -> 2,150,000
        self.version.l10n_lb_net_salary = True
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'GROSS_UP'), 2_150_000)
        self.assertEqual(self._line_total(payslip, 'ITS'), -2_150_000)
        self.assertEqual(self._line_total(payslip, 'NSSF_SM_EMP'), -3_184_500)

    # -------------------------------------------------------------------------
    # Salaries in US dollars
    # -------------------------------------------------------------------------

    def test_usd_salary(self):
        # USD 2,000 = LBP 179,000,000 at 89,500: 141,500,000 after the deduction -> 600,000 + 1,800,000
        # + 66,500,000 x 7% = 7,055,000 -> 7,060,000 = USD 78.88. NSSF: 3% of the 120M ceiling = USD 1,340.78;
        # family allowances on the 28M ceiling = USD 312.85; end-of-service on the whole salary. Without the rate of
        # the Lebanese pound, the amounts of the law cannot be converted.
        self.env.company.currency_id = self.env.ref('base.USD')
        self.env['res.currency.rate'].search([('currency_id', '=', self.lbp.id)]).unlink()
        self.version.wage = 2_000
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._month_payslip(2027, 1)
        self._set_usd_company()
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertEqual(payslip._l10n_lb_get_lbp_rate(), 89_500)
        self.assertAlmostEqual(self._line_total(payslip, 'ITS'), -78.88, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_SM_EMP'), -40.22, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_FA_EMPLR'), 18.77, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_EOS_EMPLR'), 170, places=2)

    def test_usd_december_bonus(self):
        # 7,060,000 and 7,050,000 alternately (the cumulative computation absorbs the rounding), 77,610,000 after
        # 11 months: the tax withheld in USD converts back exactly to LBP. A USD 4,000 bonus in December:
        # 2,506,000,000 - 450,000,000 = 2,056,000,000 -> 7.2M + 21.6M + 63M + 256M x 11% = 119,960,000, minus the
        # 77,610,000 withheld = 42,350,000 = USD 473.18
        self._set_usd_company()
        self.version.wage = 2_000
        self._validate_months([(2027, month) for month in range(1, 12)])
        december = self._month_payslip(2027, 12, inputs={'BONUS': 4_000})
        self._validate_payslip(december)
        days, taxable, tax = december._l10n_lb_get_tax_year_to_date()
        self.assertEqual(days, 330)
        self.assertEqual(taxable, 11 * 179_000_000)
        self.assertEqual(tax, 77_610_000)
        self.assertAlmostEqual(self._line_total(december, 'ITS'), -473.18, places=2)

    # -------------------------------------------------------------------------
    # Wage and overtime
    # -------------------------------------------------------------------------

    def test_minimum_wage_warning(self):
        # 20,000,000 a month, 8,000,000 below the 28,000,000 of the minimum wage from August 2025, above the
        # 18,000,000 of July 2025; the cost-of-living increase counts. An hourly wage of 100,000 makes 800,000 for a
        # day of 8 hours, below the 1,300,000 a day.
        warning = self.env.ref('l10n_lb_hr_payroll.hr_payroll_warning_minimum_wage_employee_lb')
        self.version.wage = 20_000_000
        self.assertEqual(self.version._l10n_lb_get_minimum_wage_gap(date(2026, 11, 1)), 8_000_000)
        self.assertEqual(self.version._l10n_lb_get_minimum_wage_gap(date(2025, 7, 1)), 0)
        records = warning._get_warning_python_records(localdict={'active_ids': self.version.ids})[0]
        self.assertEqual(records, self.version)
        self.version._set_property_input_value('COL_ALW', 8_000_000)
        self.assertEqual(self.version._l10n_lb_get_minimum_wage_gap(date(2026, 11, 1)), 0)
        self.assertFalse(warning._get_warning_python_records(localdict={'active_ids': self.version.ids})[0])
        self.version.write({'wage_type': 'hourly', 'hourly_wage': 100_000})
        self.assertEqual(self.version._l10n_lb_get_minimum_wage_gap(date(2026, 11, 1)), 500_000)

    def test_overtime_premiums(self):
        # Paid by the time types at their rate: 4 hours of overtime at 150% and 8 hours on a public holiday at 100%,
        # on top of the monthly wage, the hourly wage being 104,000,000 / 168
        self._create_overtime(date(2027, 1, 4), 17.0, 21.0)
        self._create_overtime(date(2027, 1, 9), 8.0, 16.0, work_entry_type=self.holiday_overtime_type)
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        overtime = self._worked_days_amount(payslip, self.overtime_type)
        holiday_overtime = self._worked_days_amount(payslip, self.holiday_overtime_type)
        self.assertAlmostEqual(overtime, 3_714_285.71, places=2)
        self.assertAlmostEqual(holiday_overtime, 4_952_380.95, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'BASIC'), 104_000_000 + overtime + holiday_overtime, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NSSF_BASE'), 104_000_000 + overtime + holiday_overtime, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'TAXABLE'), 104_000_000 + overtime + holiday_overtime, places=2)

    # -------------------------------------------------------------------------
    # National Social Security Fund
    # -------------------------------------------------------------------------

    def test_nssf_ceilings(self):
        # 200,000,000 a month: sickness and maternity on the 120M ceiling, family allowances on 28M from May 2026
        # (18M in April 2026), end-of-service on the whole salary
        self.version.wage = 200_000_000
        may = self._month_payslip(2026, 5)
        self._validate_payslip(may, label='may_2026')
        self.assertEqual(self._line_total(may, 'NSSF_SM_EMP'), -3_600_000)
        self.assertEqual(self._line_total(may, 'NSSF_SM_EMPLR'), 9_600_000)
        self.assertEqual(self._line_total(may, 'NSSF_FA_EMPLR'), 1_680_000)
        self.assertEqual(self._line_total(may, 'NSSF_EOS_EMPLR'), 17_000_000)
        april = self._month_payslip(2026, 4)
        self._validate_payslip(april, label='april_2026')
        self.assertEqual(self._line_total(april, 'NSSF_FA_EMPLR'), 1_080_000)

    def test_nssf_coverage(self):
        # Foreigner without reciprocity: no end-of-service contribution and no family allowance; Palestinian
        # refugee: end-of-service only; employee of 64: no more end-of-service contribution
        self.version.write({'marital': 'married', 'children': 1})
        for coverage, label in [('no_eos', 'no_eos'), ('eos_only', 'eos_only')]:
            self.version.l10n_lb_nssf_coverage = coverage
            payslip = self._month_payslip(2027, 1)
            self._validate_payslip(payslip, label=label)
            codes = set(payslip.line_ids.mapped('code'))
            if coverage == 'no_eos':
                self.assertIn('NSSF_SM_EMP', codes)
                self.assertNotIn('NSSF_EOS_EMPLR', codes)
                self.assertEqual(self._line_total(payslip, 'FAMILY_ALW'), 0)
            else:
                self.assertNotIn('NSSF_SM_EMP', codes)
                self.assertNotIn('NSSF_FA_EMPLR', codes)
                self.assertEqual(self._line_total(payslip, 'NSSF_EOS_EMPLR'), 8_840_000)
            payslip.unlink()
        self.version.l10n_lb_nssf_coverage = 'full'
        self.employee.birthday = date(1962, 12, 15)
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip, label='age_64')
        self.assertNotIn('NSSF_EOS_EMPLR', payslip.line_ids.mapped('code'))
        self.assertEqual(self._line_total(payslip, 'NSSF_SM_EMP'), -3_120_000)

    def test_family_allowance(self):
        # Spouse and 7 children: at most 5 children, 2,100,000 + 5 x 1,155,000 = 7,875,000 from May 2026;
        # 600,000 + 5 x 330,000 = 2,250,000 in June 2025. Never part of the NSSF earnings nor of the taxable income
        self.version.write({'marital': 'married', 'children': 7})
        payslip = self._month_payslip(2026, 5)
        self._validate_payslip(payslip, label='may_2026')
        self.assertEqual(self._line_total(payslip, 'FAMILY_ALW'), 7_875_000)
        self.assertEqual(self._line_total(payslip, 'NSSF_BASE'), 104_000_000)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 104_000_000)
        june_2025 = self._month_payslip(2025, 6)
        self._validate_payslip(june_2025, label='june_2025')
        self.assertEqual(self._line_total(june_2025, 'FAMILY_ALW'), 2_250_000)

    # -------------------------------------------------------------------------
    # Sick leave
    # -------------------------------------------------------------------------

    def test_sick_leave_split(self):
        # 8 years of service: 2 months on full pay and 2 months on half pay a calendar year (Labour Code, art. 40).
        # 148 days from 4 January 2027: 60 days on full pay, 60 on half pay, 28 unpaid. A sick leave later in the year
        # is unpaid, the entitlement is renewed on 1 January: a leave over the new year is unpaid until 31 December
        # and on full pay from 1 January.
        self._create_sick_leave(date(2027, 1, 4), date(2027, 5, 31))
        self.assertEqual(self._get_sick_leaves(), [
            ('full', date(2027, 1, 4), date(2027, 3, 4)),
            ('half', date(2027, 3, 5), date(2027, 5, 3)),
            ('unpaid', date(2027, 5, 4), date(2027, 5, 31)),
        ])
        # March 2027: 4 working days on full pay, 19 on half pay of the 23 working days
        march = self._month_payslip(2027, 3)
        self._validate_payslip(march, label='march_2027')
        self.assertAlmostEqual(self._line_total(march, 'BASIC'), 104_000_000 * (4 + 19 / 2) / 23, places=2)
        march.unlink()
        self._create_sick_leave(date(2027, 12, 20), date(2028, 1, 10))
        self.assertEqual(self._get_sick_leaves()[3:], [
            ('unpaid', date(2027, 12, 20), date(2027, 12, 31)),
            ('full', date(2028, 1, 1), date(2028, 1, 10)),
        ])

    def test_sick_leave_split_seniority(self):
        # Hired on 1 January 2027: no paid sick leave below 3 months of service, then half a month on full pay and
        # half a month on half pay up to 2 years of service
        self.version.write({'date_version': date(2027, 1, 1), 'contract_date_start': date(2027, 1, 1)})
        self._create_sick_leave(date(2027, 3, 20), date(2027, 4, 30))
        self.assertEqual(self._get_sick_leaves(), [
            ('unpaid', date(2027, 3, 20), date(2027, 3, 31)),
            ('full', date(2027, 4, 1), date(2027, 4, 15)),
            ('half', date(2027, 4, 16), date(2027, 4, 30)),
        ])

    def test_sick_leave_split_warning(self):
        # The request warns that it will be split before its validation
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        leave = self.env['hr.leave'].with_context(leave_fast_create=True).create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_types['full'].id,
            'request_date_from': date(2027, 1, 4),
            'request_date_to': date(2027, 5, 31),
        })
        self.assertTrue(any('This time off will be split into' in issue['message'] for issue in (leave.issues or {}).values()))

    # -------------------------------------------------------------------------
    # Termination
    # -------------------------------------------------------------------------

    def test_end_of_service(self):
        # Leaving on 31 January 2027. Lebanese employee: liquidated by the NSSF, only an amount entered is paid,
        # outside the NSSF earnings and the taxable income. Foreign employee without the NSSF end-of-service branch:
        # 8 years and 1 month -> 8 1/12 x 104,000,000 = 840,666,666.67; 7 months -> half a month. Foreign employee
        # covered by the branch: nothing computed.
        self.version.contract_date_end = date(2027, 1, 31)
        self.employee.country_id = self.env.ref('base.lb')
        payslip = self._month_payslip(2027, 1)
        self.assertNotIn('END_OF_SERVICE', payslip.line_ids.mapped('code'))
        payslip.unlink()
        payslip = self._month_payslip(2027, 1, inputs={'END_OF_SERVICE': 50_000_000})
        self._validate_payslip(payslip, label='lebanese_input')
        self.assertEqual(self._line_total(payslip, 'END_OF_SERVICE'), 50_000_000)
        self.assertEqual(self._line_total(payslip, 'NSSF_BASE'), 104_000_000)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 104_000_000)
        payslip.unlink()

        self.employee.country_id = self.env.ref('base.fr')
        payslip = self._month_payslip(2027, 1)
        self.assertNotIn('END_OF_SERVICE', payslip.line_ids.mapped('code'))
        payslip.unlink()
        self.version.l10n_lb_nssf_coverage = 'no_eos'
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip, label='foreign_8_years')
        self.assertAlmostEqual(self._line_total(payslip, 'END_OF_SERVICE'), 840_666_666.67, places=2)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 104_000_000)
        payslip.unlink()
        self.version.write({'date_version': date(2026, 6, 15), 'contract_date_start': date(2026, 6, 15)})
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip, label='foreign_7_months')
        self.assertEqual(self._line_total(payslip, 'END_OF_SERVICE'), 52_000_000)
