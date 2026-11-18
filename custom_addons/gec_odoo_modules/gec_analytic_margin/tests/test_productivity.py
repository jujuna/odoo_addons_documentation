from odoo import Command
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestRevenuePerFTE(GecMarginCommon):
    """Average FTE (March 2025, own company) and revenue per FTE.
    Full-timer 1, half-timer 0.5, starter on the 17th 15/31, leaver on the 10th 10/31,
    contractor 1, employee with no contract dates 1: 5.31 in all."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.co = cls.env['res.company'].create({'name': 'T Productivity Co'})
        cls.env.user.company_ids |= cls.co
        cls.half_time = cls.env['resource.calendar'].create({
            'name': 'T Half time', 'company_id': cls.co.id,
        })
        cls.half_time.write({'full_time_required_hours': 40.0, 'hours_per_week': 20.0})
        cls.contractor_type = cls.env['hr.employee.type'].create({'name': 'T Contractor'})

        Employee = cls.env['hr.employee'].with_company(cls.co)

        def hire(name, start='2024-01-01', **vals):
            return Employee.create({
                'name': name, 'company_id': cls.co.id,
                'date_version': start, 'contract_date_start': start, **vals,
            })

        hire('T Full')
        hire('T Half', resource_calendar_id=cls.half_time.id)
        hire('T Starter', start='2025-03-17')
        hire('T Leaver', contract_date_end='2025-03-10')
        hire('T Contractor', employee_type_id=cls.contractor_type.id)
        Employee.create({'name': 'T No Contract', 'company_id': cls.co.id,
                         'date_version': '2024-01-01'})

        stream = cls.env.ref('gec_analytic_margin.revenue_stream_maintenance')
        gl = cls.env['account.account'].create({
            'name': 'T Maintenance', 'code': 'TST996', 'account_type': 'income',
            'company_ids': [Command.set(cls.co.ids)], 'gec_revenue_stream_id': stream.id,
        })
        cls.env['account.analytic.line'].create({
            'name': 'T sale', 'date': '2025-03-15', 'amount': 31000.0,
            'company_id': cls.co.id, 'general_account_id': gl.id, cls.target_col: cls.bl_a.id,
        })
        cls.dashboard = cls.env['gec.margin.dashboard'].with_company(cls.co).with_context(
            allowed_company_ids=cls.co.ids)
        cls.expected_fte = 1 + 0.5 + 15 / 31 + 10 / 31 + 1 + 1

    def _productivity(self, date_from='2025-03-01', date_to='2025-03-31'):
        return self.dashboard.get_dashboard_data(date_from, date_to, self.target_plan.id)['profitability']['productivity']

    def test_average_fte_weights_time_and_schedule(self):
        self.assertAlmostEqual(self.half_time.work_time_rate, 0.5, places=4)
        prod = self._productivity()
        self.assertAlmostEqual(prod['fte'], self.expected_fte, places=3)
        by_type = {t['label']: t['fte'] for t in prod['by_type']}
        self.assertAlmostEqual(by_type['T Contractor'], 1.0, places=4,
                               msg="contractors count, and are shown apart")

    def test_revenue_per_fte_is_annualised(self):
        prod = self._productivity()
        annual = 31000.0 * 365 / 31
        self.assertAlmostEqual(prod['revenue_per_fte'], annual / self.expected_fte, places=0)
        self.assertAlmostEqual(prod['gross_per_fte'], annual / self.expected_fte, places=0)
        self.assertAlmostEqual(prod['recurring_per_fte'], annual / self.expected_fte, places=0)

    def test_the_previous_period_has_its_own_headcount(self):
        prod = self._productivity()
        self.assertAlmostEqual(prod['prev_fte'], 1 + 0.5 + 1 + 1 + 1, places=3)
        self.assertEqual(prod['prev_revenue_per_fte'], 0.0)

    def test_nothing_to_show_before_anyone_was_employed(self):
        self.assertEqual(self._productivity('2020-01-01', '2020-01-31'), {})

    def test_a_period_running_past_today_stops_at_today(self):
        """Nine months of revenue are not annualised over twelve."""
        from datetime import date
        today = date.today()
        prod = self._productivity('2025-03-01', '2099-12-31')
        fte = sum(self.dashboard._gec_fte(date(2025, 3, 1), today).values())
        days = (today - date(2025, 3, 1)).days + 1
        self.assertAlmostEqual(prod['fte'], fte, places=3)
        self.assertAlmostEqual(prod['revenue_per_fte'], 31000.0 * 365 / days / fte, places=0)

    def test_growth_is_annualised_on_both_sides(self):
        prod = self._productivity()
        self.assertFalse(prod['revenue_growth'])
        self.assertAlmostEqual(prod['fte_growth'], self.expected_fte / 4.5 - 1, places=4)

    def test_revenue_growth_compares_annualised_revenue(self):
        gl = self.env['account.account'].search([('code', '=', 'TST996')], limit=1)
        self.env['account.analytic.line'].create({
            'name': 'T feb sale', 'date': '2025-02-10', 'amount': 14000.0,
            'company_id': self.co.id, 'general_account_id': gl.id, self.target_col: self.bl_a.id,
        })
        prod = self._productivity()
        self.assertAlmostEqual(prod['revenue_growth'], (31000 / 31) / (14000 / 28) - 1, places=4)

    def test_headcount_splits_by_department_function(self):
        ref = self.env.ref
        rnd = ref('gec_analytic_margin.component_function_rnd')
        engineering = self.env['hr.department'].create({
            'name': 'T Engineering', 'company_id': self.co.id, 'gec_function_component_id': rnd.id,
        })
        self.env['hr.employee'].search([('name', 'in', ('T Full', 'T Half'))]).department_id = engineering
        prod = self._productivity()
        mix = {row['label']: row for row in prod['by_function']}
        self.assertAlmostEqual(mix[rnd.name]['fte'], 1.5, places=4)
        self.assertAlmostEqual(mix[rnd.name]['pct'], 1.5 / self.expected_fte, places=4)
        self.assertEqual(mix[rnd.name]['target'], (0.30, 0.40))
        self.assertAlmostEqual(mix['No function']['fte'], self.expected_fte - 1.5, places=4)

    def test_no_mix_until_a_department_names_a_function(self):
        self.assertEqual(self._productivity()['by_function'], [])

    def test_hours_split_between_customer_product_and_internal(self):
        rnd = self.env.ref('gec_analytic_margin.component_function_rnd')
        Project = self.env['project.project'].with_company(self.co)
        customer = Project.create({'name': 'T Bank', 'company_id': self.co.id})
        platform = Project.create({'name': 'T Platform', 'company_id': self.co.id})
        platform.gec_function_component_id = rnd
        full = self.env['hr.employee'].search([('name', '=', 'T Full')])
        for project, hours in ((customer, 90.0), (platform, 30.0)):
            self.env['account.analytic.line'].create({
                'name': 'T work', 'date': '2025-03-12', 'unit_amount': hours,
                'project_id': project.id, 'employee_id': full.id, 'company_id': self.co.id,
            })
        hours = self._productivity()['hours']
        self.assertAlmostEqual(hours['logged'], 120.0, places=2)
        self.assertAlmostEqual(hours['product_share'], 0.25, places=4)
        self.assertGreater(hours['available'], 0.0)
        self.assertAlmostEqual(hours['utilization'], 90.0 / hours['available'], places=4)
        by_label = {b['label']: b['hours'] for b in hours['buckets']}
        self.assertAlmostEqual(by_label[rnd.name], 30.0, places=2)

    def test_streams_rnd_per_customer_delivery_and_bespoke(self):
        ref = self.env.ref
        cogs, rnd = ref('gec_analytic_margin.component_function_cogs'), ref('gec_analytic_margin.component_function_rnd')
        self.co.gec_pl_mode = 'function'
        sale = self.env['account.analytic.line'].search([('name', '=', 'T sale'), ('company_id', '=', self.co.id)])
        sale.partner_id = self.env['res.partner'].create({'name': 'T Bank', 'is_company': True})
        Project = self.env['project.project'].with_company(self.co)
        customer = Project.create({'name': 'T Bank', 'company_id': self.co.id})
        platform = Project.create({'name': 'T Platform', 'company_id': self.co.id})
        platform.gec_function_component_id = rnd
        overhead_gl = self.env['account.account'].create({
            'name': 'T Tools', 'code': 'TST997', 'account_type': 'expense',
            'company_ids': [Command.set(self.co.ids)],
        })
        self.env['account.analytic.line'].create({
            'name': 'T tools', 'date': '2025-03-20', 'amount': -3100.0, 'company_id': self.co.id,
            'general_account_id': overhead_gl.id, 'account_id': platform.account_id.id,
        })
        Dep = self.env['hr.department']
        delivery = Dep.create({'name': 'T Delivery', 'company_id': self.co.id, 'gec_function_component_id': cogs.id})
        engineering = Dep.create({'name': 'T Eng', 'company_id': self.co.id, 'gec_function_component_id': rnd.id})
        full, half = (self.env['hr.employee'].search([('name', '=', n)]) for n in ('T Full', 'T Half'))
        full.department_id, half.department_id = delivery, engineering
        for employee, project, hours in ((full, customer, 100.0), (half, customer, 10.0), (half, platform, 30.0)):
            self.env['account.analytic.line'].create({
                'name': 'T work', 'date': '2025-03-12', 'unit_amount': hours, 'company_id': self.co.id,
                'project_id': project.id, 'employee_id': employee.id,
            })
        prod = self._productivity()
        annual = 31000.0 * 365 / 31
        stream = next(s for s in prod['stream_per_fte'] if s['name'] == 'Maintenance & Support')
        self.assertAlmostEqual(stream['per_fte'], annual / self.expected_fte, places=0)
        self.assertEqual(prod['active_customers'], 1)
        self.assertAlmostEqual(prod['rnd_per_customer'], 3100.0 * 365 / 31, places=0)
        hours = prod['hours']
        available = self.dashboard._gec_available_hours_by_employee(
            __import__('datetime').date(2025, 3, 1), __import__('datetime').date(2025, 3, 31))
        self.assertAlmostEqual(hours['delivery_utilization'], 100.0 / available[full], places=4)
        self.assertAlmostEqual(hours['bespoke_share'], 10.0 / 40.0, places=4,
                               msg="an engineer's customer hours over their project hours")

    def test_rework_is_customer_hours_on_rework_tagged_tasks(self):
        Project = self.env['project.project'].with_company(self.co)
        customer = Project.create({'name': 'T Bank', 'company_id': self.co.id})
        bug = self.env['project.tags'].create({'name': 'T Bug fix', 'gec_rework': True})
        fix = self.env['project.task'].create({'name': 'T fix', 'project_id': customer.id, 'tag_ids': [Command.set(bug.ids)]})
        build = self.env['project.task'].create({'name': 'T build', 'project_id': customer.id})
        full = self.env['hr.employee'].search([('name', '=', 'T Full')])
        for task, hours in ((fix, 8.0), (build, 72.0)):
            self.env['account.analytic.line'].create({
                'name': 'T work', 'date': '2025-03-12', 'unit_amount': hours, 'company_id': self.co.id,
                'project_id': customer.id, 'task_id': task.id, 'employee_id': full.id,
            })
        hours = self._productivity()['hours']
        self.assertAlmostEqual(hours['rework_hours'], 8.0, places=2)
        self.assertAlmostEqual(hours['rework_share'], 0.1, places=4)
