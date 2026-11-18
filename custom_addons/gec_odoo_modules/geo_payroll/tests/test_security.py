from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollSecurity(GeoPayrollCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worker_user = cls._make_user('GEO Worker')
        cls.manager_user = cls._make_user('GEO Direct Manager')
        cls.outsider_user = cls._make_user('GEO Outsider')
        cls.payroll_user = cls._make_user(
            'GEO Payroll Officer',
            groups=(cls.env.ref('hr_payroll.group_hr_payroll_officer'),),
        )
        cls.hr_manager_user = cls._make_user(
            'GEO HR Manager Without Payroll',
            groups=(cls.env.ref('hr.group_hr_manager'),),
        )
        cls.manager_employee = cls._make_employee('fixed', name='GEO Manager Employee', user=cls.manager_user)
        cls.worker_employee = cls._make_employee(
            'fixed',
            name='GEO Worker Employee',
            user=cls.worker_user,
            parent=cls.manager_employee,
            worklog_ot_enabled=True,
        )
        cls.outsider_employee = cls._make_employee(
            'fixed',
            name='GEO Outsider Employee',
            user=cls.outsider_user,
            worklog_ot_enabled=True,
        )

    def test_employee_saves_work_logs_from_own_profile(self):
        self.worker_user.with_user(self.worker_user).write({'work_log_ids': [Command.create({
            'name': 'Profile log',
            'employee_id': self.worker_employee.id,
            'date': self.period_start,
            'type': 'overtime',
            'hours': 1.0,
        })]})
        self.assertEqual(self.worker_user.work_log_ids.mapped('name'), ['Profile log'])

    def test_employee_can_create_edit_submit_and_read_own_log(self):
        log = self.env['hr.employee.work.log'].with_user(self.worker_user).create({
            'name': 'Own log',
            'employee_id': self.worker_employee.id,
            'date': self.period_start,
            'type': 'overtime',
            'hours': 2.0,
        })
        log.with_user(self.worker_user).write({'name': 'Own edited log'})
        log.with_user(self.worker_user).action_submit()
        self.assertEqual(log.state, 'submitted')
        self.assertEqual(log.with_user(self.worker_user).name, 'Own edited log')

    def test_employee_cannot_edit_own_submitted_log(self):
        log = self._make_work_log(self.worker_employee)
        log.with_user(self.worker_user).action_submit()
        with self.assertRaises(AccessError):
            log.with_user(self.worker_user).write({'name': 'Too late'})

    def test_employee_cannot_read_or_edit_another_employee_log(self):
        other_log = self._make_work_log(self.outsider_employee)
        with self.assertRaises(AccessError):
            other_log.with_user(self.worker_user).read(['name'])
        with self.assertRaises(AccessError):
            other_log.with_user(self.worker_user).write({'name': 'Forbidden'})

    def test_employee_cannot_create_log_for_someone_else(self):
        with self.assertRaises(AccessError):
            self.env['hr.employee.work.log'].with_user(self.worker_user).create({
                'name': 'Forged other log',
                'employee_id': self.outsider_employee.id,
                'date': self.period_start,
                'type': 'overtime',
                'hours': 2.0,
            })

    def test_employee_cannot_reassign_own_log(self):
        log = self._make_work_log(self.worker_employee)
        with self.assertRaises(UserError):
            log.with_user(self.worker_user).write({'employee_id': self.outsider_employee.id})

    def test_profile_nested_create_uses_real_user_rules(self):
        # One2many hardening restores the origin user; switch it too, as a real RPC request does.
        old_uid = self.uid
        try:
            self.uid = self.worker_user.id
            with self.assertRaises(AccessError):
                self.worker_user.write({
                    'work_log_ids': [Command.create({
                        'name': 'Nested forged log',
                        'employee_id': self.outsider_employee.id,
                        'date': self.period_start,
                        'type': 'overtime',
                        'hours': 2.0,
                    })],
                })
        finally:
            self.uid = old_uid

    def test_profile_nested_create_for_self_succeeds(self):
        old_uid = self.uid
        try:
            self.uid = self.worker_user.id
            self.worker_user.write({
                'work_log_ids': [Command.create({
                    'name': 'Nested own log',
                    'date': self.period_start,
                    'type': 'overtime',
                    'hours': 2.0,
                })],
            })
        finally:
            self.uid = old_uid
        own_log = self.worker_user.work_log_ids.filtered(lambda log: log.name == 'Nested own log')
        self.assertEqual(own_log.employee_id, self.worker_employee)
        self.assertEqual(own_log.user_id, self.worker_user)

    def test_employee_cannot_approve_own_log(self):
        log = self._make_work_log(self.worker_employee)
        with self.assertRaises(UserError):
            log.with_user(self.worker_user).action_approve()

    def test_direct_manager_can_create_and_approve_report_log(self):
        log = self.env['hr.employee.work.log'].with_user(self.manager_user).create({
            'name': 'Manager-entered report log',
            'employee_id': self.worker_employee.id,
            'date': self.period_start,
            'type': 'overtime',
            'hours': 2.0,
        })
        log.with_user(self.manager_user).action_approve()
        self.assertEqual(log.state, 'approved')
        self.assertEqual(log.approved_by_id, self.manager_user)

    def test_unrelated_user_cannot_approve_or_reject(self):
        log = self._make_work_log(self.worker_employee)
        log.action_submit()
        with self.assertRaises(UserError):
            log.with_user(self.outsider_user).action_approve()
        with self.assertRaises(UserError):
            log.with_user(self.outsider_user).action_reject()

    def test_payroll_user_can_approve_without_manager_relationship(self):
        log = self._make_work_log(self.outsider_employee)
        log.with_user(self.payroll_user).action_approve()
        self.assertEqual(log.state, 'approved')
        self.assertEqual(log.approved_by_id, self.payroll_user)

    def test_payroll_assistant_reads_but_cannot_approve_or_change_limits(self):
        """Assistant is the lowest payroll group: approval needs an officer, limits an administrator."""
        assistant = self._make_user('GEO Payroll Assistant', groups=(self.env.ref('hr_payroll.group_hr_payroll_user'),))
        log = self._make_work_log(self.outsider_employee)
        self.assertTrue(log.with_user(assistant).has_access('read'))
        with self.assertRaises(UserError):
            log.with_user(assistant).action_approve()
        exemption = self.env.ref('geo_payroll.tax_exemption_single_mother')
        self.assertTrue(exemption.with_user(assistant).has_access('read'))
        with self.assertRaises(AccessError):
            exemption.with_user(assistant).yearly_limit = 1.0

    def test_payroll_employee_can_approve_own_log(self):
        payroll_employee = self._make_employee('fixed', user=self.payroll_user, worklog_ot_enabled=True)
        log = self._make_work_log(payroll_employee)
        log.with_user(self.payroll_user).action_approve()
        self.assertEqual(log.state, 'approved')

    def test_non_payroll_user_cannot_cancel(self):
        log = self._make_work_log(self.worker_employee)
        with self.assertRaises(UserError):
            log.with_user(self.worker_user).action_cancel()

    def test_snapshot_fields_are_hidden_from_normal_employee(self):
        log = self._make_work_log(self.worker_employee)
        with self.assertRaises(AccessError):
            log.with_user(self.worker_user).read(['version_id', 'rate_snapshot', 'amount_snapshot'])

    def test_payroll_reassignment_resynchronizes_owner_user(self):
        log = self._make_work_log(self.worker_employee)
        log.write({'employee_id': self.outsider_employee.id})
        self.assertEqual(log.employee_id, self.outsider_employee)
        self.assertEqual(log.user_id, self.outsider_user)

    def test_company_rule_hides_other_company_logs(self):
        other_company = self.env['res.company'].create({
            'name': 'GEO Other Company',
            'country_id': self.env.ref('base.ge').id,
        })
        other_user = self._make_user('Other Company Worker', company=other_company)
        other_employee = self._make_employee(
            'fixed',
            name='Other Company Employee',
            company=other_company,
            user=other_user,
            worklog_ot_enabled=True,
        )
        other_log = self._make_work_log(other_employee)
        with self.assertRaises(AccessError):
            other_log.with_user(self.payroll_user).read(['name'])

    def test_hr_manager_without_payroll_can_batch_edit_hr_version_fields(self):
        """Hidden payroll source reads must not block ordinary HR version writes."""
        self.assertFalse(self.hr_manager_user.has_group('hr_payroll.group_hr_payroll_user'))
        employees = self._make_employee('fixed') | self._make_employee('fixed')
        versions = employees.mapped('version_id')
        department = self.env['hr.department'].create({'name': self._next_name('GEO HR Department')})

        versions.with_user(self.hr_manager_user).write({'department_id': department.id})
        self.assertEqual(versions.mapped('department_id'), department)
        with self.assertRaises(AccessError):
            versions[0].with_user(self.hr_manager_user).read(['hourly_source'])

    def test_hr_manager_without_payroll_keeps_core_contract_date_access(self):
        version = self._make_employee('fixed').version_id

        version.with_user(self.hr_manager_user).write({'contract_date_end': date(2027, 11, 30)})
        self.assertEqual(version.contract_date_end, date(2027, 11, 30))

    def test_hr_manager_unrelated_write_does_not_repair_hidden_legacy_sources(self):
        """A non-payroll HR write succeeds without silently changing payroll config."""
        version = self._seed_legacy_sources(self._make_employee('fixed').version_id)

        department = self.env['hr.department'].create({'name': self._next_name('GEO Legacy Source Department')})
        version.with_user(self.hr_manager_user).write({'department_id': department.id})

        self.assertEqual(version.department_id, department)
        self.assertEqual(version.sudo().hourly_source, 'timesheet')

    def test_payroll_officer_recompute_can_release_stale_claims(self):
        """Stale-claim release runs under the payroll user's own rights; the ledger still cannot be deleted."""
        employee = self._make_employee('fixed_hourly', worklog_ot_enabled=True, hourly_wage=10.0)
        self._approve_log(employee, hours=2.0, percentage='150')
        self._make_timesheet(employee, hours=2.0)
        payslip = self._make_payslip(employee, worked_hours=160.0)
        payslip.compute_sheet()
        settlements = payslip.gec_settlement_ids.filtered('active_claim')
        self.assertEqual(len(settlements), 2)
        self.assertFalse(settlements.with_user(self.payroll_user).has_access('unlink'))
        off_cycle = self.structures['monthly'].copy({'name': self._next_name('GEO Officer Off-Cycle')})

        officer_slip = payslip.with_user(self.payroll_user)
        officer_slip.write({'struct_id': off_cycle.id})
        officer_slip.compute_sheet()

        self.assertFalse(settlements.filtered('active_claim'))
        self.assertEqual(set(settlements.mapped('release_reason')), {'Payslip recomputed'})
