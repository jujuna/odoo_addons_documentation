# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'sectoral_compensatory_rest')
class TestPayrollSectoralCompensatoryRest(TestPayrollBase, TestBelgiumCommon):
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
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'wage': 4000.0,
            },
            tz='Europe/Brussels',
        )

    def test_sectoral_compensatory_rest_not_paid_by_employer(self):
        # The compensatory rest days of a sectoral reduction of the working time (e.g. the 12 days of the
        # construction) are paid by a third party, Constructiv for the construction: the employer doesn't pay them,
        # they are neither remuneration nor ONSS or withholding tax basis, but still declared as service code 12 in
        # the DmfA.
        rest_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_sectoral_compensatory_rest')
        self.assertEqual(rest_type.code, '165.00')
        self.assertEqual(rest_type.dmfa_code, '12')
        self.env['resource.calendar.leaves'].create({
            'name': "Sectoral compensatory rest",
            'calendar_id': self.resource_calendar.id,
            'company_id': self.env.company.id,
            'resource_id': self.employee.resource_id.id,
            # 8:00 - 16:36 in Brussels (winter time)
            'date_from': datetime(2026, 2, 10, 7, 0),
            'date_to': datetime(2026, 2, 10, 15, 36),
            'count_as': 'absence',
            'work_entry_type_id': rest_type.id,
        })
        payslip = self._generate_payslip(date(2026, 2, 1), date(2026, 2, 28))
        rest = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == rest_type)
        self.assertAlmostEqual(rest.number_of_hours, 7.6, places=2)
        self.assertFalse(rest.is_paid)
        self.assertEqual(rest.amount, 0)
        # The day is deducted from the monthly wage at the hourly rate: 4000 * 3 / (13 * 38) * 7.6
        line_values = payslip._get_line_values(['BASIC', 'SALARY'])
        self.assertAlmostEqual(line_values['BASIC'][payslip.id]['total'], 4000 - 184.62, places=2)
        self.assertAlmostEqual(line_values['SALARY'][payslip.id]['total'], 4000 - 184.62, places=2)
