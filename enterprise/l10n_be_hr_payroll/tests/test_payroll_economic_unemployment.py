# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'economic_unemployment')
class TestPayrollEconomicUnemployment(TestPayrollBase, TestBelgiumCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the work entry types of the attendances must be of the company's country
        cls.env.company.country_id = cls.env.ref('base.be')
        resource_calendar = cls.env['resource.calendar'].create({
            'name': 'Test Calendar: 38 Hours/Week',
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek in ['0', '1', '2', '3', '4'] for hour_from, hour_to in [(8.0, 12.0), (13.0, 16.6)]],
        })
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            resource_calendar=resource_calendar,
            version_fields={
                'name': 'A',
                'date_version': date(2024, 1, 1),
                'contract_date_start': date(2024, 1, 1),
                'contract_date_end': False,
                'wage': 3000.0,
            },
            tz='Europe/Brussels',
        )
        cls.employee.write({
            'l10n_be_fictive_hire_date': date(2024, 1, 1),
        })
        cls.economic_unemployment = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_temporary_economic_unemployement_employee')
        cls.worker_economic_unemployment = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment')

    def _set_week_schedule(self, attendances):
        """Replace the calendar of the version by a 38 hours week of (dayofweek, hour_from, hour_to, work entry type)"""
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        self.version.resource_calendar_id = self.env['resource.calendar'].create({
            'name': 'Test Calendar: 38 Hours/Week with Temporary Unemployment',
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': (work_entry_type or attendance).id,
            }) for dayofweek, hour_from, hour_to, work_entry_type in attendances],
        })

    def test_economic_unemployment_bonus_indexation(self):
        # The supplement of 5 EUR per day of temporary unemployment is linked to the pivot index of 2024-01-01 and
        # follows the wages of the public sector: +2% from May 2024, +2% from February 2025.
        parameter = self.env['hr.rule.parameter']
        self.assertEqual(parameter._get_parameter_from_code('economic_unemployment_bonus', date(2024, 4, 30)), 5.0)
        self.assertEqual(parameter._get_parameter_from_code('economic_unemployment_bonus', date(2024, 5, 1)), 5.1)
        self.assertEqual(parameter._get_parameter_from_code('economic_unemployment_wage_threshold', date(2024, 5, 1)), 4000)

        # one week of economic unemployment: 38 hours = 6 days in the 6 days week
        for date_from, date_to, week_start, rate in [
            (date(2025, 1, 1), date(2025, 1, 31), date(2025, 1, 13), 5.1),
            (date(2025, 2, 1), date(2025, 2, 28), date(2025, 2, 10), 5.2),
        ]:
            self._generate_leave(self.employee, week_start, week_start + relativedelta(days=4), self.economic_unemployment)
            payslip = self._generate_payslip(date_from, date_to)
            eub = payslip.line_ids.filtered(lambda l: l.code == 'EUB')
            self.assertEqual(eub.quantity, 6.0)
            self.assertAlmostEqual(eub.amount, rate, places=2)
            self.assertAlmostEqual(eub.total, 6 * rate, places=2)

    def test_economic_unemployment_deducted_from_monthly_wage(self):
        # The contract is suspended on the days of temporary unemployment: the employer pays no wage for them (the
        # ONEM pays the allowances), the monthly wage is reduced by these hours at the hourly rate.
        self._generate_leave(self.employee, date(2025, 2, 10), date(2025, 2, 14), self.economic_unemployment)
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        # 3000 * (1 - 3 / (13 * 38) * 38) = 2307.69
        self._validate_worked_days(payslip, {
            '002.00': (15.0, 114.0, 2307.69),
            '137.20': (5.0, 38.0, 0.0),
        })
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda l: l.code == 'BASIC').total, 2307.69, places=2)

    def test_economic_unemployment_compensation_cp302_partial_days(self):
        # CP 302: the employer pays 0.5187 EUR per hour of the schedule for each day of economic unemployment, at
        # least 2 EUR a day, during the first 110 days of the year. A morning of unemployment is a day of it.
        self.version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        self._set_week_schedule([
            (dayofweek, hour_from, hour_to, self.worker_economic_unemployment if dayofweek in '012' and hour_from < 12.0 else False)
            for dayofweek in '01234' for hour_from, hour_to in [(8.0, 11.6), (12.0, 16.0)]
        ])
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        # 12 mornings of 3.6 hours (Monday to Wednesday): 12 * max(2, 3.6 * 0.5187) = 24.00
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda l: l.code == 'EUC').total, 24.0, places=2)

    def test_economic_unemployment_compensation_cp302_daily_amount(self):
        # CP 302: the complement is an amount per day of economic unemployment (0.5187 EUR per hour of the day's
        # schedule): each day is paid to the cent, the month adds the daily amounts.
        self.version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        self._set_week_schedule([
            (dayofweek, hour_from, hour_to, self.worker_economic_unemployment if dayofweek in '012' and hour_from >= 12.0 else False)
            for dayofweek in '01234' for hour_from, hour_to in [(8.0, 11.6), (12.0, 16.0)]
        ])
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        # 12 afternoons of 4 hours: 4 * 0.5187 = 2.0748 = 2.07 a day, 12 * 2.07 = 24.84 (not 12 * 2.0748 = 24.90)
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda l: l.code == 'EUC').total, 24.84, places=2)

    def test_economic_unemployment_compensation_collective_closure(self):
        # A collective closure for the annual holidays is temporary unemployment, but no lack of work for economic
        # reasons: the complement of the economic unemployment (the CP 302 one as the 2 EUR a day) is not due.
        collective_closure = self.env.ref('hr_work_entry.l10n_be_work_entry_type_temporary_unemployment_collective_closure')
        for joint_committee in ['l10n_be_joint_committee_302', 'l10n_be_joint_committee_100']:
            self.version.l10n_be_joint_committee_id = self.env.ref(f'l10n_be_hr_payroll.{joint_committee}')
            self._set_week_schedule([
                (dayofweek, hour_from, hour_to, collective_closure if dayofweek in '012' else False)
                for dayofweek in '01234' for hour_from, hour_to in [(8.0, 11.6), (12.0, 16.0)]
            ])
            payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
            self.assertTrue(payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '157.00'))
            self.assertFalse(payslip.line_ids.filtered(lambda l: l.code == 'EUC').total)

    def test_economic_unemployment_bonus_registered_hours(self):
        # The supplement is due per allocation of the ONEM, which converts the hours of temporary unemployment
        # into days of the 6 days week (hours * 6 / weekly hours, rounded to the half day), not the days at the
        # average hours per day of the calendar. 38 hours week: 9 hours Monday to Thursday, 2 hours on Friday.
        self._set_week_schedule([
            (dayofweek, hour_from, hour_to, self.economic_unemployment if dayofweek in '01' else False)
            for dayofweek in '0123' for hour_from, hour_to in [(8.0, 12.0), (12.5, 17.5)]
        ] + [('4', 8.0, 10.0, False)])
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        eub = payslip.line_ids.filtered(lambda l: l.code == 'EUB')
        # 8 days of 9 hours: 72 * 6 / 38 = 11.37 -> 11.5 allocations (8 * 7.6 hours would give 9.5)
        self.assertEqual(eub.quantity, 11.5)
        self.assertAlmostEqual(eub.total, 11.5 * 5.2, places=2)

    def test_economic_unemployment_bonus_half_allocations(self):
        # A voluntary part time worker gets half allocations (hours * 12 / full time weekly hours) and half the
        # supplement for each of them, to the cent: 5.31 / 2 = 2.66 from March 2026 (FPS Employment example).
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        reference_calendar = self.env['resource.calendar'].create({
            'name': 'Test Calendar: 38 Hours/Week, 40 Hours Full Time',
            'full_time_required_hours': 40.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': attendance.id,
            }) for dayofweek in '01234' for hour_from, hour_to in [(8.0, 12.0), (12.5, 16.1)]],
        })
        self._set_week_schedule([
            (dayofweek, hour_from, hour_to, self.economic_unemployment if dayofweek in '01' else False)
            for dayofweek in '01' for hour_from, hour_to in [(8.0, 12.0), (12.5, 16.1)]
        ] + [('2', 8.0, 11.8, False)])
        self.version.resource_calendar_id.reference_calendar_id = reference_calendar
        self.version.l10n_be_part_time_status = 'voluntary'
        payslip = self._generate_payslip(date(2026, 3, 1), date(2026, 3, 31))
        eub = payslip.line_ids.filtered(lambda l: l.code == 'EUB')
        # 10 days of 7.6 hours: 76 * 12 / 38 = 24 half allocations at 2.66
        self.assertEqual(eub.quantity, 24)
        self.assertAlmostEqual(eub.amount, 2.66, places=2)
        self.assertAlmostEqual(eub.total, 63.84, places=2)

    def test_economic_unemployment_withholding_tax_without_reduction(self):
        # The supplements of the temporary unemployment bear a flat 26.75 % withholding tax without reduction
        # (Annex III, n° 79.2.2): the reduction of the work bonus only reduces the tax of the scale.
        self.version.wage = 2100.0
        self._generate_leave(self.employee, date(2025, 2, 10), date(2025, 2, 14), self.economic_unemployment)
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        line_values = payslip._get_line_values(['EmpBonus.1', 'EUB', 'P.P', 'ECONOMIC_UNEMPLOYMENT.P.P', 'P.P.DED', 'PPTOTAL'])
        total = {code: line_values[code][payslip.id]['total'] for code in line_values}
        self.assertTrue(total['EmpBonus.1'])
        self.assertAlmostEqual(total['ECONOMIC_UNEMPLOYMENT.P.P'], -round(total['EUB'] * 0.2675, 2), places=2)
        self.assertLessEqual(total['P.P.DED'], abs(total['P.P']))
        self.assertAlmostEqual(total['PPTOTAL'], abs(total['P.P']) - total['P.P.DED'] - total['ECONOMIC_UNEMPLOYMENT.P.P'], places=2)

    def test_economic_unemployment_no_withholding_taxes(self):
        # No Belgian withholding tax at all for an employee without withholding taxes (e.g. a cross-border worker),
        # the supplements included: their payslips stay out of the withholding tax declaration (274).
        self.version.no_withholding_taxes = True
        self._generate_leave(self.employee, date(2025, 2, 10), date(2025, 2, 14), self.economic_unemployment)
        payslip = self._generate_payslip(date(2025, 2, 1), date(2025, 2, 28))
        line_values = payslip._get_line_values(['EUB', 'ECONOMIC_UNEMPLOYMENT.P.P', 'PPTOTAL'])
        self.assertTrue(line_values['EUB'][payslip.id]['total'])
        self.assertFalse(line_values['ECONOMIC_UNEMPLOYMENT.P.P'][payslip.id]['total'])
        self.assertFalse(line_values['PPTOTAL'][payslip.id]['total'])
