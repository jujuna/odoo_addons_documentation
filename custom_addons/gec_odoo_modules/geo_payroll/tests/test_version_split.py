from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollVersionSplit(GeoPayrollCase):
    """One payslip pays every version of a contract for its hours; a structure type change needs a new contract."""

    @classmethod
    def _make_run(cls, employee):
        run = cls.env['hr.payslip.run'].create({
            'name': cls._next_name('GEO Run'),
            'date_start': cls.period_start,
            'date_end': cls.period_end,
            'structure_id': cls.structures['monthly'].id,
            'company_id': cls.company.id,
        })
        run.action_assign_versions(employee.ids)
        run._generate_payslips()
        return run

    def _split_contracts(self, employee):
        version_a = employee._get_version(self.period_start)
        version_a.contract_date_end = date(2026, 1, 15)
        version_b = employee.create_version({
            'date_version': date(2026, 1, 16),
            'contract_date_start': date(2026, 1, 16),
            'contract_date_end': self.contract_end,
            'pay_scheme': 'daily',
            'structure_type_id': self.structure_types['daily'].id,
            'daily_wage': 90.0,
        })
        return version_a, version_b

    def test_batch_pays_both_versions_on_one_full_period_slip(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version_a = employee._get_version(self.period_start)
        version_b = employee.create_version({'date_version': date(2026, 1, 16), 'wage': 2000.0})

        run = self._make_run(employee)

        slip = run.slip_ids
        self.assertEqual(len(slip), 1)
        self.assertEqual(slip.version_id, version_a)
        self.assertEqual(slip.date_from, self.period_start)
        self.assertEqual(slip.date_to, self.period_end)
        self.assertEqual(slip.worked_days_line_ids.version_id, version_a | version_b)
        self.assertAlmostEqual(self._line_total(slip, 'BASIC'), 1800.0, places=2)
        self.assertAlmostEqual(slip.net_wage, 1440.0, places=2)

        run.action_validate()
        self.assertEqual(slip.state, 'validated')

    def test_admin_only_version_change_keeps_the_wage(self):
        employee = self._make_employee('fixed', wage=1600.0)
        employee.create_version({'date_version': date(2026, 1, 16)})

        run = self._make_run(employee)

        self.assertEqual(len(run.slip_ids), 1)
        self.assertAlmostEqual(self._line_total(run.slip_ids, 'BASIC'), 1600.0, places=2)

    def test_structure_change_inside_one_contract_blocks_validation(self):
        employee = self._make_employee('fixed', wage=1600.0)
        employee.create_version({
            'date_version': date(2026, 1, 16),
            'pay_scheme': 'daily',
            'structure_type_id': self.structure_types['daily'].id,
            'daily_wage': 90.0,
        })
        slip = self._make_payslip(employee)
        slip.compute_sheet()

        with self.assertRaisesRegex(UserError, 'Pay scheme changed'):
            slip.action_payslip_done()

    def test_new_contract_pays_each_contract_on_its_own_slip(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version_a, version_b = self._split_contracts(employee)
        log = self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 20))

        slip_a = self._make_payslip(employee, version=version_a)
        slip_b = self._make_payslip(employee, version=version_b)
        (slip_a | slip_b).compute_sheet()

        self.assertEqual(slip_a.struct_id, self.structures['monthly'])
        self.assertEqual(slip_b.struct_id, self.structures['daily'])
        self.assertAlmostEqual(self._line_total(slip_a, 'BASIC'), 800.0, places=2)
        self.assertAlmostEqual(self._line_total(slip_b, 'DAILY_BASIC'), 90.0, places=2)
        self.assertEqual(log.settlement_ids.filtered('active_claim').payslip_id, slip_b)

        (slip_a | slip_b).action_payslip_done()
        self.assertEqual(set((slip_a | slip_b).mapped('state')), {'validated'})

    def test_second_slip_on_same_contract_is_blocked(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version_a = employee._get_version(self.period_start)
        version_b = employee.create_version({'date_version': date(2026, 1, 16), 'wage': 2000.0})

        slip_a = self._make_payslip(employee, version=version_a)
        slip_a.compute_sheet()
        slip_a.action_payslip_done()
        self.assertAlmostEqual(self._line_total(slip_a, 'BASIC'), 1800.0, places=2)

        slip_b = self._make_payslip(employee, version=version_b)
        slip_b.compute_sheet()
        with self.assertRaisesRegex(UserError, 'same contract'):
            slip_b.action_payslip_done()

    def test_same_version_overlap_still_blocked(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version = employee._get_version(self.period_start)

        first = self._make_payslip(employee, version=version)
        first.compute_sheet()
        first.action_payslip_done()

        second = self._make_payslip(employee, version=version)
        second.compute_sheet()
        with self.assertRaisesRegex(UserError, 'same contract'):
            second.action_payslip_done()

    def test_one_slip_claims_items_of_every_version(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        employee.create_version({'date_version': date(2026, 1, 16), 'hourly_wage': 20.0})
        old_log = self._approve_log(employee, work_date=date(2025, 12, 22), hours=2.0, percentage='100')
        late_log = self._approve_log(employee, work_date=date(2026, 1, 20), hours=2.0, percentage='100')

        slip = self._make_payslip(employee)
        slip.compute_sheet()

        self.assertEqual(old_log.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertEqual(late_log.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertAlmostEqual(self._line_total(slip, 'WORKLOG_OT'), 60.0, places=2)

    def test_carry_forward_when_contract_starts_mid_period(self):
        # re-hire inside the period: that slip still owns the carry-forward of the previous, already-ended contract
        employee = self._make_employee(
            'fixed', worklog_ot_enabled=True, hourly_wage=10.0,
            contract_date_end=date(2025, 11, 30))
        old_log = self._approve_log(employee, work_date=date(2025, 11, 20), hours=2.0, percentage='100')
        rehire = employee.create_version({
            'date_version': date(2026, 1, 10),
            'contract_date_start': date(2026, 1, 10),
            'contract_date_end': self.contract_end,
            'wage': 1600.0,
        })

        slip = self._make_payslip(employee, version=rehire)
        slip.compute_sheet()

        self.assertEqual(old_log.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertTrue(slip.worked_days_line_ids.filtered(lambda l: l.work_entry_type_id.code == '000.00'))

    def test_earlier_contract_slip_does_not_claim_later_contract_work(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        version_a = employee._get_version(self.period_start)
        version_a.contract_date_end = date(2026, 1, 15)
        version_b = employee.create_version({
            'date_version': date(2026, 1, 16),
            'contract_date_start': date(2026, 1, 16),
            'contract_date_end': self.contract_end,
            'hourly_wage': 20.0,
        })
        early_log = self._approve_log(employee, work_date=date(2026, 1, 8), hours=2.0, percentage='100')
        late_log = self._approve_log(employee, work_date=date(2026, 1, 20), hours=2.0, percentage='100')

        slip_b = self._make_payslip(employee, version=version_b)
        slip_a = self._make_payslip(employee, version=version_a)
        slip_b.compute_sheet()
        slip_a.compute_sheet()

        self.assertEqual(early_log.settlement_ids.filtered('active_claim').payslip_id, slip_a)
        self.assertEqual(late_log.settlement_ids.filtered('active_claim').payslip_id, slip_b)

    def test_cancelling_one_contract_slip_preserves_the_other(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version_a, version_b = self._split_contracts(employee)
        log = self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 20))
        slip_a = self._make_payslip(employee, version=version_a)
        slip_b = self._make_payslip(employee, version=version_b)
        (slip_a | slip_b).compute_sheet()
        (slip_a | slip_b).action_payslip_done()

        slip_a.action_payslip_cancel()

        self.assertEqual(slip_b.state, 'validated')
        self.assertEqual(log.settlement_ids.filtered('active_claim').payslip_id, slip_b)

    def _make_corrected_pair(self):
        employee = self._make_employee('fixed', worklog_ot_enabled=True, hourly_wage=10.0)
        self._approve_log(employee, hours=3.0, percentage='150')
        original = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        refund, correction = self._make_correction_pair(original)
        return original, refund, correction

    def test_correction_total_survives_root_cancellation(self):
        original, refund, correction = self._make_corrected_pair()
        self.assertEqual(correction.gec_component_total('worklog_ot'), 45.0)

        (refund | correction).action_payslip_cancel()
        original.action_payslip_cancel()
        self.assertFalse(original.gec_settlement_ids.filtered('active_claim'))

    def test_whole_chain_cancels_together_in_one_call(self):
        original, refund, correction = self._make_corrected_pair()
        (original | refund | correction).action_payslip_cancel()
        self.assertEqual(original.state, 'cancel')
        self.assertEqual(refund.state, 'cancel')
        self.assertEqual(correction.state, 'cancel')
        self.assertFalse(original.gec_settlement_ids.filtered('active_claim'))
