from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollTimesheetHourlyBase(GeoPayrollCase):
    """Base pay is eligible timesheet hours x work-date rate; work entries, leave, holidays and logs add nothing."""

    @classmethod
    def _make_ts_employee(cls, **values):
        values.setdefault('timesheet_pay_start_date', cls.contract_start)
        return cls._make_employee('hourly', hourly_source='timesheet', **values)

    def _waive(self, lines, reason='Abandoned'):
        """Waive lines through the timesheet-driven wizard, as the Actions menu does."""
        self.env['gec.payroll.timesheet.waiver'].with_context(
            active_ids=lines.ids).create({'reason': reason}).action_waive()

    def test_work_entry_mode_hourly_pays_work_entries_and_ignores_timesheets(self):
        employee = self._make_employee('hourly', hourly_wage=10.0)
        line = self._make_timesheet(employee, hours=8.0)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BASIC'), 1600.0)
        self.assertEqual(self._line_total(payslip, 'TIMESHEET_BASIC'), 0.0)
        self.assertFalse(line.gec_settlement_ids)
        self.assertEqual(payslip.worked_days_line_ids.mapped('amount'), [1600.0])

    def test_timesheet_mode_pays_timesheets_validated_or_not(self):
        employee = self._make_ts_employee(hourly_wage=10.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=8.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 6), hours=4.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 7), hours=5.0, validated=False)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()

        self.assertEqual(payslip.worked_days_line_ids.mapped('amount'), [0.0])
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('amount')), 0.0)
        self.assertEqual(self._line_total(payslip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(payslip, 'TIMESHEET_BASIC'), 170.0)
        self.assertEqual(self._line_total(payslip, 'GROSS'), 170.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 136.0)

        settlements = payslip.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(set(settlements.mapped('component_code')), {'timesheet_basic'})
        self.assertEqual(settlements.mapped('source_version_id'), employee.version_id)

        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_timesheet_mode_zero_month_confirms_at_zero(self):
        employee = self._make_ts_employee()
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'GROSS'), 0.0)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_timesheet_mode_uses_work_date_version_rate(self):
        employee = self._make_ts_employee(hourly_wage=10.0)
        employee.create_version({'date_version': date(2026, 1, 16), 'hourly_wage': 20.0})
        old_line = self._make_timesheet(employee, work_date=date(2026, 1, 10), hours=2.0)
        new_line = self._make_timesheet(employee, work_date=date(2026, 1, 20), hours=2.0)
        slip = self._make_payslip(employee)
        slip.compute_sheet()
        self.assertEqual(old_line.gec_settlement_ids.amount, 20.0)
        self.assertEqual(new_line.gec_settlement_ids.amount, 40.0)
        self.assertEqual(self._line_total(slip, 'TIMESHEET_BASIC'), 60.0)

    def test_confirm_blocks_edited_timesheet_mode_slip(self):
        employee = self._make_ts_employee()
        self._make_timesheet(employee, hours=8.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        payslip.edited = True
        with self.assertRaises(UserError):
            payslip.action_payslip_done()

    def test_confirm_blocks_silent_zero_when_rule_disappears_after_setup(self):
        employee = self._make_ts_employee()
        self._make_timesheet(employee, hours=8.0)
        self.structures['hourly'].rule_ids.filtered(lambda r: r.code == 'TIMESHEET_BASIC').active = False
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'GROSS'), 0.0)
        self.assertFalse(payslip.gec_settlement_ids)
        with self.assertRaises(UserError):
            payslip.action_payslip_done()

    def test_confirm_blocks_new_eligible_line_not_yet_claimed(self):
        employee = self._make_ts_employee()
        self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=8.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self._make_timesheet(employee, work_date=date(2026, 1, 6), hours=4.0)
        with self.assertRaises(UserError):
            payslip.action_payslip_done()

    def test_timesheet_mode_requires_full_configuration(self):
        """No start date and no project list are allowed."""
        with self.assertRaises(ValidationError):
            self._make_ts_employee(hourly_wage=0.0)
        with self.assertRaises(ValidationError):
            self._make_ts_employee(worklog_ot_enabled=True)
        combined = self._make_employee('fixed_hourly', hourly_source='timesheet',
                                       timesheet_pay_start_date=self.contract_start)
        self.assertEqual(combined.version_id.hourly_source, 'work_entry')

    def test_source_inherited_across_new_dated_version(self):
        employee = self._make_ts_employee()
        new_version = employee.create_version({'date_version': date(2026, 6, 1), 'hourly_wage': 15.0})
        self.assertEqual(new_version.hourly_source, 'timesheet')
        self.assertEqual(new_version.pay_scheme, 'hourly')
        self.assertEqual(new_version.timesheet_pay_start_date, employee.version_id.timesheet_pay_start_date)

    def test_source_normalized_when_new_version_changes_scheme(self):
        employee = self._make_ts_employee()
        new_version = employee.create_version({
            'date_version': date(2026, 6, 1),
            'pay_scheme': 'fixed',
            'structure_type_id': self.structure_types['monthly'].id,
        })
        self.assertEqual(new_version.hourly_source, 'work_entry')

    def test_routing_change_blocked_after_finalized_payslip(self):
        employee = self._make_ts_employee()
        self._make_timesheet(employee, hours=8.0)
        version = employee.version_id
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_done()

        with self.assertRaises(UserError):
            version.write({'hourly_source': 'work_entry'})
        with self.assertRaises(UserError):
            version.write({'pay_scheme': 'fixed', 'structure_type_id': self.structure_types['monthly'].id})
        version.write({'hourly_wage': 12.0})
        self.assertEqual(version.hourly_source, 'timesheet')

    def test_leaving_timesheet_mode_blocked_by_strandable_lines(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        version = employee.version_id

        with self.assertRaises(UserError):
            version.write({'hourly_source': 'work_entry'})

        wizard = self.env['gec.payroll.timesheet.waiver'].with_context(
            active_ids=line.ids).create({
                'reason': 'Misconfigured employee, hours must never pay',
            })
        self.assertEqual(wizard.line_ids, line)
        wizard.action_waive()
        self.assertTrue(line.sudo().gec_payroll_waived_at)
        self.assertEqual(line.sudo().gec_payroll_waived_by_id, self.env.user)

        version.write({'hourly_source': 'work_entry'})
        self.assertEqual(version.hourly_source, 'work_entry')

    def test_waived_line_is_never_claimed_again(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        self._waive(line, reason='Abandoned')

        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertFalse(line.gec_settlement_ids)
        self.assertEqual(self._line_total(payslip, 'TIMESHEET_BASIC'), 0.0)
        payslip.action_payslip_done()

    def test_waiver_is_manager_only(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        officer = self._make_user('GEO Payroll Officer', groups=(self.env.ref('hr_payroll.group_hr_payroll_user'),))
        with self.assertRaises(UserError):
            line.with_user(officer).write({'gec_payroll_waive_reason': 'nope'})
        with self.assertRaises(AccessError):
            self.env['gec.payroll.timesheet.waiver'].with_user(officer).create({'reason': 'nope'})

    def test_direct_waiver_writes_blocked_and_restore_action(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        with self.assertRaises(UserError):
            line.write({'gec_payroll_waive_reason': 'direct'})
        with self.assertRaises(UserError):
            line.sudo().write({'gec_payroll_waive_reason': 'direct'})

        self._waive(line, reason='Abandoned')
        self.assertTrue(line.sudo().gec_payroll_waived_at)

        officer = self._make_user('GEO Payroll Officer', groups=(self.env.ref('hr_payroll.group_hr_payroll_user'),))
        with self.assertRaises(UserError):
            line.with_user(officer).action_gec_restore_payroll_pay()

        line.action_gec_restore_payroll_pay()
        self.assertFalse(line.sudo().gec_payroll_waived_at)
        self.assertFalse(line.sudo().gec_payroll_waived_by_id)
        self.assertFalse(line.sudo().gec_payroll_waive_reason)

        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertTrue(line.gec_settlement_ids.filtered('active_claim'))

    def test_waived_line_identity_fields_locked(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        self._waive(line, reason='Frozen evidence')
        with self.assertRaises(UserError):
            line.write({'unit_amount': 1.0})
        line.action_gec_restore_payroll_pay()
        line.write({'unit_amount': 1.0})
        self.assertEqual(line.unit_amount, 1.0)

    def test_project_or_cutoff_change_blocked_when_lines_would_strand(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=4.0)
        version = employee.version_id

        with self.assertRaises(UserError):
            version.write({'timesheet_pay_project_ids': [Command.set([self.other_project.id])]})
        with self.assertRaises(UserError):
            version.write({'timesheet_pay_start_date': date(2026, 1, 6)})

        version.write({'timesheet_pay_project_ids': [Command.link(self.other_project.id)]})

        self._waive(line, reason='Hours must not pay')
        self.assertTrue(line.sudo().gec_payroll_waived_at)
        version.write({'timesheet_pay_project_ids': [Command.set([self.other_project.id])]})
        self.assertEqual(version.timesheet_pay_project_ids, self.other_project)

    def test_empty_project_list_means_all_projects_for_strand_guard(self):
        employee = self._make_ts_employee()
        self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=4.0)
        self._make_timesheet(employee, work_date=date(2026, 1, 12), hours=4.0, project=self.other_project)
        version = employee.version_id

        version.write({'timesheet_pay_project_ids': [Command.clear()]})
        self.assertFalse(version.timesheet_pay_project_ids)
        version.write({'timesheet_pay_start_date': date(2024, 6, 1)})
        version.write({'timesheet_pay_start_date': date(2026, 1, 5)})
        self.assertEqual(version.timesheet_pay_start_date, date(2026, 1, 5))

        with self.assertRaisesRegex(UserError, 'has 1 timesheet line'):
            version.write({'timesheet_pay_start_date': date(2026, 1, 6)})
        with self.assertRaises(UserError):
            version.write({'timesheet_pay_project_ids': [Command.set([self.other_project.id])]})

    def test_draft_claimed_line_blocks_flip_until_released_and_waived(self):
        """A flip releases draft claims and strands their lines, so draft-claimed lines block it too."""
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        settlement = line.gec_settlement_ids.filtered('active_claim')
        self.assertTrue(settlement)

        with self.assertRaises(UserError):
            employee.version_id.write({'hourly_source': 'work_entry'})

        payslip.action_payslip_cancel()
        self.assertFalse(settlement.active_claim)
        with self.assertRaises(UserError):
            employee.version_id.write({'hourly_source': 'work_entry'})

        self._waive(line, reason='Hours must not pay')
        employee.version_id.write({'hourly_source': 'work_entry'})
        self.assertEqual(employee.version_id.hourly_source, 'work_entry')

    def test_waiver_rejects_lines_outside_the_strandable_set(self):
        employee = self._make_ts_employee()
        good = self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=4.0)
        wrong_project = self._make_timesheet(
            employee, work_date=date(2026, 1, 7), hours=4.0, project=self.other_project)

        wizard = self.env['gec.payroll.timesheet.waiver'].create({'reason': 'scope test'})
        wizard.line_ids = good | wrong_project
        with self.assertRaises(UserError):
            wizard.action_waive()
        self.assertFalse(good.sudo().gec_payroll_waived_at)

        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertTrue(good.gec_settlement_ids.filtered('active_claim'))
        wizard = self.env['gec.payroll.timesheet.waiver'].create({'reason': 'scope test'})
        wizard.line_ids = good
        with self.assertRaises(UserError):
            wizard.action_waive()
        self.assertFalse(good.sudo().gec_payroll_waived_at)

    def test_wizard_prefills_only_waivable_lines_from_selection(self):
        employee = self._make_ts_employee()
        good = self._make_timesheet(employee, work_date=date(2026, 1, 5), hours=4.0)
        unvalidated = self._make_timesheet(employee, work_date=date(2026, 1, 6), hours=4.0, validated=False)
        wrong_project = self._make_timesheet(
            employee, work_date=date(2026, 1, 7), hours=4.0, project=self.other_project)
        wizard = self.env['gec.payroll.timesheet.waiver'].with_context(
            active_ids=(good | unvalidated | wrong_project).ids).create({'reason': 'prefill'})
        self.assertEqual(wizard.line_ids, good | unvalidated)
        wizard.action_waive()
        self.assertTrue(good.sudo().gec_payroll_waived_at)
        self.assertTrue(unvalidated.sudo().gec_payroll_waived_at)
        self.assertFalse(wrong_project.sudo().gec_payroll_waived_at)

    def test_restore_action_reclaims_line(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=8.0)
        self._waive(line, reason='Abandoned')
        line.action_gec_restore_payroll_pay()
        self.assertFalse(line.sudo().gec_payroll_waived_at)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertTrue(line.gec_settlement_ids.filtered('active_claim'))

    def test_waived_line_cannot_be_deleted(self):
        employee = self._make_ts_employee()
        line = self._make_timesheet(employee, hours=4.0)
        self._waive(line, reason='Abandoned')
        self.assertTrue(line.sudo().gec_payroll_waived_at)
        with self.assertRaises(UserError):
            line.unlink()

    def test_payrun_computes_validates_and_resets_timesheet_base(self):
        run = self.env['hr.payslip.run'].create({
            'name': self._next_name('GEO TS Pay Run'),
            'date_start': self.period_start,
            'date_end': self.period_end,
            'structure_id': self.structures['hourly'].id,
        })
        worker = self._make_ts_employee(hourly_wage=10.0)
        idle = self._make_ts_employee()
        line = self._make_timesheet(worker, hours=8.0)
        worker_slip = self._make_payslip(worker, payslip_run_id=run.id)
        idle_slip = self._make_payslip(idle, payslip_run_id=run.id)

        run.action_confirm()
        self.assertEqual(self._line_total(worker_slip, 'TIMESHEET_BASIC'), 80.0)
        self.assertEqual(self._line_total(worker_slip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(idle_slip, 'GROSS'), 0.0)
        claim = line.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(claim.payslip_id, worker_slip)

        run.action_validate()
        self.assertEqual(set(run.slip_ids.mapped('state')), {'validated'})

        run.action_draft()
        self.assertEqual(set(run.slip_ids.mapped('state')), {'draft'})
        self.assertEqual(line.gec_settlement_ids.filtered('active_claim'), claim)
        worker_slip.compute_sheet()
        self.assertEqual(line.gec_settlement_ids.filtered('active_claim'), claim)
        self.assertEqual(self._line_total(worker_slip, 'TIMESHEET_BASIC'), 80.0)

    def test_day_total_over_24h_blocks_compute(self):
        employee = self._make_ts_employee()
        day = date(2026, 1, 5)
        self._make_timesheet(employee, work_date=day, hours=15.0)
        self._make_timesheet(employee, work_date=day, hours=15.0)
        payslip = self._make_payslip(employee)
        with self.assertRaises(UserError):
            payslip.compute_sheet()

    def test_day_cap_counts_hours_already_claimed(self):
        employee = self._make_ts_employee()
        day = date(2026, 1, 5)
        self._make_timesheet(employee, work_date=day, hours=10.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self._make_timesheet(employee, work_date=day, hours=15.0)
        with self.assertRaises(UserError):
            payslip.compute_sheet()

    def test_day_cap_also_protects_additive_timesheets(self):
        employee = self._make_employee('fixed_hourly', hourly_wage=10.0)
        day = date(2026, 1, 5)
        self._make_timesheet(employee, work_date=day, hours=15.0)
        self._make_timesheet(employee, work_date=day, hours=15.0)
        payslip = self._make_payslip(employee)
        with self.assertRaises(UserError):
            payslip.compute_sheet()

    def test_overtime_work_log_approval_refused_in_timesheet_mode(self):
        employee = self._make_ts_employee()
        log = self._make_work_log(employee, hours=2.0)
        with self.assertRaises(UserError):
            log.action_approve()

    def test_late_timesheet_carries_forward_across_scheme_switch(self):
        employee = self._make_ts_employee(hourly_wage=10.0)
        jan_version = employee.version_id
        employee.create_version({
            'date_version': date(2026, 2, 1),
            'pay_scheme': 'fixed',
            'structure_type_id': self.structure_types['monthly'].id,
        })
        late_line = self._make_timesheet(employee, work_date=date(2026, 1, 20), hours=4.0)

        feb_slip = self._make_payslip(
            employee,
            date_from=date(2026, 2, 1),
            date_to=date(2026, 2, 28),
            version=employee._get_version(date(2026, 2, 1)),
            worked_hours=160.0,
        )
        feb_slip.compute_sheet()

        settlement = late_line.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(settlement.payslip_id, feb_slip)
        self.assertEqual(settlement.component_code, 'timesheet_basic')
        self.assertEqual(settlement.source_version_id, jan_version)
        self.assertEqual(settlement.amount, 40.0)
        self.assertEqual(self._line_total(feb_slip, 'BASIC'), 1600.0)
        self.assertEqual(self._line_total(feb_slip, 'TIMESHEET_BASIC'), 40.0)
        self.assertEqual(self._line_total(feb_slip, 'GROSS'), 1640.0)

        feb_slip.action_payslip_done()
        self.assertEqual(feb_slip.state, 'validated')

        # the finalized Feb settlement is priced by the Jan version: its routing is locked
        with self.assertRaises(UserError):
            jan_version.write({'hourly_source': 'work_entry'})
        with self.assertRaises(UserError):
            jan_version.write({'pay_scheme': 'fixed', 'structure_type_id': self.structure_types['monthly'].id})
