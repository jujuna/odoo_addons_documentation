# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'salary_increase')
class TestSalaryIncreaseWizard(TestPayrollCommon):

    def _legal_indexation(self, employees, year):
        wizard = self.env['hr.payroll.salary.increase'].with_company(self.belgian_company).create({
            'employee_ids': employees.ids,
            'type': 'legal',
            'year': str(year),
            'increase_date': date(year, 1, 1),
        })
        wizard.action_confirm()
        return wizard

    def test_legal_indexation_2026_not_moderated(self):
        """ The wage moderation of the index ("index en centimes") only starts with the first indexation from
            1 June 2026: the indexation of January 2026 applies to the whole wage.
        """
        employee = self.create_employee({
            'name': 'Employee Above Cap',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'wage': 5000,
        })
        self._legal_indexation(employee, 2026)
        version = employee._get_version(date(2026, 1, 1))
        self.assertEqual(version.date_version, date(2026, 1, 1))
        self.assertAlmostEqual(version.wage, 5110.50, places=2)
        self.assertFalse(version.l10n_be_capped_amount)

    def test_legal_indexation_moderated_amount(self):
        """ During a moderation period, the index applies up to 2% on the reference wage capped at 4.000 €, and
            the index above 2% on the whole wage (ONSS FAQ "Index en centimes", examples and table).
        """
        wizard = self.env['hr.payroll.salary.increase'].with_company(self.belgian_company).new({'type': 'legal'})
        for wage, rate, increase in [
            (10000, 0.01, 40),
            (10000, 0.022, 100),
            (4500, 0.022, 89),
            (3000, 0.022, 66),
            (3000, 0.01, 30),
        ]:
            self.assertAlmostEqual(wizard._compute_increase_amount(wage, 4000.0, rate), increase, places=2,
                                   msg=f"{wage} indexed by {rate}")

    def test_legal_indexation_moderated_part_time(self):
        """ The reference wage compared with the cap is a full-time one: a half-time wage of 2.500 € is a full-time
            wage of 5.000 €, above the 4.000 € cap, and the moderated increase is prorated back to the half-time.
        """
        self.env['hr.rule.parameter.value'].sudo().create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_l10n_be_legal_index').id,
            'parameter_value': str({'200': (0.0221, 4000.0)}),
            'date_from': date(2027, 1, 1),
        })
        employee = self.create_employee({
            'name': 'Half-Time Employee',
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
            'resource_calendar_id': self.resource_calendar_mid_time.id,
            'wage': 2500,
        })
        self.assertAlmostEqual(employee.version_id.work_time_rate, 0.5, places=2)
        self._legal_indexation(employee, 2027)
        version = employee._get_version(date(2027, 1, 1))
        self.assertEqual(version.date_version, date(2027, 1, 1))
        # (4.000 x 2% + 5.000 x 0.21%) x 50%
        self.assertAlmostEqual(version.wage, 2545.25, places=2)

    def test_legal_indexation_future_versions(self):
        """ The versions of the contract dated after the indexation date are indexed as well. """
        employee = self.create_employee({
            'name': 'Employee With Future Version',
            'date_version': date(2025, 6, 1),
            'contract_date_start': date(2025, 6, 1),
            'wage': 3000,
        })
        future_version = employee.create_version({
            'date_version': date(2026, 3, 1),
            'wage': 3000,
        })
        self._legal_indexation(employee, 2026)
        self.assertAlmostEqual(employee._get_version(date(2026, 1, 1)).wage, 3066.30, places=2)
        self.assertAlmostEqual(future_version.wage, 3066.30, places=2)

    def test_legal_indexation_invalid_year(self):
        """ An empty or non numeric year doesn't crash the wizard. """
        employee = self.create_employee({'name': 'Employee Year', 'date_version': date(2025, 1, 1), 'contract_date_start': date(2025, 1, 1)})
        Wizard = self.env['hr.payroll.salary.increase'].with_company(self.belgian_company)
        for year in ('2026a', False):
            wizard = Wizard.new({'type': 'legal', 'year': year, 'employee_ids': employee.ids})
            self.assertEqual(wizard.rate, 0.0)
            self.assertFalse(wizard.legal_indexation_available)
        self.assertEqual(Wizard.new({'type': 'legal', 'year': '2026'}).rate, 0.0)
