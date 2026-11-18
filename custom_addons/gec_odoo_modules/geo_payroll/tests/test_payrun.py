from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollPayRun(GeoPayrollCase):
    def _make_run(self, structure=None):
        return self.env['hr.payslip.run'].create({
            'name': self._next_name('GEO Pay Run'),
            'date_start': self.period_start,
            'date_end': self.period_end,
            'structure_id': (structure or self.structures['monthly']).id,
        })

    def test_payrun_computes_and_validates_worklog_and_timesheet_slips(self):
        run = self._make_run()
        overtime_employee = self._make_employee('fixed', worklog_ot_enabled=True)
        overtime_log = self._approve_log(overtime_employee, hours=3.0, percentage='150')
        timesheet_employee = self._make_employee('fixed_hourly')
        timesheet = self._make_timesheet(timesheet_employee, hours=4.0)
        overtime_slip = self._make_payslip(overtime_employee, payslip_run_id=run.id)
        timesheet_slip = self._make_payslip(timesheet_employee, payslip_run_id=run.id)

        run.action_confirm()

        self.assertEqual(overtime_log.settlement_ids.filtered('active_claim').payslip_id, overtime_slip)
        self.assertEqual(timesheet.gec_settlement_ids.filtered('active_claim').payslip_id, timesheet_slip)
        self.assertEqual(self._line_total(overtime_slip, 'WORKLOG_OT'), 45.0)
        self.assertEqual(self._line_total(timesheet_slip, 'TIMESHEET_EXTRA'), 40.0)

        run.action_validate()
        self.assertEqual(set(run.slip_ids.mapped('state')), {'validated'})
        self.assertEqual(run.state, '02_close')
        self.assertEqual(overtime_log.settlement_state, 'paid')

    def test_payrun_reset_to_draft_keeps_unchanged_claim_idempotent(self):
        run = self._make_run()
        employee = self._make_employee('fixed', worklog_ot_enabled=True)
        log = self._approve_log(employee)
        slip = self._make_payslip(employee, payslip_run_id=run.id)
        run.action_confirm()
        claim = log.settlement_ids.filtered('active_claim')
        run.action_validate()

        run.action_draft()

        self.assertEqual(slip.state, 'draft')
        self.assertEqual(log.settlement_ids.filtered('active_claim'), claim)
        self.assertEqual(len(log.settlement_ids), 1)

    def test_payrun_reset_after_version_type_change_aligns_and_recomputes(self):
        run = self._make_run()
        employee = self._make_employee('fixed')
        version = employee.version_id
        slip = self._make_payslip(employee, payslip_run_id=run.id)
        run.action_confirm()
        run.action_validate()

        with self.assertRaises(UserError):
            version.write({'pay_scheme': 'daily', 'structure_type_id': self.structure_types['daily'].id})
        self.assertEqual(slip.struct_id, self.structures['monthly'])

        run.action_draft()
        version.write({'pay_scheme': 'daily', 'structure_type_id': self.structure_types['daily'].id})

        self.assertEqual(slip.state, 'draft')
        self.assertEqual(slip.struct_id, self.structures['daily'])
        self.assertEqual(self._line_total(slip, 'BASIC'), 0.0)

    def test_paid_payrun_cannot_be_reset_to_draft(self):
        run = self._make_run()
        employee = self._make_employee('fixed')
        self._make_payslip(employee, payslip_run_id=run.id)
        run.action_confirm()
        run.action_validate()
        run.action_paid()
        self.assertEqual(run.state, '03_paid')
        with self.assertRaises(ValidationError):
            run.action_draft()

    def test_payrun_reset_does_not_rewrite_refund_or_correction(self):
        run = self._make_run()
        employee = self._make_employee('fixed')
        original = self._make_payslip(employee)
        refund, correction = self._make_correction_pair(original)
        # A validated origin blocks a routing change, so set the new type directly.
        version = employee.version_id
        version.flush_recordset()
        self.env.cr.execute(
            "UPDATE hr_version SET pay_scheme = 'hourly', wage_type = 'hourly', "
            "structure_type_id = %s WHERE id = %s",
            (self.structure_types['hourly'].id, version.id))
        version.invalidate_recordset(['pay_scheme', 'wage_type', 'structure_type_id'])
        (refund | correction).write({
            'payslip_run_id': run.id,
            'state': 'validated',
            'done_date': fields.Datetime.now(),
        })
        old_structures = {refund.id: refund.struct_id, correction.id: correction.struct_id}

        run.action_draft()

        self.assertEqual(refund.struct_id, old_structures[refund.id])
        self.assertEqual(correction.struct_id, old_structures[correction.id])
