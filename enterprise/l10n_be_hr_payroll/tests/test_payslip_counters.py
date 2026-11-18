from datetime import date

from odoo.fields import Command
from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install', 'post_install_l10n', '-at_install', 'payslip_counter')
class TestPayslipReportCounters(TestPayrollCommon):
    """ Counters rendered in the payslip PDF: supplementary hours and time off. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.struct = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        cls.overtime_type = cls.env.ref('hr_work_entry.be_work_entry_type_overtime')
        cls.voluntary_net_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_voluntary_overtime_net')
        cls.cp302 = cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        # Dedicated time off types: the allocation requirement of a shared one can no
        # longer be changed as soon as a leave of that type exists in the database.
        cls.leave_type = cls._create_time_off_type('Counter Legal Time Off', 'CTRLEGAL')
        cls.employee = cls.create_employee({
            'name': 'Counter Employee',
            'date_version': date(2023, 1, 1),
            'contract_date_start': date(2023, 1, 1),
        })

    @classmethod
    def _create_time_off_type(cls, name, code, **vals):
        return cls.env['hr.work.entry.type'].create({
            'name': name,
            'code': code,
            'country_id': cls.env.ref('base.be').id,
            'count_as': 'absence',
            'requires_allocation': True,
            'request_unit': 'day',
            'unit_of_measure': 'day',
            'leave_validation_type': 'no_validation',
            'allocation_validation_type': 'no_validation',
            **vals,
        })

    def _make_payslip(self, overtime_lines=(), date_from=date(2024, 7, 1), date_to=date(2024, 7, 31), state='draft', employee=None, version=None):
        employee = employee or self.employee
        version = version or employee.version_id
        payslip = self.env['hr.payslip'].create({
            'name': f'Counter Payslip {date_from}',
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'version_id': version.id,
            'struct_id': self.struct.id,
            'date_from': date_from,
            'date_to': date_to,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': work_entry_type.id,
                'version_id': version.id,
                'number_of_hours': hours,
                # the hourly wage of 10 with the rate of the type, as the 274.44 base
                'amount': hours * work_entry_type.amount_rate * 10,
            }) for work_entry_type, hours in overtime_lines],
        })
        payslip.state = state
        return payslip

    def _supplementary_hours(self, payslip):
        section = payslip._l10n_be_get_report_supplementary_hours()
        return [section[key] for key in ('month_with', 'month_without', 'year_with', 'year_without')]

    def _allocate(self, work_entry_type, days=20, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31), employee=None, **vals):
        allocation = self.env['hr.leave.allocation'].sudo().create({
            'name': 'Allocation',
            'employee_id': (employee or self.employee).id,
            'work_entry_type_id': work_entry_type.id,
            'number_of_days': days,
            'date_from': date_from,
            'date_to': date_to,
            **vals,
        })
        allocation.action_approve()
        return allocation

    def _take_leave(self, work_entry_type, date_from, date_to, employee=None):
        self.env['hr.leave'].sudo().create({
            'employee_id': (employee or self.employee).id,
            'work_entry_type_id': work_entry_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        }).action_approve()

    def _counter(self, payslip):
        [counter] = payslip._l10n_be_get_report_time_off_counters()['time_off']
        return [round(counter[key], 2) for key in ('initial', 'previous', 'earned', 'taken', 'final')]

    def _render(self, payslip, report='l10n_be_hr_payroll.action_report_payslip_be'):
        return str(self.env['ir.actions.report']._render_qweb_html(report, payslip.ids)[0])

    def test_supplementary_hours_split_on_reduction(self):
        """Only the overtime opening a right to an overtime supplement is tax reduced."""
        payslip = self._make_payslip([(self.overtime_type, 6.0), (self.voluntary_net_type, 4.0)])
        self.assertEqual(self._supplementary_hours(payslip), [6.0, 4.0, 6.0, 4.0])

    def test_supplementary_hours_quota_exhausted(self):
        """Once the yearly quota is reached the extra hours move to the second bucket."""
        quota = self.env['hr.rule.parameter']._get_parameter_from_code('cp200_overtime_threshold', date(2024, 7, 31))
        self.assertEqual(quota, 180, "fixture relies on the CP200 quota")
        self._make_payslip([(self.overtime_type, 175.0)], date(2024, 6, 1), date(2024, 6, 30), state='paid')
        payslip = self._make_payslip([(self.overtime_type, 20.0)])
        self.assertEqual(self._supplementary_hours(payslip), [5.0, 15.0, 180.0, 15.0])

    def test_supplementary_hours_cp302_quota(self):
        """The hotel industry has its own quota, whatever the cash register (circular 2024/C/6)."""
        employee = self.create_employee({
            'name': 'Counter CP302 Employee',
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'l10n_be_joint_committee_id': self.cp302.id,
        })
        self._make_payslip([(self.overtime_type, 350.0)], date(2024, 6, 1), date(2024, 6, 30), state='paid', employee=employee)
        payslip = self._make_payslip([(self.overtime_type, 20.0)], employee=employee)
        company = employee.company_id
        for cash_register in (False, True):
            company.l10n_be_cash_register_active = cash_register
            quota = payslip._l10n_be_get_overtime_cap('302', company, payslip.date_from)
            self.assertEqual(quota, 360, "fixture relies on the CP302 quota")
            self.assertEqual(self._supplementary_hours(payslip), [10.0, 10.0, 360.0, 10.0])

    def test_supplementary_hours_joint_committee_change(self):
        """Each joint committee of the year has its own quota, the one of the payslip's version."""
        employee = self.create_employee({
            'name': 'Counter Changing Employee',
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
        })
        june_version = employee.version_id
        july_version = employee.create_version({
            'date_version': date(2024, 7, 1),
            'l10n_be_joint_committee_id': self.cp302.id,
        })
        self._make_payslip([(self.overtime_type, 190.0)], date(2024, 6, 1), date(2024, 6, 30), state='paid', employee=employee, version=june_version)
        payslip = self._make_payslip([(self.overtime_type, 20.0)], employee=employee, version=july_version)
        # 180 of the 190 hours of June within the CP200 quota, the 20 of July within the CP302 one
        self.assertEqual(self._supplementary_hours(payslip), [20.0, 0.0, 200.0, 10.0])

    def test_supplementary_hours_same_as_274(self):
        """The supplementary hours with a reduced tax burden are the base of the 274.44 exemption."""
        self._make_payslip([(self.overtime_type, 100.0)], date(2024, 5, 1), date(2024, 5, 31), state='paid')
        june = self._make_payslip([(self.overtime_type, 60.0)], date(2024, 6, 1), date(2024, 6, 30), state='paid')
        july = self._make_payslip([(self.overtime_type, 30.0), (self.voluntary_net_type, 4.0)], state='validated')
        sheet = self.env['l10n_be.274_xx']
        for payslip, expected_hours in ((june, 60.0), (july, 20.0)):
            month_with = payslip._l10n_be_get_report_supplementary_hours()['month_with']
            self.assertEqual(month_with, expected_hours)
            [line] = sheet._get_extra_hours_lines_ids(payslip, payslip.date_from, {'PPTOTAL': {payslip.id: {'total': 0}}})[0]
            self.assertEqual(line['nature_code'], '274.44')
            # the hourly wage of the fixture is 10
            self.assertAlmostEqual(line['taxable_amount'], month_with * 10, places=2)

    def test_supplementary_hours_hidden_without_extra_hours(self):
        """The supplementary hours table is only printed with supplementary hours."""
        director = self.create_employee({
            'name': 'Counter Director',
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'l10n_be_joint_committee_id': self.env['l10n.be.joint.committee'].search([('egov3_code', '=', '999')], limit=1).id,
        })
        payslip = self._make_payslip(employee=director)
        # the Extra Information section is only printed with some third party information
        payslip.payroll_config_id.sudo().group_insurance_name = 'Counter Group Insurance'
        self.assertEqual(self._supplementary_hours(payslip), [0.0, 0.0, 0.0, 0.0])
        html = self._render(payslip)
        self.assertNotIn('l10n_be_counters', html)
        self.assertIn('l10n_be_salary_heading', html)
        self.assertIn('l10n_be_extra_information_heading', html)

        payslip = self._make_payslip([(self.voluntary_net_type, 4.0)], employee=director)
        self.assertEqual(self._supplementary_hours(payslip), [0.0, 4.0, 0.0, 4.0])
        self.assertIn('l10n_be_supplementary_hours_table', self._render(payslip))

    def test_time_off_counter_chains_across_months(self):
        """Leaves taken earlier open the balance, and a leave crossing the end of the
            month only counts its elapsed part so that August opens where July closed.
        """
        self._allocate(self.leave_type)
        self._take_leave(self.leave_type, date(2024, 3, 11), date(2024, 3, 12))
        self._take_leave(self.leave_type, date(2024, 7, 8), date(2024, 7, 9))
        self._take_leave(self.leave_type, date(2024, 7, 29), date(2024, 8, 2))
        self._take_leave(self.leave_type, date(2024, 8, 5), date(2024, 8, 6))

        # initial, previous, earned, taken, final
        self.assertEqual(self._counter(self._make_payslip()), [20.0, 18.0, 0.0, 5.0, 13.0])
        august = self._make_payslip(date_from=date(2024, 8, 1), date_to=date(2024, 8, 31))
        self.assertEqual(self._counter(august), [20.0, 13.0, 0.0, 4.0, 9.0])
        # the allocation of the start of the year is the initial budget of January, not earned in January
        january = self._make_payslip(date_from=date(2024, 1, 1), date_to=date(2024, 1, 31))
        self.assertEqual(self._counter(january), [20.0, 20.0, 0.0, 0.0, 20.0])

    def test_time_off_counter_display(self):
        """An allocation that did not move is reported while days are left on it, but neither
            an allocation used up before the period nor a time off without allocation is.
        """
        used_up_type = self._create_time_off_type('Counter Used Up Time Off', 'CTRUSED')
        no_allocation_type = self._create_time_off_type(
            'Counter Time Off Without Allocation', 'CTRNOALLOC', requires_allocation=False)
        self._allocate(self.leave_type)
        self._allocate(used_up_type, days=2)
        self._take_leave(used_up_type, date(2024, 3, 11), date(2024, 3, 12))
        self._take_leave(no_allocation_type, date(2024, 7, 8), date(2024, 7, 9))
        self.assertEqual(self._counter(self._make_payslip()), [20.0, 20.0, 0.0, 0.0, 20.0])

    def test_time_off_counter_contract_start_and_later_allocation(self):
        """The allocation of the start of the contract is the initial budget, a later one is earned."""
        employee = self.create_employee({
            'name': 'Counter Newcomer',
            'date_version': date(2024, 3, 15),
            'contract_date_start': date(2024, 3, 15),
        })
        self._allocate(self.leave_type, days=10, date_from=date(2024, 3, 15), employee=employee)
        self._allocate(self.leave_type, days=5, date_from=date(2024, 7, 10), employee=employee)
        self._take_leave(self.leave_type, date(2024, 7, 15), date(2024, 7, 16), employee=employee)

        march = self._make_payslip(date_from=date(2024, 3, 1), date_to=date(2024, 3, 31), employee=employee)
        self.assertEqual(self._counter(march), [10.0, 10.0, 0.0, 0.0, 10.0])
        july = self._make_payslip(employee=employee)
        self.assertEqual(self._counter(july), [10.0, 10.0, 5.0, 2.0, 13.0])
        august = self._make_payslip(date_from=date(2024, 8, 1), date_to=date(2024, 8, 31), employee=employee)
        self.assertEqual(self._counter(august), [10.0, 13.0, 0.0, 0.0, 13.0])

    def test_time_off_counter_accrual(self):
        """An accrual plan grants its time off at each accrual date: what is granted at the start of
            the year is the initial budget, then each month earns its own accrual, whatever was
            accrued since the payslip's period.
        """
        accrual_type = self._create_time_off_type('Counter Accrual Time Off', 'CTRACCRUAL')
        plan = self.env['hr.leave.accrual.plan'].create({
            'name': 'Counter Monthly Accrual',
            'accrued_gain_time': 'start',
            'can_be_carryover': False,
            'work_entry_type_id': accrual_type.id,
            'level_ids': [Command.create({
                'milestone_date': 'creation',
                'added_value_type': 'day',
                'added_value': 2,
                'frequency': 'monthly',
                'first_day': '1',
            })],
        })
        allocation = self._allocate(
            accrual_type, days=0, date_to=False, accrual_plan_id=plan.id)
        # the cron accrues up to today: the counters of the past don't depend on it
        allocation._update_accrual()
        self._take_leave(accrual_type, date(2024, 3, 11), date(2024, 3, 12))
        self._take_leave(accrual_type, date(2024, 7, 8), date(2024, 7, 8))

        # initial, previous, earned, taken, final
        self.assertEqual(self._counter(self._make_payslip()), [2.0, 10.0, 2.0, 1.0, 11.0])
        january = self._make_payslip(date_from=date(2024, 1, 1), date_to=date(2024, 1, 31))
        self.assertEqual(self._counter(january), [2.0, 2.0, 0.0, 0.0, 2.0])
        february = self._make_payslip(date_from=date(2024, 2, 1), date_to=date(2024, 2, 29))
        self.assertEqual(self._counter(february), [2.0, 2.0, 2.0, 0.0, 4.0])

    def test_counters_only_on_monthly_payslip_report(self):
        """The counters are printed on the monthly payslip, not on the holiday attests."""
        self._allocate(self.leave_type)
        payslip = self._make_payslip([(self.overtime_type, 6.0)])
        html = self._render(payslip)
        self.assertIn('l10n_be_counters', html)
        self.assertIn('l10n_be_supplementary_hours_table', html)
        self.assertIn('l10n_be_time_off_counters_table', html)
        self.assertIn('Counter Legal Time Off', html)
        for report in (
            'l10n_be_hr_payroll.action_report_termination_holiday_n',
            'l10n_be_hr_payroll.action_report_termination_holiday_n1',
        ):
            self.assertNotIn('l10n_be_counters', self._render(payslip, report))
