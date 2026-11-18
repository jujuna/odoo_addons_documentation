from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollCorrectionChain(GeoPayrollCase):
    def _validated_original(self):
        employee = self._make_employee('fixed', wage=1600.0)
        original = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        original.compute_sheet()
        original.action_payslip_done()
        return employee, original

    def test_native_pair_validates_and_keeps_one_base_salary(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)

        (refund | correction).action_payslip_done()

        self.assertEqual(refund.state, 'validated')
        self.assertEqual(correction.state, 'validated')
        self.assertEqual(self._line_total(original, 'BASIC'), 1600.0)
        self.assertEqual(self._line_total(refund, 'BASIC'), -1600.0)
        self.assertEqual(self._line_total(correction, 'BASIC'), 1600.0)
        self.assertEqual(sum((original | refund | correction).mapped('net_wage')), 1280.0)

    def test_correction_waits_for_matching_refund(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)
        self.assertEqual(refund.state, 'validated')
        refund.action_payslip_cancel()

        with self.assertRaisesRegex(UserError, 'matching validated refund'):
            correction.action_payslip_done()

    def test_cancel_validated_refund_alone_is_blocked(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)
        (refund | correction).action_payslip_done()

        with self.assertRaisesRegex(UserError, 'would leave'):
            refund.action_payslip_cancel()

        (refund | correction).action_payslip_cancel()
        self.assertEqual(refund.state, 'cancel')
        self.assertEqual(correction.state, 'cancel')

    def test_cancel_correction_alone_leaves_valid_refund_only_flow(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)
        (refund | correction).action_payslip_done()

        correction.action_payslip_cancel()

        self.assertEqual(correction.state, 'cancel')
        self.assertEqual(refund.state, 'validated')
        self.assertEqual(sum((original | refund).mapped('net_wage')), 0.0)

    def test_payrun_rejects_correction_after_draft_refund_is_cancelled(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)
        run = self.env['hr.payslip.run'].create({
            'name': self._next_name('GEO Broken Correction Run'),
            'date_start': self.period_start,
            'date_end': self.period_end,
        })
        (refund | correction).write({'payslip_run_id': run.id})
        refund.action_payslip_cancel()

        with self.assertRaisesRegex(UserError, 'matching validated refund'):
            run.action_validate()
        self.assertEqual(correction.state, 'draft')

    def test_one_refund_cannot_balance_two_corrections(self):
        _employee, original = self._validated_original()
        refund_1, correction_1 = self._make_correction_pair(original)
        refund_2, correction_2 = self._make_correction_pair(original)
        refund_2.action_payslip_cancel()
        (refund_1 | correction_1).action_payslip_done()

        with self.assertRaisesRegex(UserError, 'matching validated refund'):
            correction_2.action_payslip_done()

    def test_manual_origin_links_cannot_bypass_validation_guard(self):
        employee, original = self._validated_original()
        forged_on_create = self._make_payslip(employee, origin_payslip_id=original.id)
        forged_on_create.compute_sheet()
        with self.assertRaisesRegex(UserError, 'matching validated refund'):
            forged_on_create.action_payslip_done()

        forged = self._make_payslip(employee)
        forged.write({'origin_payslip_id': original.id})
        forged.compute_sheet()
        with self.assertRaisesRegex(UserError, 'matching validated refund'):
            forged.action_payslip_done()

    def test_standalone_credit_note_cannot_bypass_duplicate_base_guard(self):
        employee, _original = self._validated_original()
        forged_refund = self._make_payslip(employee, credit_note=True, worked_hours=160.0)
        forged_refund.compute_sheet()

        with self.assertRaisesRegex(UserError, 'not linked to the payslip'):
            forged_refund.action_payslip_done()

    def test_native_refund_only_flow_still_validates(self):
        _employee, original = self._validated_original()
        refund = original._action_refund_payslips()

        refund.action_payslip_done()

        self.assertEqual(refund.state, 'validated')
        self.assertEqual(sum((original | refund).mapped('net_wage')), 0.0)

    def test_correction_with_different_current_structure_still_validates(self):
        """Routing edits are blocked after validation; a new dated version is the way."""
        employee, original = self._validated_original()
        with self.assertRaises(UserError):
            employee.version_id.write({
                'pay_scheme': 'hourly',
                'structure_type_id': self.structure_types['hourly'].id,
                'hourly_wage': 12.0,
            })
        employee.create_version({
            'date_version': date(2026, 2, 1),
            'pay_scheme': 'hourly',
            'structure_type_id': self.structure_types['hourly'].id,
            'hourly_wage': 12.0,
        })
        refund, correction = self._make_correction_pair(original)
        self.assertEqual(refund.struct_id, original.struct_id)

        (refund | correction).action_payslip_done()

        self.assertEqual(correction.state, 'validated')

    def test_run_with_correction_lineage_cannot_be_deleted(self):
        _employee, original = self._validated_original()
        refund, correction = self._make_correction_pair(original)
        run = self.env['hr.payslip.run'].create({
            'name': self._next_name('GEO Correction Audit Run'),
            'date_start': self.period_start,
            'date_end': self.period_end,
        })
        (refund | correction).write({'payslip_run_id': run.id})

        # Core validates the refund on creation, so it refuses to delete the run.
        with self.assertRaises(UserError):
            run.unlink()
