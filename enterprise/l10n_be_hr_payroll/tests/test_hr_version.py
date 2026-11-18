from datetime import date
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from odoo.tests import Form, tagged
from .common import TestPayrollCommon
from ..models.hr_version import EMPLOYER_ONSS


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPayrollHrVersion(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_company = cls.create_belgian_company()
        cls.test_200_structure = cls.env['hr.payroll.structure.type'].create({
            'name': 'CP200 BE',
        })
        cls.test_other_structure = cls.env['hr.payroll.structure.type'].create({
            'name': 'Employee',
        })

        cls.test_job = cls.env["hr.job"].create({"name": "Test Job"})

        cls.student_emp = cls.env['hr.employee'].create({
            'name': 'Student 19yo',
            'birthday': date(2026, 1, 1) - relativedelta(years=19),
            'company_id': cls.test_company.id,
            'job_id': cls.test_job.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_dimona_category': 'stu',
            'wage': 1500.0,
            'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': cls.env.ref('l10n_be_hr_payroll.cp200_b').id,
        })

        cls.departure_reason = cls.env['hr.departure.reason'].create({
            'name': 'End of Contract'
        })

        cls.worker_code_495 = cls.env.ref("l10n_be_hr_payroll.l10n_be_worker_code_00495")

        cls.worker_code_other = cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015')

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee'
        })

        cls.dimona_open = cls.env['l10n.be.dimona.declaration'].create({
            'name': 'IN Declaration',
            'date_start': date.today(),
            'company_id': cls.test_company.id,
            'date_end': False  # Open declaration
        })
        cls.dimona_closed = cls.env['l10n.be.dimona.declaration'].create({
            'name': 'OUT Declaration',
            'date_start': '2026-01-01',
            'company_id': cls.test_company.id,
            'date_end': '2026-04-17'  # Closed declaration
        })

    def check_warnings(self, warning_ids, warning_name, expected_employee, assertion):
        applicable_warnings = []
        for warning_id in warning_ids:
            warnings = self.env['hr.payroll.warning'].with_company(self.test_company).get_payroll_dashboard_warning_cards([warning_id])
            for warning in warnings:
                if warning['name'] == warning_name:
                    applicable_warnings.append(warning)
        if not expected_employee:
            self.assertEqual(applicable_warnings, [])
        elif not applicable_warnings:
            self.assertFalse(assertion)
        else:
            self.assertEqual(expected_employee in applicable_warnings[0]['warning_records'], assertion)

    def test_car_travel_amount_2026(self):
        """ The default car mileage allowance follows the monthly amounts of April, May and June 2026 """
        for today, amount in [
            ('2026-04-15', 0.4571),
            ('2026-05-15', 0.4841),
            ('2026-06-15', 0.5055),
            ('2026-07-15', 0.4440),
        ]:
            with freeze_time(today):
                employee = self.env['hr.employee'].create({'name': f'Car {today}', 'company_id': self.test_company.id})
                self.assertEqual(employee.version_id.l10n_be_lsa_car_travel_amount, amount, today)

    def test_compute_display_be_with_200_strucure(self):
        """
        Test an employee with CP200 salary structure, the scale display field should be true.
        """
        test_version_with_salary_scale = self.env['hr.version'].create({
            'name': "Emp1",
            'structure_type_id': self.test_200_structure.id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'company_id': self.test_company.id,
        })
        self.assertEqual(test_version_with_salary_scale.display_l10n_be_scale, True)

    def test_compute_display_be_without_joint_committee(self):
        """
        Test an employee with another salary structure, the scale display field should be false.
        """
        test_version_without_salary_scale = self.env['hr.version'].create({
            'name': "Emp1",
            'l10n_be_joint_committee_id': False,
            'company_id': self.test_company.id,
        })
        self.assertEqual(test_version_without_salary_scale.display_l10n_be_scale, False)

    @freeze_time('2026-01-01')
    def test_normal_employee_seniority_0_below_scale(self):
        """ Check warning triggers for a 0yrs employee with l10n_be_scale_category A minimum wage (2194.32) """
        normal_emp = self.env['hr.employee'].create({
            'name': 'Normal Employee',
            'company_id': self.test_company.id,
            'job_id': self.test_job.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'wage': 1500.0,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_a').id,
        })
        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', normal_emp, True)

    @freeze_time('2026-01-01')
    def test_normal_employee_seniority_5_above_scale(self):
        """ Check warning triggers for a 5yrs experienced employee with l10n_be_scale_category C minimum wage """
        emp_senior = self.env['hr.employee'].create({
            'name': 'Senior Employee',
            'company_id': self.test_company.id,
            'job_id': self.test_job.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'wage': 2000.0,
            'l10n_be_scale_seniority': 5,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_c').id,
        })

        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', emp_senior, True)

    @freeze_time('2026-01-01')
    def test_student19_b_below_scale_warning(self):
        """ Check warning triggers for a student earning less than the 19yo with Salary Scale - Category B minimum wage """
        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', self.student_emp, True)

    @freeze_time('2026-01-01')
    def test_student19_b_above_scale_no_warning(self):
        """ Check no warning triggers for a student earning more than the 19yo with Salary Scale - Category B minimum wage """
        self.student_emp.wage = 2100
        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', self.student_emp, False)

    @freeze_time('2026-01-01')
    def test_student18_d_below_scale_warning(self):
        """ Check warning triggers for a student earning less than the 18yo with Salary Scale - Category D minimum wage (2262.47) """
        self.student_emp.birthday = date(2026, 1, 1) - relativedelta(years=18)
        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', self.student_emp, True)

    @freeze_time('2026-01-01')
    def test_chairman_999_exclusion_no_warning(self):
        chairman_emp = self.env['hr.employee'].create({
            'name': 'The Chairman',
            'company_id': self.test_company.id,
            'job_id': self.test_job.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
            'wage': 500.0,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
        })
        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', chairman_emp, False)

    @freeze_time('2026-01-01')
    def test_sale_representative_exclusion_no_warning(self):
        sale_emp = self.env['hr.employee'].create({
            'name': 'Sale Representative',
            'company_id': self.test_company.id,
            'job_id': self.test_job.id,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'wage': 500.0,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_d').id,
            'l10n_be_is_sale_representative': True,
        })

        dashboard_data = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(dashboard_data, 'Employees Under Minimum Wage', sale_emp, False)

    def test_check_dimona_out_requirements_all_conditions_met_returns_true(self):
        """ Test: Code 495 + Open Dimona + Departure Reason Set = TRUE """
        dimona_emp = self.env["hr.employee"].create(
            {
                'name': "dimona employee",
                'company_id': self.test_company.id,
                'date_version': "2026-06-29",
                'contract_date_start': "2026-06-29",
                'l10n_be_worker_code_id': self.worker_code_495.id,
                'l10n_be_dimona_declaration_id': self.dimona_open.id,
            }
        )
        dimona_emp.departure_reason_id = self.departure_reason.id

        result = dimona_emp.version_id._check_dimona_out_requirements()
        self.assertTrue(result, "Should return True when all conditions are met.")

    def test_check_dimona_out_requirements_blue_collar_returns_true(self):
        """ Test: Code 015 + Open Dimona + Departure Reason Set = TRUE """
        dimona_emp = self.env["hr.employee"].create(
            {
                'name': "dimona employee",
                'company_id': self.test_company.id,
                'date_version': "2026-06-29",
                'contract_date_start': "2026-06-29",
                'l10n_be_worker_code_id': self.worker_code_other.id,
                'l10n_be_dimona_declaration_id': self.dimona_open.id,
            }
        )
        dimona_emp.departure_reason_id = self.departure_reason.id

        result = dimona_emp.version_id._check_dimona_out_requirements()
        self.assertTrue(result, "Any open Dimona period must be closed, whatever the worker code.")

    def test_check_dimona_out_requirements_closed_period_returns_false(self):
        """ Test: Code 495 + Dimona declared with an end date + Departure Reason Set = FALSE """
        # date_end is computed from the content of the declaration, which is empty here
        self.dimona_closed.date_end = date(2026, 4, 17)
        dimona_emp = self.env["hr.employee"].create(
            {
                'name': "dimona employee",
                'company_id': self.test_company.id,
                'date_version': "2026-01-01",
                'contract_date_start': "2026-01-01",
                'l10n_be_worker_code_id': self.worker_code_495.id,
                'l10n_be_dimona_declaration_id': self.dimona_closed.id,
            }
        )
        dimona_emp.departure_reason_id = self.departure_reason.id

        result = dimona_emp.version_id._check_dimona_out_requirements()
        self.assertFalse(result, "The end date of the period was declared with the entrance, no Dimona OUT is needed.")

    def test_check_dimona_out_requirements_no_declaration_returns_false(self):
        """ Test: Code 495 + No Dimona IN + Departure Reason Set = FALSE """
        dimona_emp = self.env["hr.employee"].create(
            {
                'name': "dimona employee",
                'company_id': self.test_company.id,
                'date_version': "2026-06-29",
                'contract_date_start': "2026-06-29",
                'l10n_be_worker_code_id': self.worker_code_495.id,
            }
        )
        dimona_emp.departure_reason_id = self.departure_reason.id

        result = dimona_emp.version_id._check_dimona_out_requirements()
        self.assertFalse(result, "There is no Dimona period to close.")

    def test_check_dimona_out_requirements_no_departure_reason_returns_false(self):
        """ Test: Code 495 + Open Dimona + NO Departure Reason = FALSE """
        dimona_emp = self.env["hr.employee"].create(
            {
                'name': "dimona employee",
                'company_id': self.test_company.id,
                'date_version': "2026-06-29",
                'contract_date_start': "2026-06-29",
                'l10n_be_worker_code_id': self.worker_code_495.id,
                'l10n_be_dimona_declaration_id': self.dimona_open.id,
            }
        )
        dimona_emp.departure_reason_id = False

        result = dimona_emp.version_id._check_dimona_out_requirements()
        self.assertFalse(result, "Should return False because employee has no departure reason set.")

    def test_dimona_name_uses_legal_names(self):
        """ A single-word employee name is enough when the legal first and last names are set """
        dimona_emp = self.env["hr.employee"].create({
            'name': "Dimona",
            'company_id': self.test_company.id,
            'l10n_be_legal_first_name': "John",
            'l10n_be_legal_last_name': "Doe",
        })
        self.assertEqual(dimona_emp._get_split_name(), ("John", "Doe"))
        issues = dimona_emp.version_id._l10n_be_dimona_issues('in')
        self.assertNotIn('- The employee name is incomplete', issues)

        dimona_emp.write({'l10n_be_legal_first_name': False, 'l10n_be_legal_last_name': False})
        issues = dimona_emp.version_id._l10n_be_dimona_issues('in')
        self.assertIn('- The employee name is incomplete', issues)

        # The fallback split and the legal name compute agree on the order
        dimona_emp.name = "John Doe"
        self.assertEqual(dimona_emp._l10n_be_split_name(), ("John", "Doe"))
        self.assertEqual(
            (dimona_emp.l10n_be_legal_first_name, dimona_emp.l10n_be_legal_last_name),
            ("John", "Doe"))

    @freeze_time('2026-01-01')
    def test_computed_seniority_batch_cp200(self):
        employees = self.env['hr.employee'].create([{
            'name': 'CP200 Employee %s' % i,
            'company_id': self.test_company.id,
            'job_id': self.test_job.id,
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'wage': 2000.0,
            'l10n_be_scale_seniority': i,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_a').id,
        } for i in range(2)])

        # 2 years of company seniority (hired 2024-01-01, today 2026-01-01) + scale seniority (0 and 1).
        self.assertEqual(employees.version_id.mapped('l10n_be_computed_seniority_years'), [2, 3])

    def test_mobility_budget_too_low(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.employee = self.employee.with_env(self.env)
        self.employee.write({
            'wage': 3000.0,
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 200.0,
        })

        messages = [issue["message"] for issue in self.employee.version_id.issues.values()]
        self.assertTrue(any(
            "Mobility Budget amount is below the minimum allowed value" in msg for msg in messages
        ))
        self.assertFalse(any(
            "Mobility Budget amount exceeds the maximum allowed value" in msg for msg in messages
        ))
        self.assertFalse(any(
            "Mobility Budget amount exceeds 20% of the yearly wage" in msg for msg in messages
        ))

    def test_mobility_budget_too_high(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.employee = self.employee.with_env(self.env)
        self.employee.write({
            'wage': 3000.0,
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 20000.0,
        })

        messages = [issue["message"] for issue in self.employee.version_id.issues.values()]
        self.assertTrue(any(
            "Mobility Budget amount exceeds 20% of the yearly wage" in msg for msg in messages
        ))
        self.assertTrue(any(
            "Mobility Budget amount exceeds the maximum allowed value" in msg for msg in messages
        ))
        self.assertFalse(any(
            "Mobility Budget amount is below the minimum allowed value" in msg for msg in messages
        ))

    def test_mobility_budget_within_limits(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.employee = self.employee.with_env(self.env)
        min_budget = self.env['hr.rule.parameter']._get_parameter_from_code('mobility_budget_min', raise_if_not_found=False) or 3233
        max_budget = self.env['hr.rule.parameter']._get_parameter_from_code('mobility_budget_max', raise_if_not_found=False) or 17244
        valid_amount = (min_budget + max_budget) / 2

        self.employee.write({
            'wage': 10000.0,
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': valid_amount,
        })

        messages = [issue["message"] for issue in (self.employee.version_id.issues or {}).values()]
        self.assertFalse(any("Mobility Budget amount is below the minimum allowed value" in msg for msg in messages))
        self.assertFalse(any("Mobility Budget amount exceeds the maximum allowed value" in msg for msg in messages))
        self.assertFalse(any("Mobility Budget amount exceeds 20% of the yearly wage" in msg for msg in messages))

    def test_occupation_weekly_days_change(self):
        employee = self.create_employee({
            'name': 'Changing schedule employee',
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
        })
        fixed = employee.version_id
        calendar = fixed.resource_calendar_id
        variable_calendar = self.env['resource.calendar'].create({
            'name': 'Variable full-time schedule',
            'company_id': employee.company_id.id,
            'calendar_type': 'variable',
            'hours_per_week': calendar.hours_per_week,
            'days_per_week': calendar.days_per_week,
            'full_time_required_hours': calendar.full_time_required_hours,
            'reference_calendar_id': calendar.id,
            'attendance_ids': [(5, 0, 0)],
        })
        variable = fixed.copy({
            'date_version': date(2025, 8, 1),
            'resource_calendar_id': variable_calendar.id,
        })
        fixed_again = fixed.copy({'date_version': date(2025, 9, 1)})
        salary_change = fixed_again.copy({'date_version': date(2025, 9, 15), 'wage': 2700})
        self.assertTrue(fixed._is_same_occupation(variable))
        variable_calendar.days_per_week = 4.5
        self.assertFalse(fixed._is_same_occupation(variable))
        self.assertFalse(variable._is_same_occupation(fixed_again))
        self.assertTrue(fixed_again._is_same_occupation(salary_change))
        groups = employee.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()
        self.assertEqual(len(groups), 3)
        self.assertEqual({frozenset(versions.ids) for versions, _start, _end in groups}, {
            frozenset(fixed.ids), frozenset(variable.ids), frozenset((fixed_again | salary_change).ids),
        })

    def test_occupation_contract_gap(self):
        """
        Contracts with the same occupation data are one occupation only without a day between them, as the day
        contracts of a flexi-job: Monday and Tuesday are one occupation, Thursday another one.
        """
        employee = self.create_employee({
            'name': 'Day contracts employee',
            'date_version': date(2025, 7, 7),
            'contract_date_start': date(2025, 7, 7),
            'contract_date_end': date(2025, 7, 7),
        })
        monday = employee.version_id
        tuesday, thursday = (employee.create_version({
            'date_version': day,
            'contract_date_start': day,
            'contract_date_end': day,
        }) for day in (date(2025, 7, 8), date(2025, 7, 10)))
        groups = employee.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()
        self.assertEqual({(frozenset(versions.ids), date_from, date_to) for versions, date_from, date_to in groups}, {
            (frozenset((monday | tuesday).ids), date(2025, 7, 7), date(2025, 7, 8)),
            (frozenset(thursday.ids), date(2025, 7, 10), date(2025, 7, 10)),
        })

    def test_yearly_costs_include_employer_onss_on_benefits(self):
        benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_housing_onss')
        version = self.employee.version_id
        version.l10n_be_dimona_category = 'oth'

        onss_rules = benefit.salary_rule_ids.filtered(
            lambda rule: self.env.ref('l10n_be_hr_payroll.ONSS_BASE') in rule.category_ids
        )
        self.assertTrue(onss_rules)
        self.assertEqual(benefit._l10n_be_get_onss_values({version: benefit}), {version: {benefit: 0.0}})
        yearly_cost_without_benefit = version.with_context(prefetch_fields=False)._get_benefits_costs()
        version.write({'housing_onss_amount': 100, 'housing_fiscal_amount': 100})
        self.assertEqual(benefit._l10n_be_get_onss_values({version: benefit}), {version: {benefit: 100.0}})
        yearly_cost_with_benefit = version._get_benefits_costs()

        self.assertEqual(benefit.cost_field, 'housing_onss_amount')
        self.assertAlmostEqual(
            yearly_cost_with_benefit - yearly_cost_without_benefit,
            100 * 12 * (1 + version._l10n_be_get_employer_onss_rate()) + 100 * 12,
        )

    def test_yearly_costs_do_not_add_employer_onss_for_no_onss_employee(self):
        version = self.employee.version_id
        # Company executive (JC 999): no ONSS
        version.employee_type_id = self.env.ref('hr.contract_type_company_executive')
        self.assertEqual(version.l10n_be_egov3_code, '999')

        yearly_cost_without_benefit = version._get_benefits_costs()
        version.write({'housing_onss_amount': 100, 'housing_fiscal_amount': 100})
        yearly_cost_with_benefit = version._get_benefits_costs()

        self.assertAlmostEqual(
            yearly_cost_with_benefit - yearly_cost_without_benefit,
            100 * 12 + 100 * 12,
        )

    def test_yearly_costs_employer_onss_on_phone_subscription(self):
        version = self.employee.version_id
        version.mobile = 0
        yearly_cost_without_benefit = version._get_benefits_costs()
        version.mobile = 30
        yearly_cost_with_benefit = version._get_benefits_costs()
        bik_phone_amount = self.env['hr.rule.parameter']._get_parameter_from_code('bik_phone_sub_amount')
        self.assertEqual(bik_phone_amount, 4)
        # 12 x 30 € (cost) + 12 x 4 € (benefit in kind subject to ONSS) x employer rate (imported: 25 %)
        self.assertAlmostEqual(
            yearly_cost_with_benefit - yearly_cost_without_benefit,
            12 * 30 + 12 * 4 * 0.25,
        )

    def test_yearly_costs_imported_employer_onss_rate(self):
        # The employer rate comes from the ONSS rates imported for the employer category (010) and the
        # worker code (495): 19.88 % (basic) + 5.12 % (wage moderation)
        version = self.employee.version_id
        self.assertEqual(version.company_id.current_payroll_config_id.l10n_be_employer_category_id.dmfa_code, '010')
        self.assertEqual(version.l10n_be_worker_code_id.dmfa_code, '495')
        self.assertAlmostEqual(version._l10n_be_get_employer_onss_rate(), 0.25)
        version.write({'wage': 3000, 'mobile': 30})
        # Wage and benefits: 3000 x (13.92 + 13 x 25 %) + 12 x 30 € + 12 x 4 € x 25 %
        self.assertAlmostEqual(version.final_yearly_costs, 51882.0, places=2)

    def test_yearly_costs_employer_onss_rate_fallback(self):
        # Without imported ONSS rates (not fetched yet), the flat employer rate is used
        version = self.employee.version_id
        self.env['hr.rule.parameter'].search([('code', '=like', 'l10n_be_onss_rates_010_495_%')]).unlink()
        self.env.transaction.invalidate_ormcache()
        self.assertAlmostEqual(version._l10n_be_get_employer_onss_rate(), EMPLOYER_ONSS)
        version.write({'wage': 3000, 'mobile': 30})
        # 3000 x (13.92 + 13 x 27.14 %) + 12 x 30 € + 12 x 4 € x 27.14 %
        self.assertAlmostEqual(version.final_yearly_costs, 52717.63, places=2)

    def test_yearly_costs_recomputed_on_joint_committee_change(self):
        version = self.employee.version_id
        version.write({'wage': 3000, 'mobile': 30})
        # 3000 x (13.92 + 13 x 25 %) + 12 x 30 € + 12 x 4 € x 25 %
        self.assertAlmostEqual(version.final_yearly_costs, 51882.0, places=2)
        version.employee_type_id = self.env.ref('hr.contract_type_company_executive')
        self.assertEqual(version.l10n_be_egov3_code, '999')
        # Company executive: no ONSS, no 13th month and no double holiday pay: 12 x 3000 + 12 x 30 €
        self.assertAlmostEqual(version.final_yearly_costs, 36360.0, places=2)

    def test_wage_kept_on_joint_committee_change_in_form(self):
        # The yearly cost is recomputed in the form (onchange) and converted back to the wage on save: the
        # archived benefits (e.g. the lump sum allowances, with a default amount) must not be counted in the
        # onchange only, or the wage increases at each change.
        self.employee.write({'wage': 3000, 'mobile': 30})
        yearly_costs = self.employee.final_yearly_costs
        for joint_committee in ('l10n_be_joint_committee_124', 'l10n_be_joint_committee_200'):
            with Form(self.employee) as employee_form:
                employee_form.l10n_be_joint_committee_id = self.env.ref(f'l10n_be_hr_payroll.{joint_committee}')
            self.assertEqual(self.employee.wage, 3000)
            self.assertAlmostEqual(self.employee.final_yearly_costs, yearly_costs, places=2)

    def _create_company_car(self, driver=False):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'Test Model',
            'brand_id': brand.id,
            'default_car_value': 30000.0,
            'default_fuel_type': 'diesel',
            'default_co2': 90.0,
        })
        return self.env['fleet.vehicle'].create({
            'model_id': model.id,
            'company_id': self.employee.company_id.id,
            'car_value': 30000.0,
            'co2': 90.0,
            'driver_id': driver and driver.id,
        })

    def test_company_car_uses_company_car(self):
        version = self.employee.version_id
        version.private_car_employee_kilometer = 10
        self.assertFalse(version.transport_mode_car)
        car = self._create_company_car(self.employee.work_contact_id)
        # Set from the employee form
        self.employee.car_id = car
        self.assertTrue(version.transport_mode_car)
        self.assertEqual(version.private_car_employee_kilometer, 0)
        self.employee.car_id = False
        self.assertFalse(version.transport_mode_car)

    def test_company_car_wrong_driver_warning(self):
        warning_name = 'Company cars with wrong driver'
        other_partner = self.env['res.partner'].create({'name': 'Other Driver'})
        car = self._create_company_car(other_partner)
        self.employee.car_id = car
        # e.g. a pool car given to another driver afterwards
        car.future_driver_id = False
        self.assertEqual(car.driver_id, other_partner)

        def dashboard_records():
            warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
            cards = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards(warning_ids)
            return sum((card['warning_records'] for card in cards if card['name'] == warning_name), self.env['hr.employee'])

        def version_issues():
            version = self.employee.version_id.with_context(hr_payroll_force_compute_issue=True)
            version.invalidate_recordset(['issues'])
            version._compute_issues()
            return [issue['message'] for issue in (version.issues or {}).values()]

        message = "The employee is not set as driver or future driver of their company car"
        self.assertIn(self.employee, dashboard_records())
        self.assertIn(message, version_issues())

        car.future_driver_id = self.employee.work_contact_id
        self.assertNotIn(self.employee, dashboard_records())
        self.assertNotIn(message, version_issues())

    def _create_bike_model(self):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Test Bike Brand'})
        return self.env['fleet.vehicle.model'].create({
            'name': 'Test Bike Model',
            'brand_id': brand.id,
            'vehicle_type': 'bike',
            'default_recurring_cost_amount_depreciated': 50.0,
        })

    def test_company_bike_uses_company_bike(self):
        version = self.employee.version_id
        self.assertFalse(version.transport_mode_bike)
        bike = self.env['fleet.vehicle'].create({
            'model_id': self._create_bike_model().id,
            'company_id': self.employee.company_id.id,
        })
        # Set from the employee form: "Uses company bike" follows the company bike, which costs the employer
        self.employee.bike_id = bike
        self.assertTrue(version.transport_mode_bike)
        self.assertEqual(version.company_bike_depreciated_cost, 50.0)
        # Unticking "Uses company bike" discards the company bike
        version.transport_mode_bike = False
        self.assertFalse(version.bike_id)
        self.assertEqual(version.company_bike_depreciated_cost, 0.0)

    def test_company_bike_new_bike_requested(self):
        version = self.employee.version_id
        bike_model = self._create_bike_model()
        # New bike requested (as written by the salary configurator)
        version.write({
            'transport_mode_bike': True,
            'new_bike': True,
            'new_bike_model_id': bike_model.id,
            'bike_id': False,
        })
        self.assertEqual(version.company_bike_depreciated_cost, 50.0)
        # Recomputing "Uses company bike" keeps the model of the new bike
        version.new_bike = True
        self.assertTrue(version.transport_mode_bike)
        self.assertEqual(version.new_bike_model_id, bike_model)
        self.assertEqual(version.company_bike_depreciated_cost, 50.0)
        # The bike is delivered: the request is closed
        bike = self.env['fleet.vehicle'].create({'model_id': bike_model.id, 'company_id': self.employee.company_id.id})
        version.bike_id = bike
        self.assertTrue(version.transport_mode_bike)
        self.assertFalse(version.new_bike)
        self.assertFalse(version.new_bike_model_id)
        # No company bike anymore: nothing is requested either
        version.transport_mode_bike = False
        self.assertFalse(version.bike_id)
        self.assertFalse(version.new_bike)

    def test_bike_reimbursement_daily_cap(self):
        # CP200: 0.32 € / km from October 2026, capped at 12.80 € a day (40 km)
        version = self.employee.version_id
        version.write({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'bike_transport_employee_kilometer': 25,
        })
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(date(2026, 9, 15)), 10.80, places=2)
        self.assertAlmostEqual(version._get_bike_reimbursed_amount(date(2026, 10, 15)), 12.80, places=2)

    def test_student_eco_checks(self):
        version = self.employee.version_id
        self.assertTrue(version.eco_checks)
        version.l10n_be_dimona_category = 'stu'
        self.assertEqual(version.eco_checks, 0)
