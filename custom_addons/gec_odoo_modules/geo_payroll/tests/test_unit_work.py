from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollUnitRate(GeoPayrollCase):
    def test_price_must_be_positive(self):
        for bad_price in (0.0, -5.0):
            with self.subTest(price=bad_price), self.assertRaises(ValidationError):
                self._make_unit_rate(price=bad_price)

    def test_manager_manages_officer_and_user_read_only(self):
        rate = self._make_unit_rate(price=10.0)
        officer = self._make_user('GEO Rate Officer', groups=(self.env.ref('hr_payroll.group_hr_payroll_user'),))
        normal = self._make_user('GEO Rate Reader')
        for user in (officer, normal):
            self.assertEqual(rate.with_user(user).name, rate.name)
            with self.assertRaises(AccessError):
                rate.with_user(user).write({'price_per_unit': 99.0})
            with self.assertRaises(AccessError):
                self.env['hr.payroll.unit.rate'].with_user(user).create({
                    'name': 'Forged rate',
                    'uom_id': self.uom_sqm.id,
                    'price_per_unit': 1.0,
                    'currency_id': self.company.currency_id.id,
                })
            with self.assertRaises(AccessError):
                rate.with_user(user).unlink()

    def test_referenced_rate_cannot_be_deleted_unreferenced_can(self):
        used = self._make_unit_rate(price=10.0)
        employee = self._make_employee('unit')
        self._approve_log(employee, log_type='unit', work_unit=used, unit_qty=2.0)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            used.unlink()
        unused = self._make_unit_rate(price=10.0)
        unused.unlink()
        self.assertFalse(unused.exists())


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollUnitWorkLog(GeoPayrollCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rate_sqm = cls._make_unit_rate(name='GEO Tile Laying', price=10.0, uom=cls.uom_sqm)
        cls.rate_piece = cls._make_unit_rate(name='GEO Door Fitting', price=3.5, uom=cls.uom_unit)

    def test_unit_quantity_boundaries(self):
        employee = self._make_employee('unit')
        for invalid in (-1.0, 0.0, 0.004):
            with self.subTest(qty=invalid), self.assertRaises(ValidationError):
                self._make_work_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=invalid)
        huge = self._make_work_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=999999.99)
        self.assertEqual(huge.unit_qty, 999999.99)

    def test_unit_log_requires_rate_item(self):
        employee = self._make_employee('unit')
        with self.assertRaises(ValidationError):
            self._make_work_log(employee, log_type='unit', unit_qty=1.0)

    def test_cross_field_hygiene_in_both_directions(self):
        employee = self._make_employee('unit', worklog_ot_enabled=True)
        illogical = (
            {'log_type': 'unit', 'work_unit': self.rate_sqm, 'unit_qty': 1.0, 'hours': 2.0},
            {'log_type': 'unit', 'work_unit': self.rate_sqm, 'unit_qty': 1.0, 'units': 1.0},
            {'log_type': 'overtime', 'hours': 2.0, 'unit_qty': 1.0},
            {'log_type': 'overtime', 'hours': 2.0, 'work_unit': self.rate_sqm},
            {'log_type': 'daily', 'units': 1.0, 'unit_qty': 1.0},
            {'log_type': 'daily', 'units': 1.0, 'work_unit': self.rate_sqm},
        )
        foreign = {'unit': ('hours', 'units'), 'overtime': ('units', 'unit_qty', 'work_unit_id'), 'daily': ('hours', 'unit_qty', 'work_unit_id')}
        for index, values in enumerate(illogical):
            with self.subTest(values=values):
                log = self._make_work_log(employee, work_date=date(2026, 1, 1 + index), **values)
                self.assertFalse(any(log[field] for field in foreign[values['log_type']]))

    def test_onchange_type_clears_foreign_quantities(self):
        employee = self._make_employee('unit')
        form = Form(self.env['hr.employee.work.log'])
        form.employee_id = employee
        form.name = 'Unit onchange log'
        form.type = 'unit'
        form.work_unit_id = self.rate_sqm
        form.unit_qty = 5.0
        form.type = 'daily'
        self.assertFalse(form.work_unit_id)
        self.assertEqual(form.unit_qty, 0.0)
        self.assertEqual(form.units, 1.0)
        form.type = 'unit'
        self.assertEqual(form.unit_qty, 1.0)
        self.assertEqual(form.units, 0.0)

    def test_multiple_unit_logs_same_day_and_item_are_allowed(self):
        employee = self._make_employee('unit')
        logs = self.env['hr.employee.work.log']
        for qty in (2.0, 3.0, 4.0):
            logs |= self._make_work_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=qty)
        logs |= self._make_work_log(employee, log_type='unit', work_unit=self.rate_piece, unit_qty=1.0)
        logs.action_approve()
        self.assertEqual(set(logs.mapped('state')), {'approved'})

    def test_forged_create_strips_unit_snapshot(self):
        employee = self._make_employee('unit')
        log = self._make_work_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=1.0,
            state='approved',
            unit_uom_snapshot_id=self.uom_unit.id,
            rate_snapshot=999.0,
            amount_snapshot=999.0,
        )
        self.assertRecordValues(log, [{
            'state': 'draft',
            'unit_uom_snapshot_id': False,
            'rate_snapshot': 0.0,
            'amount_snapshot': 0.0,
        }])

    def test_direct_unit_snapshot_write_is_forbidden(self):
        employee = self._make_employee('unit')
        log = self._make_work_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=1.0)
        with self.assertRaises(UserError):
            log.write({'unit_uom_snapshot_id': self.uom_unit.id})
        with self.assertRaises(UserError):
            log.sudo().write({'unit_uom_snapshot_id': self.uom_unit.id})

    def test_approval_freezes_price_amount_uom_and_identity(self):
        employee = self._make_employee('unit')
        log = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=12.5)
        self.assertRecordValues(log, [{
            'state': 'approved',
            'version_id': employee.version_id.id,
            'rate_snapshot': 10.0,
            'amount_snapshot': 125.0,
            'component_code_snapshot': 'unit_basic',
            'currency_id_snapshot': self.company.currency_id.id,
            'unit_uom_snapshot_id': self.uom_sqm.id,
        }])
        with self.assertRaises(UserError):
            log.write({'unit_qty': 50.0})
        with self.assertRaises(UserError):
            log.write({'work_unit_id': self.rate_piece.id})

    def test_catalog_price_change_never_reprices_approved_log(self):
        employee = self._make_employee('unit')
        approved = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=10.0)
        self.rate_sqm.price_per_unit = 15.0
        self.assertEqual(approved.rate_snapshot, 10.0)
        self.assertEqual(approved.amount_snapshot, 100.0)
        later = self._approve_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=10.0,
            work_date=self.period_start.replace(day=2))
        self.assertEqual(later.amount_snapshot, 150.0)

    def test_catalog_uom_change_never_relabels_approved_log(self):
        employee = self._make_employee('unit')
        approved = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=4.0)
        draft = self._make_work_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=4.0,
            work_date=self.period_start.replace(day=2))
        self.rate_sqm.uom_id = self.uom_unit
        self.assertEqual(approved.unit_uom_snapshot_id, self.uom_sqm)
        self.assertEqual(approved.unit_uom_id, self.uom_sqm)
        self.assertEqual(draft.unit_uom_id, self.uom_unit)

    def test_display_fields_for_employee_switch_from_live_to_frozen(self):
        worker = self._make_user('GEO Unit Worker')
        employee = self._make_employee('unit', user=worker)
        log = self.env['hr.employee.work.log'].with_user(worker).create({
            'name': 'Own unit log',
            'employee_id': employee.id,
            'date': self.period_start,
            'type': 'unit',
            'work_unit_id': self.rate_sqm.id,
            'unit_qty': 3.0,
        }).with_env(self.env)
        as_worker = log.with_user(worker)
        self.assertEqual(as_worker.unit_price_display, 10.0)
        self.assertEqual(as_worker.unit_amount_display, 30.0)
        log.action_approve()
        self.rate_sqm.price_per_unit = 99.0
        self.rate_sqm.uom_id = self.uom_unit
        as_worker.invalidate_recordset()
        self.assertEqual(as_worker.unit_price_display, 10.0)
        self.assertEqual(as_worker.unit_amount_display, 30.0)
        self.assertEqual(as_worker.unit_uom_id, self.uom_sqm)
        with self.assertRaises(AccessError):
            as_worker.read(['rate_snapshot', 'unit_uom_snapshot_id'])

    def test_cancelled_approved_log_keeps_frozen_display(self):
        employee = self._make_employee('unit')
        log = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=3.0)
        log.action_cancel()
        self.rate_sqm.price_per_unit = 99.0
        self.rate_sqm.uom_id = self.uom_unit
        self.assertEqual(log.state, 'cancelled')
        self.assertEqual(log.unit_price_display, 10.0)
        self.assertEqual(log.unit_amount_display, 30.0)
        self.assertEqual(log.unit_uom_id, self.uom_sqm)

    def test_reset_to_draft_clears_unit_snapshot(self):
        employee = self._make_employee('unit')
        log = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=2.0)
        log.action_reset_to_draft()
        self.assertRecordValues(log, [{
            'state': 'draft',
            'unit_uom_snapshot_id': False,
            'rate_snapshot': 0.0,
            'amount_snapshot': 0.0,
            'component_code_snapshot': False,
        }])

    def test_unit_log_refused_on_every_legacy_scheme(self):
        for scheme in ('fixed', 'hourly', 'daily', 'fixed_daily', 'fixed_hourly', 'daily_hourly'):
            with self.subTest(scheme=scheme):
                employee = self._make_employee(scheme)
                log = self._make_work_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=1.0)
                with self.assertRaisesRegex(UserError, 'does not pay'):
                    log.action_approve()

    def test_daily_log_refused_on_pure_unit_scheme(self):
        employee = self._make_employee('unit')
        log = self._make_work_log(employee, log_type='daily')
        with self.assertRaisesRegex(UserError, 'does not pay'):
            log.action_approve()

    def test_archived_rate_blocks_new_approval_not_existing_pay(self):
        employee = self._make_employee('unit')
        rate = self._make_unit_rate(price=20.0)
        approved = self._approve_log(employee, log_type='unit', work_unit=rate, unit_qty=2.0)
        rate.action_archive()
        pending = self._make_work_log(
            employee, log_type='unit', work_unit=rate, unit_qty=2.0,
            work_date=self.period_start.replace(day=2))
        with self.assertRaisesRegex(UserError, 'archived'):
            pending.action_approve()
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertEqual(approved.settlement_ids.filtered('active_claim').payslip_id, payslip)
        self.assertEqual(self._line_total(payslip, 'UNIT_BASIC'), 40.0)

    def test_currency_mismatch_blocks_approval(self):
        other_currency = self.env.ref('base.EUR')
        if other_currency == self.company.currency_id:
            other_currency = self.env.ref('base.USD')
        other_currency.active = True
        foreign_rate = self._make_unit_rate(price=10.0, currency_id=other_currency.id)
        employee = self._make_employee('unit')
        log = self._make_work_log(employee, log_type='unit', work_unit=foreign_rate, unit_qty=1.0)
        with self.assertRaisesRegex(UserError, 'currency'):
            log.action_approve()

    def test_overtime_still_needs_hourly_wage_on_unit_scheme(self):
        employee = self._make_employee('unit', worklog_ot_enabled=True, hourly_wage=0.0)
        log = self._make_work_log(employee, hours=2.0)
        with self.assertRaisesRegex(UserError, 'Hourly Wage'):
            log.action_approve()


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollUnitSchemes(GeoPayrollCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rate_sqm = cls._make_unit_rate(name='GEO Plastering', price=10.0, uom=cls.uom_sqm)
        cls.rate_piece = cls._make_unit_rate(name='GEO Socket Install', price=3.5, uom=cls.uom_unit)

    def test_pure_unit_pays_only_approved_unit_logs(self):
        employee = self._make_employee('unit')
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=12.5)
        self._approve_log(
            employee, log_type='unit', work_unit=self.rate_piece, unit_qty=4.0,
            work_date=self.period_start.replace(day=2))
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(payslip.worked_days_line_ids.mapped('amount'), [0.0])
        self.assertEqual(sum(payslip.worked_days_line_ids.mapped('amount')), 0.0)
        self.assertEqual(self._line_total(payslip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(payslip, 'UNIT_BASIC'), 139.0)
        self.assertEqual(self._line_total(payslip, 'GROSS'), 139.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 111.2)
        settlements = payslip.gec_settlement_ids.filtered('active_claim')
        self.assertRecordValues(settlements.sorted('amount'), [
            {'component_code': 'unit_basic', 'quantity': 4.0, 'rate': 3.5,
             'amount': 14.0, 'uom_id': self.uom_unit.id},
            {'component_code': 'unit_basic', 'quantity': 12.5, 'rate': 10.0,
             'amount': 125.0, 'uom_id': self.uom_sqm.id},
        ])
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_pure_unit_zero_month_confirms_at_zero(self):
        employee = self._make_employee('unit')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'GROSS'), 0.0)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_daily_unit_pays_both_sources_and_overtime(self):
        employee = self._make_employee('daily_unit', daily_wage=80.0, worklog_ot_enabled=True, hourly_wage=10.0)
        self._approve_log(employee, log_type='daily', units=1.0, work_date=date(2026, 1, 5))
        self._approve_log(employee, log_type='daily', units=0.5, work_date=date(2026, 1, 6))
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=10.0, work_date=date(2026, 1, 7))
        self._approve_log(
            employee, log_type='unit', work_unit=self.rate_piece, unit_qty=20.0,
            work_date=date(2026, 1, 8))
        self._approve_log(employee, hours=2.0, percentage='150', work_date=date(2026, 1, 9))
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 120.0)
        self.assertEqual(self._line_total(payslip, 'UNIT_EXTRA'), 170.0)
        self.assertEqual(self._line_total(payslip, 'UNIT_BASIC'), 0.0)
        self.assertEqual(self._line_total(payslip, 'WORKLOG_OT'), 30.0)
        self.assertEqual(self._line_total(payslip, 'GROSS'), 320.0)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_daily_unit_same_day_daily_and_unit_both_pay_by_design(self):
        employee = self._make_employee('daily_unit', daily_wage=80.0)
        work_day = date(2026, 1, 5)
        self._approve_log(employee, log_type='daily', units=1.0, work_date=work_day)
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=8.0, work_date=work_day)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)
        self.assertEqual(self._line_total(payslip, 'UNIT_EXTRA'), 80.0)

    def test_fixed_to_unit_switch_keeps_wage_value_but_pays_zero_base(self):
        employee = self._make_employee('fixed', wage=1600.0)
        version = employee.version_id
        version.write({'pay_scheme': 'unit', 'structure_type_id': self.structure_types['unit'].id})
        self.assertEqual(version.wage, 1600.0)
        self.assertEqual(version.wage_type, 'unit')
        self.assertEqual(version._get_contract_wage(), 0.0)
        self.assertEqual(version._get_normalized_wage(), 0.0)
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=5.0)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self.assertEqual(self._line_total(payslip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(payslip, 'UNIT_BASIC'), 50.0)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

    def test_confirm_blocks_tampered_worked_day_amount(self):
        employee = self._make_employee('unit')
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=2.0)
        payslip = self._make_payslip(employee, worked_hours=8.0, worked_days=1.0)
        payslip.compute_sheet()
        self.assertEqual(payslip.worked_days_line_ids.mapped('amount'), [0.0])
        payslip.worked_days_line_ids[0].amount = 80.0
        with self.assertRaisesRegex(UserError, 'instead of work logs'):
            payslip.action_payslip_done()

    def test_confirm_blocks_tampered_unit_line(self):
        employee = self._make_employee('unit')
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=2.0)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        payslip.line_ids.filtered(lambda line: line.code == 'UNIT_BASIC').total += 1.0
        with self.assertRaisesRegex(UserError, 'does not match its work logs'):
            payslip.action_payslip_done()

    def test_confirm_blocks_unclaimed_unit_log(self):
        employee = self._make_employee('unit')
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=1.0)
        with self.assertRaisesRegex(UserError, 'missing from the payslip'):
            payslip.action_payslip_done()

    def test_recompute_is_idempotent(self):
        employee = self._make_employee('unit')
        log = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        claim = log.settlement_ids.filtered('active_claim')
        payslip.compute_sheet()
        self.assertEqual(log.settlement_ids.filtered('active_claim'), claim)
        self.assertEqual(len(log.settlement_ids), 1)
        self.assertEqual(self._line_total(payslip, 'UNIT_BASIC'), 30.0)

    def test_cancel_releases_and_reopen_reclaims(self):
        employee = self._make_employee('unit')
        log = self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=3.0)
        payslip = self._make_payslip(employee)
        payslip.compute_sheet()
        old_claim = log.settlement_ids.filtered('active_claim')
        payslip.action_payslip_cancel()
        self.assertFalse(old_claim.active_claim)
        payslip.action_payslip_draft()
        new_claim = log.settlement_ids.filtered('active_claim')
        self.assertTrue(new_claim)
        self.assertNotEqual(new_claim, old_claim)
        self.assertEqual(new_claim.uom_id, self.uom_sqm)

    def test_late_unit_log_carries_forward_across_scheme_switch(self):
        employee = self._make_employee('unit')
        jan_version = employee.version_id
        employee.create_version({
            'date_version': date(2026, 2, 1),
            'pay_scheme': 'fixed',
            'structure_type_id': self.structure_types['monthly'].id,
        })
        late_log = self._approve_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=4.0,
            work_date=date(2026, 1, 20))
        feb_slip = self._make_payslip(
            employee,
            date_from=date(2026, 2, 1),
            date_to=date(2026, 2, 28),
            version=employee._get_version(date(2026, 2, 1)),
            worked_hours=160.0,
        )
        feb_slip.compute_sheet()
        settlement = late_log.settlement_ids.filtered('active_claim')
        self.assertEqual(settlement.payslip_id, feb_slip)
        self.assertEqual(settlement.component_code, 'unit_basic')
        self.assertEqual(settlement.source_version_id, jan_version)
        self.assertEqual(settlement.uom_id, self.uom_sqm)
        self.assertEqual(self._line_total(feb_slip, 'BASIC'), 1600.0)
        self.assertEqual(self._line_total(feb_slip, 'UNIT_BASIC'), 40.0)
        self.assertEqual(self._line_total(feb_slip, 'GROSS'), 1640.0)

    def test_mid_period_version_change_claims_on_one_slip(self):
        employee = self._make_employee('unit')
        version_a = employee._get_version(self.period_start)
        version_b = employee.create_version({'date_version': date(2026, 1, 16)})
        early = self._approve_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=2.0,
            work_date=date(2026, 1, 10))
        late = self._approve_log(
            employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=3.0,
            work_date=date(2026, 1, 20))
        slip = self._make_payslip(employee, version=version_a)
        slip.compute_sheet()
        self.assertEqual(early.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertEqual(late.settlement_ids.filtered('active_claim').payslip_id, slip)
        self.assertEqual(early.settlement_ids.filtered('active_claim').source_version_id, version_a)
        self.assertEqual(late.settlement_ids.filtered('active_claim').source_version_id, version_b)
        self.assertEqual(self._line_total(slip, 'UNIT_BASIC'), 50.0)

    def test_correction_chain_totals_follow_root_and_sign(self):
        employee = self._make_employee('unit')
        self._approve_log(employee, log_type='unit', work_unit=self.rate_sqm, unit_qty=10.0)
        original = self._make_payslip(employee, worked_hours=160.0)
        original.compute_sheet()
        original.action_payslip_done()
        refund, correction = self._make_correction_pair(original)
        self.assertEqual(original.gec_component_total('unit_basic'), 100.0)
        self.assertEqual(refund.gec_component_total('unit_basic'), -100.0)
        self.assertEqual(correction.gec_component_total('unit_basic'), 100.0)
        (refund | correction).action_payslip_done()
        self.assertEqual(self._line_total(refund, 'UNIT_BASIC'), -100.0)
        self.assertEqual(self._line_total(correction, 'UNIT_BASIC'), 100.0)
        self.assertEqual(sum((original | refund | correction).mapped('net_wage')), 80.0)

    def test_payrun_computes_validates_and_resets_unit_slips(self):
        run = self.env['hr.payslip.run'].create({
            'name': self._next_name('GEO Unit Pay Run'),
            'date_start': self.period_start,
            'date_end': self.period_end,
            'structure_id': self.structures['unit'].id,
        })
        worker = self._make_employee('unit')
        idle = self._make_employee('unit')
        log = self._approve_log(worker, log_type='unit', work_unit=self.rate_sqm, unit_qty=6.0)
        worker_slip = self._make_payslip(worker, payslip_run_id=run.id)
        idle_slip = self._make_payslip(idle, payslip_run_id=run.id)
        run.action_confirm()
        self.assertEqual(self._line_total(worker_slip, 'UNIT_BASIC'), 60.0)
        self.assertEqual(self._line_total(worker_slip, 'BASIC'), 0.0)
        self.assertEqual(self._line_total(idle_slip, 'GROSS'), 0.0)
        claim = log.settlement_ids.filtered('active_claim')
        run.action_validate()
        self.assertEqual(set(run.slip_ids.mapped('state')), {'validated'})
        self.assertEqual(log.settlement_state, 'paid')
        run.action_draft()
        self.assertEqual(log.settlement_ids.filtered('active_claim'), claim)
        self.assertEqual(len(log.settlement_ids), 1)

    def test_default_struct_repair_fills_only_empty(self):
        stype = self.env['hr.payroll.structure.type'].create({
            'name': 'GEO Repair Target',
            'wage_type': 'unit',
            'country_id': self.env.ref('base.ge').id,
        })
        stype._gec_set_missing_default_struct(self.structures['unit'].id)
        self.assertEqual(stype.default_struct_id, self.structures['unit'])
        other = self.env['hr.payroll.structure'].create({
            'name': 'GEO Repair Other Structure',
            'type_id': stype.id,
            'country_id': self.env.ref('base.ge').id,
            'use_worked_day_lines': True,
        })
        stype._gec_set_missing_default_struct(other.id)
        self.assertEqual(stype.default_struct_id, self.structures['unit'])
