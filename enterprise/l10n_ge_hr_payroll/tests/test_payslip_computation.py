# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta

from odoo.fields import Command
from odoo.tests import Form, tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_ge_hr_payroll')
class TestL10nGePayslip(TestPayrollBase):
    """Georgia regular pay structure.

    The expected payslip lines live in tests/test_files/payslips/test_payslip_computation/<test>.json,
    regenerate them with the ',SAVE_JSON' pseudo tag (see hr_payroll.tests.common). The figures the
    tests are about are also asserted explicitly.

    The company pays in GEL, the employee is a Georgian citizen participating in the funded pension, works
    40 hours a week (Monday to Friday) since 1 January 2019 for GEL 5,200 a month, in a standard company.
    Without privilege, the pension is 2% of the taxable salary and the income tax 20% of the salary less the
    pension: 5,200 - 104 - 1,019.20 = 4,076.80.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attendance_type = cls.env.ref('hr_work_entry.ge_work_entry_type_attendance')
        cls.gel = cls.env.ref('base.GEL')
        cls.gel.active = True
        cls.env.company.write({
            'country_id': cls.env.ref('base.ge').id,
            'currency_id': cls.gel.id,
        })
        calendar = cls.env['resource.calendar'].create({
            'name': "Georgia 40 Hours/Week",
            'company_id': cls.env.company.id,
            'hours_per_day': 8.0,
            'full_time_required_hours': 40.0,
            'attendance_ids': [(5, 0, 0)] + [Command.create({
                'dayofweek': str(dayofweek),
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': attendance_type.id,
            }) for dayofweek in range(5) for hour_from, hour_to in [(9.0, 13.0), (14.0, 18.0)]],
        })
        cls._setup_common(
            country=cls.env.ref('base.ge'),
            structure=cls.env.ref('l10n_ge_hr_payroll.hr_payroll_structure_ge_employee_salary'),
            structure_type=cls.env.ref('l10n_ge_hr_payroll.structure_type_employee_ge'),
            resource_calendar=calendar,
            version_fields={
                'date_version': date(2019, 1, 1),
                'contract_date_start': date(2019, 1, 1),
                'wage': 5_200.0,
            },
            tz='Asia/Tbilisi',
        )
        cls.rules = {rule.code: rule for rule in cls.structure.rule_ids}

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

    def _create_leave(self, xml_id, date_from, date_to):
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.env.ref(xml_id).id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        })._action_validate()

    def _line_total(self, payslip, code):
        return payslip._get_line_values([code])[code][payslip.id]['total']

    def _validate_months(self, months, inputs=None):
        """Generate and validate the monthly payslips of the given (year, month)."""
        payslips = self.env['hr.payslip']
        for year, month in months:
            payslip = self._month_payslip(year, month, inputs=inputs)
            payslip.action_validate()
            payslips |= payslip
        return payslips

    def _create_departure(self, xml_id, dismissal_date, notice_period):
        return self.env['hr.employee.departure'].create({
            'employee_id': self.employee.id,
            'departure_reason_id': self.env.ref(f'l10n_ge_hr_payroll.{xml_id}').id,
            'dismissal_date': dismissal_date,
            'l10n_ge_notice_period': notice_period,
        })

    # -------------------------------------------------------------------------
    # Worked example of the specification
    # -------------------------------------------------------------------------

    def test_worked_example_january_2027(self):
        # 3 days of business trip at the GEL 30 per diem, exempt. Taxable salary 5,200: pension 2% = 104 withheld
        # and 104 paid by the employer, income tax (5,200 - 104) x 20% = 1,019.20, net 5,200 + 90 - 104 - 1,019.20
        # = 4,166.80. The State adds 2% within the first GEL 24,000 of the year.
        payslip = self._month_payslip(2027, 1, inputs={'PER_DIEM': 90})
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 5_200)
        self.assertEqual(self._line_total(payslip, 'PENSION_EE'), -104)
        self.assertEqual(self._line_total(payslip, 'PENSION_ER'), 104)
        self.assertEqual(self._line_total(payslip, 'PENSION_STATE'), 104)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -1_019.20, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 4_166.80, places=2)

    # -------------------------------------------------------------------------
    # Personal income tax
    # -------------------------------------------------------------------------

    def _pit_base(self, payslip):
        return payslip._get_line_values(['PIT'], vals_list=['amount'])['PIT'][payslip.id]['amount']

    def test_privilege_cumulative(self):
        # Disability privilege of GEL 6,000 a year, computed in the income tax line: the 5,096 of January (after
        # the pension) are not taxed, February uses the 904 left: (5,096 - 904) x 20% = 838.40, March is fully
        # taxed
        self.version.l10n_ge_tax_privilege = 'b'
        january = self._month_payslip(2027, 1)
        january.action_validate()
        self.assertEqual(self._pit_base(january), 0)
        self.assertEqual(self._line_total(january, 'PIT'), 0)
        self.assertAlmostEqual(self._line_total(january, 'NET'), 5_096, places=2)
        february = self._month_payslip(2027, 2)
        self._validate_payslip(february)
        self.assertEqual(self._pit_base(february), 4_192)
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -838.40, places=2)
        february.action_validate()
        march = self._month_payslip(2027, 3)
        self.assertEqual(self._pit_base(march), 5_096)
        self.assertAlmostEqual(self._line_total(march, 'PIT'), -1_019.20, places=2)

    def test_privilege_used_before_hiring(self):
        # Single parent (GEL 3,000) hired on 1 March 2027, 2,000 already used at the previous employer:
        # (5,096 - 1,000) x 20% = 819.20. The amount used before does not count the following year.
        self.version.write({
            'date_version': date(2027, 3, 1),
            'contract_date_start': date(2027, 3, 1),
            'l10n_ge_tax_privilege': 'a',
            'l10n_ge_privilege_used': 2_000,
        })
        payslip = self._month_payslip(2027, 3)
        self._validate_payslip(payslip)
        self.assertEqual(self._pit_base(payslip), 4_096)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -819.20, places=2)
        next_year = self._month_payslip(2028, 1)
        self.assertEqual(self._pit_base(next_year), 2_096)
        self.assertAlmostEqual(self._line_total(next_year, 'PIT'), -419.20, places=2)

    def test_tax_regimes(self):
        # Income tax regime of the company, pension 104 and income tax on 5,096: 5% for the international and R&D
        # service companies and the start-up in its years 4 to 6, 10% in the years 7 to 10, 20% for an
        # innovative SME and a virtual zone person, nothing in a Free Industrial Zone
        for regime, tax, pension in [
            ('international', 254.80, 104),
            ('rnd', 254.80, 104),
            ('startup_4', 254.80, 104),
            ('startup_7', 509.60, 104),
            ('innovative_sme', 1_019.20, 104),
            ('vzp', 1_019.20, 104),
            ('fiz', 0, 0),
        ]:
            self.env.company.l10n_ge_tax_regime = regime
            payslip = self._month_payslip(2027, 1)
            self._validate_payslip(payslip, label=regime)
            self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -tax, places=2, msg=regime)
            self.assertEqual(self._line_total(payslip, 'PENSION_EE'), -pension, regime)
            payslip.unlink()

    def test_innovation_startup_cap(self):
        # First 3 years of an innovative start-up: GEL 10,000 of the 12,000 a month exempt, the rest after the
        # pension taxed at 20%: (12,000 - 240 - 10,000) x 20% = 352
        self.env.company.l10n_ge_tax_regime = 'startup_1'
        self.version.wage = 12_000
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'PENSION_EE'), -240)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -352, places=2)

    def test_net_salary_basis(self):
        # The employer bears the income tax and the pension: gross-up G = (2% + 20% x 98%) x (5,200 + G),
        # G = 1,123.20 / 0.784 = 1,432.65, taxable 6,632.65, pension 132.65, tax 1,300: the net is the 5,200
        # agreed
        self.version.l10n_ge_net_salary = True
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS_UP'), 1_432.65, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -132.65, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -1_300, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 5_200, places=2)

    def test_usd_company(self):
        # Company in USD, GEL 2.70 for USD 1: the GEL 6,000 privilege is USD 2,222.22. A salary of USD 2,000 uses
        # 1,960 in January; February is taxed on 1,960 - 262.22: 339.56
        self.env.company.currency_id = self.env.ref('base.USD')
        self.env['res.currency.rate'].create({
            'currency_id': self.gel.id,
            'name': date(2027, 1, 1),
            'rate': 2.7,
            'company_id': self.env.company.id,
        })
        self.version.write({'wage': 2_000, 'l10n_ge_tax_privilege': 'b'})
        self._validate_months([(2027, 1)])
        february = self._month_payslip(2027, 2)
        self._validate_payslip(february)
        self.assertAlmostEqual(self._pit_base(february), 1_697.78, places=2)
        self.assertAlmostEqual(self._line_total(february, 'PIT'), -339.56, places=2)

    # -------------------------------------------------------------------------
    # Funded pension
    # -------------------------------------------------------------------------

    def test_pension_statuses(self):
        # No contribution for an employee who opted out or is not covered: tax 20% x 5,200 = 1,040
        for status in ('opted_out', 'not_covered'):
            self.version.l10n_ge_pension_status = status
            payslip = self._month_payslip(2027, 1)
            self._validate_payslip(payslip, label=status)
            self.assertEqual(self._line_total(payslip, 'PENSION_EE'), 0, status)
            self.assertEqual(self._line_total(payslip, 'PENSION_ER'), 0, status)
            self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -1_040, places=2, msg=status)
            self.assertAlmostEqual(self._line_total(payslip, 'NET'), 4_160, places=2, msg=status)
            payslip.unlink()

    def test_state_pension_bands(self):
        # GEL 10,000 a month: 2% in January and February, then 2% x 4,000 + 1% x 6,000 in March, and nothing
        # above GEL 60,000 from July
        self.version.wage = 10_000
        self._validate_months([(2027, 1), (2027, 2)])
        march = self._month_payslip(2027, 3)
        self._validate_payslip(march)
        self.assertEqual(self._line_total(march, 'PENSION_STATE'), 140)
        march.action_validate()
        self._validate_months([(2027, month) for month in range(4, 7)])
        july = self._month_payslip(2027, 7)
        self.assertEqual(self._line_total(july, 'PENSION_STATE'), 0)
        self.assertEqual(self._line_total(july, 'PENSION_ER'), 200)

    # -------------------------------------------------------------------------
    # Leaves
    # -------------------------------------------------------------------------

    def test_sick_leave(self):
        # The sick days are paid by the employer at the full wage
        self._create_leave('hr_work_entry.ge_work_entry_type_sick_leave', date(2027, 1, 11), date(2027, 1, 15))
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        sick_line = payslip.worked_days_line_ids.filtered(lambda line: line.code == '013.00')
        self.assertEqual(sick_line.number_of_days, 5)
        self.assertEqual(self._line_total(payslip, 'BASIC'), 5_200)

    # -------------------------------------------------------------------------
    # Termination and deductions
    # -------------------------------------------------------------------------

    def test_departure_notice_period(self):
        # Only the Georgian reasons are proposed. The employee leaves at the end of the notice period and is
        # archived the day after; a notice shorter than 30 days is flagged.
        departure_form = Form(self.env['hr.employee.departure'].with_context(active_id=self.employee.id))
        self.assertEqual(departure_form.departure_reason_id.country_id, self.env.ref('base.ge'))
        departure_form.departure_reason_id = self.env.ref('l10n_ge_hr_payroll.l10n_ge_departure_redundancy')
        departure_form.dismissal_date = date(2027, 1, 1)
        self.assertEqual(departure_form.l10n_ge_notice_period, 30)
        self.assertFalse(departure_form.l10n_ge_short_notice)
        self.assertEqual(departure_form.departure_date, date(2027, 1, 31))
        self.assertEqual(departure_form.action_date, date(2027, 2, 1))
        departure_form.l10n_ge_notice_period = 3
        self.assertTrue(departure_form.l10n_ge_short_notice)
        self.assertEqual(departure_form.departure_date, date(2027, 1, 4))
        self.assertEqual(departure_form.action_date, date(2027, 1, 5))
        departure = departure_form.save()
        self.assertEqual(self.version.departure_id, departure)
        self.assertEqual(self.version.contract_date_end, date(2027, 1, 4))

    def test_severance(self):
        # Redundancy with the regular allowance of 520: 1 month of 5,720 with 30 days' notice, 2 months with 3
        # days' notice, on the payslip of the departure date, taxable and bearing the pension. No severance on a
        # resignation.
        for xml_id, dismissal_date, notice, severance, label in [
            ('l10n_ge_departure_redundancy', date(2027, 1, 1), 30, 5_720, 'notice'),
            ('l10n_ge_departure_redundancy', date(2027, 1, 28), 3, 11_440, 'short_notice'),
            ('l10n_ge_departure_resignation', date(2027, 1, 1), 30, 0, 'resignation'),
        ]:
            with self.subTest(label=label):
                departure = self._create_departure(xml_id, dismissal_date, notice)
                payslip = self._month_payslip(2027, 1, inputs={'REGULAR_ALW': 520})
                self._validate_payslip(payslip, label=label)
                self.assertEqual(self._line_total(payslip, 'SEVERANCE'), severance)
                taxable = self._line_total(payslip, 'TAXABLE')
                self.assertEqual(taxable, 5_720 + severance)
                self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -round(taxable * 0.98 * 0.2, 2), places=2)
                payslip.unlink()
                self.version.write({'departure_id': False, 'contract_date_end': False})
                departure.unlink()
        # Without departure in the period, no severance
        self._create_departure('l10n_ge_departure_redundancy', date(2027, 1, 15), 30)
        self.assertEqual(self._line_total(self._month_payslip(2027, 1), 'SEVERANCE'), 0)

    def test_unused_annual_leave(self):
        # 24 days of annual leave allocated for 2027, 4 taken in January: the 20 left are paid on the departure
        # at the gross of December 2026 (5,200) divided by its 23 working days: 20 x 226.09 = 4,521.74
        self.assertEqual(self.env.company.l10n_ge_annual_leave_type_id, self.env.ref('hr_work_entry.ge_work_entry_type_legal_leave'))
        self.env['hr.leave.allocation'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.ge_work_entry_type_legal_leave').id,
            'number_of_days': 24,
            'date_from': date(2027, 1, 1),
        }).action_approve()
        self._create_leave('hr_work_entry.ge_work_entry_type_legal_leave', date(2027, 1, 11), date(2027, 1, 14))
        self._validate_months([(2026, 12)])
        self._create_departure('l10n_ge_departure_resignation', date(2027, 1, 1), 30)
        payslip = self._month_payslip(2027, 1)
        self._validate_payslip(payslip)
        leave_line = payslip.line_ids.filtered(lambda line: line.code == 'LEAVE_IN_LIEU')
        self.assertEqual(leave_line.quantity, 20)
        self.assertAlmostEqual(leave_line.amount, 5_200 / 23, places=2)
        self.assertAlmostEqual(leave_line.total, 4_521.74, places=2)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 5_200 + leave_line.total)

    def test_deduction_cap(self):
        # Net before the recoveries 4,076.80: the advance takes at most 50% = 2,038.40, nothing is left for the
        # loan. The court order comes first and is not capped.
        payslip = self._month_payslip(2027, 1, inputs={'ADVANCE_RECOVERY': 3_000, 'LOAN_RECOVERY': 500})
        self._validate_payslip(payslip, label='advance_and_loan')
        self.assertAlmostEqual(self._line_total(payslip, 'ADVANCE_RECOVERY'), -2_038.40, places=2)
        self.assertEqual(self._line_total(payslip, 'LOAN_RECOVERY'), 0)
        payslip.unlink()
        payslip = self._month_payslip(2027, 1, inputs={'ATTACH_SALARY': 1_076.80, 'LOAN_RECOVERY': 2_000})
        self._validate_payslip(payslip, label='court_order')
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN_RECOVERY'), -1_500, places=2)

    def test_benefit_in_kind(self):
        # A benefit in kind of 500 is taxable and bears the pension without being paid: pension 114, tax
        # (5,700 - 114) x 20% = 1,117.20, net 5,200 - 114 - 1,117.20 = 3,968.80
        payslip = self._month_payslip(2027, 1, inputs={'BENEFIT_IN_KIND': 500})
        self._validate_payslip(payslip)
        self.assertEqual(self._line_total(payslip, 'TAXABLE'), 5_700)
        self.assertEqual(self._line_total(payslip, 'PENSION_EE'), -114)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -1_117.20, places=2)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 3_968.80, places=2)
