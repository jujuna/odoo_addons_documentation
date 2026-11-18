# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.fields import Command
from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestWorkedDaysAmount(TestPayrollCommon):
    _minimal_payroll_setup = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.resource_calendar_40.reference_calendar_id = cls.resource_calendar_40
        cls.employee = cls.create_employee({
            'name': 'Monthly employee',
            'resource_calendar_id': cls.resource_calendar_40.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'wage': 3500.0,
        })
        cls.attendance_type = cls.env.ref('hr_work_entry.be_work_entry_type_attendance')
        cls.paid_leave_type = cls.env['hr.work.entry.type'].create({
            'name': 'Paid leave', 'code': 'PAID_LEAVE_TEST',
            'count_as': 'absence', 'amount_rate': 1.0,
        })

    def _create_payslip(self, worked_days):
        """Create a draft payslip with editable worked days on the employee's 40-hour calendar."""
        version = self.employee.version_id
        # These inputs select the Belgian monthly formula used by the expected amounts below.
        self.assertEqual(version._get_contract_wage(), 3500)
        self.assertEqual(version.work_time_rate, 1)
        self.assertRecordValues(version.resource_calendar_id, [{
            'calendar_type': 'fixed', 'hours_per_week': 40, 'hours_per_day': 8,
        }])
        self.assertRecordValues(self.attendance_type, [{
            'code': '002.00', 'amount_rate': 1, 'is_extra_hours': False, 'l10n_be_is_time_credit': False,
        }])
        self.assertRecordValues(self.paid_leave_type, [{
            'amount_rate': 1, 'is_extra_hours': False, 'l10n_be_is_time_credit': False,
        }])
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': version.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': date(2026, 7, 1),
            'date_to': date(2026, 7, 31),
            'worked_days_line_ids': [Command.create({
                'version_id': version.id,
                'work_entry_type_id': time_type.id,
                'number_of_hours': hours,
                'number_of_days': hours / 8,
                'sequence': sequence,
            }) for time_type, hours, sequence in worked_days],
        })
        self.assertRecordValues(payslip, [{'state': 'draft', 'edited': False, 'wage_type': 'monthly'}])
        self.assertEqual(payslip.struct_id.country_id, self.env.ref('base.be'))
        self.assertEqual(payslip.currency_id.rounding, 0.01)
        self.env.flush_all()
        return payslip

    def test_leave_rate_change_redistributes_monthly_amount(self):
        """
        July has 23 working days: one day of attendance and 22 paid leave days
        (176 hours). The leave deduction exceeds the 3,500 EUR wage by 53.85 EUR.
        At a 50% leave rate, this excess must reduce the capped 1,750 EUR leave
        payment to 1,696.15 EUR, with zero attendance amount. Changing the leave
        rate must update that monthly adjustment.
        """
        payslip = self._create_payslip([
            (self.attendance_type, 8, 10),
            (self.paid_leave_type, 176, 20),
        ])
        attendance, leave = payslip.worked_days_line_ids
        self.assertEqual(leave.amount, 3446.15)
        self.paid_leave_type.amount_rate = 0.5
        self.env.flush_all()
        self.assertEqual(attendance.amount, 0)
        self.assertEqual(leave.amount, 1696.15)

    def test_leave_rate_change_keeps_rounding_on_attendance(self):
        """
        July's 23 working days contain four paid leave days and 19 attendance
        days (152 hours). Each 8-hour leave receives 161.54 EUR and attendance
        receives 2,853.84 EUR, totalling 3,500 EUR. At a 10% leave rate, each
        leave receives 16.15 EUR. Their rounding residue must increase attendance
        to 2,853.86 EUR, giving a total of 2,918.46 EUR.
        """
        payslip = self._create_payslip([
            (self.attendance_type, 152, 10),
            *[(self.paid_leave_type, 8, 20) for _ in range(4)],
        ])
        lines = payslip.worked_days_line_ids
        attendance = lines.filtered(lambda line: line.work_entry_type_id == self.attendance_type)
        self.assertEqual(payslip.currency_id.round(sum(lines.mapped('amount'))), 3500)
        self.assertEqual(attendance.amount, 2853.84)
        self.paid_leave_type.amount_rate = 0.1
        self.env.flush_all()
        self.assertEqual((lines - attendance).mapped('amount'), [16.15] * 4)
        self.assertEqual(attendance.amount, 2853.86)
        self.assertEqual(payslip.currency_id.round(sum(lines.mapped('amount'))), 2918.46)

    def test_unpaid_days_deducted_per_day(self):
        """
        July's 23 working days contain 18 attendance days and 5 unpaid days of
        8 hours. The hourly rate is 3,500 x 3 / 13 / 40 = 20.1923 EUR (4
        decimals), so every unpaid day deducts 161.54 EUR, rounded to the cent:
        5 x 161.54 = 807.70 EUR, not 807.69 EUR (the 40 hours at once). The
        attendance pays 3,500 - 807.70 = 2,692.30 EUR.
        """
        unpaid_type = self.paid_leave_type.copy({
            'name': 'Unpaid leave',
            'code': 'UNPAID_LEAVE_TEST',
            'amount_rate': 0,
        })
        payslip = self._create_payslip([
            (self.attendance_type, 144, 10),
            (unpaid_type, 40, 20),
        ])
        attendance, unpaid = payslip.worked_days_line_ids
        self.assertRecordValues(attendance | unpaid, [
            {'is_paid': True, 'number_of_days': 18},
            {'is_paid': False, 'number_of_days': 5},
        ])
        self.assertEqual(attendance.amount, 2692.3)
        self.assertEqual(unpaid.amount, 0)

    def test_attendance_hours_change_keeps_half_month_payment(self):
        """
        July's 184 working hours are split equally between attendance and unpaid
        leave. Unpaid FTE is 50%, so the employee receives half the wage, 1,750 EUR.
        Correcting attendance from 92 hours to 84 and then back to 92 must restore
        that half-month payment, including unpaid leave in the valuation.
        """
        unpaid_type = self.paid_leave_type.copy({
            'name': 'Unpaid leave',
            'code': 'UNPAID_LEAVE_TEST',
            'amount_rate': 0,
        })
        payslip = self._create_payslip([
            (self.attendance_type, 92, 10),
            (unpaid_type, 92, 20),
        ])
        attendance, unpaid = payslip.worked_days_line_ids
        self.assertRecordValues(attendance | unpaid, [
            {'is_paid': True, 'fte': 0.5},
            {'is_paid': False, 'fte': 0.5},
        ])
        self.assertEqual(attendance.amount, 1750)
        attendance.number_of_hours = 84
        self.env.flush_all()
        self.assertEqual(attendance.amount, 1696.15)
        attendance.number_of_hours = 92
        self.env.flush_all()
        self.assertEqual(attendance.amount, 1750)
        self.assertEqual(unpaid.amount, 0)

    def test_correcting_hours_restores_the_first_remainder_line(self):
        """
        July contains two 88-hour attendance lines and one 8-hour paid leave.
        With equal attendance hours, sequence 10 receives the month's remainder
        (1,561.54 EUR); sequence 20 receives 1,776.92 EUR and leave gets 161.54 EUR.
        Temporarily increasing sequence 20 to 89 hours makes it the largest.
        Correcting it back must restore the remainder to sequence 10 and keep
        the total at 3,500 EUR.
        """
        payslip = self._create_payslip([
            (self.attendance_type, 88, 20),
            (self.attendance_type, 88, 10),
            (self.paid_leave_type, 8, 30),
        ])
        main, other, leave = payslip.worked_days_line_ids.sorted('sequence')
        self.assertEqual(main.amount, 1561.54)
        other.number_of_hours = 89
        self.env.flush_all()
        self.assertEqual(other.amount, 1561.54)
        self.assertEqual(main.amount, 1776.92)
        other.number_of_hours = 88
        self.env.flush_all()
        self.assertEqual(main.amount, 1561.54)
        self.assertEqual(other.amount, 1776.92)
        self.assertEqual(leave.amount, 161.54)
        self.assertEqual(payslip.currency_id.round(sum(payslip.worked_days_line_ids.mapped('amount'))), 3500)

    def test_rate_change_preserves_edited_and_paid_payslips(self):
        """
        A later leave-rate change must not overwrite the amounts already edited
        by a payroll officer or stored on a paid payslip. Preserve the customized
        123 EUR attendance and 456 EUR leave amounts in both cases.
        """
        for values in ({'edited': True}, {'state': 'paid'}):
            with self.subTest(values=values):
                self.paid_leave_type.amount_rate = 1
                payslip = self._create_payslip([
                    (self.attendance_type, 176, 10),
                    (self.paid_leave_type, 8, 20),
                ])
                attendance, leave = payslip.worked_days_line_ids
                payslip.write(values)
                attendance.amount = 123
                leave.amount = 456
                self.paid_leave_type.amount_rate = 0.5
                self.env.flush_all()
                self.assertEqual(attendance.amount, 123)
                self.assertEqual(leave.amount, 456)
