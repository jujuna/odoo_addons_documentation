# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import date
from unittest.mock import patch

from freezegun import freeze_time

from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestPayrollTransportExemption(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with freeze_time('2026-01-20'):
            cls.transport_employee = cls.create_employee({
                'name': 'Transport Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 0.0,
            })
            cls.transport_employee.version_id.generate_work_entries(date(2026, 1, 1), date(2026, 1, 31))

    def _compute_january_payslip(self):
        payslip = self.env['hr.payslip'].create({
            'name': 'Transport Payslip January 2026',
            'employee_id': self.transport_employee.id,
            'company_id': self.belgian_company.id,
            'version_id': self.transport_employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
        })
        payslip.compute_sheet()
        return payslip

    def _get_line(self, payslip, code):
        return payslip.line_ids.filtered(lambda l: l.code == code)

    def test_no_transport_no_deduction(self):
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
        self.assertFalse(self._get_line(payslip, 'CAR.PRIV').total)
        self.assertFalse(self._get_line(payslip, 'CYCLE.TAX').total)
        self.assertFalse(self._get_line(payslip, 'TRANSPORT_TAX_DED').total,
            "Without any taxable transportation amount, no exemption may be granted")

    def test_private_car_and_cycle_count_split_working_schedule_shifts(self):
        version = self.transport_employee.version_id
        split_shift_calendar = self.env['resource.calendar'].create({
            'name': 'Split-shift calendar',
            'company_id': self.belgian_company.id,
            'full_time_required_hours': 40,
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 16}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '1', 'hour_from': 13, 'hour_to': 17}),
                (0, 0, {'dayofweek': '2', 'hour_from': 8, 'hour_to': 16}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 16}),
                (0, 0, {'dayofweek': '4', 'hour_from': 8, 'hour_to': 16}),
            ],
        })
        version.resource_calendar_id = split_shift_calendar
        self._set_joint_committee(version, '302')

        # March 2026 (daily scale) has 22 workdays, among which five Tuesdays (3, 10, 17, 24 and 31)
        # with two shifts: 17 * 1 + 5 * 2 = 27. Both benefits must agree on that count, whether the
        # employee is reimbursed by car only, by bike only, or both at once.
        scenarios = [
            ('car only', {'private_car_employee_kilometer': 25, 'bike_transport_employee_kilometer': 0}, 27, 0),
            ('bike only', {'private_car_employee_kilometer': 0, 'bike_transport_employee_kilometer': 5}, 0, 27),
            ('car and bike', {'private_car_employee_kilometer': 25, 'bike_transport_employee_kilometer': 5}, 27, 27),
        ]
        for label, benefit_vals, expected_car_qty, expected_cycle_qty in scenarios:
            with self.subTest(label=label), freeze_time('2026-03-20'):
                version.write(benefit_vals)
                payslip = self.env['hr.payslip'].create({
                    'name': 'Transport Payslip March 2026',
                    'employee_id': self.transport_employee.id,
                    'company_id': self.belgian_company.id,
                    'version_id': version.id,
                    'date_from': date(2026, 3, 1),
                    'date_to': date(2026, 3, 31),
                })
                payslip.compute_sheet()
                self.assertEqual(
                    self._get_line(payslip, 'CAR.PRIV').quantity,
                    expected_car_qty,
                    f"Unexpected private car quantity with {label}",
                )
                self.assertEqual(
                    self._get_line(payslip, 'CYCLE').quantity,
                    expected_cycle_qty,
                    f"Unexpected cycle quantity with {label}",
                )
                # the shifts are not merged, but the days and hours worked are unchanged
                attendance = payslip.worked_days_line_ids.filtered(lambda line: line.code == '002.00')
                self.assertEqual(attendance.number_of_days, 22)
                self.assertEqual(attendance.number_of_hours, 176)

    def test_private_car_added_to_withholding_base(self):
        with freeze_time('2026-01-20'):
            baseline = self._compute_january_payslip()
            gross_without = self._get_line(baseline, 'GROSS').total

            self.transport_employee.version_id.write({
                'private_car_employee_kilometer': 25,
            })
            payslip = self._compute_january_payslip()

        car_priv = self._get_line(payslip, 'CAR.PRIV')
        self.assertTrue(car_priv.total, "The private car reimbursement should be paid")
        self.assertAlmostEqual(self._get_line(payslip, 'GROSS').total, gross_without + car_priv.total, 2,
            "The reimbursement should be added to the withholding tax base")
        # Annexe III 2026: up to 41.70 a month
        expected_deduction = -min(12 * 41.7, 12 * car_priv.total)
        self.assertAlmostEqual(self._get_line(payslip, 'TRANSPORT_TAX_DED').total, expected_deduction, 2)

    def test_private_car_keyed_amount(self):
        # The amount keyed on the payslip replaces the reimbursement of the distance, and is paid without a distance
        # too (an employer paying its own daily amount)
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
            payslip._set_input_value('CAR.PRIV', 35.0)
            payslip.compute_sheet()
            self.assertAlmostEqual(self._get_line(payslip, 'CAR.PRIV').total, 35.0, 2)
            # exempted as the computed reimbursement: 35.00 a month, under the 41.70 of Annexe III
            self.assertAlmostEqual(self._get_line(payslip, 'TRANSPORT_TAX_DED').total, -12 * 35.0, 2)

            self.transport_employee.version_id.private_car_employee_kilometer = 25
            payslip.compute_sheet()
            self.assertAlmostEqual(self._get_line(payslip, 'CAR.PRIV').total, 35.0, 2)

    def test_private_car_withholding_exemption_2025(self):
        # The withholding tax of 2025 exempts up to 41.70 a month (Annexe III), although the yearly exemption of the
        # 2025 income is 490: the fiche 281.10 keeps 490.
        with freeze_time('2025-01-20'):
            self.transport_employee.version_id.generate_work_entries(date(2025, 1, 1), date(2025, 1, 31))
            self.transport_employee.version_id.write({'private_car_employee_kilometer': 25})
            payslip = self.env['hr.payslip'].create({
                'name': 'Transport Payslip January 2025',
                'employee_id': self.transport_employee.id,
                'company_id': self.belgian_company.id,
                'version_id': self.transport_employee.version_id.id,
                'date_from': date(2025, 1, 1),
                'date_to': date(2025, 1, 31),
            })
            payslip.compute_sheet()
        car_priv = self._get_line(payslip, 'CAR.PRIV').total
        self.assertGreater(car_priv, 41.7, "Premise: the reimbursement is above the monthly exemption")
        self.assertAlmostEqual(self._get_line(payslip, 'TRANSPORT_TAX_DED').total, -500.4, 2)
        self.assertEqual(payslip._rule_parameter('pricate_car_taxable_threshold'), 490)

    def test_private_car_fully_exempt_does_not_increase_withholding(self):
        # A private-car reimbursement fully below the yearly exemption cap is added to the
        # taxable base and cancelled by TRANSPORT_TAX_DED, so it must not change the withholding
        # tax. Regression: the reimbursement used to be counted a second time in the bareme,
        # over-taxing an amount that is entirely exempt.
        with freeze_time('2026-01-20'):
            baseline = self._compute_january_payslip()
            pp_without = self._get_line(baseline, 'P.P').total
            net_without = self._get_line(baseline, 'NET').total

            self.transport_employee.version_id.write({'private_car_employee_kilometer': 10})
            payslip = self._compute_january_payslip()

        car_priv = self._get_line(payslip, 'CAR.PRIV').total
        deduction = self._get_line(payslip, 'TRANSPORT_TAX_DED').total
        self.assertTrue(car_priv, "The private car reimbursement should be taxable")
        self.assertAlmostEqual(deduction, -12 * car_priv, 2,
            "Premise: the reimbursement is fully below the yearly exemption cap")
        self.assertAlmostEqual(self._get_line(payslip, 'P.P').total, pp_without, 2,
            "A fully-exempt transport reimbursement must not change the withholding tax")
        self.assertAlmostEqual(self._get_line(payslip, 'NET').total, net_without + car_priv, 2,
            "The reimbursement is still fully paid to the employee")

    def test_fuel_card_commute_taxed_in_full(self):
        # The commuting fuel card is taxable pay: it is not a reimbursement of the commuting costs, so it
        # gets no share of the yearly transport exemption.
        with freeze_time('2026-01-20'):
            baseline = self._compute_january_payslip()
            gross_without = self._get_line(baseline, 'GROSS').total
            payslip = self._compute_january_payslip()
            payslip._set_input_value('FUEL_CARD_COMMUTE', 30.0)
            payslip.compute_sheet()
        self.assertAlmostEqual(self._get_line(payslip, 'FUEL_CARD_COMMUTE').total, 30.0, 2)
        self.assertAlmostEqual(self._get_line(payslip, 'GROSS').total, gross_without + 30.0, 2)
        self.assertFalse(self._get_line(payslip, 'TRANSPORT_TAX_DED').total,
            "The fuel card alone does not open the transport exemption")

    def test_fuel_card_commute_beside_private_car(self):
        # The fuel card does not replace the private car reimbursement: both are paid, and the
        # exemption only covers the reimbursement.
        self.transport_employee.version_id.write({'private_car_employee_kilometer': 10})
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
            payslip._set_input_value('FUEL_CARD_COMMUTE', 30.0)
            payslip.compute_sheet()
        car_priv = self._get_line(payslip, 'CAR.PRIV').total
        self.assertTrue(car_priv, "The private car reimbursement is paid beside the fuel card")
        self.assertLess(12 * car_priv, 500, "Premise: the reimbursement alone stays below the yearly exemption cap")
        self.assertAlmostEqual(self._get_line(payslip, 'FUEL_CARD_COMMUTE').total, 30.0, 2)
        self.assertAlmostEqual(self._get_line(payslip, 'TRANSPORT_TAX_DED').total, -12 * car_priv, 2)

    def test_private_car_cp302_student(self):
        # Before the daily scale of February 2026, CP 302 pays its students the private car allowance of its other
        # workers, 70% of the train price, not the 50% of CP 200.
        version = self.transport_employee.version_id
        version.write({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_dimona_category': 'stu',
            'private_car_employee_kilometer': 10,
        })
        ref_date = date(2025, 6, 1)
        self.assertAlmostEqual(
            version._get_private_car_reimbursed_amount(ref_date=ref_date),
            version._get_train_equivalent_amount(10, ref_date=ref_date) * 0.7, 2)

    def _set_joint_committee(self, version, code):
        joint_committee = self.env.ref(f'l10n_be_hr_payroll.l10n_be_joint_committee_{code}') if code else False
        if joint_committee:
            joint_committee.active = True
        version.l10n_be_joint_committee_id = joint_committee

    def test_private_car_daily_scale_brackets(self):
        # The value under the key n of the daily scale applies from n km to the next key excluded, as in the
        # train tables. CP 200 only intervenes from 3 km, CP 302 from 1 km.
        version = self.transport_employee.version_id
        for code, kilometer, daily_amount in (
            ('200', 2, 0.0),
            ('200', 3, 1.10),
            ('200', 30, 3.37),
            ('200', 31, 3.48),
            ('200', 33, 3.48),
            ('200', 34, 3.69),
            ('200', 145, 9.18),
            ('200', 146, 9.44),
            ('200', 200, 9.44),
            ('302', 0, 0.0),
            ('302', 1, 1.54),
            ('302', 30, 4.72),
            ('302', 31, 4.88),
            ('302', 33, 4.88),
            ('302', 34, 5.17),
            ('124', 41, 0.0),
        ):
            with self.subTest(code=code, kilometer=kilometer):
                self._set_joint_committee(version, code)
                version.private_car_employee_kilometer = kilometer
                self.assertAlmostEqual(version._get_private_car_daily_amount(ref_date=date(2026, 3, 1)), daily_amount, 2)

    def test_private_car_monthly_amount(self):
        version = self.transport_employee.version_id
        version.private_car_employee_kilometer = 41
        ref_date = date(2026, 3, 1)
        # CP 200 and 302 from February 2026: daily amount x 5 days x 13 weeks / 3 months
        self._set_joint_committee(version, '200')
        self.assertAlmostEqual(version._get_private_car_reimbursed_amount(ref_date=ref_date), 89.05, 2)  # 4.11
        self._set_joint_committee(version, '302')
        self.assertAlmostEqual(version._get_private_car_reimbursed_amount(ref_date=ref_date), 124.58, 2)  # 5.75
        # Other joint committees (or none): no sector scale, 70% of the train price for the distance
        train_amount = version._get_train_equivalent_amount(41, ref_date=ref_date)
        self.assertTrue(train_amount)
        for code in ('124', False):
            self._set_joint_committee(version, code)
            self.assertAlmostEqual(version._get_private_car_reimbursed_amount(ref_date=ref_date), train_amount * 0.7, 2)
        # CP 200 under 3 km: nothing, before February 2026 too
        self._set_joint_committee(version, '200')
        version.private_car_employee_kilometer = 2
        self.assertFalse(version._get_private_car_reimbursed_amount(ref_date=ref_date))
        self.assertFalse(version._get_private_car_reimbursed_amount(ref_date=date(2025, 6, 1)))

    def test_private_car_monthly_amount_split_on_reference_days(self):
        # Before February 2026, the monthly amount is paid for a full month, also with more granted days than in the
        # reference calendar (e.g. a worked Saturday), and 3/13/5 of it per granted day for a partial month.
        version = self.transport_employee.version_id
        version.private_car_employee_kilometer = 41
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
        monthly_amount = version._get_private_car_reimbursed_amount(ref_date=date(2026, 1, 1))
        self.assertTrue(monthly_amount)
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        weekdays = [date(2026, 1, day) for day in range(1, 32) if date(2026, 1, day).weekday() < 5]
        self.assertEqual(len(weekdays), 22)
        for days, expected_amount, expected_qty in (
            (weekdays, monthly_amount / 22, 22),
            (weekdays + [date(2026, 1, 10)], monthly_amount / 22, 22),
            (weekdays[:10], monthly_amount * 3 / 13 / 5, 10),
        ):
            with self.subTest(days=len(days)):
                work_entries = [{'date': day, 'work_entry_type_id': attendance} for day in days]
                amount, qty, rate = payslip._get_be_private_car_reimbursement_amount(work_entries)
                self.assertAlmostEqual(amount, expected_amount, 2)
                self.assertEqual(qty, expected_qty)
                self.assertEqual(rate, 100)
                # the misspelled name stays available
                self.assertEqual(payslip._get_be_private_car_reimursement_amount(work_entries), (amount, qty, rate))
        # A reference calendar without any working day in the month: nothing, no division by zero
        version.resource_calendar_id.reference_calendar_id = self.env['resource.calendar'].create({
            'name': 'No Working Day',
            'attendance_ids': [(5, 0, 0)],
        })
        self.assertEqual(payslip._get_be_private_car_reimbursement_amount([]), (0, 0, 100))

    def test_distance_tables_brackets(self):
        # Train tables of 1 February 2026: the value under the key n applies from n km to the next key excluded, and
        # nothing below the first key (no distance)
        version = self.env['hr.version']
        ref_date = date(2026, 3, 1)
        for kilometer, train_amount, train_71_8_amount in (
            (0, 0, 0),
            (1, 47.5, 34),
            (3, 47.5, 34),
            (4, 52, 37),
            (110, 325, 228),
            (111, 336, 237),
            (145, 398, 245),
            (146, 409, 245),
            (200, 409, 245),
        ):
            with self.subTest(kilometer=kilometer):
                self.assertAlmostEqual(version._get_train_equivalent_amount(kilometer, ref_date=ref_date), train_amount, 2)
                self.assertAlmostEqual(version._get_train_71_8_amount(kilometer, ref_date=ref_date), train_71_8_amount, 2)
        self.assertAlmostEqual(version._get_train_71_8_amount(4, 'yearly', ref_date=ref_date), 366, 2)
        # Without a 71.8% table (before February 2026): 71.8% of the train table, nothing without a distance
        self.assertFalse(version._get_train_71_8_amount(0, ref_date=date(2025, 6, 1)))
        self.assertAlmostEqual(
            version._get_train_71_8_amount(4, ref_date=date(2025, 6, 1)),
            0.718 * version._get_train_equivalent_amount(4, ref_date=date(2025, 6, 1)), 2)

    def test_private_car_default_scale_warning(self):
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_private_car_default_scale')

        def get_dashboard_employees():
            return self.env['hr.employee'].union(
                warning_data['records'] for warning_data in warning._get_applicable_payroll_warnings(self.env.company)
            )

        version = self.transport_employee.version_id
        self.assertNotIn(self.transport_employee, get_dashboard_employees())
        version.private_car_employee_kilometer = 41
        for code, warned in (('200', False), ('302', False), ('124', True), (False, True)):
            with self.subTest(code=code):
                self._set_joint_committee(version, code)
                if warned:
                    self.assertIn(self.transport_employee, get_dashboard_employees())
                else:
                    self.assertNotIn(self.transport_employee, get_dashboard_employees())
        self.assertFalse(warning.block_payslips)

    def test_cycle_reimbursement_within_exempt_rate(self):
        self.transport_employee.version_id.write({
            'bike_transport_employee_kilometer': 5,
        })
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
        self.assertTrue(self._get_line(payslip, 'CYCLE').total, "The bike reimbursement should be paid")
        self.assertFalse(self._get_line(payslip, 'CYCLE.TAX').total,
            "A bike allowance at or below the exempt rate per km is fully exempted")
        self.assertFalse(self._get_line(payslip, 'TRANSPORT_TAX_DED').total)

    def test_cycle_reimbursement_above_exempt_rate(self):
        self.env['hr.rule.parameter.value'].create({
            'parameter_value': '0.45',
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_cp200_cycle_reimbursement_per_km').id,
            'date_from': date(2026, 1, 1),
        })
        self.transport_employee.version_id.write({
            'bike_transport_employee_kilometer': 5,
        })
        with freeze_time('2026-01-20'):
            payslip = self._compute_january_payslip()
        cycle = self._get_line(payslip, 'CYCLE')
        cycle_tax = self._get_line(payslip, 'CYCLE.TAX')
        # paid: 0.45 x 5 km x 2 = 4.5/day, exempt: 0.37 x 5 km x 2 = 3.7/day
        self.assertAlmostEqual(cycle_tax.amount, 0.8, 2,
            "Only the 0.08/km above the exempt rate is taxable")
        self.assertAlmostEqual(cycle.amount, 3.7, 2)
        self.assertAlmostEqual(cycle.total + cycle_tax.total, 4.5 * cycle.quantity, 2,
            "The two lines together still pay the whole reimbursement")
        self.assertTrue(cycle_tax.total)
        expected_deduction = -min(500, 12 * cycle_tax.total)
        self.assertAlmostEqual(self._get_line(payslip, 'TRANSPORT_TAX_DED').total, expected_deduction, 2)

    @freeze_time('2026-10-20')
    def test_cycle_reimbursement_payslip_reference_date(self):
        version = self.transport_employee.version_id
        version.bike_transport_employee_kilometer = 10
        # Recomputing an older payslip must not pick the rate effective in October.
        for date_from, date_to, daily_amount in (
            (date(2026, 8, 1), date(2026, 8, 31), 5.4),
            (date(2026, 9, 1), date(2026, 9, 30), 5.4),
            (date(2026, 10, 1), date(2026, 10, 31), 6.4),
        ):
            version.generate_work_entries(date_from, date_to)
            payslip = self.env['hr.payslip'].create({
                'employee_id': self.transport_employee.id,
                'company_id': self.belgian_company.id,
                'version_id': version.id,
                'date_from': date_from,
                'date_to': date_to,
            })
            for computation_date in ('2026-09-20', '2026-10-20'):
                with self.subTest(date_from=date_from, computation_date=computation_date), freeze_time(computation_date):
                    payslip.compute_sheet()
                    cycle = self._get_line(payslip, 'CYCLE')
                    self.assertGreater(cycle.quantity, 0)
                    self.assertAlmostEqual(cycle.amount, daily_amount, 2)
                    self.assertFalse(self._get_line(payslip, 'CYCLE.TAX').total)

    @freeze_time('2026-10-20')
    def test_cycle_reimbursement_salary_package_current_date(self):
        version = self.transport_employee.version_id
        version.bike_transport_employee_kilometer = 10
        self.assertAlmostEqual(version.bike_reimbursed_amount, 6.4, 2)
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(reference_date=date(2026, 8, 31)), 5.4, 2)
        self.assertAlmostEqual(version.bike_reimbursed_amount, 6.4, 2)

    @freeze_time('2026-10-20')
    def test_cycle_reimbursement_daily_cap_reference_date(self):
        version = self.transport_employee.version_id
        version.bike_transport_employee_kilometer = 50
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(reference_date=date(2025, 8, 31)), 8, 2)
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(reference_date=date(2026, 8, 31)), 10.8, 2)
        # 0.32 a km from October 2026, at most 12.80 a day, as in the salary package (cp200_cycle_reimbursement_max)
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(reference_date=date(2026, 10, 31)), 12.8, 2)

    def test_train_reimbursement_payslip_reference_date(self):
        # A January 2026 payslip computed later in the year uses the train table of 1 February 2025 and the CP200
        # intervention of 80%, not the ones of 1 February 2026 (100%)
        self.transport_employee.version_id.train_transport_employee_kilometer = 30
        with freeze_time('2026-10-24'):
            payslip = self._compute_january_payslip()
        # 30 km monthly: 142 in the table of 2025, 146 in the table of 2026
        self.assertAlmostEqual(self._get_line(payslip, 'TRAIN').total, 142.0 * 0.8, 2)

    def test_public_transport_reimbursement_payslip_reference_date(self):
        # CP200 bus by distance: the table amount for the distance, at most 75% of the price (2025 and 2026 rules)
        version = self.transport_employee.version_id
        version.write({
            'bus_transport_employee_amount': 100,
            'bus_transport_periodicity': 'monthly',
            'bus_transport_employee_kilometer': 5,
        })
        with freeze_time('2026-10-24'):
            payslip = self._compute_january_payslip()
        expected = version._get_public_transport_reimbursed_amount('bus', ref_date=date(2026, 1, 1))
        self.assertTrue(expected)
        self.assertAlmostEqual(self._get_line(payslip, 'PUB.TRANS').total, expected, 2)

    def test_bike_yearly_cap_other_joint_committee(self):
        # The bike allowance of a joint committee without a cap of its own (e.g. the construction, 124) is capped
        # yearly as the one of the employees (200), not as the one of the hotel industry (302, from 2026 only)
        version = self.transport_employee.version_id
        version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_124')
        payslip = self.env['hr.payslip'].create({
            'name': 'Transport Payslip December 2025',
            'employee_id': self.transport_employee.id,
            'company_id': self.belgian_company.id,
            'version_id': version.id,
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
        })
        self.assertEqual(payslip._rule_parameter('bike_max_reimbursement_yearly_cp200'), 3610)
        version.bike_transport_employee_kilometer = 20
        result_rules = defaultdict(lambda: {'total': 0, 'ytd': 0})
        result_rules['BASIC'] = {'total': 3000, 'ytd': 36000}
        # 3.600 EUR already exempted during the year, 20 days of 10 EUR this month
        result_rules['CYCLE'] = {'total': 0, 'ytd': 3600}
        with patch.object(self.env.registry['hr.payslip'], '_get_be_benefit_count', lambda *args: 20), \
                patch.object(self.env.registry['hr.version'], '_get_bike_reimbursed_amount', lambda *args, **kwargs: 10):
            exempt, taxable = payslip._get_be_bike_reimbursement_amounts(result_rules, [])
        # the whole allowance is paid, the part above the yearly exempt amount (3.610 EUR in 2025) is taxable
        self.assertAlmostEqual((exempt + taxable) * 20, 200, 2)
        self.assertAlmostEqual(exempt * 20, 10, 2)

    def test_bike_allowance_above_yearly_cap_taxed(self):
        # 2025: 0.36 EUR/km and 3.610 EUR a year exempted; above, the allowance is still paid but taxable
        version = self.transport_employee.version_id
        version.bike_transport_employee_kilometer = 25
        payslip = self.env['hr.payslip'].create({
            'name': 'Transport Payslip December 2025',
            'employee_id': self.transport_employee.id,
            'company_id': self.belgian_company.id,
            'version_id': version.id,
            'date_from': date(2025, 12, 1),
            'date_to': date(2025, 12, 31),
        })
        result_rules = defaultdict(lambda: {'total': 0, 'ytd': 0})
        result_rules['BASIC'] = {'total': 3000, 'ytd': 36000}
        # 3.330 EUR already exempted before December, 18 EUR a day (25 km x 2 x 0.36) in December
        result_rules['CYCLE'] = {'total': 0, 'ytd': 3330}
        with patch.object(self.env.registry['hr.payslip'], '_get_be_benefit_count', lambda *args: 20), \
                patch.object(self.env.registry['hr.version'], '_get_bike_reimbursed_amount', lambda *args, **kwargs: 18):
            exempt, taxable = payslip._get_be_bike_reimbursement_amounts(result_rules, [])
        # December: 360 EUR paid, 280 EUR exempted (the room left), 80 EUR taxed
        self.assertAlmostEqual(exempt * 20, 280, 2)
        self.assertAlmostEqual(taxable * 20, 80, 2)
        # 2024: 3.500 EUR a year
        payslip.write({'date_from': date(2024, 12, 1), 'date_to': date(2024, 12, 31)})
        self.assertEqual(payslip._rule_parameter('bike_max_reimbursement_yearly_cp200'), 3500)
        self.assertEqual(payslip._rule_parameter('bike_exempt_reimbursement_per_km'), 0.35)

    def test_bike_commute_allowance_yearly_cap(self):
        # The yearly cap of the lump sum bike commute allowance applies to the allowances of the whole year
        self.env.ref('l10n_be_hr_payroll.employees_salary_bike_travel').active = True
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Bike Commute Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'l10n_be_lsa_bike_travel_amount': 0.27,
            })
        yearly_cap = self.env['hr.rule.parameter']._get_parameter_from_code(
            'representation_fees_bike_travel_max_yearly', date(2026, 1, 1))
        allowances = []
        for month in (1, 2):
            payslip = self.env['hr.payslip'].create({
                'name': f'Bike Commute Payslip {month}',
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'employee_id': employee.id,
                'company_id': self.belgian_company.id,
                'version_id': employee.version_id.id,
                'date_from': date(2026, month, 1),
                'date_to': date(2026, month, 28),
            })
            payslip._set_input_value('LSA_BIKE_TRAVEL_KM', 10000)
            payslip.compute_sheet()
            payslip.action_payslip_done()
            allowances.append(sum(self._get_line(payslip, 'LSA_BIKE_TRAVEL_KM').mapped('total')))

        self.assertAlmostEqual(allowances[0], 2700, 2)
        self.assertAlmostEqual(allowances[1], yearly_cap - 2700, 2)

    def test_commute_allowances_taxed_as_commuting_reimbursements(self):
        # The lump sum commute allowances are interventions in the commuting costs: the car one is part of the taxable
        # salary with the commuting exemption of the withholding tax, the bike one is exempt up to the exempt amount
        # per kilometer, the excess being taxable.
        self.env.ref('l10n_be_hr_payroll.employees_salary_car_travel').active = True
        self.env.ref('l10n_be_hr_payroll.employees_salary_bike_travel').active = True
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Commute Allowance Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'l10n_be_lsa_car_travel_amount': 0.4,
                'l10n_be_lsa_bike_travel_amount': 0.45,
            })
        payslip = self.env['hr.payslip'].create({
            'name': 'Commute Allowance Payslip',
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
        })
        payslip.compute_sheet()
        gross = self._get_line(payslip, 'GROSS').total
        net = self._get_line(payslip, 'NET').total
        withholding = sum(self._get_line(payslip, 'PPTOTAL').mapped('total'))
        payslip._set_input_value('LSA_CAR_TRAVEL_KM', 100)
        payslip._set_input_value('LSA_BIKE_TRAVEL_KM', 100)
        payslip.compute_sheet()

        exempt_rate = self.env['hr.rule.parameter']._get_parameter_from_code('bike_exempt_reimbursement_per_km', date(2026, 1, 1))
        car = self._get_line(payslip, 'LSA_CAR_TRAVEL_KM')
        bike = self._get_line(payslip, 'LSA_BIKE_TRAVEL_KM')
        bike_taxable = self._get_line(payslip, 'LSA_BIKE_TRAVEL_KM.TAX')
        self.assertAlmostEqual(car.total, 40, 2)
        self.assertAlmostEqual(bike.total, 100 * exempt_rate, 2)
        self.assertEqual(bike.quantity, 100, "The kilometers are declared with the bike allowance")
        self.assertAlmostEqual(bike_taxable.total, 45 - 100 * exempt_rate, 2)
        self.assertFalse(sum(self._get_line(payslip, 'REP.FEES').mapped('total')), "No expenses of the employer")
        self.assertAlmostEqual(self._get_line(payslip, 'GROSS').total - gross, car.total + bike_taxable.total, 2)
        self.assertAlmostEqual(self._get_line(payslip, 'NET').total - net,
            40 + 45 - (sum(self._get_line(payslip, 'PPTOTAL').mapped('total')) - withholding), 2)
        # The car allowance is within the monthly commuting exemption of the withholding tax
        self.assertAlmostEqual(sum(self._get_line(payslip, 'PPTOTAL').mapped('total')), withholding, delta=bike_taxable.total)

    def test_bike_exempt_rate_2025(self):
        # In 2025, the bike allowances are exempt up to 0.36 euro per kilometer, the excess is taxable
        self.env.ref('l10n_be_hr_payroll.employees_salary_bike_travel').active = True
        with freeze_time('2025-01-20'):
            employee = self.create_employee({
                'name': 'Bike Employee 2025',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'l10n_be_lsa_bike_travel_amount': 0.45,
            })
            payslip = self.env['hr.payslip'].create({
                'name': 'Bike Payslip 2025',
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'employee_id': employee.id,
                'company_id': self.belgian_company.id,
                'version_id': employee.version_id.id,
                'date_from': date(2025, 1, 1),
                'date_to': date(2025, 1, 31),
            })
            payslip._set_input_value('LSA_BIKE_TRAVEL_KM', 100)
            payslip.compute_sheet()
        self.assertAlmostEqual(self._get_line(payslip, 'LSA_BIKE_TRAVEL_KM').total, 36, 2)
        self.assertAlmostEqual(self._get_line(payslip, 'LSA_BIKE_TRAVEL_KM.TAX').total, 9, 2)
