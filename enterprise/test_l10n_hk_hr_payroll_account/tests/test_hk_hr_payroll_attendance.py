from datetime import date

from odoo.tests import tagged

from .common import TestL10NHkHrPayrollAccountCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHkHrPayrollAttendance(TestL10NHkHrPayrollAccountCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids |= cls.env.ref('hr_attendance.group_hr_attendance_user')
        cls.flexible_calendar = cls.env['resource.calendar'].create({
            'name': 'Hong Kong Flexible Calendar',
            'company_id': cls.env.company.id,
            'calendar_type': 'undefined',
            'attendance_ids': [],
        })

        cls.hk_hourly_employee = cls._setup_employee(
            country=cls.env.ref('base.hk'),
            structure_type=cls.env.ref('l10n_hk_hr_payroll.structure_type_employee_cap57'),
            resource_calendar=cls.flexible_calendar,
            contract_fields={
                'wage': 5000,
                'wage_type': 'hourly',
                'hourly_wage': 100,
                'date_version': date(2026, 1, 1),
                'contract_date_start': date(2026, 1, 1),
                'attendance_based': True,
            },
        )
        cls.hk_fixed_employee = cls._setup_employee(
            country=cls.env.ref('base.hk'),
            structure_type=cls.env.ref('l10n_hk_hr_payroll.structure_type_employee_cap57'),
            resource_calendar=cls.flexible_calendar,
            contract_fields={
                'wage': 5000,
                'date_version': date(2026, 1, 1),
                'contract_date_start': date(2026, 1, 1),
                'attendance_based': True,
            },
        )
        attendance_vals = [
            (cls.hk_hourly_employee.id, '2026-01-01 09:00:00'),
            (cls.hk_hourly_employee.id, '2026-01-02 09:00:00'),
            (cls.hk_fixed_employee.id, '2026-01-01 09:00:00'),
            (cls.hk_fixed_employee.id, '2026-01-02 07:00:00'),
        ]
        cls.env['hr.attendance'].create([  # noqa: OLS03001
            {
                'employee_id': employee_id,
                'check_in': check_in,
                'check_out': check_in[:10] + ' 17:00:00',
            }
            for employee_id, check_in in attendance_vals
        ])

    def test_hk_payslip_hourly_wage_comp_with_flexible_working_schedule(self):
        """
        Ensure that hourly wage computation works without a working schedule.
        """
        employee = self.hk_hourly_employee
        payslip = self._generate_payslip(
            date(2026, 1, 1), date(2026, 1, 31),
            employee_id=employee.id,
            version_id=employee.version_id.id,
        )

        self._validate_worked_days(payslip, {'002.00': (2, 16, 1600)})

    def test_hk_payslip_fixed_wage_comp_with_flexible_working_schedule(self):
        """
        Ensure that fixed wage computation works without a working schedule.
        """
        employee = self.hk_fixed_employee
        payslip = self._generate_payslip(
            date(2026, 1, 1), date(2026, 1, 31),
            employee_id=employee.id,
            version_id=employee.version_id.id,
        )

        self._validate_worked_days(payslip, {'002.00': (2.25, 18, 5000)})
