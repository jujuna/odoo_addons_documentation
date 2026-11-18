from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo.tests import tagged, Form
from .common import TestPayrollCommon
from freezegun import freeze_time


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrPayrollEmployeeDepartureNotice(TestPayrollCommon):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.leaving_type_fired = self.env['hr.departure.reason'].create({
            'name': 'Fired',
            'l10n_be_reason_code': 342,
        })
        self.leaving_type_resigned = self.env['hr.departure.reason'].create({
            'name': 'Resigned',
            'l10n_be_reason_code': 343,
        })

        self.eco_unemployment_calendar_full = self.resource_calendar.copy({
            'name': 'Calendar Economic Unemployment 5 days',
            'full_time_required_hours': 38,
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '0', 'hour_from': 13, 'hour_to': 16.6, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '1', 'hour_from': 13, 'hour_to': 16.6, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '2', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '2', 'hour_from': 13, 'hour_to': 16.6, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '3', 'hour_from': 13, 'hour_to': 16.6, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '4', 'hour_from': 8, 'hour_to': 12, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id}),
                (0, 0, {'dayofweek': '4', 'hour_from': 13, 'hour_to': 16.6, 'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment').id})
            ]
        })

        self.employee_eco_unemployment = self.create_employee({
            'name': 'Employee Economic Unemployment',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 8, 30),
            'resource_calendar_id': self.eco_unemployment_calendar_full.id,
        })

        self.eco_unemployment_work_entry_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_temporary_economic_unemployement_employee')
        self.employee_eco_unemployment_leaves = self.create_employee({
            'name': 'Employee Economic Unemployment Time Off',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })
        self.employee_eco_unemployment_leaves_part_time = self.create_employee({
            'name': 'Employee Economic Unemployment Time Off Part-Time',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': self.resource_calendar_mid_time.id,
        })

    def _create_eco_unemployment_leaves(self, employee, periods):
        leaves = self.env['hr.leave'].create([{
            'employee_id': employee.id,
            'work_entry_type_id': self.eco_unemployment_work_entry_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        } for date_from, date_to in periods])
        leaves.action_approve()
        self.assertEqual(set(leaves.mapped('state')), {'validate'})
        return leaves

    def _create_departure(self, employee, dismissal_date, reason):
        return self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': dismissal_date,
            'departure_reason_id': reason.id,
            'departure_description': reason.name,
        })

    @freeze_time("2025-07-21")
    def test_notice_period_calculation_economic_unemployment_resigned(self):
        departure_eco = self.env['hr.employee.departure'].create({
            'employee_id': self.employee_eco_unemployment.id,
            'dismissal_date': '2025-07-21',
            'departure_reason_id': self.leaving_type_resigned.id,
            'departure_description': 'Resigned',
        })

        self.assertTrue(departure_eco.l10n_be_is_economic_unemployment)
        self.assertEqual(departure_eco.l10n_be_notice_duration_week_after_2014, 0)

    @freeze_time("2025-07-21")
    def test_notice_period_calculation_economic_unemployment_fired(self):
        departure_eco = self.env['hr.employee.departure'].create({
            'employee_id': self.employee_eco_unemployment.id,
            'dismissal_date': '2025-07-21',
            'departure_reason_id': self.leaving_type_fired.id,
            'departure_description': 'Fired',
        })

        self.assertTrue(departure_eco.l10n_be_is_economic_unemployment)
        self.assertTrue(departure_eco.l10n_be_notice_period_start > date(2025, 8, 30), "Notice period should start after last day of economic unemployment")
        self.assertEqual(departure_eco.l10n_be_notice_duration_week_after_2014, 6)

    def test_reference_salary_termination_fees_rule(self):
        """
        Checks that the rule Reference Salary is well computed when generating a termination payslip.
        """
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Audi'})
        model = self.env['fleet.vehicle.model'].create({'name': 'TT RS', 'brand_id': brand.id})
        car = self.env['fleet.vehicle'].create({'model_id': model.id, 'company_id': self.belgian_company.id, 'atn': 2000, 'driver_employee_id': self.employee_a.id})

        self.employee_a.version_id.write({
            'transport_mode_car': True,
            'car_id': car.id})

        departure = self.env['hr.employee.departure'].create({
            'employee_id': self.employee_a.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': '2025-07-20',
            'l10n_be_notice_respect': 'without',
            'departure_description': "Oh no you're fired",
        })
        # self.env.flush_all()
        departure.action_register()
        departure_payslips = departure._generate_termination_payslip()
        departure_payslips = self.env['hr.payslip'].search([('id', 'in', departure_payslips.ids)])
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees = departure_payslips.filtered(lambda dep: dep.struct_id == struct_id)
        termination_fees.compute_sheet()
        rules = ['YEAREND_BONUS', 'VARIABLE_SALARY', 'RESIDENCE', 'EXPATRIATE', 'BASIC2', 'PAY_VARIABLE_SALARY', 'ATN_CAR_TERM']
        self.assertEqual(sum(termination_fees.line_ids.filtered(lambda l: l.code in rules).mapped('total')),
            termination_fees.line_ids.filtered(lambda l: l.code == 'TERM_REF_SALARY').total)

    def test_withholding_taxes_termination_fees_rule(self):
        """
        Checks that the rule withholding tax is well computed when generating a termination payslip for an employee
        without children.
        Reference salary = (Gross yearly salary + year-end bonus + annual variable salary + residence allowance
        + expatriation allowance + Pay on variable salary + benefit in kind).
        In our case, Reference salary = Gross yearly salary + year-end bonus = 32300 + 2500 = 34800
        Taxable reference salary = Reference Salary - ONSS_TERM_REF (13.07 %) = 34800 - 4548.36 = 30251,64
        Withholding tax on taxable salary (30251,64) has rate of 24,92
        (source: https://www.securex.be/getattachment/eeaf8a4e-0c87-47e9-8af2-1cf41db24148/Annexe-III-AR-CIR-2026.pdf)
        Base of withholding salary is TERM_GROSS - children exoneration = TERM_GROSS - 0 = 7988.06
        24.92% of 7988.06 = 1990.6245
        """
        departure = self.env['hr.employee.departure'].create({
            'employee_id': self.employee_a.id,
            'departure_reason_id': self.env.ref('hr.departure_fired').id,
            'dismissal_date': '2025-07-20',
            'l10n_be_notice_respect': 'without',
            'departure_description': "Oh no you're fired",
        })
        departure.action_register()
        departure_payslips = departure._generate_termination_payslip()
        departure_payslips = self.env['hr.payslip'].search([('id', 'in', departure_payslips.ids)])
        struct_id = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
        termination_fees = departure_payslips.filtered(lambda dep: dep.struct_id == struct_id)
        termination_fees.compute_sheet()
        taxable_salary = termination_fees.line_ids.filtered(lambda l: l.code == 'TERM_GROSS').total
        withholding_tax = termination_fees.line_ids.filtered(lambda l: l.code == 'TERM_PP').total
        self.assertAlmostEqual(round(- (taxable_salary / 100) * 24.92, 2), withholding_tax)

    @freeze_time("2025-07-21")
    def test_notice_period_calculation_employer_fired_reasons(self):
        employer_reasons = [
            self.env.ref('l10n_be_hr_payroll.departure_fired_notice_employer'),
            self.env.ref('l10n_be_hr_payroll.departure_fired_termination_employer'),
        ]
        for reason in employer_reasons:
            departure = self.env['hr.employee.departure'].create({
                'employee_id': self.employee_test.id,
                'dismissal_date': '2025-07-21',
                'departure_reason_id': reason.id,
            })

            self.assertGreater(
                departure.l10n_be_notice_duration_week_after_2014, 0,
                f"Reason {reason.name} should calculate notice duration as Fired"
            )

    @freeze_time("2025-07-21")
    def test_notice_period_calculation_without_notice_reasons(self):
        zero_notice_reasons = [
            self.env.ref('l10n_be_hr_payroll.departure_resigned_medical_force_majeure'),
            self.env.ref('l10n_be_hr_payroll.departure_contract_end_fixed_term'),
            self.env.ref('l10n_be_hr_payroll.departure_contract_end_specific_work'),
        ]
        for reason in zero_notice_reasons:
            departure = self.env['hr.employee.departure'].create({
                'employee_id': self.employee_test.id,
                'dismissal_date': '2025-07-21',
                'departure_reason_id': reason.id,
            })

            self.assertEqual(
                departure.l10n_be_notice_duration_week_after_2014, 0,
                f"Reason {reason.name} must have 0 weeks notice duration"
            )

    @freeze_time("2025-07-21")
    def test_fixed_term_contract_updated_on_departure_create(self):
        """ Test that ending collaboration with Fixed Term reason automatically sets fixed_term = True
            on the employee version when the notice period is fully worked.
        """
        fixed_term_reason = self.env.ref('l10n_be_hr_payroll.departure_contract_end_fixed_term')

        # Ensure fixed_term is initially False
        version = self.employee_test._get_version(date(2025, 7, 21))
        self.assertFalse(version.fixed_term)

        wizard_form = Form(self.env['hr.employee.departure'].with_context(
            allowed_company_ids=self.belgian_company.ids,
            active_id=self.employee_test.id,
        ))
        wizard_form.dismissal_date = date(2025, 7, 21)
        wizard_form.departure_reason_id = fixed_term_reason
        wizard_form.save()

        # Verify fixed_term is updated to True on the version
        self.assertTrue(version.fixed_term)

    @freeze_time("2025-07-21")
    def test_departure_not_archived_by_default(self):
        """ A Belgian departure keeps "Don't archive" unless an archive date is set. """
        departure_form = Form(self.env['hr.employee.departure'].with_context(
            allowed_company_ids=self.belgian_company.ids,
            active_id=self.employee_test.id,
        ))
        departure_form.dismissal_date = date(2025, 7, 1)
        departure_form.departure_reason_id = self.leaving_type_resigned
        departure_form.departure_date = date(2025, 7, 15)
        self.assertFalse(departure_form.action_date)
        departure = departure_form.save()
        self.assertFalse(departure._get_departures_to_archive())

    @freeze_time("2025-07-21")
    def test_fixed_term_contract_updated_on_action_register(self):
        """ Test that registering an end of collaboration with a Fixed Term reason ensures the
            employee version is flagged as fixed term.
        """
        fixed_term_reason = self.env.ref('l10n_be_hr_payroll.departure_contract_end_fixed_term')

        departure = self.env['hr.employee.departure'].create({
            'employee_id': self.employee_test.id,
            'dismissal_date': '2025-07-21',
            'departure_reason_id': fixed_term_reason.id,
        })

        version = self.employee_test._get_version(date(2025, 7, 21))
        # Reset value to False to test explicit execution of action_register
        version.sudo().write({'fixed_term': False})

        departure.action_register()

        self.assertTrue(version.fixed_term)

    def test_departure_without_dismissal_date(self):
        Departure = self.env['hr.employee.departure'].with_context(
            default_employee_id=self.employee_a.id,
        )
        departure_form = Form(Departure)
        departure_form.departure_reason_id = self.env.ref('hr.departure_fired')
        departure_form.dismissal_date = False

    @freeze_time("2026-10-01")
    def test_notice_period_regime_with_amendment_after_august_2026(self):
        """ The notice regime applicable from 01/08/2026 depends on the start of
            the employment, not on the start of the current amendment.
        """
        employee = self.create_employee({
            'name': 'Employee Hired Before August 2026',
            'date_version': date(2026, 6, 1),
            'contract_date_start': date(2026, 6, 1),
        })
        employee.create_version({
            'date_version': date(2026, 9, 1),
            'wage': 3000,
        })
        self.assertEqual(employee.current_version_id.date_start, date(2026, 9, 1))
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-10-01',
            'departure_reason_id': self.leaving_type_fired.id,
        })
        self.assertEqual(departure.l10n_be_first_contract_date, date(2026, 6, 1))
        # 4 months of seniority: 4 weeks with the regime before 01/08/2026 (1 week after)
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 4)

    @freeze_time("2026-11-02")
    def test_notice_period_fired_capped_after_august_2026(self):
        """ The notice given by the employer for an employment started from 01/08/2026 is capped
            at 52 weeks, whatever the seniority recognized at hiring.
        """
        for date_start, scale_seniority, expected_weeks in [
            (date(2026, 8, 3), 20, 52),  # 62 weeks without the cap
            (date(2026, 8, 3), 30, 52),  # beyond the table: 72 weeks without the cap
            (date(2026, 8, 3), 16, 51),  # below the cap
            (date(2026, 8, 1), 20, 52),  # the cap applies from 01/08/2026 included
        ]:
            employee = self.create_employee({
                'name': f'Employee {date_start} {scale_seniority} years',
                'date_version': date_start,
                'contract_date_start': date_start,
                'l10n_be_scale_seniority': scale_seniority,
            })
            departure = self._create_departure(employee, date(2026, 11, 2), self.leaving_type_fired)
            self.assertEqual(
                departure.l10n_be_notice_duration_week_after_2014, expected_weeks,
                f'Started on {date_start} with {scale_seniority} years of seniority')

    @freeze_time("2026-11-02")
    def test_notice_period_not_capped_after_august_2026(self):
        """ The 52 weeks cap neither applies to an employment started before 01/08/2026 (even with a
            fictive hire date) nor to a resignation.
        """
        employee_before = self.create_employee({
            'name': 'Employee Hired Before August 2026',
            'date_version': date(2026, 6, 1),
            'contract_date_start': date(2026, 6, 1),
            'l10n_be_scale_seniority': 20,
        })
        departure = self._create_departure(employee_before, date(2026, 11, 2), self.leaving_type_fired)
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 62)

        employee_fictive = self.create_employee({
            'name': 'Employee Fictive Hire Date',
            'date_version': date(2026, 8, 3),
            'contract_date_start': date(2026, 8, 3),
            'l10n_be_scale_seniority': 20,
        })
        employee_fictive.l10n_be_fictive_hire_date = date(2015, 1, 1)
        departure = self._create_departure(employee_fictive, date(2026, 11, 2), self.leaving_type_fired)
        self.assertEqual(departure.l10n_be_first_contract_date, date(2015, 1, 1))
        # 11 years and 10 months + 20 years: 65 weeks + 1 week per year from the 24th year
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 73)

        employee_resigned = self.create_employee({
            'name': 'Employee Resigning',
            'date_version': date(2026, 8, 3),
            'contract_date_start': date(2026, 8, 3),
            'l10n_be_scale_seniority': 20,
        })
        departure = self._create_departure(employee_resigned, date(2026, 11, 2), self.leaving_type_resigned)
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 13)

    @freeze_time("2026-12-30")
    def test_departure_date_without_notice_reasons(self):
        """ Without notice (serious misconduct, death, end of a fixed term...), the contract ends on the
            dismissal date, not on the Sunday after it.
        """
        employee = self.create_employee({
            'name': 'Employee Without Notice',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
        })
        no_notice_reasons = [
            self.env.ref('l10n_be_hr_payroll.departure_resigned_force_majeure'),
            self.env.ref('l10n_be_hr_payroll.departure_fired_serious_misconduct'),
            self.env.ref('l10n_be_hr_payroll.departure_resigned_serious_employer_misconduct'),
            self.env.ref('hr.departure_dead'),
            self.env.ref('l10n_be_hr_payroll.departure_contract_end_fixed_term'),
            self.env.ref('l10n_be_hr_payroll.departure_contract_end_specific_work'),
        ]
        for reason in no_notice_reasons:
            departure = self.env['hr.employee.departure'].create({
                'employee_id': employee.id,
                'dismissal_date': '2026-12-30',  # a Wednesday
                'departure_reason_id': reason.id,
            })
            self.assertEqual(departure.l10n_be_notice_period_start, date(2026, 12, 30), reason.name)
            self.assertEqual(departure.l10n_be_notice_period_theoretical_end, date(2026, 12, 30), reason.name)
            self.assertEqual(departure.departure_date, date(2026, 12, 30), reason.name)
            departure.unlink()

    @freeze_time("2026-10-05")
    def test_notice_period_calculation_dismissal_early_retirement(self):
        """ A dismissal in view of the unemployment with company supplement (RCC) follows the normal rules of a
            dismissal by the employer: Part I + Part II and the 3 working days of the registered letter.
        """
        employee = self.create_employee({
            'name': 'Employee RCC',
            'date_version': date(2010, 3, 1),
            'contract_date_start': date(2010, 3, 1),
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-10-05',  # a Monday
            'departure_reason_id': self.env.ref('l10n_be_hr_payroll.departure_fired_early_retirement').id,
        })
        self.assertTrue(departure.l10n_be_salary_visibility)
        # 3 years and 10 months before 2014, salary > 32.254 €: 1 month per started year, 3 months minimum
        self.assertEqual(departure.l10n_be_notice_duration_month_before_2014, 4)
        # 12 years and 9 months since 2014
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 39)
        # registered letter effective on the third working day (Thursday), notice from the next Monday
        self.assertEqual(departure.l10n_be_notice_period_start, date(2026, 10, 12))

    @freeze_time("2026-12-23")
    def test_notice_period_start_with_public_holidays(self):
        """ The registered letter takes effect on the third working day after its sending: Sundays and the public
            holidays (on their local date) aren't working days.
        """
        calendar = self.resource_calendar.copy({'name': 'Calendar With Public Holidays'})
        bank_holiday = self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday')
        self.env['resource.calendar.leaves'].create([{
            'name': 'Christmas',
            'calendar_id': calendar.id,
            'work_entry_type_id': bank_holiday.id,
            'date_from': datetime(2026, 12, 25, 7, 0),
            'date_to': datetime(2026, 12, 25, 16, 0),
        }, {
            # a whole day in Brussels starts the day before in UTC
            'name': 'Ascension',
            'calendar_id': calendar.id,
            'work_entry_type_id': bank_holiday.id,
            'date_from': datetime(2027, 5, 5, 22, 0),
            'date_to': datetime(2027, 5, 6, 21, 59, 59),
        }])
        employee = self.create_employee({
            'name': 'Employee Public Holidays',
            'tz': 'Europe/Brussels',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
            'resource_calendar_id': calendar.id,
        })
        for dismissal_date, notice_start in [
            # Thursday 24, Saturday 26, Monday 28: notice from the next Monday
            (date(2026, 12, 23), date(2027, 1, 4)),
            # Friday 7, Saturday 8, Monday 10: notice from the next Monday
            (date(2027, 5, 5), date(2027, 5, 17)),
        ]:
            departure = self.env['hr.employee.departure'].create({
                'employee_id': employee.id,
                'dismissal_date': dismissal_date,
                'departure_reason_id': self.leaving_type_fired.id,
            })
            self.assertEqual(departure.l10n_be_notice_period_start, notice_start, dismissal_date)
            departure.unlink()

    @freeze_time("2026-01-13")
    def test_termination_fees_partially_worked_notice(self):
        """ When the notice is partially worked, the indemnity covers the remaining part of the notice, to the day.
        """
        employee = self.create_employee({
            'name': 'Employee Partial Notice',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2025-12-29',
            'departure_reason_id': self.leaving_type_fired.id,
        })
        self.assertEqual(departure.l10n_be_notice_period_start, date(2026, 1, 5))
        notice_weeks = departure.l10n_be_notice_duration_week_after_2014
        departure.l10n_be_notice_respect = 'partial'
        departure.departure_date = date(2026, 1, 13)  # 9 days worked
        payslip = departure._generate_termination_payslip()
        inputs = {line.code: line.amount for line in payslip.input_line_ids}
        # notice_weeks x 7 - 9 days remain
        self.assertEqual(inputs['ND_WEEK'], notice_weeks - 2)
        self.assertEqual(inputs.get('ND_DAY', 0), 5)
        # the indemnity is due at the end of the contract
        self.assertEqual(payslip.date_from, date(2026, 1, 13))
        self.assertEqual(payslip.date_to, date(2026, 1, 13))
        self.assertEqual(departure._generate_termination_payslip(), payslip)

    @freeze_time("2026-02-23")
    def test_notice_period_seniority_at_hiring_after_2014(self):
        """ The notice of a contract started after 2013 has no Part I: the seniority recognized at hiring is
            counted with the unified table, not as seniority before 2014.
        """
        employee = self.create_employee({
            'name': 'Employee Recognized Seniority',
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
            'l10n_be_scale_seniority': 10,
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-02-23',
            'departure_reason_id': self.leaving_type_fired.id,
        })
        self.assertEqual(departure.l10n_be_notice_period_start, date(2026, 3, 2))
        self.assertFalse(departure.l10n_be_salary_visibility)
        self.assertEqual(departure.l10n_be_notice_duration_month_before_2014, 0)
        # 6 years and 2 months + 10 years: 16 years and 2 months
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 51)

    @freeze_time("2025-12-29")
    def test_notice_period_theoretical_end_part_one_in_months(self):
        """ The Part I of the notice is in calendar months, the Part II in weeks. """
        employee = self.create_employee({
            'name': 'Employee Hired In 2004',
            'date_version': date(2004, 1, 1),
            'contract_date_start': date(2004, 1, 1),
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2025-12-29',
            'departure_reason_id': self.leaving_type_fired.id,
        })
        notice_start = departure.l10n_be_notice_period_start
        self.assertEqual(notice_start, date(2026, 1, 5))
        months = departure.l10n_be_notice_duration_month_before_2014
        weeks = departure.l10n_be_notice_duration_week_after_2014
        self.assertEqual(months, 10)
        self.assertEqual(
            departure.l10n_be_notice_period_theoretical_end,
            notice_start + relativedelta(months=months, weeks=weeks, days=-1))

    @freeze_time("2026-03-02")
    def test_termination_fees_contribution_basis_part_two(self):
        """ The closing fund contribution on the termination fees (812) is only due on the part of the indemnity
            based on the seniority since 2014: the Part II of the notice, not a share of the days of service.
        """
        employee = self.create_employee({
            'name': 'Employee Hired In 2013',
            'date_version': date(2013, 1, 1),
            'contract_date_start': date(2013, 1, 1),
        })
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': '2026-03-02',
            'departure_reason_id': self.leaving_type_fired.id,
            'l10n_be_notice_respect': 'without',
        })
        departure.action_register()
        # 1 year of service before 2014: 3 months
        self.assertEqual(departure.l10n_be_notice_duration_month_before_2014, 3)
        weeks = departure.l10n_be_notice_duration_week_after_2014
        payslip = departure._generate_termination_payslip()
        # 3 months are 13 weeks
        self.assertAlmostEqual(payslip._get_termination_fees_contribution_basis(1000.0), 1000.0 * weeks / (13 + weeks), places=2)

    @freeze_time("2026-03-02")
    def test_outplacement_only_on_dismissal(self):
        """ The outplacement is only offered to a worker dismissed by his employer (not for serious misconduct). """
        employee = self.create_employee({
            'name': 'Employee Aged 50',
            'birthday': date(1976, 1, 1),
            'date_version': date(2020, 1, 1),
            'contract_date_start': date(2020, 1, 1),
        })
        employee.version_id.payroll_config_id.l10n_be_sector = 'private'
        for reason, outplacement in [
            (self.leaving_type_fired, 'special'),
            (self.leaving_type_resigned, False),
            (self.env.ref('l10n_be_hr_payroll.departure_fired_serious_misconduct'), False),
            (self.env.ref('hr.departure_dead'), False),
        ]:
            departure = self.env['hr.employee.departure'].create({
                'employee_id': employee.id,
                'dismissal_date': '2026-03-02',
                'departure_reason_id': reason.id,
            })
            self.assertEqual(departure.l10n_be_professional_reclassification, outplacement, reason.name)
            departure.unlink()

    def test_termination_year_end_bonus_paid_by_fund(self):
        """
        The year-end bonus of the construction workers (JC 124) is paid by Constructiv as fidelity stamps, not by the
        employer: it is not part of the remuneration of the termination fees, unlike the one of the other workers.
        """
        worker = self.create_employee({
            'name': 'Construction Worker',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'wage': 2500,
        })
        worker.version_id.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015')
        departure = self.env['hr.employee.departure'].create({
            'employee_id': worker.id,
            'departure_reason_id': self.leaving_type_fired.id,
            'dismissal_date': date(2026, 3, 2),
            'departure_date': date(2026, 4, 30),
            'departure_description': 'Fired',
        })
        version = worker.version_id
        self.assertTrue(version.is_worker())
        self.assertTrue(departure._get_termination_year_end_bonus(version, True))

        version.l10n_be_joint_committee_id = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_124')
        self.assertEqual(departure._get_termination_year_end_bonus(version, True), 0)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_resigned(self):
        """ Resignation while an approved economic unemployment time off covers the notification date: no notice
            (law of 3 July 1978, art. 51 / 77/4). Outside of the time off, the usual notice applies. """
        employee = self.employee_eco_unemployment_leaves
        self._create_eco_unemployment_leaves(employee, [(date(2025, 7, 21), date(2025, 7, 25))])

        departure_inside = self._create_departure(employee, date(2025, 7, 23), self.leaving_type_resigned)
        self.assertTrue(departure_inside.l10n_be_is_economic_unemployment)
        self.assertEqual(departure_inside.l10n_be_notice_duration_week_after_2014, 0)

        departure_inside.dismissal_date = date(2025, 7, 15)
        self.assertFalse(departure_inside.l10n_be_is_economic_unemployment)
        self.assertGreater(departure_inside.l10n_be_notice_duration_week_after_2014, 0)

        departure_outside = self._create_departure(employee, date(2025, 7, 28), self.leaving_type_resigned)
        self.assertFalse(departure_outside.l10n_be_is_economic_unemployment)
        self.assertGreater(departure_outside.l10n_be_notice_duration_week_after_2014, 0)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_not_validated(self):
        employee = self.employee_eco_unemployment_leaves
        leave = self.env['hr.leave'].create({
            'employee_id': employee.id,
            'work_entry_type_id': self.eco_unemployment_work_entry_type.id,
            'request_date_from': date(2025, 7, 21),
            'request_date_to': date(2025, 7, 25),
        })
        leave.action_refuse()
        self.assertEqual(leave.state, 'refuse')
        departure = self._create_departure(employee, date(2025, 7, 23), self.leaving_type_resigned)
        self.assertFalse(departure.l10n_be_is_economic_unemployment)
        self.assertGreater(departure.l10n_be_notice_duration_week_after_2014, 0)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_fired_no_leave(self):
        departure = self._create_departure(self.employee_eco_unemployment_leaves, date(2025, 7, 21), self.leaving_type_fired)
        self.assertFalse(departure.l10n_be_is_economic_unemployment)
        self.assertEqual(departure.l10n_be_notice_period_start, date(2025, 7, 28))
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 6)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_fired_postponed(self):
        """ The notice given by the employer starts after the last consecutive economic unemployment time off
            following the notification, the weekend between two time off does not break the period. """
        employee = self.employee_eco_unemployment_leaves
        self._create_eco_unemployment_leaves(employee, [
            (date(2025, 7, 21), date(2025, 7, 25)),
            (date(2025, 7, 28), date(2025, 8, 8)),
        ])
        departure = self._create_departure(employee, date(2025, 7, 21), self.leaving_type_fired)
        self.assertTrue(departure.l10n_be_is_economic_unemployment)
        # unemployment until Friday 8 August, then 3 calendar days (Saturday, Monday, Tuesday): next Monday
        self.assertEqual(departure.l10n_be_notice_period_start, date(2025, 8, 18))
        self.assertEqual(departure.l10n_be_notice_duration_week_after_2014, 6)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_fired_not_consecutive(self):
        """ A later economic unemployment time off separated by working days does not postpone the notice. """
        employee = self.employee_eco_unemployment_leaves
        self._create_eco_unemployment_leaves(employee, [
            (date(2025, 7, 21), date(2025, 7, 25)),
            (date(2025, 8, 5), date(2025, 8, 8)),
        ])
        departure = self._create_departure(employee, date(2025, 7, 21), self.leaving_type_fired)
        self.assertTrue(departure.l10n_be_is_economic_unemployment)
        # unemployment until Friday 25 July, then 3 calendar days (Saturday, Monday, Tuesday): next Monday
        self.assertEqual(departure.l10n_be_notice_period_start, date(2025, 8, 4))

        # notification after the time off: no postponement
        departure.dismissal_date = date(2025, 7, 29)
        self.assertFalse(departure.l10n_be_is_economic_unemployment)
        self.assertEqual(departure.l10n_be_notice_period_start, date(2025, 8, 4))

    @freeze_time("2025-07-21")
    def test_economic_unemployment_leaves_part_time(self):
        """ The days off of a part-time schedule (Thursday, Friday) don't break the economic unemployment
            period. """
        employee = self.employee_eco_unemployment_leaves_part_time
        self._create_eco_unemployment_leaves(employee, [
            (date(2025, 7, 21), date(2025, 7, 23)),
            (date(2025, 7, 28), date(2025, 7, 30)),
        ])
        departure_fired = self._create_departure(employee, date(2025, 7, 22), self.leaving_type_fired)
        self.assertTrue(departure_fired.l10n_be_is_economic_unemployment)
        # unemployment until Wednesday 30 July, then 3 calendar days (Thursday, Friday, Saturday): next Monday
        self.assertEqual(departure_fired.l10n_be_notice_period_start, date(2025, 8, 4))

        departure_resigned = self._create_departure(employee, date(2025, 7, 22), self.leaving_type_resigned)
        self.assertTrue(departure_resigned.l10n_be_is_economic_unemployment)
        self.assertEqual(departure_resigned.l10n_be_notice_duration_week_after_2014, 0)

    @freeze_time("2025-07-21")
    def test_economic_unemployment_non_belgian_company(self):
        company = self.env['res.company'].create({
            'name': 'French Company',
            'country_id': self.env.ref('base.fr').id,
        })
        employee = self.env['hr.employee'].with_company(company).create({
            'name': 'French Employee',
            'company_id': company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })
        departure = self.env['hr.employee.departure'].with_company(company).create({
            'employee_id': employee.id,
            'dismissal_date': date(2025, 7, 21),
            'departure_reason_id': self.leaving_type_resigned.id,
        })
        self.assertFalse(departure.l10n_be_is_economic_unemployment)

        departure_no_date = self.env['hr.employee.departure'].new({
            'employee_id': self.employee_eco_unemployment.id,
            'departure_reason_id': self.leaving_type_resigned.id,
            'dismissal_date': False,
        })
        self.assertFalse(departure_no_date.l10n_be_is_economic_unemployment)
