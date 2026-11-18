from datetime import date

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollPayslipLifecycle(GeoPayrollCase):
    def _off_cycle_structure(self, wage_type='monthly'):
        return self.structures[wage_type].copy({'name': self._next_name('GEO Off-Cycle Structure')})

    def test_claim_owner_gate_covers_all_payslip_variations(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        original = self._make_payslip(employee)
        refund, correction = self._make_correction_pair(original)
        base = self._make_payslip(employee)
        edited = self._make_payslip(employee, edited=True)
        off_cycle = self._make_payslip(employee, structure=self._off_cycle_structure())
        validated = self._make_payslip(employee, state='validated')
        no_version = self._make_payslip(employee)
        no_version.version_id = False

        self.assertTrue(base._gec_can_claim())
        for slip in edited | refund | correction | off_cycle | validated | no_version:
            with self.subTest(slip=slip.name):
                self.assertFalse(slip._gec_can_claim())

    def test_work_log_recompute_is_idempotent(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        log = self._approve_log(employee, hours=2.0, percentage='150')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        claim = log.settlement_ids.filtered('active_claim')
        line_total = self._line_total(payslip, 'WORKLOG_OT')

        payslip.compute_sheet()

        self.assertEqual(log.settlement_ids.filtered('active_claim'), claim)
        self.assertEqual(len(log.settlement_ids), 1)
        self.assertEqual(self._line_total(payslip, 'WORKLOG_OT'), line_total)
        self.assertEqual(line_total, 30.0)

    def test_work_log_carries_forward_but_never_claims_after_period_end(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        old_log = self._approve_log(employee, work_date=date(2025, 12, 15))
        later_log = self._approve_log(employee, work_date=date(2026, 2, 1))
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(old_log.settlement_ids.filtered('active_claim').payslip_id, payslip)
        self.assertFalse(later_log.settlement_ids.filtered('active_claim'))

    def test_frozen_daily_component_survives_later_scheme_type_change(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        log = self._approve_log(employee, log_type='daily', units=1.0)
        self.assertEqual(log.component_code_snapshot, 'daily_basic')
        employee.version_id.write({'pay_scheme': 'fixed', 'structure_type_id': self.structure_types['monthly'].id})
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(log.settlement_ids.filtered('active_claim').payslip_id, payslip)
        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)

    def test_recompute_releases_claim_after_manual_off_cycle_move(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        old_claim = log.settlement_ids.filtered('active_claim')

        payslip.struct_id = self._off_cycle_structure()
        payslip.compute_sheet()

        self.assertFalse(old_claim.active_claim)
        self.assertEqual(old_claim.release_reason, 'Payslip recomputed')
        self.assertFalse(log.settlement_ids.filtered('active_claim'))

    def test_cancel_releases_and_reopen_reclaims_with_new_ledger_row(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        old_claim = log.settlement_ids.filtered('active_claim')

        payslip.action_payslip_cancel()
        self.assertFalse(old_claim.active_claim)
        self.assertEqual(old_claim.release_reason, 'Payslip cancelled')

        payslip.action_payslip_draft()
        new_claim = log.settlement_ids.filtered('active_claim')
        self.assertTrue(new_claim)
        self.assertNotEqual(new_claim, old_claim)
        self.assertEqual(new_claim.payslip_id, payslip)

    def test_confirmation_blocks_new_unclaimed_work_after_compute(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self._approve_log(employee)

        with self.assertRaisesRegex(UserError, 'missing from the payslip'):
            payslip.action_payslip_done()

    def test_confirmation_blocks_manually_changed_component_line(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        self._approve_log(employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        component = payslip.line_ids.filtered(lambda line: line.code == 'WORKLOG_OT')
        component.total += 1.0

        with self.assertRaisesRegex(UserError, 'does not match its work logs'):
            payslip.action_payslip_done()

    def test_confirmation_blocks_source_snapshot_changed_after_claim(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        log._write_workflow({'amount_snapshot': log.amount_snapshot + 1.0})

        with self.assertRaisesRegex(UserError, 'changed after it was computed'):
            payslip.action_payslip_done()

    def test_daily_confirmation_blocks_schedule_priced_basic(self):
        employee = self._make_employee('daily', daily_wage=80.0)
        payslip = self._make_payslip(employee, worked_hours=8.0, worked_days=1.0)
        payslip.worked_days_line_ids.amount = 80.0
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BASIC'), 80.0)

        with self.assertRaisesRegex(UserError, 'instead of work logs'):
            payslip.action_payslip_done()

    def test_overlapping_regular_base_payslip_is_blocked(self):
        employee = self._make_employee('fixed')
        first = self._make_payslip(employee, worked_hours=160.0)
        first.compute_sheet()
        first.action_payslip_done()
        second = self._make_payslip(employee, worked_hours=160.0)
        second.compute_sheet()

        with self.assertRaisesRegex(UserError, 'already has a regular payslip'):
            second.action_payslip_done()

    def test_cancelled_regular_payslip_does_not_block_replacement(self):
        employee = self._make_employee('fixed')
        old = self._make_payslip(employee, worked_hours=160.0)
        old.compute_sheet()
        old.action_payslip_done()
        old.action_payslip_cancel()

        replacement = self._make_payslip(employee, worked_hours=160.0)
        replacement.compute_sheet()
        replacement.action_payslip_done()
        self.assertEqual(replacement.state, 'validated')

    def test_refund_and_correction_are_not_treated_as_duplicate_base(self):
        employee = self._make_employee('fixed')
        original = self._make_payslip(employee, worked_hours=160.0)
        original.compute_sheet()
        original.action_payslip_done()
        refund, correction = self._make_correction_pair(original)
        refund._gec_check_no_overlap()
        correction._gec_check_no_overlap()

    def test_work_log_settlement_state_tracks_claim_validate_and_paid(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        self.assertEqual(log.settlement_state, 'unclaimed')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(log.settlement_state, 'claimed')
        payslip.action_payslip_done()
        self.assertEqual(log.settlement_state, 'paid')
        payslip.action_payslip_paid()
        self.assertEqual(log.settlement_state, 'paid')

    def test_component_totals_follow_root_origin_and_credit_sign(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        self._approve_log(employee, hours=3.0, percentage='150')
        original = self._make_payslip(employee, worked_hours=160.0)
        original.compute_sheet()
        refund, correction = self._make_correction_pair(original)
        _second_refund, second_correction = self._make_correction_pair(correction)
        self.assertEqual(original.gec_component_total('worklog_ot'), 45.0)
        self.assertEqual(correction.gec_component_total('worklog_ot'), 45.0)
        self.assertEqual(refund.gec_component_total('worklog_ot'), -45.0)
        self.assertEqual(second_correction.gec_component_total('worklog_ot'), 45.0)

    def test_open_settlements_action_is_scoped_to_payslip(self):
        employee = self._make_employee('fixed')
        payslip = self._make_payslip(employee)
        action = payslip.action_open_gec_settlements()
        self.assertEqual(action['res_model'], 'hr.payroll.component.settlement')
        self.assertEqual(action['domain'], [('payslip_id', '=', payslip.id)])


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollVersionPayslipRefresh(GeoPayrollCase):
    def _make_cross_type_versions(self):
        employee = self._make_employee(
            'daily_hourly',
            daily_wage=30.0,
            hourly_wage=20.0,
            timesheet_pay_start_date=self.period_start,
        )
        old_version = employee._get_version(self.period_start)
        # One payslip pays all versions of a contract, so a structure type change needs a new contract.
        old_version.contract_date_end = date(2026, 1, 15)
        new_version = employee.create_version({
            'date_version': date(2026, 1, 16),
            'contract_date_start': date(2026, 1, 16),
            'contract_date_end': self.contract_end,
            'pay_scheme': 'fixed_hourly',
            'structure_type_id': self.structure_types['monthly'].id,
            'wage': 6500.0,
            'hourly_wage': 20.0,
        })
        return employee, old_version, new_version

    def test_form_version_switch_realigns_structure_and_claims_new_timesheet(self):
        employee, old_version, new_version = self._make_cross_type_versions()
        line = self._make_timesheet(employee, work_date=date(2026, 1, 20), hours=8 + 29 / 60)
        payslip = self._make_payslip(employee, version=old_version, structure=self.structures['daily'])

        with Form(payslip) as form:
            form.version_id = new_version

        self.assertEqual(payslip.struct_id, self.structures['monthly'])
        payslip.compute_sheet()

        settlement = line.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(settlement.payslip_id, payslip)
        self.assertEqual(settlement.source_version_id, new_version)
        self.assertAlmostEqual(settlement.quantity, 8 + 29 / 60, places=4)
        self.assertAlmostEqual(settlement.amount, 169.67, places=2)
        timesheet_line = payslip.line_ids.filtered(lambda salary_line: salary_line.code == 'TIMESHEET_EXTRA')
        self.assertAlmostEqual(timesheet_line.quantity, 8 + 29 / 60, places=2)
        self.assertAlmostEqual(timesheet_line.total, 169.67, places=2)

    def test_compute_repairs_stale_structure_created_outside_form(self):
        employee, _old_version, new_version = self._make_cross_type_versions()
        line = self._make_timesheet(employee, work_date=date(2026, 1, 20), hours=2.0)
        payslip = self._make_payslip(employee, version=new_version, structure=self.structures['daily'])
        self.assertEqual(payslip.struct_id, self.structures['daily'])

        payslip.compute_sheet()

        self.assertEqual(payslip.struct_id, self.structures['monthly'])
        self.assertEqual(line.gec_settlement_ids.filtered('active_claim').payslip_id, payslip)
        self.assertAlmostEqual(self._line_total(payslip, 'TIMESHEET_EXTRA'), 40.0)

    def test_orm_version_switch_realigns_regular_draft(self):
        employee, old_version, new_version = self._make_cross_type_versions()
        payslip = self._make_payslip(employee, version=old_version, structure=self.structures['daily'])

        payslip.write({'version_id': new_version.id})

        self.assertEqual(payslip.struct_id, self.structures['monthly'])

    def test_version_switch_preserves_special_draft_structures(self):
        employee, old_version, new_version = self._make_cross_type_versions()
        original = self._make_payslip(employee, version=old_version)
        refund, correction = self._make_correction_pair(original)
        edited = self._make_payslip(employee, version=old_version, edited=True)
        off_cycle_structure = self.structures['daily'].copy({'name': self._next_name('GEO Cross-Type Off-Cycle')})
        off_cycle = self._make_payslip(employee, version=old_version, structure=off_cycle_structure)
        specials = edited | refund | correction | off_cycle
        old_structures = {slip.id: slip.struct_id for slip in specials}

        specials.write({'version_id': new_version.id})

        for slip in specials:
            with self.subTest(slip=slip.name):
                self.assertEqual(slip.struct_id, old_structures[slip.id])

    def test_every_scheme_to_every_other_scheme_refreshes_draft_base(self):
        schemes = ('fixed', 'hourly', 'daily', 'unit', 'fixed_daily', 'fixed_hourly', 'daily_hourly', 'daily_unit')
        for source in schemes:
            for target in schemes:
                if source == target:
                    continue
                with self.subTest(source=source, target=target):
                    employee = self._make_employee(source)
                    version = employee.version_id
                    payslip = self._make_payslip(employee, worked_hours=160.0)
                    payslip.compute_sheet()
                    target_wage_type = self._scheme_wage_type(target)
                    values = {'pay_scheme': target, 'structure_type_id': self.structure_types[target_wage_type].id}
                    if target in ('fixed_hourly', 'daily_hourly'):
                        values['timesheet_pay_start_date'] = self.contract_start
                    version.write(values)
                    self.assertEqual(version.pay_scheme, target)
                    self.assertEqual(version.wage_type, target_wage_type)
                    self.assertEqual(payslip.struct_id, self.structures[target_wage_type])
                    self.assertTrue(payslip.line_ids)

    def test_validated_and_paid_history_is_not_rewritten_by_version_change(self):
        """Routing changes are blocked after finalized payroll; other changes never rewrite paid history."""
        for final_state in ('validated', 'paid'):
            with self.subTest(final_state=final_state):
                employee = self._make_employee('fixed', wage=1600.0)
                version = employee.version_id
                payslip = self._make_payslip(employee, worked_hours=160.0)
                payslip.compute_sheet()
                payslip.action_payslip_done()
                if final_state == 'paid':
                    payslip.action_payslip_paid()
                structure = payslip.struct_id
                lines = [(line.code, line.total) for line in payslip.line_ids]

                with self.assertRaises(UserError):
                    version.write({
                        'pay_scheme': 'hourly',
                        'structure_type_id': self.structure_types['hourly'].id,
                        'hourly_wage': 25.0,
                    })
                version.write({'hourly_wage': 25.0})

                self.assertEqual(payslip.state, final_state)
                self.assertEqual(payslip.struct_id, structure)
                self.assertEqual([(line.code, line.total) for line in payslip.line_ids], lines)

    def test_cancelled_regular_reopens_on_new_version_type_and_recomputes(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version = employee.version_id
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.action_payslip_cancel()
        version.write({'pay_scheme': 'daily', 'structure_type_id': self.structure_types['daily'].id})
        self.assertEqual(payslip.struct_id, self.structures['monthly'])

        payslip.action_payslip_draft()

        self.assertEqual(payslip.state, 'draft')
        self.assertEqual(payslip.struct_id, self.structures['daily'])
        self.assertEqual(self._line_total(payslip, 'BASIC'), 0.0)

    def test_special_draft_slips_are_not_rewritten_by_version_change(self):
        employee = self._make_employee('fixed')
        version = employee.version_id
        original = self._make_payslip(employee)
        refund, correction = self._make_correction_pair(original)
        # Core validates refunds on creation; cancel the slips so the routing change is allowed.
        refund.action_payslip_cancel()
        original.action_payslip_cancel()
        edited = self._make_payslip(employee, edited=True)
        off_cycle = self._make_payslip(
            employee,
            structure=self.structures['monthly'].copy({
                'name': self._next_name('GEO Special Structure'),
            }),
        )
        specials = edited | correction | off_cycle
        old_structures = {slip.id: slip.struct_id for slip in specials}

        version.write({'pay_scheme': 'hourly', 'structure_type_id': self.structure_types['hourly'].id})

        for slip in specials:
            with self.subTest(slip=slip.name):
                self.assertEqual(slip.struct_id, old_structures[slip.id])

    def test_cancelled_refund_is_not_realigned_when_reopened(self):
        employee = self._make_employee('fixed')
        version = employee.version_id
        original = self._make_payslip(employee)
        original.compute_sheet()
        original.action_payslip_done()
        refund = original._action_refund_payslips()
        refund.action_payslip_cancel()
        original.action_payslip_cancel()
        version.write({'pay_scheme': 'hourly', 'structure_type_id': self.structure_types['hourly'].id})
        refund.action_payslip_draft()
        self.assertEqual(refund.struct_id, self.structures['monthly'])
