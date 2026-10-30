# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date

from odoo.tests import tagged
from odoo.exceptions import UserError
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
