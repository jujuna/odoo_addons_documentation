# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_compare

from .common import TestPayrollCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestPayrollHolidayAttestOccupation(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        contract_start_date = date(2024, 1, 1)
        contract_end_date = date(2024, 12, 31)
        cls.employee_isaac = cls.create_employee(
            {
                "name": "Isaac Morris",
                "date_version": date(2024, 1, 1),
                "contract_date_start": contract_start_date,
                "contract_date_end": contract_end_date,
                "resource_calendar_id": cls.belgian_company.resource_calendar_id.id,
            }
        )
        calendar_4_days, calendar_3_days = cls.env["resource.calendar"].create(
            [
                {
                    "attendance_ids": [
                        (
                            0,
                            0,
                            {
                                "dayofweek": weekday,
                                "hour_from": hour_from,
                                "hour_to": hour_to,
                            },
                        )
                        for weekday in ["0", "1", "2", "3"]
                        for hour_from, hour_to in [(8, 12), (13, 16.6)]
                    ],
                    "name": "Standard 4d/week",
                },
                {
                    "attendance_ids": [
                        (
                            0,
                            0,
                            {
                                "dayofweek": weekday,
                                "hour_from": hour_from,
                                "hour_to": hour_to,
                            },
                        )
                        for weekday in ["0", "2", "4"]
                        for hour_from, hour_to in [(8, 12), (13, 16.6)]
                    ],
                    "name": "Standard 3d/week",
                },
            ]
        )
        cls.employee_isaac_version_may = cls.employee_isaac.create_version(
            {
                "date_version": date(2024, 5, 1),
                "contract_date_start": contract_start_date,
                "contract_date_end": contract_end_date,
                "resource_calendar_id": calendar_3_days.id,
            }
        )
        cls.employee_isaac_version_sep = cls.employee_isaac.create_version(
            {
                "date_version": date(2024, 9, 1),
                "contract_date_start": contract_start_date,
                "contract_date_end": contract_end_date,
                "resource_calendar_id": calendar_4_days.id,
            }
        )

    def _validate_holiday_attest(self, result, expected):
        errors = []

        for idx, expected_dict in enumerate(expected):
            if idx >= len(result):
                errors.append(f"{'MISSING ENTRY':>20} │ Index {idx} not found in result")
                continue

            result_dict = result[idx]

            # Check values
            for key, expected_val in expected_dict.items():
                if key not in result_dict:
                    errors.append(
                        f"{'MISSING KEY':>20} │ {key:<30} │ {expected_val!s:>15} │ {'/':>15} │"
                    )
                    continue

                real_val = result_dict[key]

                # Float-safe comparison
                if isinstance(expected_val, float):
                    if float_compare(real_val, expected_val, 2):
                        diff = round(real_val - expected_val, 2)
                        errors.append(
                            f"{'WRONG VALUE':>20} │ {key:<30} │ {expected_val:>15} │ {real_val:>15} │ {diff:>15} │"
                        )
                else:
                    if real_val != expected_val:
                        errors.append(
                            f"{'WRONG VALUE':>20} │ {key:<30} │ {expected_val!s:>15} │ {real_val!s:>15} │"
                        )

            # Check unexpected keys
            for key in result_dict:
                if key not in expected_dict:
                    errors.append(
                        f"{'UNEXPECTED KEY':>20} │ {key:<30} │ {'/':>15} │ {result_dict[key]!s:>15} │"
                    )

        # Check extra entries
        if len(result) > len(expected):
            for idx in range(len(expected), len(result)):
                errors.append(f"{'EXTRA ENTRY':>20} │ Index {idx} present in result but not expected")

        # Pretty header
        if errors:
            errors.insert(
                0,
                f"{'ERROR':>20} │ {'FIELD':<30} │ {'EXPECTED':>15} │ {'REALITY':>15} │ {'DIFF':>15} │\n"
                f"{'':>20} │ {'':<30} │ {'':>15} │ {'':>15} │ {'':>15} │"
            )
            errors.extend([
                "",
                "Full result:",
                str(result)
            ])

        self.assertEqual(len(errors), 0, "\n\n" + "\n".join(errors))

    def _create_departure(self, employee, dismissal_date, **values):
        return self.env["hr.employee.departure"].create({
            "employee_id": employee.id,
            "dismissal_date": dismissal_date,
            "l10n_be_notice_respect": "without",
            **values,
        })

    def _get_in_contract_days(self, payslips):
        """Number of days of the payslips' worked-day lines, except the out-of-contract (000.00) ones."""
        in_contract_days = payslips._get_worked_days_line_values(["000.00"], ["number_of_days"], compute_sum=True, exclude_codes=True)
        return sum(values["sum"]["number_of_days"] for values in in_contract_days.values())

    def _assert_attest_counts_worked_days(self, employee, payslips, date_start, departure_date):
        """
        A single-occupation attestation must count every in-contract (not out-of-contract) worked day of the given payslips,
        up to the departure date.
        """
        occupations = employee.get_l10n_be_holiday_attest_occupations(departure_date.year)
        self.assertEqual(len(occupations), 1)
        self.assertEqual(occupations[0]["date_end"], departure_date)

        self._validate_holiday_attest(
            [occupations[0]],
            [
                {
                    "date_start": date_start,
                    "date_end": departure_date,
                    "hours_per_week": 38.0,
                    "reference_hours_per_week": 38.0,
                    "days_per_week": 5,
                    # Including the days worked in the final, partial month up to the departure date.
                    "equivalent_days": self._get_in_contract_days(payslips),
                    "senior_youth_leaves": 0,
                    "european_leaves": 0,
                    "paid_leaves": 0,
                    "postponed_leaves": 0,
                    "attest_paid_leaves": 0,
                    "non_equivalent_days": 0,
                    "european_leaves_amount": 0,
                },
            ],
        )

    def test_holiday_attest_occupation(self):
        be_work_entry_type_unpaid_leave = self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave')
        be_work_entry_type_unjustified_reason_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_unjustified_reason')
        be_work_entry_type_unpredictable_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_unpredictable')
        be_work_entry_type_credit_time_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_credit_time')
        be_work_entry_type_youth_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_youth_time_off')
        be_work_entry_type_european_leave = self.env.ref('hr_work_entry.l10n_be_work_entry_type_european')
        be_work_entry_type_paid_leave = self.env.ref('hr_work_entry.be_work_entry_type_legal_leave')

        self.env["hr.leave.allocation"].create([
            {
                "employee_id": self.employee_isaac.id,
                "work_entry_type_id": work_entry_type.id,
                "number_of_days": 30,
                "date_from": date(2024, 1, 1),
            }
            for work_entry_type in (
                be_work_entry_type_unjustified_reason_leave,
                be_work_entry_type_youth_leave,
                be_work_entry_type_european_leave,
                be_work_entry_type_paid_leave,
                be_work_entry_type_unpredictable_leave,
            )
        ]).action_approve()

        leave_data = [
            ('unpaid leave', be_work_entry_type_unpaid_leave, datetime(2024, 1, 16), datetime(2024, 1, 27)),
            ('unjustified leave', be_work_entry_type_unjustified_reason_leave, datetime(2024, 6, 3, 6, 0, 0), datetime(2024, 6, 14, 14, 36, 0)),
            ('unpredictable leave', be_work_entry_type_unpredictable_leave, datetime(2024, 9, 27), datetime(2024, 10, 7)),
            ('credit time leave', be_work_entry_type_credit_time_leave, datetime(2024, 11, 20), datetime(2024, 11, 28)),
            ('youth leave 1', be_work_entry_type_youth_leave, datetime(2024, 2, 11), datetime(2024, 2, 19)),
            ('youth leave 2', be_work_entry_type_youth_leave, datetime(2024, 5, 11), datetime(2024, 5, 21)),
            ('youth leave 3', be_work_entry_type_youth_leave, datetime(2024, 12, 17), datetime(2024, 12, 26)),
            ('european leave 1', be_work_entry_type_european_leave, datetime(2024, 1, 1), datetime(2024, 1, 5)),
            ('european leave 2', be_work_entry_type_european_leave, datetime(2024, 7, 1), datetime(2024, 7, 6)),
            ('european leave 3', be_work_entry_type_european_leave, datetime(2024, 10, 9), datetime(2024, 10, 13)),
            ('paid leave 1', be_work_entry_type_paid_leave, datetime(2024, 1, 7), datetime(2024, 1, 12)),
            ('paid leave 2', be_work_entry_type_paid_leave, datetime(2024, 8, 5), datetime(2024, 8, 11)),
            ('paid leave 3', be_work_entry_type_paid_leave, datetime(2024, 10, 21), datetime(2024, 10, 25)),
        ]
        self.env["hr.leave"].create(
            [
                {
                    "name": name,
                    "employee_id": self.employee_isaac.id,
                    "work_entry_type_id": work_entry_type.id,
                    "request_date_from": date_from,
                    "request_date_to": date_to,
                }
                for name, work_entry_type, date_from, date_to in leave_data
            ]
        )._action_validate()
        for version, months in (
            (self.employee_isaac._get_version(date(2024, 1, 1)), [1, 2, 3, 4]),
            (self.employee_isaac_version_may, [5, 6, 7, 8]),
            (self.employee_isaac_version_sep, [9, 10, 11, 12]),
        ):
            self.create_and_validate_payslips(self.employee_isaac, 2024, months, {"version_id": version.id})

        holiday_attest_occupation = self.employee_isaac.get_l10n_be_holiday_attest_occupations(2024)
        holiday_attest_occupation_values = [
            {
                "date_start": date(2024, 1, 1),
                "hours_per_week": 38.0,
                "reference_hours_per_week": 38.0,
                "days_per_week": 5,
                "date_end": date(2024, 4, 30),
                "equivalent_days": 67.0,
                "senior_youth_leaves": 6.0,
                "european_leaves": 5.0,
                "paid_leaves": 5.0,
                "postponed_leaves": 0,
                "attest_paid_leaves": 0,
                "non_equivalent_days": 9.0,
                "european_leaves_amount": 576.92,
            },
            {
                "date_start": date(2024, 5, 1),
                "hours_per_week": 22.8,
                "reference_hours_per_week": 38.0,
                "days_per_week": 3,
                "date_end": date(2024, 8, 31),
                "equivalent_days": 40.0,
                "senior_youth_leaves": 4.0,
                "european_leaves": 3.0,
                "paid_leaves": 3.0,
                "postponed_leaves": 0,
                "attest_paid_leaves": 0,
                "non_equivalent_days": 6.0,
                "european_leaves_amount": 576.92,
            },
            {
                "date_start": date(2024, 9, 1),
                "hours_per_week": 30.4,
                "reference_hours_per_week": 38.0,
                "days_per_week": 4,
                "date_end": date(2024, 12, 31),
                "equivalent_days": 50.0,
                "senior_youth_leaves": 7.0,
                "european_leaves": 2.0,
                "paid_leaves": 4.0,
                "postponed_leaves": 0,
                "attest_paid_leaves": 0,
                "non_equivalent_days": 11.0,
                "european_leaves_amount": 288.46,
            },
        ]
        self._validate_holiday_attest(holiday_attest_occupation, holiday_attest_occupation_values)

    def test_holiday_attest_mid_month_departure(self):
        """
        An employee dismissed mid-month must have that month's worked days counted on the holiday attestation.
        """
        departure_date = date(2026, 4, 16)
        employee = self.create_employee({
            "name": "April Leaver",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })

        self._create_departure(employee, departure_date)
        self.assertEqual(employee.departure_date, departure_date)
        self.assertEqual(employee.contract_date_end, departure_date)

        # A full month and the departure month
        payslips = self.create_and_validate_payslips(employee, 2026, [3, 4])

        # The April slip spans the whole month but the contract ends on the 16th, so its
        # worked days split into 002.00 (days actually worked) and 000.00 (out of contract).
        # The attestation must count the 002.00 days and ignore the out-of-contract ones.
        self.assertEqual(
            set(payslips[-1].worked_days_line_ids.mapped("code")),
            {"002.00", "000.00"},
            "April slip should carry both worked and out-of-contract days",
        )

        self._assert_attest_counts_worked_days(employee, payslips, date(2026, 1, 1), departure_date)

    def test_holiday_attest_notice_period_worked_out(self):
        """
        An employee who works out a notice period leaves mid-month, so the departure month's payslip spans beyond the
        departure date. The holiday attestation must still count the days actually worked that month and ignore the
        out-of-contract tail.
        """
        employee = self.create_employee({
            "name": "Notice Leaver",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })

        departure = self._create_departure(
            employee,
            date(2026, 4, 1),
            departure_reason_id=self.env.ref("hr.departure_fired").id,
            l10n_be_notice_respect="with",
        )
        # The wizard computes the departure date from the notice period and ends the contract on it
        departure_date = departure.departure_date
        self.assertEqual(employee.contract_date_end, departure_date)
        self.assertEqual(
            departure_date,
            date(2026, 4, 26),
            "The departure date should be on the 26th of april",
        )

        # A full month and the departure month
        payslips = self.create_and_validate_payslips(employee, 2026, [3, 4])

        self.assertIn(
            "000.00",
            set(payslips[-1].worked_days_line_ids.mapped("code")),
            "The departure-month slip should carry out-of-contract days after the departure date",
        )

        self._assert_attest_counts_worked_days(employee, payslips, date(2026, 1, 1), departure_date)

    def test_holiday_attest_last_payslip_generation(self):
        """
        The departure flow generates the missing departure-month payslip. With only Jan-Mar validated, the
        Holiday Attest is blocked until the April Last Payslip is generated AND validated.
        """
        departure_date = date(2026, 4, 16)
        employee = self.create_employee({
            "name": "Last Payslip Leaver",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        departure = self._create_departure(employee, departure_date)
        self.assertEqual(employee.departure_date, departure_date)
        self.assertEqual(
            employee.contract_date_end,
            departure_date,
            "Creating the departure ends the contract on the departure date",
        )

        # The month before goes through the normal flow; the departure month (April) is missing.
        march_payslip = self.create_and_validate_payslips(employee, 2026, 3)

        self.assertTrue(
            departure.l10n_be_holiday_attest_blocked_reason,
            "April (the departure month) has no validated payslip, so the period is uncovered",
        )
        with self.assertRaises(UserError):
            employee.action_generate_termination_holidays()

        # Generate the Last Payslip: a DRAFT April BEMONTHLY spanning the WHOLE month, with the
        # post-departure days (17-30 April) as unpaid out-of-contract (000.00) days.
        last_payslip = departure._generate_termination_last_payslip()
        self.assertEqual(last_payslip.state, "draft")
        self.assertEqual((last_payslip.date_from, last_payslip.date_to), (date(2026, 4, 1), date(2026, 4, 30)))
        self.assertEqual(
            set(last_payslip.worked_days_line_ids.mapped("code")),
            {"002.00", "000.00"},
            "A whole-month departure slip carries the worked days plus an out-of-contract tail",
        )
        worked_days = last_payslip._get_worked_days_line_values(["002.00"], ["number_of_days"])["002.00"][last_payslip.id]
        self.assertEqual(worked_days["number_of_days"], 12)

        self.assertTrue(
            departure.l10n_be_holiday_attest_blocked_reason,
            "A draft departure-month slip does not cover the period; the attest stays guarded",
        )
        last_payslip.action_payslip_done()

        self.assertFalse(
            departure.l10n_be_holiday_attest_blocked_reason,
            "Validating the departure-month slip covers the period and clears the guard",
        )
        self.assertIn(last_payslip, departure.l10n_be_payslip_n_ids)

        occupations = employee.get_l10n_be_holiday_attest_occupations(2026)
        self.assertEqual(len(occupations), 1)
        self.assertEqual(
            occupations[0]["equivalent_days"],
            self._get_in_contract_days(march_payslip | last_payslip),
            "Only the in-contract days count toward the attest; the out-of-contract tail is excluded",
        )
        self.assertTrue(
            employee.action_generate_termination_holidays()["domain"],
            "With the period covered, the guard no longer blocks and the attest generates",
        )

    def test_holiday_attest_future_departure_blocked(self):
        """
        A departure dated today or in the future has no validated departure-month payslip as the month isn't over and
        therefore the attest stays blocked and flagged. The rule applies regardless of whether the departure date is
        past or future.
        """
        departure_date = fields.Date.today() + relativedelta(months=2, day=15)
        employee = self.create_employee({
            "name": "Future Leaver",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "contract_date_end": departure_date,
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        departure = self._create_departure(employee, departure_date)
        self.assertEqual(employee.departure_date, departure_date)

        self.assertTrue(
            departure.l10n_be_holiday_attest_blocked_reason,
            "A future departure month has no validated payslip yet, so the period is uncovered",
        )
        self.assertTrue(
            employee.l10n_be_holiday_attest_blocked_reason,
            "The uncovered period hides the Holiday Attests button of the dropdown",
        )
        with self.assertRaises(UserError):
            employee.action_generate_termination_holidays()
        with self.assertRaises(UserError, msg="The departure month hasn't started, no last payslip can be generated yet"):
            departure._generate_termination_last_payslip()

    def test_holiday_attest_not_blocked_once_termination_documents_generated(self):
        """
        A departure whose termination documents are already generated (from a pay run, or before the database was
        used) is handled: no warning and no blocking, even without a validated departure-month payslip.
        """
        departure_date = date(2026, 4, 16)
        employee = self.create_employee({
            "name": "Handled Leaver",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        departure = self._create_departure(employee, departure_date)
        warning = self.env.ref("l10n_be_hr_payroll.hr_payroll_warning_departure_uncovered_work_period")
        versions = employee.version_id
        self.assertTrue(departure.l10n_be_holiday_attest_blocked_reason)
        self.assertEqual(warning._get_warning_python_records({"active_ids": versions.ids, "records": versions})[0], versions)

        departure.l10n_be_termination_documents_generated = True
        self.assertFalse(departure.l10n_be_holiday_attest_blocked_reason)
        self.assertFalse(employee.l10n_be_holiday_attest_blocked_reason)
        self.assertFalse(warning._get_warning_python_records({"active_ids": versions.ids, "records": versions})[0])

    def test_holiday_attest_time_credit_and_long_sick_non_effective(self):
        """
        Time-credit absences (parental time off) and long-term sickness (123.00) must land in the
        non-effective (non_equivalent_days) column, while first-year sickness (013.00) stays effective.
        """
        parental = self.env.ref("hr_work_entry.l10n_be_work_entry_type_parental_time_off")  # 147.05
        long_sick = self.env.ref("hr_work_entry.l10n_be_work_entry_type_long_sick")  # 123.00
        first_year_sick = self.env.ref("hr_work_entry.be_work_entry_type_sick_leave")  # 013.00

        employee = self.create_employee({
            "name": "Nora Timecredit",
            "date_version": date(2024, 1, 1),
            "contract_date_start": date(2024, 1, 1),
            "contract_date_end": date(2024, 12, 31),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        self.env["hr.leave.allocation"].create({
            "employee_id": employee.id,
            "work_entry_type_id": parental.id,
            "number_of_days": 30,
            "date_from": date(2024, 1, 1),
        }).action_approve()
        self.env["hr.leave"].create([
            {
                "name": name,
                "employee_id": employee.id,
                "work_entry_type_id": work_entry_type.id,
                "request_date_from": date_from,
                "request_date_to": date_to,
            }
            for name, work_entry_type, date_from, date_to in [
                ("parental time off", parental, datetime(2024, 3, 4), datetime(2024, 3, 8)),
                ("long term sick", long_sick, datetime(2024, 6, 3), datetime(2024, 6, 14)),
                ("first year sick", first_year_sick, datetime(2024, 9, 2), datetime(2024, 9, 6)),
            ]
        ])._action_validate()

        # Only the months with a leave
        payslips = self.create_and_validate_payslips(employee, 2024, [3, 6, 9])

        occupations = employee.get_l10n_be_holiday_attest_occupations(2024)
        self.assertEqual(len(occupations), 1)
        occupation = occupations[0]

        leave_codes = ("147.05", "123.00", "013.00")
        leave_days = payslips._get_worked_days_line_values(leave_codes, ["number_of_days"], compute_sum=True)
        parental_days, long_sick_days, first_year_sick_days = (leave_days[code]["sum"]["number_of_days"] for code in leave_codes)
        # Sanity: the three leaves actually materialized as worked-day lines.
        self.assertTrue(parental_days and long_sick_days and first_year_sick_days)

        self.assertEqual(
            occupation["non_equivalent_days"],
            parental_days + long_sick_days,
            "Parental time off (147.05) and long-term sickness (123.00) count as non-effective",
        )
        self.assertEqual(
            occupation["equivalent_days"],
            self._get_in_contract_days(payslips) - occupation["non_equivalent_days"],
            "First-year sickness (013.00) stays in the effective column and is not subtracted",
        )

    def test_holiday_attest_days_taken_on_certificate_and_postponed(self):
        """
        In the "vacation days already taken" table, the legal days covered by a previous employer's
        holiday certificate are reported apart from the other legal days, and postponed days have
        their own column.
        """
        legal_leave = self.env.ref("hr_work_entry.be_work_entry_type_legal_leave")  # 016.00
        postponed_n1 = self.env.ref("hr_work_entry.l10n_be_work_entry_type_postponed_paid_time_off_n1")  # 142.24

        employee = self.create_employee({
            "name": "Olivia Newhire",
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        # 3 days earned at the previous employer during the 2025 exercise
        self.env["l10n.be.holiday.attest"].create({
            "employee_id": employee.id,
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 12, 31),
            "prev_work_hours_per_week": 38,
            "prev_reference_work_hours_per_week": 38,
            "prev_work_days_per_week": 5,
            "prev_days_earned": 3,
            "prev_simple_holiday_pay_paid": 500,
            "prev_double_holiday_pay_paid": 500,
        })
        self.env["hr.leave.allocation"].create([
            {
                "employee_id": employee.id,
                "work_entry_type_id": work_entry_type.id,
                "number_of_days": 10,
                "date_from": date(2026, 1, 1),
                "date_to": date(2026, 12, 31),
            }
            for work_entry_type in (legal_leave, postponed_n1)
        ]).action_approve()
        self.env["hr.leave"].create([
            {
                "name": name,
                "employee_id": employee.id,
                "work_entry_type_id": work_entry_type.id,
                "request_date_from": date_from,
                "request_date_to": date_to,
            }
            for name, work_entry_type, date_from, date_to in [
                ("legal leave", legal_leave, datetime(2026, 2, 2), datetime(2026, 2, 6)),
                ("postponed leave", postponed_n1, datetime(2026, 3, 2), datetime(2026, 3, 3)),
            ]
        ])._action_validate()

        # Only the months with a leave
        payslips = self.create_and_validate_payslips(employee, 2026, [2, 3])
        leave_days = payslips._get_worked_days_line_values(["016.00", "142.24"], ["number_of_days"], compute_sum=True)
        self.assertEqual(leave_days["016.00"]["sum"]["number_of_days"], 5)
        self.assertEqual(leave_days["142.24"]["sum"]["number_of_days"], 2)

        occupations = employee.get_l10n_be_holiday_attest_occupations(2026)
        self.assertEqual(len(occupations), 1)
        self.assertEqual(
            (occupations[0]["paid_leaves"], occupations[0]["attest_paid_leaves"], occupations[0]["postponed_leaves"]),
            (5, 3, 2),
            "The 3 days earned on the previous employer's certificate are taken first, out of the 5 legal days",
        )

    def test_holiday_attest_reports_render(self):
        """Both holiday attests (N and N-1) of a leaver render, with the mockup's columns and rows."""
        departure_date = date(2026, 3, 13)
        employee = self.create_employee({
            "name": "Rendering Leaver",
            "date_version": date(2025, 7, 1),
            "contract_date_start": date(2025, 7, 1),
            "resource_calendar_id": self.belgian_company.resource_calendar_id.id,
        })
        departure = self._create_departure(employee, departure_date)
        # The departure month is enough: the attests only need it covered, and a contract started
        # in 2025 to generate the N-1 one.
        departure._generate_termination_last_payslip().action_payslip_done()

        holiday_payslips = self.env["hr.payslip"].search(employee.action_generate_termination_holidays()["domain"])
        self.assertEqual(set(holiday_payslips.struct_id.mapped("code")), {"BEHOLN", "BEHOLN1"})
        for payslip in holiday_payslips:
            report = "l10n_be_hr_payroll.action_report_termination_holidays_%s" % (
                "n1" if payslip.struct_id.code == "BEHOLN1" else "n"
            )
            html = str(self.env["ir.actions.report"]._render_qweb_html(report, payslip.ids)[0])
            self.assertIn("Simple holiday pay with ONSS", html)
            self.assertIn("Double holiday pay not subject to the special contribution", html)
            if payslip.struct_id.code == "BEHOLN1":
                self.assertIn("Legal holidays based on a holiday certificate / voucher", html)
                self.assertIn("Postponed vacation days", html)
                # 31/12/2025 is in ISO week 1 of 2026: a week-year format would print 31/12/2026
                self.assertIn("31/12/2025", html)
