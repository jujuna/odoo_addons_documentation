from datetime import date
from freezegun import freeze_time

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestAnnualLeaveBalanceOM(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        work_entry_type = cls.env['hr.work.entry.type'].create({
            'name': 'Test Paid Time Off Oman',
            'code': 'TESTPTOOM',
        })
        cls.company = cls.env['res.company'].create({
            'name': 'Test Oman Company',
            'country_id': cls.env.ref('base.om').id,
            'l10n_om_annual_work_entry_type_id': work_entry_type.id,
        })
        cls.employees = cls.env['hr.employee'].with_context(tracking_disable=True).create([
            {'name': f'OM Employee {i}', 'company_id': cls.company.id} for i in range(3)
        ])
        cls.emp_departing = cls.employees[0]
        cls.emp_departing.departure_date = date(2026, 2, 28)
        allocations = cls.env['hr.leave.allocation'].create([
            {
                'employee_id': employee.id,
                'work_entry_type_id': work_entry_type.id,
                'number_of_days': number_of_days,
                'date_from': date_from,
                'date_to': date_to,
            }
            for employee in cls.employees
            for number_of_days, date_from, date_to in [
                (10, date(2026, 1, 1), date(2026, 3, 31)),
                (5, date(2026, 4, 1), date(2026, 12, 31)),
            ]
        ])
        allocations.action_approve()

    @freeze_time('2026-06-01')
    def test_balance_with_multiple_employees_and_mixed_departure_dates(self):
        """Two or more OM employees in one company must not raise 'Expected singleton'."""
        balance_per_employee = {
            employee: employee.l10n_om_remaining_annual_leave_balance
            for employee in self.employees
        }

        # Odoo evaluates the balance in hours by default (8 hours per day)
        self.assertEqual(balance_per_employee, {
            self.employees[0]: 80.0,  # 10 days * 8 hours
            self.employees[1]: 40.0,  # 5 days * 8 hours
            self.employees[2]: 40.0,  # 5 days * 8 hours
        })
