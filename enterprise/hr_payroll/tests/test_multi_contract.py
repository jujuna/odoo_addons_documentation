# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.tests.common import tagged
from odoo.addons.hr_payroll.tests.common import TestPayslipContractBase


@tagged('payslips_multi_contract')
@tagged('at_install', '-post_install')  # LEGACY at_install
class TestPayslipMultiContract(TestPayslipContractBase):

    def test_multi_contract(self):
        start = date(2015, 11, 1)
        end = date(2015, 11, 30)

        # First contact: 40h, start of the month
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'date_from': start,
            'date_to': end,
            'version_id': self.contract_cdd.id,
            'struct_id': self.developer_pay_structure.id,
        })
        attendance_line = payslip.worked_days_line_ids[0]
        self.assertEqual(attendance_line.number_of_hours, 80)
        self.assertEqual(attendance_line.number_of_days, 10)
        OUT_of_contract_line = payslip.worked_days_line_ids[1]
        self.assertEqual(OUT_of_contract_line.number_of_hours, 88)
        self.assertEqual(OUT_of_contract_line.number_of_days, 11)

        # Second contract: 35h, end of the month
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'date_from': start,
            'date_to': end,
            'version_id': self.contract_cdi.id,
            'struct_id': self.developer_pay_structure.id,
        })
        attendance_line = payslip.worked_days_line_ids[0]
        self.assertEqual(attendance_line.number_of_hours, 77)
        self.assertEqual(attendance_line.number_of_days, 11)
        OUT_of_contract_line = payslip.worked_days_line_ids[1]
        self.assertEqual(OUT_of_contract_line.number_of_hours, 70)
        self.assertEqual(OUT_of_contract_line.number_of_days, 10)

    def test_multiple_version_per_month(self):
        """
        In the case where 2 versions have the same contract dates and where some versions are effective starting in the middle of the payslip worked day
        lines should be merged
        """
        multi_version_employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 1),
            'name': "Multi Version Employee",
            'wage': 10000
        })

        version_1 = multi_version_employee.version_id

        version_2 = multi_version_employee.create_version({
            'date_version': date(2026, 1, 15),
            'contract_date_start': date(2026, 1, 1),
            'wage': 5000
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': multi_version_employee.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        # Should have 2 attendance lines
        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # Should have 2 versions
        self.assertEqual(len(payslip.worked_days_line_ids.version_id), 2)

        version_1_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_1)
        version_2_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_2)
        self.assertEqual(version_1_worked_days.number_of_days, 10, "First version should have 10 days")
        self.assertEqual(version_2_worked_days.number_of_days, 12, "Second version should have 12 days")

    def test_multiple_version_per_month_different_contract_dates(self):
        multi_version_employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 1, 14),
            'name': "Multi Version Employee",
            'wage': 10000
        })

        version_1 = multi_version_employee.version_id

        version_2 = multi_version_employee.create_version({
            'date_version': date(2026, 1, 15),
            'contract_date_start': date(2026, 1, 15),
            'wage': 5000
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': multi_version_employee.id,
            'version_id': version_1.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        # Should have 2 attendance lines (Attendance + 000.00)
        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # Should have 1 versions
        self.assertEqual(len(payslip.worked_days_line_ids.version_id), 1)

        version_1_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_1 and w.work_entry_type_id.code == '002.00')
        version_1_OUT_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_1 and w.work_entry_type_id.code == '000.00')

        version_2_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_2)

        self.assertEqual(version_1_worked_days.number_of_days, 10, "First version should have 10 002.00 days")
        self.assertEqual(version_1_OUT_days.number_of_days, 12, "First version should have 12 000.00 days")
        self.assertFalse(version_2_worked_days)

        payslip = self.env['hr.payslip'].create({
            'employee_id': multi_version_employee.id,
            'version_id': version_2.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        # Should have 2 attendance lines (Attendance + 000.00)
        self.assertEqual(len(payslip.worked_days_line_ids), 2)

        # Should have 1 versions
        self.assertEqual(len(payslip.worked_days_line_ids.version_id), 1)

        version_1_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_1)
        version_2_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_2 and w.work_entry_type_id.code == '002.00')
        version_2_OUT_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_2 and w.work_entry_type_id.code == '000.00')

        self.assertFalse(version_1_worked_days)
        self.assertEqual(version_2_worked_days.number_of_days, 12, "Second version should have 10 000.00 days")
        self.assertEqual(version_2_OUT_days.number_of_days, 10, "Second version should have 12 Attendance days")

    def test_multiple_version_per_month_same_contract_dates_with_OUT(self):
        multi_version_employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 5),
            'contract_date_end': date(2026, 1, 28),
            'name': "Multi Version Employee",
            'wage': 10000
        })

        version_1 = multi_version_employee.version_id

        version_2 = multi_version_employee.create_version({
            'date_version': date(2026, 1, 10),
            'contract_date_start': date(2026, 1, 5),
            'contract_date_end': date(2026, 1, 28),
            'wage': 5000
        })

        version_3 = multi_version_employee.create_version({
            'date_version': date(2026, 1, 20),
            'contract_date_start': date(2026, 1, 5),
            'contract_date_end': date(2026, 1, 28),
            'wage': 3000
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': multi_version_employee.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        # Should have 5 attendance lines (3 Attendance + 2 000.00 coming from starting and ending version)
        self.assertEqual(len(payslip.worked_days_line_ids), 5)

        # Should have 1 versions
        self.assertEqual(len(payslip.worked_days_line_ids.version_id), 3)

        version_1_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_1)
        version_2_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_2)
        version_3_worked_days = payslip.worked_days_line_ids.filtered(lambda w: w.version_id == version_3)

        self.assertEqual(len(version_1_worked_days), 2)
        self.assertEqual(len(version_2_worked_days), 1)
        self.assertEqual(len(version_3_worked_days), 2)

        version_1_WORK100 = version_1_worked_days.filtered(lambda w: w.work_entry_type_id.code == '002.00')
        version_1_OUT = version_1_worked_days.filtered(lambda w: w.work_entry_type_id.code == '000.00')

        version_2_WORK100 = version_2_worked_days.filtered(lambda w: w.work_entry_type_id.code == '002.00')
        version_2_OUT = version_2_worked_days.filtered(lambda w: w.work_entry_type_id.code == '000.00')

        version_3_WORK100 = version_3_worked_days.filtered(lambda w: w.work_entry_type_id.code == '002.00')
        version_3_OUT = version_3_worked_days.filtered(lambda w: w.work_entry_type_id.code == '000.00')

        self.assertEqual(version_1_WORK100.number_of_days, 5)
        self.assertEqual(version_1_OUT.number_of_days, 2)

        self.assertEqual(version_2_WORK100.number_of_days, 6)
        self.assertEqual(version_2_OUT.number_of_days, 0)

        self.assertEqual(version_3_WORK100.number_of_days, 7)
        self.assertEqual(version_3_OUT.number_of_days, 2)

    def test_version_rehired_during_period(self):
        """
        An employee whose contract ended before the period and who is rehired during the period
        should get the version of the new contract on a payslip created without version.
        """
        employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 2, 28),
            'name': "Rehired Employee",
            'wage': 3000,
        })
        new_version = employee.create_version({
            'date_version': date(2026, 4, 15),
            'contract_date_start': date(2026, 4, 15),
            'contract_date_end': False,
            'wage': 3000,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2026, 4, 1),
            'date_to': date(2026, 4, 30),
            'struct_id': self.developer_pay_structure.id,
        })
        self.assertEqual(payslip.version_id, new_version)
        self.assertEqual(payslip.worked_days_line_ids.version_id, new_version)

        payslip.state = 'validated'
        self.assertFalse(payslip.is_wrong_version)

    def test_multiple_version_per_month_different_calendars(self):
        """
        When the working schedule changes during the period, the hourly rate of each version
        should be computed with the working schedule of that version.
        """
        employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 1),
            'resource_calendar_id': self.calendar_40h.id,
            'name': "Part-time Employee",
            'wage': 4000,
        })
        version_1 = employee.version_id
        version_2 = employee.create_version({
            'date_version': date(2026, 1, 15),
            'resource_calendar_id': self.calendar_16h.id,
            'wage': 1600,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        lines_per_version = payslip.worked_days_line_ids.grouped('version_id')
        # January 2026: 176 hours in the 40h calendar and 69.5 hours in the 16h calendar
        self.assertAlmostEqual(lines_per_version[version_1].amount, 4000 / 176 * lines_per_version[version_1].number_of_hours, places=2)
        self.assertAlmostEqual(lines_per_version[version_2].amount, 1600 / 69.5 * lines_per_version[version_2].number_of_hours, places=2)

    def test_multiple_version_per_month_recompute_payslip(self):
        """
        Updating the wage of a version should recompute the draft payslips containing worked days
        of this version, even if it is not the main version of the payslip.
        """
        employee = self.env['hr.employee'].create({
            'date_version': date(2026, 1, 1),
            'structure_type_id': self.developer_pay_structure.type_id.id,
            'contract_date_start': date(2026, 1, 1),
            'name': "Multi Version Employee",
            'wage': 10000,
        })
        version_1 = employee.version_id
        version_2 = employee.create_version({
            'date_version': date(2026, 1, 15),
            'wage': 5000,
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'struct_id': self.developer_pay_structure.id,
        })
        self.assertEqual(payslip.version_id, version_1)
        self.assertEqual(payslip.worked_days_line_ids.version_id, version_1 | version_2)

        refreshed_payslips = self.env['hr.payslip']

        def _refresh(payslips):
            nonlocal refreshed_payslips
            refreshed_payslips |= payslips

        with patch.object(self.registry['hr.payslip'], 'action_refresh_from_work_entries', _refresh):
            version_2.wage = 6000
        self.assertEqual(refreshed_payslips, payslip)
