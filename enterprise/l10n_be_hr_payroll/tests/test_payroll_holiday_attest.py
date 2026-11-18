import math
from datetime import date, datetime

from freezegun import freeze_time

from odoo.fields import Command
from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrPayrollHolidayAttest(TestPayrollCommon):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.leaving_type_fired = self.env['hr.departure.reason'].create({
            'name': 'Fired',
            'l10n_be_reason_code': 342,
        })

        self.payslip_structure_type = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        self.struct_n_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        self.worker_code_015 = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015')
        self.worker_employee_type = self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_be_worker')

    def _create_employee(self, name):
        employee = self.env['hr.employee'].create({
            'name': name,
            'resource_calendar_id': self.resource_calendar.id,
            'contract_date_start': date(2025, 1, 1),
            'wage': 3000,
        })
        self.env['hr.leave'].create({
            'name': 'Sick leave',
            'employee_id': employee.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_sick_leave').id,
            'request_date_from': datetime(2026, 1, 1),
            'request_date_to': datetime(2026, 4, 30),
        })._action_validate()
        return employee

    def _create_departure(self, employee):
        return self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-06-11',
            'departure_date': '2026-07-01',
            'departure_reason_id': self.leaving_type_fired.id,
            'departure_description': 'Test',
        })

    def _create_attest_employee(self, worker=False):
        values = {
            'name': 'Attestation Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_dimona_category': 'oth',
            'l10n_be_worker_code_id': (self.worker_code_015 if worker else self.worker_code_id).id,
        }
        if worker:
            values['employee_type_id'] = self.worker_employee_type.id
        return self.create_employee(values)

    def _create_attestation(self, employee, **values):
        attest_values = {
            'employee_id': employee.id,
            'attest_type': 'worker',
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
            'prev_work_hours_per_week': 38,
            'prev_reference_work_hours_per_week': 38,
            'prev_work_days_per_week': 5,
        }
        attest_values.update(values)
        if attest_values['attest_type'] == 'worker':
            attest_values.setdefault('prev_days_earned', 10)
            attest_values.setdefault('prev_total_holiday_pay_paid', 2000)
        else:
            attest_values.setdefault('prev_days_earned', 20)
            attest_values.setdefault('prev_simple_holiday_pay_paid', 1000)
            attest_values.setdefault('prev_double_holiday_pay_paid', 1000)
        return self.env['l10n.be.holiday.attest'].create(attest_values)

    def _create_regular_payslip_with_leave(self, attestation):
        attestation.leave_allocation_id.action_approve()
        self.env['hr.leave'].create({
            'name': 'Holiday Attestation Leave',
            'employee_id': attestation.employee_id.id,
            'work_entry_type_id': attestation.leave_allocation_id.work_entry_type_id.id,
            'request_date_from': date(2026, 1, 5),
            'request_date_to': date(2026, 1, 9),
        })._action_validate()
        payslip = self.env['hr.payslip'].create({
            'name': 'January 2026',
            'employee_id': attestation.employee_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.payslip_structure_type.id,
        })
        payslip.compute_sheet()
        return payslip._get_line_values(['HolPayRec'])['HolPayRec'][payslip.id]['total']

    def _get_double_holiday_recovery(self, employee, year):
        payslip = self.env['hr.payslip'].create({
            'name': f'Double Holiday Pay {year}',
            'employee_id': employee.id,
            'date_from': date(year, 6, 1),
            'date_to': date(year, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        payslip.compute_sheet()
        return payslip._get_line_values(['DOUBLERECOVERY'])['DOUBLERECOVERY'][payslip.id]['total']

    def _create_payslip(self, employee, date_from, date_to):
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'company_id': self.env.company.id,
            'struct_id': self.payslip_structure_type.id,
            'date_from': date_from,
            'date_to': date_to
        })
        payslip.action_validate()
        return payslip

    def _get_termination_payslip_values(self, employee):
        employee_departure = self._create_departure(employee)
        employee_departure._generate_termination_holidays()
        employee_departure_holiday_attest = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('struct_id', '=', self.struct_n_id.id)
        ], order='id desc', limit=1)
        payslip_values = employee_departure_holiday_attest._get_line_values(['PPTOTAL'])
        professional_tax = payslip_values['PPTOTAL'][employee_departure_holiday_attest.id]['total']
        return professional_tax

    def test_holiday_attest_witholding_tax_with_longterm_sick_leave(self):
        employee_with_sick_leave = self._create_employee('Employee Sick Leave')
        april_payslip = self._create_payslip(employee_with_sick_leave, datetime(2026, 4, 1), datetime(2026, 4, 30))

        april_payslip_basic = april_payslip._get_line_values(['BASIC'])['BASIC'][april_payslip.id]['total']
        self.assertEqual(april_payslip_basic, 0, "The basic salary should be zero for long sick leave after 30 days.")

        professional_tax = self._get_termination_payslip_values(employee_with_sick_leave)
        self.assertAlmostEqual(professional_tax, 148.87, places=2, msg="The professional tax should not be 0 even with long-term sick leave.")

    def test_holiday_attest_witholding_tax_with_longterm_sick_leave_and_bik(self):
        employee_with_sick_leave = self._create_employee('Employee 2 Sick Leave')
        employee_with_sick_leave.write({
            'internet': 50.0,
            'mobile': 50.0,
            'laptop': 50.0,
            'tablet': 50.0,
            'mobile_amount': 50.0,
        })

        april_payslip = self._create_payslip(employee_with_sick_leave, datetime(2026, 4, 1), datetime(2026, 4, 30))
        april_payslip_basic = april_payslip._get_line_values(['BASIC'])['BASIC'][april_payslip.id]['total']
        self.assertEqual(april_payslip_basic, 0, "The basic salary should be zero for long sick leave after 30 days.")

        professional_tax = self._get_termination_payslip_values(employee_with_sick_leave)
        self.assertEqual(professional_tax, 149.90, "The professional tax should not be 0 even with long-term sick leave.")

    def _create_double_holiday_attest_calendar(self, days):
        return self.env['resource.calendar'].create({
            'name': f'Calendar {days}/5',
            'company_id': self.belgian_company.id,
            'full_time_required_hours': 38,
            'attendance_ids': [
                Command.create({'dayofweek': str(weekday), 'hour_from': hour_from, 'hour_to': hour_to})
                for weekday in range(days)
                for hour_from, hour_to in [(8, 12), (13, 16.6)]
            ],
        })

    def _compute_double_holiday_with_attest(self, days, attest_hours, contract_date_start, attest_date_to):
        """ Double holiday pay of June 2026 for a 4,000 full-time wage worked {days}/5, the previous employer's
        certificate covering 2025 until attest_date_to at attest_hours/38, that employer having paid the double
        holiday pay of its own fraction. """
        employee = self.create_employee({
            'name': 'Double Holiday Attest Employee',
            'resource_calendar_id': self._create_double_holiday_attest_calendar(days).id,
            'wage': 4000 * days / 5,
            'internet': False,
            'mobile': False,
            'date_version': contract_date_start,
            'contract_date_start': contract_date_start,
            'l10n_be_dimona_category': 'oth',
            'l10n_be_worker_code_id': self.worker_code_id.id,
        })
        attest_months = attest_date_to.month / 12
        attest = self._create_attestation(
            employee,
            attest_type='employee',
            date_to=attest_date_to,
            prev_work_hours_per_week=attest_hours,
            prev_double_holiday_pay_paid=round(4000 * 0.92 * attest_hours / 38 * attest_months, 2),
        )
        payslip = self.env['hr.payslip'].create({
            'name': 'Double Holiday Pay 2026',
            'employee_id': employee.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        payslip.compute_sheet()
        codes = ['DOUBLE', 'DOUBLE_COMPLEMENTARY', 'DOUBLERECOVERY']
        line_values = payslip._get_line_values(codes)
        totals = {code: line_values[code][payslip.id]['total'] for code in codes}
        return attest, totals['DOUBLE'] + totals['DOUBLE_COMPLEMENTARY'], totals['DOUBLERECOVERY']

    def test_double_holiday_pay_attest_work_time_rates(self):
        """ The certificate months are weighed by the certificate fraction over the current one, capped at 1: the
        current pay already carries the current fraction. Hired 01/01/2026, certificate for the whole of 2025. """
        # (current days per week, certificate hours per week, double holiday pay = recovery cap)
        cases = [
            (5, 38, 3680.0),    # full time on both sides
            (4, 30.4, 2944.0),  # equal fractions: no prorata
            (4, 15.2, 1472.0),  # the fraction increases: certificate fraction / current fraction
            (2, 30.4, 1472.0),  # the fraction decreases: the current pay, no extra factor
            (5, 15.2, 1472.0),  # increase to full time
            (2, 38, 1472.0),    # decrease from full time
        ]
        for days, attest_hours, expected in cases:
            with self.subTest(days=days, attest_hours=attest_hours):
                attest, double_holiday_pay, recovery = self._compute_double_holiday_with_attest(
                    days, attest_hours, date(2026, 1, 1), date(2025, 12, 31))
                self.assertAlmostEqual(double_holiday_pay, expected, delta=0.01)
                self.assertAlmostEqual(attest.double_holiday_pay_cap, expected, delta=0.01)
                self.assertAlmostEqual(recovery, -expected, delta=0.01)

    def test_double_holiday_pay_attest_and_own_months_part_time(self):
        """ Hired 01/07/2025, certificate from 01/01/2025 to 30/06/2025, both part-time: the recovery of the
        certificate never eats into the double holiday pay of the months worked here (6 / 12 of the pay). """
        # (current days per week, certificate hours per week, double holiday pay, recovery)
        cases = [
            (4, 15.2, 2208.0, -730.34),  # 3200 * 92% * (6 + 6 * 0.4 / 0.8) / 12; cap 2944 * 129 / 260 * 0.5
            (2, 30.4, 1472.0, -730.34),  # 1600 * 92% * (6 + 6) / 12; cap 1472 * 129 / 260
        ]
        for days, attest_hours, expected, expected_recovery in cases:
            with self.subTest(days=days, attest_hours=attest_hours):
                _attest, double_holiday_pay, recovery = self._compute_double_holiday_with_attest(
                    days, attest_hours, date(2025, 7, 1), date(2025, 6, 30))
                self.assertAlmostEqual(double_holiday_pay, expected, delta=0.01)
                self.assertAlmostEqual(recovery, expected_recovery, delta=0.01)
                own_double_holiday_pay = 4000 * days / 5 * 0.92 * 6 / 12
                self.assertGreaterEqual(double_holiday_pay + recovery, own_double_holiday_pay)

    def test_get_number_of_months(self):
        """Fractional month count within a single calendar year (dates are
        constrained to one year by _check_dates)."""
        Attest = self.env['l10n.be.holiday.attest']

        # Full single month -> 1.0
        att = Attest.new({'date_from': date(2024, 3, 1), 'date_to': date(2024, 3, 31)})
        self.assertAlmostEqual(att._get_number_of_months(), 1.0, places=6)

        # Partial single month, leap February (15 of 29 days)
        att = Attest.new({'date_from': date(2024, 2, 1), 'date_to': date(2024, 2, 15)})
        self.assertAlmostEqual(att._get_number_of_months(), 15 / 29, places=6)

        # Multi-month span: 15 Jan -> 20 Mar = 1 whole month + start/end fractions
        att = Attest.new({'date_from': date(2024, 1, 15), 'date_to': date(2024, 3, 20)})
        expected = 1 + (31 - 15 + 1) / 31 + 20 / 31
        self.assertAlmostEqual(att._get_number_of_months(), expected, places=6)

    def test_holiday_pay_caps_track_wage_and_daily_wage(self):
        """Double holiday pay is priced off the contract wage, simple holiday pay off the daily wage."""
        variable_calendar = self.env["resource.calendar"].create({
            "name": "Variable Calendar",
            "calendar_type": "variable",
            "days_per_week": 0.0,
            "hours_per_week": 38.0,
            "full_time_required_hours": 38,
            "company_id": self.belgian_company.id,
        })
        employee = self.create_employee({
            "name": "Hourly Variable",
            "date_version": date(2020, 1, 1),
            "contract_date_start": date(2020, 1, 1),
            "resource_calendar_id": variable_calendar.id,
            "wage_type": "hourly",
            "wage": 0,
            "hourly_wage": 25.0,
        })
        version = employee.version_id

        attestation = self.env["l10n.be.holiday.attest"].create({
            "employee_id": employee.id,
            "date_from": date(2024, 1, 1),
            "date_to": date(2024, 3, 31),
            "prev_work_hours_per_week": 38,
            "prev_reference_work_hours_per_week": 38,
            "prev_work_days_per_week": 5,
            "prev_assimilated_days": 60,
            "prev_simple_holiday_pay_paid": 500,
            "prev_double_holiday_pay_paid": 1000,
        })

        # An hourly wage on a variable calendar: there is a wage, but no hours to price a day with.
        self.assertTrue(
            attestation.has_contract_wage,
            "The attestation should have a contract wage, as the employee's hourly wage is set",
        )
        # 0.92 * (25.0 * 38 * 13 / 3) * min(1, 60 / (52 * 5)) = 874.0
        self.assertAlmostEqual(
            attestation.double_holiday_pay_cap,
            874.0,
            places=2,
            msg="The attestation should have a double holiday pay cap, as it is priced off the contract wage",
        )
        self.assertEqual(
            attestation.l10n_be_daily_wage,
            0,
            "The attestation should have no daily wage, as a variable calendar gives no hours per day to price one with",
        )
        self.assertEqual(
            attestation.simple_holiday_pay_cap,
            0,
            "The attestation should have no simple holiday pay cap, as it is priced off the daily wage",
        )

        version.resource_calendar_id = self.resource_calendar.id

        self.assertTrue(
            attestation.has_contract_wage,
            "The attestation should still have a contract wage, as the hourly wage is unchanged",
        )
        self.assertAlmostEqual(
            attestation.double_holiday_pay_cap,
            874.0,
            places=2,
            msg="The attestation should still have a double holiday pay cap, as the contract wage is unchanged",
        )
        self.assertEqual(
            attestation.l10n_be_daily_wage,
            190.0,
            "The attestation should have a daily wage, as the calendar now gives 7.6 hours per day at 25.0 per hour",
        )
        self.assertEqual(
            attestation.simple_holiday_pay_cap,
            500.0,
            "The attestation should have a simple holiday pay cap, capped at the amount the previous employer paid",
        )

        version.hourly_wage = 0

        self.assertFalse(
            attestation.has_contract_wage,
            "The attestation should have no contract wage, as the employee's hourly wage is cleared",
        )
        self.assertEqual(
            attestation.double_holiday_pay_cap,
            0,
            "The attestation should have no double holiday pay cap, as it is priced off the contract wage",
        )
        self.assertEqual(
            attestation.l10n_be_daily_wage,
            0,
            "The attestation should have no daily wage, as it is the hourly wage times the hours per day",
        )
        self.assertEqual(
            attestation.simple_holiday_pay_cap,
            0,
            "The attestation should have no simple holiday pay cap, as it is priced off the daily wage",
        )

    def test_holiday_pay_caps_match_for_equivalent_hourly_and_monthly_wages(self):
        """Paying a wage by the hour rather than by the month must not change what is recovered."""
        hourly_wage = 25.0
        # 38 hours a week, priced over the 13 / 3 weeks that make up a month.
        equivalent_monthly_wage = hourly_wage * 38 * 13 / 3
        hourly_employee = self.create_employee({
            "name": "Paid Hourly",
            "date_version": date(2020, 1, 1),
            "contract_date_start": date(2020, 1, 1),
            "wage_type": "hourly",
            "wage": 0,
            "hourly_wage": hourly_wage,
        })
        monthly_employee = self.create_employee({
            "name": "Paid Monthly",
            "date_version": date(2020, 1, 1),
            "contract_date_start": date(2020, 1, 1),
            "wage": equivalent_monthly_wage,
        })

        # The amounts paid by the previous employer are set high enough that both caps land on the
        # theoretical ceiling, which is what the wage feeds, rather than on the certificate amount.
        attestation_values = {
            "date_from": date(2024, 1, 1),
            "date_to": date(2024, 3, 31),
            "prev_work_hours_per_week": 38,
            "prev_reference_work_hours_per_week": 38,
            "prev_work_days_per_week": 5,
            "prev_assimilated_days": 60,
            "prev_simple_holiday_pay_paid": 50000,
            "prev_double_holiday_pay_paid": 50000,
        }
        Attestation = self.env["l10n.be.holiday.attest"]
        hourly_attestation = Attestation.create({**attestation_values, "employee_id": hourly_employee.id})
        monthly_attestation = Attestation.create({**attestation_values, "employee_id": monthly_employee.id})

        self.assertAlmostEqual(
            monthly_attestation.double_holiday_pay_cap,
            874.0,
            places=2,
            msg="The monthly employee should have a double holiday pay cap of 0.92 of their monthly wage, prorated",
        )
        self.assertAlmostEqual(
            hourly_attestation.l10n_be_daily_wage,
            monthly_attestation.l10n_be_daily_wage,
            places=2,
            msg="Both employees should have the same daily wage, as they are paid the same amount",
        )
        self.assertAlmostEqual(
            hourly_attestation.simple_holiday_pay_cap,
            monthly_attestation.simple_holiday_pay_cap,
            places=2,
            msg="Both employees should recover the same simple holiday pay, as it is priced off the daily wage",
        )
        self.assertAlmostEqual(
            hourly_attestation.double_holiday_pay_cap,
            monthly_attestation.double_holiday_pay_cap,
            places=2,
            msg="Both employees should recover the same double holiday pay, as it is priced off the monthly wage",
        )

    @freeze_time('2026-01-01')
    def test_attestation_days_rounded_up(self):
        """The days of a certificate converted to the current schedule are rounded up to the unit, the hours stay."""
        employee = self._create_attest_employee()
        attestation = self._create_attestation(
            employee, attest_type='employee', prev_days_earned=7,
            prev_work_hours_per_week=35, prev_reference_work_hours_per_week=35)
        hours_per_day = employee.version_id.resource_calendar_id.hours_per_day
        days = attestation.hours_to_allocate / hours_per_day
        self.assertNotEqual(days, round(days * 2) / 2)
        self.assertEqual(attestation.days_to_allocate, math.ceil(days))

    def test_worker_attestation_recovery_and_allocation(self):
        """A worker certificate grants employee leave and recovers holiday pay after solidarity."""
        former_worker = self._create_attest_employee()
        # 01/01-18/11/2025 = 322 calendar days -> 230 assimilated days (5d/week).
        # round(230 x 5/5 x 38/38) = 230 -> ONVA table 221-230 -> 19 days (employee formula would give 18).
        worker_attest = self._create_attestation(
            former_worker,
            date_from=date(2025, 1, 1),
            date_to=date(2025, 11, 18),
        )

        employee = self._create_attest_employee()
        self._create_attestation(employee, attest_type='employee')

        self.assertEqual(worker_attest.prev_total_holiday_pay_paid, 2000)
        self.assertFalse(worker_attest.is_worker)
        self.assertEqual(worker_attest.prev_simple_holiday_pay_paid, 1000)
        self.assertEqual(worker_attest.prev_double_holiday_pay_paid, 1000)
        self.assertAlmostEqual(worker_attest.limit_hours, 144.4)
        self.assertEqual(worker_attest.hours_to_allocate, 76)
        # 1% holiday-fund solidarity: 1000 x 0.99 = 990.
        self.assertEqual(worker_attest.simple_holiday_pay_cap, 990)
        self.assertEqual(worker_attest.leave_allocation_id.number_of_days, 10)
        self.assertEqual(worker_attest.leave_allocation_id.number_of_hours, 76)
        self.assertEqual(
            worker_attest.leave_allocation_id.work_entry_type_id,
            self.env.ref('hr_work_entry.be_work_entry_type_legal_leave'),
        )
        # 90% of 2500 x 3/13 recovered when the leave is taken.
        self.assertAlmostEqual(self._create_regular_payslip_with_leave(worker_attest), -519.23, places=2)
        self.assertEqual(self._get_double_holiday_recovery(former_worker, 2026), -990)
        # Employee certificates have no solidarity deduction.
        self.assertEqual(self._get_double_holiday_recovery(employee, 2026), -1000)

        january_payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', former_worker.id),
            ('date_from', '=', date(2026, 1, 1)),
        ], limit=1)
        january_payslip.action_payslip_done()
        december_payslip = self.env['hr.payslip'].create({
            'name': 'December 2026',
            'employee_id': former_worker.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.payslip_structure_type.id,
        })
        december_payslip.compute_sheet()
        holiday_pay_regularization = december_payslip._get_line_values(['HolPayReg'])['HolPayReg'][
            december_payslip.id
        ]['total']
        # The cap prorated to the hours taken: 990 x 38 / 76 = 495, the 519.23 recovered are 24.23 too much.
        self.assertAlmostEqual(holiday_pay_regularization, 24.23, places=2)

    @freeze_time('2026-01-01')
    def test_attestation_amount_recovered(self):
        """The amounts recovered on the validated payslips, negative lines, are the recovered amounts of the attest."""
        former_worker = self._create_attest_employee()
        attest = self._create_attestation(former_worker, date_from=date(2025, 1, 1), date_to=date(2025, 11, 18))
        self.assertEqual(attest.simple_holiday_pay_cap, 990)
        self.assertEqual(attest.double_holiday_pay_cap, 990)

        self.assertAlmostEqual(self._create_regular_payslip_with_leave(attest), -519.23, places=2)
        self.assertEqual(self._get_double_holiday_recovery(former_worker, 2026), -990)
        self.env['hr.payslip'].search([('employee_id', '=', former_worker.id)]).action_payslip_done()
        december_payslip = self.env['hr.payslip'].create({
            'name': 'December 2026',
            'employee_id': former_worker.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.payslip_structure_type.id,
        })
        december_payslip.compute_sheet()
        # The regularization refunds what exceeds the cap prorated to the hours taken: 990 x 38 / 76 = 495
        self.assertAlmostEqual(attest.hours_to_allocate, 76, places=2)
        self.assertAlmostEqual(
            december_payslip._get_line_values(['HolPayReg'])['HolPayReg'][december_payslip.id]['total'], 24.23, places=2)
        december_payslip.action_payslip_done()

        attest.invalidate_recordset(['simple_holiday_pay_amount_recovered', 'double_holiday_pay_amount_recovered'])
        self.assertAlmostEqual(attest.simple_holiday_pay_amount_recovered, 495, places=2)
        self.assertEqual(attest.double_holiday_pay_amount_recovered, 990)

    @freeze_time('2026-01-01')
    def test_worker_attestation_for_current_worker(self):
        """A current worker receives worker leave without employer holiday-pay recovery."""
        worker = self._create_attest_employee(worker=True)
        attest = self._create_attestation(worker, prev_days_earned=25)

        self.assertTrue(attest.is_worker)
        self.assertEqual(attest.leave_allocation_id.number_of_days, 20)
        self.assertEqual(attest.leave_allocation_id.number_of_hours, 152)
        self.assertEqual(
            attest.leave_allocation_id.work_entry_type_id,
            self.env.ref('hr_work_entry.l10n_be_work_entry_type_worker_time_off'),
        )
        self.assertEqual(self._create_regular_payslip_with_leave(attest), 0)
        self.assertEqual(self._get_double_holiday_recovery(worker, 2026), 0)

    def test_departure_double_holiday_pay_n1_without_previous_employer(self):
        """
        The exit double holiday pay of the previous year is 7.67% of the gross earned at this employer: the months
        of the previous employer's certificate were paid by the previous employer.
        """
        for departure_date, double_paid_in_june in ((date(2026, 3, 31), False), (date(2026, 8, 31), True)):
            employee = self.create_employee({
                'name': 'Hired with a certificate',
                'date_version': date(2025, 7, 1),
                'contract_date_start': date(2025, 7, 1),
                'wage': 3000,
            })
            self._create_attestation(
                employee,
                attest_type='employee',
                date_from=date(2025, 1, 1),
                date_to=date(2025, 6, 30),
                prev_days_earned=10,
                prev_simple_holiday_pay_paid=1380,
                prev_double_holiday_pay_paid=1380,
            )
            self.create_and_validate_payslips(employee, 2025, list(range(7, 13)))
            double_paid = 0
            if double_paid_in_june:
                # the double holiday pay of June covers the certificate's months and recovers what the previous
                # employer paid
                double_payslip = self.create_and_validate_payslips(employee, 2026, 6, {
                    'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
                })
                codes = ['DH_BASIC', 'DOUBLERECOVERYONSS', 'DOUBLERECOVERYNOONSS']
                values = double_payslip._get_line_values(codes, compute_sum=True)
                self.assertTrue(values['DOUBLERECOVERYONSS']['sum']['total'])
                double_paid = sum(values[code]['sum']['total'] for code in codes)
            departure = self.env['hr.employee.departure'].create({
                'employee_id': employee.id,
                'dismissal_date': departure_date,
                'departure_date': departure_date,
                'departure_reason_id': self.leaving_type_fired.id,
                'departure_description': 'Test',
            })
            departure._generate_termination_holidays()
            payslip_n1 = self.env['hr.payslip'].search([
                ('employee_id', '=', employee.id),
                ('struct_id', '=', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id),
            ])
            self.assertEqual(len(payslip_n1), 1)
            self.assertAlmostEqual(payslip_n1._get_input_line_amount('GROSS_REF'), 18000, places=2)
            values = payslip_n1._get_line_values(['PAY_DOUBLE', 'PAY_DOUBLE_COMPLEMENTARY'], compute_sum=True)
            double_holiday_pay = values['PAY_DOUBLE']['sum']['total'] + values['PAY_DOUBLE_COMPLEMENTARY']['sum']['total']
            self.assertAlmostEqual(double_holiday_pay, max(0, 18000 * 0.0767 - double_paid), places=1,
                                   msg=f"Departure on {departure_date}")

    def test_departure_simple_holiday_pay_n1_without_recovered_days(self):
        """
        The leave days covered by the previous employer's certificate are paid by that employer: the wage paid for
        them is recovered (HolPayRec). They are not simple holiday pay already paid by this employer when the
        departing employer settles the simple holiday pay of the previous year.
        """
        employee = self.create_employee({
            'name': 'Hired with a certificate',
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
            'wage': 3000,
        })
        attestation = self._create_attestation(
            employee,
            attest_type='employee',
            date_from=date(2025, 1, 1),
            date_to=date(2025, 6, 30),
            prev_days_earned=10,
            prev_simple_holiday_pay_paid=1380,
            prev_double_holiday_pay_paid=1380,
        )
        self.create_and_validate_payslips(employee, 2025, list(range(7, 13)))
        recovered = self._create_regular_payslip_with_leave(attestation)
        self.assertTrue(recovered)
        january_payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('date_from', '=', date(2026, 1, 1)),
        ])
        january_payslip.action_payslip_done()
        holiday_pay = january_payslip._get_worked_days_line_values(['016.00'], ['amount'], True)['016.00']['sum']['amount']
        self.assertTrue(holiday_pay)

        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-03-31',
            'departure_date': '2026-03-31',
            'departure_reason_id': self.leaving_type_fired.id,
            'departure_description': 'Test',
        })
        departure._generate_termination_holidays()
        payslip_n1 = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('struct_id', '=', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n1_holidays').id),
        ])
        simple_holiday_pay = payslip_n1._get_line_values(['PAY_SIMPLE'], compute_sum=True)['PAY_SIMPLE']['sum']['total']
        # 7.67% of the gross of 2025 at this employer, minus the holiday pay this employer kept paying
        self.assertAlmostEqual(simple_holiday_pay, 18000 * 0.0767 - (holiday_pay + recovered), places=1)

    def test_holiday_pay_regularization_on_last_monthly_payslip(self):
        """
        The final settlement of the simple holiday pay recovery happens in December or at the end of the contract,
        also without a termination fees payslip.
        """
        employee = self._create_attest_employee()
        attestation = self._create_attestation(employee, attest_type='employee')
        recovered = self._create_regular_payslip_with_leave(attestation)
        self.assertTrue(recovered)
        january_payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('date_from', '=', date(2026, 1, 1)),
        ])
        january_payslip.action_payslip_done()
        holiday_pay = january_payslip._get_worked_days_line_values(['016.00'], ['amount'], True)['016.00']['sum']['amount']

        self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-05-31',
            'departure_date': '2026-05-31',
            'departure_reason_id': self.leaving_type_fired.id,
            'departure_description': 'Test',
        })
        self.assertEqual(employee.departure_date, date(2026, 5, 31))
        may_payslip = self._create_payslip(employee, date(2026, 5, 1), date(2026, 5, 31))
        regularization = may_payslip._get_line_values(['HolPayReg'])['HolPayReg'][may_payslip.id]['total']
        # the leave taken, within the certificate's cap prorated to the 38 hours taken
        prorated_cap = attestation.simple_holiday_pay_cap * 38 / attestation.hours_to_allocate
        self.assertAlmostEqual(regularization, -(min(holiday_pay, prorated_cap) + recovered), places=2)
        self.assertTrue(regularization)

        # a termination fees payslip does not recover it a second time
        termination_payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2026, 5, 1),
            'date_to': date(2026, 5, 31),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id,
        })
        termination_payslip.compute_sheet()
        self.assertAlmostEqual(termination_payslip._get_line_values(['HolPayReg'])['HolPayReg'][termination_payslip.id]['total'], 0, places=2)

    def test_departure_gross_reference_current_contract_only(self):
        """
        The exit holiday pay of an earlier contract of the same year was paid at its own end: the gross reference
        of a later departure only counts the payslips of the current contract.
        """
        employee = self.create_employee({
            'name': 'Rehired',
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 3, 31),
            'wage': 3000,
        })
        first_version = employee.version_id
        first_payslips = self.create_and_validate_payslips(employee, 2026, [1, 2, 3], {'version_id': first_version.id})
        second_version = employee.create_version({
            'date_version': date(2026, 9, 1),
            'contract_date_start': date(2026, 9, 1),
            'contract_date_end': False,
        })
        self.assertNotEqual(first_version, second_version)
        second_payslips = self.create_and_validate_payslips(employee, 2026, [9, 10, 11], {'version_id': second_version.id})
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-11-30',
            'departure_date': '2026-11-30',
            'departure_reason_id': self.leaving_type_fired.id,
            'departure_description': 'Test',
        })
        self.assertEqual(departure.l10n_be_first_contract_date, date(2026, 9, 1))
        self.assertEqual(departure.l10n_be_payslip_n_ids, second_payslips)
        self.assertFalse(departure.l10n_be_payslip_n_ids & first_payslips)

    def test_holiday_pay_regularization_hours_of_the_certificate(self):
        """
        The settlement of the holiday pay recovery covers the hours the certificate allocates (4 weeks of the
        previous schedule, 152 h), not its days times the hours a day of the new schedule (20 x 9.5 = 190 h): the
        days of the employer's own allocation are not recovered.
        """
        calendar = self.env['resource.calendar'].create({
            'name': '4 days of 9.5 hours',
            'company_id': self.belgian_company.id,
            'attendance_ids': [(0, 0, {
                'dayofweek': str(day), 'hour_from': 8, 'hour_to': 17.5,
            }) for day in range(4)],
        })
        employee = self.create_employee({
            'name': 'Four days',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': calendar.id,
            'wage': 3000,
        })
        attestation = self._create_attestation(
            employee,
            attest_type='employee',
            prev_days_earned=20,
            prev_simple_holiday_pay_paid=5000,
            prev_double_holiday_pay_paid=5000,
        )
        self.assertEqual(attestation.hours_to_allocate, 152)
        attestation.leave_allocation_id.action_approve()
        own_allocation = self.env['hr.leave.allocation'].create({
            'name': 'Own paid time off',
            'employee_id': employee.id,
            'work_entry_type_id': attestation.leave_allocation_id.work_entry_type_id.id,
            'number_of_days': 10,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 12, 31),
        })
        own_allocation.action_approve()
        # 20 days of 9.5 hours (190 h): 16 days of the certificate and 4 own days
        for date_from, date_to in ((date(2026, 1, 5), date(2026, 1, 29)), (date(2026, 2, 2), date(2026, 2, 5))):
            self.env['hr.leave'].create({
                'name': 'Holidays',
                'employee_id': employee.id,
                'work_entry_type_id': attestation.leave_allocation_id.work_entry_type_id.id,
                'request_date_from': date_from,
                'request_date_to': date_to,
            })._action_validate()
        payslips = self._create_payslip(employee, date(2026, 1, 1), date(2026, 1, 31))
        payslips |= self._create_payslip(employee, date(2026, 2, 1), date(2026, 2, 28))
        holiday_hours = sum(payslips.worked_days_line_ids.filtered(lambda wd: wd.code == '016.00').mapped('number_of_hours'))
        self.assertAlmostEqual(holiday_hours, 190, places=2)
        december_payslip = self.env['hr.payslip'].create({
            'name': 'December 2026',
            'employee_id': employee.id,
            'date_from': date(2026, 12, 1),
            'date_to': date(2026, 12, 31),
            'struct_id': self.payslip_structure_type.id,
        })
        december_payslip.compute_sheet()
        recovered = (payslips + december_payslip)._get_line_values(['HolPayRec', 'HolPayReg'], compute_sum=True)
        total_recovered = recovered['HolPayRec']['sum']['total'] + recovered['HolPayReg']['sum']['total']
        hourly_wage = 3000 * 3 / 13 / 38
        self.assertLess(152 * hourly_wage, attestation.simple_holiday_pay_cap)
        self.assertAlmostEqual(total_recovered, -152 * hourly_wage, places=1)

    def test_issues_without_dates(self):
        # The form computes the issues while a date is still empty
        attestation = self.env['l10n.be.holiday.attest'].new({'date_from': date(2025, 1, 1), 'date_to': False})
        self.assertFalse(attestation.issues)
        attestation = self.env['l10n.be.holiday.attest'].new({'date_from': date(2025, 2, 1), 'date_to': date(2025, 1, 1)})
        self.assertTrue(attestation.issues)
