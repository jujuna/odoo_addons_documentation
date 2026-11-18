from datetime import date, datetime

from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install', 'post_install_l10n', '-at_install', 'payslip_counter')
class TestPayslipCompensatoryOvertime(TestPayrollBase, TestBelgiumCommon):
    """ Compensatory time off section of the payslip PDF. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            tz='Europe/Brussels',
        )
        cls.env.company.attendance_work_entry_type_id = cls.env.company._get_default_attendance_work_entry_type()
        cls.compensatory_type = cls.env['hr.work.entry.type'].create({
            'name': 'Compensatory Rest',
            'code': 'CTRCOMP',
            'country_id': cls.env.ref('base.be').id,
            'requires_allocation': True,
            'time_off_selectable': True,
            'leave_validation_type': 'no_validation',
        })
        cls.env['hr.time.rule'].search([]).active = False
        # Extra hours beyond the daily schedule are given back 1:1 as compensatory rest.
        cls.time_rule = cls.env['hr.time.rule'].create({
            'name': 'Give back as time off',
            'calendar_source': 'employee',
            'quantity_period': 'day',
            'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_overtime').id,
            'condition_work_entry_type_ids': [cls.env.company.attendance_work_entry_type_id.id],
            'leave_compensation_rate': 1.0,
            'allocation_type_id': cls.compensatory_type.id,
        })

    def _work_on_saturday(self, day, hours):
        """ Nothing is scheduled on a Saturday: every hour worked is extra. Badged on the
            day itself, as the allocation the hours are credited to opens when first credited.
        """
        with freeze_time(day):
            self.env['hr.attendance'].create({
                'employee_id': self.employee.id,
                'check_in': datetime(day.year, day.month, day.day, 8),
                'check_out': datetime(day.year, day.month, day.day, 8 + hours),
            })

    def _take_time_off(self, day):
        leave = self.env['hr.leave'].sudo().create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.compensatory_type.id,
            'request_date_from': day,
            'request_date_to': day,
        })
        leave.action_approve()
        return leave

    def _payslip(self):
        return self.env['hr.payslip'].create({
            'name': 'Compensatory Payslip',
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.env.company.id,
            'struct_id': self.structure.id,
            'date_from': date(2024, 7, 1),
            'date_to': date(2024, 7, 31),
        })

    def _allocate(self, days, date_to):
        allocation = self.env['hr.leave.allocation'].sudo().create({
            'name': 'Regular Compensatory Rest',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.compensatory_type.id,
            'number_of_days': days,
            'date_from': date(2024, 1, 1),
            'date_to': date_to,
        })
        allocation.action_approve()
        return allocation

    def _counters(self):
        counters = self._payslip()._l10n_be_get_report_time_off_counters()
        return (
            [[round(row[key], 2) for key in ('initial', 'previous', 'earned', 'taken', 'final')] for row in counters['time_off']],
            [[round(row[key], 2) for key in ('previous', 'earned', 'taken', 'final')] for row in counters['overtime']],
        )

    def _section(self):
        time_off, [overtime] = self._counters()
        self.assertFalse(time_off, "the credited hours are only reported under Overtime")
        return overtime

    def test_hours_earned(self):
        """Hours credited before the period open the budget, the ones of the period are earned
            at the rule's compensation rate, and the ones after the period are left out.
        """
        self._work_on_saturday(date(2024, 6, 15), 4)
        self.time_rule.leave_compensation_rate = 1.5
        self._work_on_saturday(date(2024, 7, 6), 2)
        self._work_on_saturday(date(2024, 8, 3), 5)
        self.assertEqual(self._section(), [4.0, 3.0, 0.0, 7.0])

    def test_regular_allocation_used_first(self):
        """A type both allocated and credited by the rules gets a row in each subsection.
            As in hr_holidays, the leaves draw on the regular allocation before the credits.
        """
        regular = self._allocate(1, date(2024, 12, 31)).number_of_hours
        self._work_on_saturday(date(2024, 6, 15), 8)
        taken = self._take_time_off(date(2024, 7, 8)).number_of_hours + self._take_time_off(date(2024, 7, 9)).number_of_hours
        self.assertGreater(taken, regular, "fixture relies on the leaves exceeding the regular allocation")

        time_off, overtime = self._counters()
        # initial, previous, earned, taken, final
        self.assertEqual(time_off, [[regular, regular, 0.0, regular, 0.0]])
        # previous, earned, taken, final
        self.assertEqual(overtime, [[8.0, 0.0, round(taken - regular, 2), round(8.0 - (taken - regular), 2)]])

    def test_credits_added_to_open_allocation(self):
        """The rules credit an open-ended allocation in place: its regular budget stays under
            Time Off, only the credited hours move to Overtime.
        """
        regular = self._allocate(1, False).number_of_hours
        self._work_on_saturday(date(2024, 7, 6), 4)

        time_off, overtime = self._counters()
        self.assertEqual(time_off, [[regular, regular, 0.0, 0.0, regular]])
        self.assertEqual(overtime, [[0.0, 4.0, 0.0, 4.0]])
