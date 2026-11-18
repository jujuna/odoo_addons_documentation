# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date

from odoo.tests import tagged
from odoo.exceptions import UserError, ValidationError
from .common import TestPayrollCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestPayrollScheduleChange(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_change_schedule_without_start_date(self):
        """
        Test Case:
        Using the "Working Schedule Change" without a contract start date on the version will cause an UserError.
        """
        today = date.today()

        new_employee = self.create_employee({
            "name": "Test employee",
            "date_version": date(today.year - 2, 1, 1),
            "contract_date_start": False,
        })

        with self.assertRaises(UserError):
            new_employee.version_id.action_work_schedule_change_wizard()

    def test_change_schedule_creates_amendments(self):
        """
        Test Case:
        A schedule change on a running contract creates amendments (a new version
        at the start date and a version reverting to the original schedule after
        the end date) but never changes the contract dates.
        """
        employee = self.create_employee({
            "name": "Test employee",
            "date_version": date(2023, 1, 1),
            "contract_date_start": date(2023, 1, 1),
            "wage": 3000,
        })
        original_version = employee.version_id
        original_calendar = original_version.resource_calendar_id
        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=original_version.id,
        ).new({
            'date_start': date(2024, 2, 1),
            'date_end': date(2024, 4, 30),
            'resource_calendar_id': self.resource_calendar_mid_time.id,
        })
        wizard.action_validate()

        versions = employee.version_ids
        self.assertEqual(versions.mapped('date_version'), [date(2023, 1, 1), date(2024, 2, 1), date(2024, 5, 1)])
        self.assertEqual(set(versions.mapped('contract_date_start')), {date(2023, 1, 1)})
        self.assertEqual(set(versions.mapped('contract_date_end')), {False})
        self.assertEqual(versions.mapped('resource_calendar_id'), original_calendar | self.resource_calendar_mid_time | original_calendar)
        self.assertEqual(versions[1].date_end, date(2024, 4, 30))
        self.assertAlmostEqual(versions[1].wage, 1500, 2)
        self.assertAlmostEqual(versions[2].wage, 3000, 2)

        # A version already exists at the start date: it is updated
        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=versions[2].id,
        ).new({
            'date_start': date(2024, 5, 1),
            'date_end': date(2024, 6, 30),
            'resource_calendar_id': self.resource_calendar_4_5.id,
        })
        wizard.action_validate()
        self.assertEqual(employee.version_ids[:3], versions)
        self.assertEqual(versions[2].resource_calendar_id, self.resource_calendar_4_5)
        self.assertAlmostEqual(versions[2].wage, 2400, 2)
        revert_version = employee.version_ids[3]
        self.assertEqual(revert_version.date_version, date(2024, 7, 1))
        self.assertEqual(revert_version.resource_calendar_id, original_calendar)
        self.assertAlmostEqual(revert_version.wage, 3000, 2)
        self.assertEqual(set(employee.version_ids.mapped('contract_date_start')), {date(2023, 1, 1)})
        self.assertEqual(set(employee.version_ids.mapped('contract_date_end')), {False})

    def test_change_schedule_without_reference_calendar(self):
        """
        Test Case:
        A schedule without reference calendar uses the company working schedule as full time,
        not the default schedule of the structure type nor no reference at all.
        """
        self.belgian_company.resource_calendar_id = self.resource_calendar
        self.env.ref('hr.structure_type_employee_cp200').default_resource_calendar_id = self.resource_calendar_4_5
        part_time_calendar = self.env['resource.calendar'].create({
            'name': 'Part time 19h',
            'company_id': self.belgian_company.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': day, 'hour_from': 8, 'hour_to': 11.8}) for day in '01234'
            ],
        })
        self.assertFalse(part_time_calendar.reference_calendar_id)
        self.assertRecordValues(part_time_calendar, [{'full_time_required_hours': 38, 'work_time_rate': 0.5}])

        employee = self.create_employee({
            "name": "Test employee",
            "date_version": date(2024, 1, 1),
            "contract_date_start": date(2024, 1, 1),
            "resource_calendar_id": part_time_calendar.id,
        })
        version = employee.version_id
        self.assertEqual(version._get_reference_calendar(), self.resource_calendar)

        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=version.id,
        ).new({
            'date_start': date(2024, 6, 1),
            'resource_calendar_id': self.resource_calendar.id,
        })
        self.assertEqual(wizard.full_resource_calendar_id, self.resource_calendar)

        occupations = employee.get_l10n_be_holiday_attest_occupations(2024)
        self.assertEqual([(o['hours_per_week'], o['reference_hours_per_week']) for o in occupations], [(19, 38)])

    def test_change_schedule_to_undefined_calendar(self):
        employee = self.create_employee({"name": "Test employee", "wage": 5000})
        # An Undefined schedule without any hours is fully flexible and keeps the full wage.
        for hours_per_week, expected_wage in [(38, 5000), (19, 2500), (0, 5000)]:
            with self.subTest(hours_per_week=hours_per_week):
                undefined_calendar = self.env['resource.calendar'].create({
                    'name': f'Undefined {hours_per_week}h/week',
                    'calendar_type': 'undefined',
                    'hours_per_week': hours_per_week,
                })
                wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
                    allowed_company_ids=self.belgian_company.ids, active_id=employee.version_id.id,
                ).new({'resource_calendar_id': undefined_calendar.id})
                self.assertAlmostEqual(wizard.wage, expected_wage, 2)

    def test_change_schedule_from_and_to_undefined_calendar(self):
        employee = self.create_employee({
            "name": "Test employee",
            "date_version": date(2024, 1, 1),
            "contract_date_start": date(2024, 1, 1),
            "wage": 5000,
        })
        original_calendar = employee.version_id.resource_calendar_id
        undefined_calendar = self.env['resource.calendar'].create({
            'name': 'Undefined 19h/week',
            'calendar_type': 'undefined',
            'hours_per_week': 19,
            'days_per_week': 5,
        })
        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=employee.version_id.id,
        ).new({'date_start': date(2024, 3, 1), 'resource_calendar_id': undefined_calendar.id})
        wizard.action_validate()
        undefined_version = employee.version_ids[-1]
        self.assertRecordValues(undefined_version, [{
            'date_version': date(2024, 3, 1), 'resource_calendar_id': undefined_calendar.id, 'wage': 2500, 'work_time_rate': 0.5,
        }])

        # Back to the full time fixed schedule: the full time wage is restored
        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=undefined_version.id,
        ).new({'date_start': date(2024, 6, 1), 'resource_calendar_id': original_calendar.id})
        self.assertAlmostEqual(wizard.full_wage, 5000, 2)
        self.assertAlmostEqual(wizard.wage, 5000, 2)

        # A Belgian version can't be on an Undefined schedule without hours: the popup refuses it
        fully_flexible_calendar = self.env['resource.calendar'].create({'name': 'Undefined', 'calendar_type': 'undefined'})
        wizard = self.env['l10n_be.hr.payroll.schedule.change.wizard'].with_context(
            allowed_company_ids=self.belgian_company.ids, active_id=undefined_version.id,
        ).new({'date_start': date(2024, 6, 1), 'resource_calendar_id': fully_flexible_calendar.id})
        with self.assertRaisesRegex(ValidationError, "Undefined without any hours"):
            wizard.action_validate()
        self.assertEqual(len(employee.version_ids), 2)
