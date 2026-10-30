# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from freezegun import freeze_time

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestSeniorityLostPeriod(TestPayrollCommon):
    """ An interruption between two contracts longer than the period configured in the
    `l10n_be_seniority_lost_period` rule parameter (1 month for CP200, 0 days for CP302)
    makes the employee lose the seniority acquired before that interruption. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fired = cls.env['hr.departure.reason'].create({
            'name': 'Fired',
            'l10n_be_reason_code': 342,
        })

    def create_cp200_employee(self, contracts):
        """ :param contracts: list of (date_start, date_end) tuples, oldest first """
        return self.create_seniority_employee(contracts)

    def create_cp302_employee(self, contracts):
        return self.create_seniority_employee(
            contracts,
            l10n_be_joint_committee_id=self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            l10n_be_salary_scale_id=self.env.ref('l10n_be_hr_payroll.cp302_5').id,
        )

    def create_seniority_employee(self, contracts, **version_values):
        """ :param contracts: list of (date_start, date_end) tuples, oldest first """
        date_start, date_end = contracts[0]
        employee = self.create_employee({
            'name': 'Seniority Employee',
            'date_version': date_start,
            'contract_date_start': date_start,
            'contract_date_end': date_end,
            **version_values,
        })
        for date_start, date_end in contracts[1:]:
            employee.create_version({
                'date_version': date_start,
                'contract_date_start': date_start,
                'contract_date_end': date_end,
                **version_values,
            })
        # `l10n_be_fictive_hire_date` is computed from the first contract date for every
        # belgian employee and it short circuits the seniority computation. Reset it so
        # that the tests below exercise the interruption logic itself.
        employee.l10n_be_fictive_hire_date = False
        return employee

    def test_seniority_start_date_short_interruption(self):
        """ CP200: an interruption of less than a month keeps the previous seniority. """
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 1, 15), False),
        ])
        self.assertEqual(employee._get_first_contract_date(), date(2020, 1, 1),
            "A 2 weeks interruption does not break the seniority.")

    def test_seniority_start_date_long_interruption(self):
        """ CP200: an interruption of more than a month resets the seniority. """
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 3, 1), False),
        ])
        self.assertEqual(employee._get_first_contract_date(), date(2021, 3, 1),
            "A 2 months interruption restarts the seniority at the new contract.")

    def test_seniority_start_date_fictive_hire_date(self):
        """ The fictive hire date set by the payroll manager always wins. """
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 3, 1), False),
        ])
        employee.l10n_be_fictive_hire_date = date(2018, 6, 1)
        self.assertEqual(employee._get_first_contract_date(), date(2018, 6, 1))

    @freeze_time('2026-01-01')
    def test_cp200_computed_seniority_kept(self):
        """ CP200 tolerates one month: the seniority still starts at the 2018 contract. """
        employee = self.create_cp200_employee([
            (date(2018, 1, 1), date(2019, 12, 31)),
            (date(2020, 1, 20), False),
        ])
        employee.version_id.l10n_be_scale_seniority = 0
        self.assertEqual(employee.version_id.l10n_be_computed_seniority_years, 8,
            "The 20 days interruption keeps the seniority acquired since 2018.")

    @freeze_time('2026-01-01')
    def test_cp200_computed_seniority_lost(self):
        """ CP200: an interruption longer than a month restarts the seniority. """
        employee = self.create_cp200_employee([
            (date(2018, 1, 1), date(2019, 12, 31)),
            (date(2023, 1, 1), False),
        ])
        employee.version_id.l10n_be_scale_seniority = 0
        self.assertEqual(employee.version_id.l10n_be_computed_seniority_years, 3,
            "Only the contract started in 2023 counts, the 2018 one is lost.")

    @freeze_time('2026-01-01')
    def test_cp302_computed_seniority_kept(self):
        """ CP302 tolerates no working day: a week end between two contracts is not an interruption. """
        # 2021-01-01 is a friday, 2021-01-04 the next monday
        employee = self.create_cp302_employee([
            (date(2020, 1, 1), date(2021, 1, 1)),
            (date(2021, 1, 4), False),
        ])
        self.assertEqual(employee.version_id.l10n_be_computed_seniority_years, 6,
            "The week end holds no working day, the seniority starts at the 2020 contract.")

    @freeze_time('2026-01-01')
    def test_cp302_computed_seniority_lost(self):
        """ CP302: a single working day of interruption restarts the seniority. """
        employee = self.create_cp302_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 2, 1), False),
        ])
        self.assertEqual(employee.version_id.l10n_be_computed_seniority_years, 4,
            "The seniority restarts at the 2021 contract.")

    def test_departure_first_contract_no_interruption(self):
        """ Without a long interruption the first contract stays the oldest one. """
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 1, 15), date(2021, 12, 31)),
            (date(2022, 1, 10), False),
        ])
        departure = self.env['hr.employee.departure'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=employee.id).create({
            'employee_id': employee.id,
            'dismissal_date': date(2022, 6, 1),
            'departure_reason_id': self.fired.id,
            'departure_description': 'Fired',
        })
        self.assertEqual(departure.l10n_be_first_contract_id, employee.version_ids[0])
        self.assertEqual(departure.l10n_be_first_contract_date, date(2020, 1, 1))

    def test_departure_first_contract_with_interruption(self):
        """ The contracts preceding a long interruption are ignored, the ones after are kept. """
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 6, 1), date(2021, 12, 31)),
            (date(2022, 1, 10), False),
        ])
        departure = self.env['hr.employee.departure'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=employee.id).create({
            'employee_id': employee.id,
            'dismissal_date': date(2022, 6, 1),
            'departure_reason_id': self.fired.id,
            'departure_description': 'Fired',
        })
        self.assertEqual(departure.l10n_be_first_contract_id, employee.version_ids[1],
            "The 5 months interruption of 2021 resets the first contract, "
            "but the 10 days one of 2022 does not.")
        self.assertEqual(departure.l10n_be_first_contract_date, date(2021, 6, 1))

    def test_departure_first_contract_date_fictive_hire_date(self):
        employee = self.create_cp200_employee([
            (date(2020, 1, 1), date(2020, 12, 31)),
            (date(2021, 6, 1), False),
        ])
        employee.l10n_be_fictive_hire_date = date(2018, 6, 1)
        departure = self.env['hr.employee.departure'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=employee.id).create({
            'employee_id': employee.id,
            'dismissal_date': date(2022, 6, 1),
            'departure_reason_id': self.fired.id,
            'departure_description': 'Fired',
        })
        self.assertEqual(departure.l10n_be_first_contract_date, date(2018, 6, 1))

    def get_fictive_hire_date_activities(self, employee):
        return employee.activity_ids.filtered(
            lambda a: a.technical_usage == 'l10n_be_hr_payroll_fictive_hiring_date_verification')

    def test_activity_scheduled_after_long_interruption(self):
        """ A new contract after a long interruption warns the user to check the fictive hire date. """
        employee = self.create_cp200_employee([(date(2020, 1, 1), date(2020, 12, 31))])
        employee.l10n_be_fictive_hire_date = date(2018, 6, 1)

        employee.create_version({
            'date_version': date(2021, 6, 1),
            'contract_date_start': date(2021, 6, 1),
        })

        activities = self.get_fictive_hire_date_activities(employee)
        self.assertEqual(len(activities), 1)
        self.assertIn('fictive hiring date', activities.note)

    def test_no_activity_after_short_interruption(self):
        """ An interruption within the tolerated period does not warn anybody. """
        employee = self.create_cp200_employee([(date(2020, 1, 1), date(2020, 12, 31))])
        employee.l10n_be_fictive_hire_date = date(2018, 6, 1)

        employee.create_version({
            'date_version': date(2021, 1, 15),
            'contract_date_start': date(2021, 1, 15),
        })

        self.assertFalse(self.get_fictive_hire_date_activities(employee))

    def test_activity_not_duplicated(self):
        """ Only one verification activity is kept at a time. """
        employee = self.create_cp200_employee([(date(2020, 1, 1), date(2020, 12, 31))])
        employee.l10n_be_fictive_hire_date = date(2018, 6, 1)

        employee.create_version({
            'date_version': date(2021, 6, 1),
            'contract_date_start': date(2021, 6, 1),
            'contract_date_end': date(2021, 12, 31),
        })
        employee.create_version({
            'date_version': date(2022, 6, 1),
            'contract_date_start': date(2022, 6, 1),
        })

        self.assertEqual(len(self.get_fictive_hire_date_activities(employee)), 1)
