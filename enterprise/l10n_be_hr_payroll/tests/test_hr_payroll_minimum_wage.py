# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo import fields
from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrContractMinWage(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = date.today()

        cls.job = cls.env['hr.job'].create({
            'name': 'Test Job',
        })

        cls.employee_with_job = cls.create_employee({
            'name': 'Job Employee',
            'date_version': date(today.year - 2, 1, 1),
            'contract_date_start': date(today.year - 2, 1, 1),
            'contract_date_end': date(today.year + 2, 12, 31),
            'job_id': cls.job.id,
        })
        cls.contract_with_job = cls.employee_with_job.version_id

        cls.employee_without_job = cls.create_employee({
            'name': 'No Job Employee',
            'date_version': date(today.year - 2, 1, 1),
            'contract_date_start': date(today.year - 2, 1, 1),
            'contract_date_end': date(today.year + 2, 12, 31),
        })
        cls.contract_without_job = cls.employee_without_job.version_id

        cls.student_emp = cls.create_employee({
            'name': 'Student 19yo',
            'birthday': today - relativedelta(years=19),
            'employee_type_id': cls.env.ref('hr.contract_type_student').id,
            'date_version': date(today.year - 2, 1, 1),
            'contract_date_start': date(today.year - 2, 1, 1),
            'contract_date_end': date(today.year + 2, 12, 31),
            'job_id': cls.job.id,
        })
        cls.contract_student = cls.student_emp.version_id

    def check_warnings(self, warning_ids, warning_name, expected_employee, assertion):
        applicable_warnings = []
        for warning_id in warning_ids:
            warnings = self.env['hr.payroll.warning'].get_payroll_dashboard_warning_cards([warning_id])
            for warning in warnings:
                if warning['name'] == warning_name:
                    applicable_warnings.append(warning)
        if not expected_employee:
            self.assertEqual(applicable_warnings, [])
        else:
            self.assertEqual(expected_employee in applicable_warnings[0]['warning_records'], assertion)

    def test_above_min_wage_with_job(self):
        """
        Test that a contract above minimum wage with a job title will not show the warning
        """

        contract = self.contract_with_job
        contract.wage = 4000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_below_min_wage_with_job(self):
        """
        Test that a contract below minimum wage with a job title will show the warning
        """

        contract = self.contract_with_job
        contract.wage = 1000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

    def test_above_min_wage_no_job(self):
        """
        Test that a contract above minimum wage without a job will not show the warning
        """

        contract = self.contract_without_job
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_below_min_wage_no_job(self):
        """
        Test that a contract below minimum wage without a job will show the warning
        """

        contract = self.contract_without_job
        contract.wage = 1000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

    def test_hourly_min_wage(self):
        """
        Test that a contract with an hourly wage below the minimum will show the warning
        """

        contract = self.contract_with_job
        contract.write({
            'wage_type': 'monthly',
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'wage': 2000,
            'employee_type_id': self.env.ref('hr.contract_type_employee').id,
        })
        company_seniority = relativedelta(fields.Date.context_today(self), contract.employee_id._get_first_version_date()).years
        seniority = contract.l10n_be_scale_seniority + company_seniority
        hours_per_week = contract.resource_calendar_id.hours_per_week
        min_monthly_wage = contract._get_employee_min_wage(
            salary_scale=contract.l10n_be_salary_scale_id.code,
            company_seniority=company_seniority,
            seniority=seniority,
            wage_type='monthly',
            hours_per_week=hours_per_week,
        )
        min_hourly_wage = contract._get_employee_min_wage(
            salary_scale=contract.l10n_be_salary_scale_id.code,
            company_seniority=company_seniority,
            seniority=seniority,
            wage_type='hourly',
            hours_per_week=hours_per_week,
        )
        self.assertAlmostEqual(min_hourly_wage, (min_monthly_wage * 3) / 13 / hours_per_week, places=2)

        # Both wages below their respective minimums → warning expected
        contract.write({
            'wage_type': 'monthly',
            'wage': min_monthly_wage - 1,
        })
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

        contract.wage_type = 'hourly'
        contract.hourly_wage = min_hourly_wage - 1
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

        # Hourly wage above its minimum, but monthly wage still below → warning still expected
        contract.hourly_wage = min_hourly_wage + 1
        contract.wage_type = 'monthly'
        contract.wage = min_monthly_wage - 1
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

        # Monthly wage set above hourly min but below monthly min → still triggers warning
        # (each type must be compared against its own minimum, not the other type's)
        above_hourly_but_below_monthly = min_hourly_wage + 1
        self.assertLess(
            above_hourly_but_below_monthly,
            min_monthly_wage,
            "Precondition: the chosen wage must be below the monthly minimum to validate the comparison logic.",
        )
        contract.wage = above_hourly_but_below_monthly
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(
            warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True,
        )

        # Both wages above their respective minimums → no warning
        contract.wage = min_monthly_wage + 1
        contract.wage_type = 'hourly'
        contract.hourly_wage = min_hourly_wage + 1
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_adjust_wages_keeps_new_version_in_active_contract(self):
        """ Test that adjusting wages must create a new version inside the active contract (not starting a new). """
        employee = self.employee_with_job
        original_version = self.contract_with_job

        # Set wage below CP200 minimum for triggering the warning's adjust action.
        original_version.wage = 1000
        original_start = original_version.contract_date_start
        original_end = original_version.contract_date_end

        employee.l10n_be_action_adjust_min_wages()

        # The new active version must inherit the active contract's boundaries.
        new_version = employee.version_id
        self.assertNotEqual(new_version, original_version, "A new version must be created by the adjust-wages action.")
        self.assertEqual(new_version.contract_date_start, original_start, "The new version must inherit the active contract's start date.")
        self.assertEqual(new_version.contract_date_end, original_end, "The new version must inherit the active contract's end date (no new contract).")
        self.assertEqual(original_version.contract_date_end, original_end, "The previous version's contract_date_end must remain unchanged (not terminated to yesterday).")

    def test_student_above_min_wage(self):
        """
        Test that a contract above minimum wage with a job title will not show the warning
        """

        contract = self.contract_student
        contract.wage = 4000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_student_below_min_wage(self):
        """
        Test that a contract below minimum wage with a job title will show the warning
        """

        contract = self.contract_student
        contract.wage = 1000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

    def test_student_without_salary_scale(self):
        """
        Test that a contract without a salary scale for a student will not show the warning, even if the wage is below the minimum for their age
        """

        self.student_emp.l10n_be_salary_scale_id = None
        contract = self.contract_student
        contract.wage = 1000
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_not_applicable_salary_scale(self):
        """
        Test that a contract with the "Not Applicable" salary scale has no minimum wage, hence no warning
        """
        self.employee_without_job.l10n_be_salary_scale_id = self.env.ref('l10n_be_hr_payroll.salary_scale_na')
        contract = self.contract_without_job
        contract.wage = 1000
        self.assertEqual(contract._get_l10n_be_min_wage(), (0, False, 0))
        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_equal_min_wage_no_warning(self):
        """
        Test that a contract with wage exactly equal to the minimum wage does not show the warning
        """
        contract = self.contract_with_job
        min_wage, _, _ = contract._get_l10n_be_min_wage()
        contract.wage = min_wage

        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_adjust_wage_removes_warning(self):
        """
        Test that clicking 'Adjust Wage' sets the wage to the minimum and removes the warning
        """
        contract = self.contract_with_job
        contract.wage = 1000

        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, True)

        contract.employee_id.l10n_be_action_adjust_min_wages()

        warning_ids = self.env['hr.payroll.warning'].get_payroll_dashboard_data()['warning_ids']
        self.check_warnings(warning_ids, 'Employees Under Minimum Wage', contract.employee_id, False)

    def test_min_wage_contract_template(self):
        """ A CP200 contract template (a version without employee) has the minimum of its scale without seniority. """
        template = self.env['hr.version'].create({
            'name': 'CP200 Template',
            'company_id': self.belgian_company.id,
            'structure_type_id': self.env.ref('hr.structure_type_employee_cp200').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
            'contract_date_start': date(2026, 1, 1),
            'wage': 100,
        })
        self.assertFalse(template.employee_id)
        min_wage = template._get_l10n_be_min_wage()[0]
        self.assertTrue(min_wage)
        self.assertLess(template.wage, min_wage)

    def test_flexi_min_wage_from_parameter(self):
        """ The flexi minimum hourly wage is the dated rule parameter min_hourly_wage_flexi, at the
        current date or at the start of a version starting later """
        def flexi_version(date_from, date_to):
            return self.create_employee({
                'name': f'Flexi {date_from}',
                'date_version': date_from,
                'contract_date_start': date_from,
                'contract_date_end': date_to,
                'l10n_be_dimona_category': 'flx',
                'wage_type': 'hourly',
            }).version_id

        version = flexi_version(date(2025, 6, 1), date(2025, 6, 30))
        with freeze_time('2025-06-15'):
            self.assertEqual(version._get_l10n_be_min_wage(), (11.64, 'hourly', 0))
        with freeze_time('2026-04-15'):
            self.assertEqual(version._get_l10n_be_min_wage(), (11.87, 'hourly', 0))
        future_version = flexi_version(date(2027, 2, 1), date(2027, 3, 31))
        with freeze_time('2026-09-15'):
            self.assertEqual(version._get_l10n_be_min_wage(), (12.11, 'hourly', 0))
            self.assertEqual(future_version._get_l10n_be_min_wage(), (12.11, 'hourly', 0))
            self.env['hr.rule.parameter.value'].create({
                'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_min_hourly_wage_flexi').id,
                'date_from': date(2027, 1, 1),
                'parameter_value': '12.5',
            })
            self.assertEqual(version._get_l10n_be_min_wage(), (12.11, 'hourly', 0))
            self.assertEqual(future_version._get_l10n_be_min_wage(), (12.5, 'hourly', 0))
