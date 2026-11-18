from datetime import date, timedelta

from odoo import Command
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollTimesheet(GeoPayrollCase):
    def test_valid_timesheet_is_claimed_with_frozen_work_date_rate(self):
        employee = self._make_employee('fixed_hourly', hourly_wage=10.0)
        line = self._make_timesheet(employee, hours=3.5)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = payslip.gec_settlement_ids.filtered('active_claim')
        self.assertRecordValues(settlement, [{
            'timesheet_line_id': line.id,
            'employee_id': employee.id,
            'component_code': 'timesheet_extra',
            'quantity': 3.5,
            'rate': 10.0,
            'amount': 35.0,
            'active_claim': True,
        }])

    def test_timesheet_claim_is_idempotent(self):
        employee = self._make_employee('fixed_hourly')
        self._make_timesheet(employee, hours=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        original = payslip.gec_settlement_ids.filtered('active_claim')
        payslip.compute_sheet()
        self.assertEqual(payslip.gec_settlement_ids.filtered('active_claim'), original)
        self.assertEqual(len(payslip.gec_settlement_ids), 1)

    def test_only_fully_eligible_timesheets_are_claimed(self):
        employee = self._make_employee(
            'fixed_hourly',
            timesheet_pay_start_date=self.period_start,
            worklog_ot_enabled=True,
        )
        valid = self._make_timesheet(employee, hours=2.0)
        valid |= self._make_timesheet(employee, hours=2.0, validated=False)
        ignored = self.env['account.analytic.line']
        ignored |= self._make_timesheet(employee, hours=2.0, project=self.other_project)
        ignored |= self._make_timesheet(employee, work_date=self.period_start - timedelta(days=1), hours=2.0)
        ignored |= self._make_timesheet(employee, hours=0.0)
        ignored |= self._make_timesheet(employee, hours=-1.0)
        ignored |= self._make_timesheet(employee, hours=24.01)
        ignored |= self._make_timesheet(employee, work_date=self.period_end + timedelta(days=1), hours=2.0)
        ignored |= self._make_timesheet(employee, hours=2.0, project_id=False)
        # the timesheet mirror of an approved overtime log is paid through the log only
        overtime = self._approve_log(employee, hours=2.0, project_id=self.project.id)
        self.assertTrue(overtime.timesheet_ids)
        ignored |= overtime.timesheet_ids
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        claimed_lines = payslip.gec_settlement_ids.filtered('active_claim').timesheet_line_id
        self.assertEqual(claimed_lines, valid)
        self.assertFalse(claimed_lines & ignored)

    def test_timesheet_outside_contract_is_ignored(self):
        employee = self._make_employee('fixed_hourly', timesheet_pay_start_date=date(2024, 1, 1))
        line = self._make_timesheet(employee, work_date=date(2024, 12, 31), hours=2.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertFalse(line.gec_settlement_ids)

    def test_timesheet_is_ignored_when_scheme_does_not_enable_it(self):
        employee = self._make_employee('fixed')
        line = self._make_timesheet(employee, hours=2.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertFalse(line.gec_settlement_ids)

    def test_fixed_hourly_empty_projects_pays_any_project(self):
        employee = self._make_employee('fixed_hourly', timesheet_pay_project_ids=[Command.clear()])
        line = self._make_timesheet(employee, hours=2.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'TIMESHEET_EXTRA'), 20.0)
        self.assertTrue(line.gec_settlement_ids.filtered('active_claim'))

    def test_default_structure_must_contain_component_rule(self):
        custom_type = self.env['hr.payroll.structure.type'].create({
            'name': 'GEO Monthly Without Timesheet Rule',
            'wage_type': 'monthly',
            'country_id': self.env.ref('base.ge').id,
        })
        custom_structure = self.env['hr.payroll.structure'].create({
            'name': 'GEO No Timesheet Structure',
            'type_id': custom_type.id,
            'country_id': self.env.ref('base.ge').id,
            'use_worked_day_lines': True,
        })
        custom_type.default_struct_id = custom_structure
        employee = self._make_employee('fixed_hourly', structure_type=custom_type)
        line = self._make_timesheet(employee, hours=2.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertFalse(line.gec_settlement_ids)

    def test_late_timesheet_carries_forward_without_lower_period_bound(self):
        employee = self._make_employee('fixed_hourly', timesheet_pay_start_date=self.contract_start)
        old_line = self._make_timesheet(employee, work_date=date(2025, 12, 15), hours=4.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = old_line.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(settlement.payslip_id, payslip)
        self.assertEqual(settlement.amount, 40.0)

    def test_lines_use_version_active_on_each_work_date(self):
        employee = self._make_employee('fixed_hourly', hourly_wage=10.0)
        old_version = employee._get_version(self.period_start)
        new_version = employee.create_version({'date_version': date(2026, 1, 16), 'hourly_wage': 20.0})
        old_line = self._make_timesheet(employee, work_date=date(2026, 1, 15), hours=2.0)
        new_line = self._make_timesheet(employee, work_date=date(2026, 1, 16), hours=2.0)
        payslip = self._make_payslip(employee, version=old_version)
        payslip.compute_sheet()
        self.assertEqual(old_line.gec_settlement_ids.payslip_id, payslip)
        self.assertEqual(new_line.gec_settlement_ids.payslip_id, payslip)
        self.assertEqual(new_line.gec_settlement_ids.source_version_id, new_version)
        self.assertEqual(old_line.gec_settlement_ids.rate, 10.0)
        self.assertEqual(old_line.gec_settlement_ids.amount, 20.0)
        self.assertEqual(new_line.gec_settlement_ids.rate, 20.0)
        self.assertEqual(new_line.gec_settlement_ids.amount, 40.0)

    def test_hourly_rate_change_releases_and_reprices_draft_timesheet_claim(self):
        employee = self._make_employee('fixed_hourly', hourly_wage=10.0)
        line = self._make_timesheet(employee, hours=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        old = line.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(old.amount, 30.0)

        employee.version_id.write({'hourly_wage': 15.0})

        new = line.gec_settlement_ids.filtered('active_claim')
        self.assertNotEqual(new, old)
        self.assertFalse(old.active_claim)
        self.assertEqual(old.release_reason, 'Payslip recomputed')
        self.assertEqual(new.payslip_id, payslip)
        self.assertEqual(new.rate, 15.0)
        self.assertEqual(new.amount, 45.0)

    def test_project_allow_list_change_releases_draft_claim(self):
        employee = self._make_employee('fixed_hourly')
        line = self._make_timesheet(employee, hours=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = line.gec_settlement_ids.filtered('active_claim')

        employee.version_id.write({'timesheet_pay_project_ids': [Command.set([self.other_project.id])]})

        self.assertFalse(settlement.active_claim)
        self.assertFalse(line.gec_settlement_ids.filtered('active_claim'))

    def test_cutoff_change_releases_draft_claim(self):
        employee = self._make_employee('fixed_hourly')
        line = self._make_timesheet(employee, hours=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = line.gec_settlement_ids.filtered('active_claim')

        employee.version_id.write({'timesheet_pay_start_date': self.period_start + timedelta(days=1)})

        self.assertFalse(settlement.active_claim)
        self.assertFalse(line.gec_settlement_ids.filtered('active_claim'))

    def test_switching_away_from_timesheet_scheme_releases_draft_claim(self):
        employee = self._make_employee('fixed_hourly')
        line = self._make_timesheet(employee, hours=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = line.gec_settlement_ids.filtered('active_claim')

        employee.version_id.write({'pay_scheme': 'fixed', 'structure_type_id': self.structure_types['monthly'].id})

        self.assertFalse(settlement.active_claim)
        self.assertFalse(line.gec_settlement_ids.filtered('active_claim'))

    def test_work_log_claim_is_not_repriced_by_later_version_change(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        log = self._approve_log(employee, hours=3.0, percentage='150')
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = log.settlement_ids.filtered('active_claim')

        employee.version_id.write({'hourly_wage': 50.0, 'worklog_ot_enabled': False})

        self.assertTrue(settlement.active_claim)
        self.assertEqual(log.settlement_ids.filtered('active_claim'), settlement)
        self.assertEqual(settlement.rate, 10.0)
        self.assertEqual(settlement.amount, 45.0)
