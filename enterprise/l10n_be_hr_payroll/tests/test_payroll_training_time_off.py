# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'training_time_off')
class TestPayrollTrainingTimeOff(TestPayrollBase, TestBelgiumCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the work entry types of the attendances must be of the company's country
        cls.env.company.country_id = cls.env.ref('base.be')
        resource_calendar = cls.env['resource.calendar'].create({
            'name': 'Test Calendar: 38 Hours/Week',
            'hours_per_day': 7.6,
            'full_time_required_hours': 38.0,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'dayofweek': dayofweek,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'work_entry_type_id': cls.env.ref('hr_work_entry.be_work_entry_type_attendance').id,
            }) for dayofweek in ['0', '1', '2', '3', '4'] for hour_from, hour_to in [(8.0, 12.0), (13.0, 16.6)]],
        })
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            resource_calendar=resource_calendar,
            version_fields={
                'name': 'A',
                'date_version': date(2024, 1, 1),
                'contract_date_start': date(2024, 1, 1),
                'contract_date_end': False,
                'wage': 4000.0,
            },
            tz='Europe/Brussels',
        )
        cls.employee.write({
            'l10n_be_fictive_hire_date': date(2024, 1, 1),
        })

    def test_training_time_off_threshold_by_school_year(self):
        # The normal wage paid for the hours of paid educational leave is capped (art. 114 of the law of
        # 22 January 1985): 3,500 EUR in the school year 2023-2024, 3,641 EUR in 2024-2025.
        for leave_day, threshold in [(date(2024, 2, 6), 3500), (date(2025, 2, 4), 3641)]:
            self.env['resource.calendar.leaves'].create({
                'name': "Educational leave",
                'calendar_id': self.resource_calendar.id,
                'company_id': self.env.company.id,
                'resource_id': self.employee.resource_id.id,
                # 8:00 - 16:36 in Brussels (winter time)
                'date_from': datetime(leave_day.year, leave_day.month, leave_day.day, 7, 0),
                'date_to': datetime(leave_day.year, leave_day.month, leave_day.day, 15, 36),
                'count_as': 'absence',
                'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_training_time_off').id,
            })
            payslip = self._generate_payslip(leave_day + relativedelta(day=1), leave_day + relativedelta(day=31))
            training = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == '024.00')
            self.assertAlmostEqual(training.number_of_hours, 7.6, places=2)
            # min(wage, threshold) at the hourly rate: threshold * 3 / (13 * 38) * 7.6
            self.assertAlmostEqual(training.amount, round(threshold * 3 / (13 * 38) * 7.6, 2), places=2)
