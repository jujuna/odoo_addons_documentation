from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestDelivery(GecMarginCommon):
    """On time and to plan: milestones, go-live, finish dates, templates; dated around today."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.start = cls.today - timedelta(days=60)
        cls.project_plan, _others = cls.env['account.analytic.plan']._get_all_plans()
        cls.project = cls._project(name='T Delivery', allow_milestones=True, allocated_hours=100.0,
                                   date_start=cls.start, date=cls.today + timedelta(days=30))
        cls.employee = cls.env['hr.employee'].create({'name': 'T Consultant'})
        cls.D = cls.env['gec.margin.dashboard']

    @classmethod
    def _project(cls, **vals):
        project = cls.env['project.project'].create(dict(vals, allow_timesheets=True))
        if not project.account_id:
            project.account_id = cls.env['account.analytic.account'].create(
                {'name': vals['name'], 'plan_id': cls.project_plan.id})
        return project

    def _data(self):
        return self.D.get_dashboard_data(self.start, self.today, self.D.COMPANY_WIDE)

    def _milestone(self, deadline, reached=False):
        milestone = self.env['project.milestone'].create({
            'name': 'T milestone', 'project_id': self.project.id, 'deadline': deadline})
        if reached:
            milestone.is_reached = True
            self.env.flush_all()
            self.env.cr.execute("UPDATE project_milestone SET reached_date = %s WHERE id = %s", (reached, milestone.id))
            milestone.invalidate_recordset(['reached_date'])
        return milestone

    def test_a_milestone_is_on_time_only_if_reached_by_its_deadline(self):
        due = self.today - timedelta(days=20)
        self._milestone(due, reached=due - timedelta(days=1))
        self._milestone(due, reached=due + timedelta(days=5))
        self._milestone(due)
        self._milestone(self.today + timedelta(days=10))
        m = self._data()['delivery']['milestones']
        self.assertEqual((m['due'], m['on_time'], m['open_overdue']), (3, 1, 1))
        self.assertAlmostEqual(m['rate'], 1 / 3, places=4)

    def test_go_live_slips_when_late_or_still_not_live(self):
        self.project.write({'gec_golive_planned': self.today - timedelta(days=10)})
        self._project(name='T On Time', gec_golive_planned=self.today - timedelta(days=30),
                      gec_golive_actual=self.today - timedelta(days=31))
        g = self._data()['delivery']['golive']
        self.assertEqual((g['due'], g['slipped']), (2, 1), "one live early, one past its date and not live")
        self.assertAlmostEqual(g['avg_days'], 10.0, places=4)

    def test_the_end_date_follows_the_pace_of_the_last_weeks(self):
        """40 hours over the last 8 weeks = 5 a week; 60 to go = 12 weeks."""
        for week in range(8):
            self.env['account.analytic.line'].create({
                'name': 'T work', 'project_id': self.project.id, 'employee_id': self.employee.id,
                'unit_amount': 5.0, 'date': self.today - timedelta(days=7 * week + 1),
            })
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.gec_burn_rate, 5.0, places=4)
        self.assertEqual(self.project.gec_end_forecast, self.today + timedelta(days=84))
        self.assertEqual(self.project.gec_end_delay_days, 54, "84 days out against a planned end in 30")

    def test_a_project_created_from_a_template_remembers_it(self):
        template = self.env['project.project'].create({'name': 'T Template', 'is_template': True})
        project = template.with_context(copy_from_template=True).copy({'name': 'T From Template'})
        self.assertEqual(project.gec_template_id, template)
        self.assertFalse(self.project.copy().gec_template_id, "an ordinary copy is not built from a template")


@tagged('post_install', '-at_install')
class TestCash(GecMarginCommon):
    """Receivables, cash and how good the revenue forecast was."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cls.company.id)], limit=1)
        cls.income = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', cls.company.ids)], limit=1)
        cls.partner = cls.env['res.partner'].create({'name': 'T Bank Customer'})
        cls.D = cls.env['gec.margin.dashboard']

    def _invoice(self, amount, date, due=None):
        if not self.journal or not self.income:
            self.skipTest("no chart of accounts in this database")
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': date, 'invoice_date_due': due or date,
            'invoice_line_ids': [Command.create({
                'name': 'T licence', 'quantity': 1, 'price_unit': amount, 'account_id': self.income.id,
                'tax_ids': [Command.clear()]})],
        })
        invoice.action_post()
        return invoice

    def _cash(self, date_from, date_to):
        return self.D.get_dashboard_data(date_from, date_to, self.D.COMPANY_WIDE)['cash']

    def test_dso_is_receivables_over_invoiced_times_days(self):
        start = self.today - timedelta(days=29)
        before = self._cash(start, self.today).get('dso', {})
        paid = self._invoice(3000.0, start)
        self._invoice(1000.0, start + timedelta(days=10))
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=paid.ids).create({'payment_date': start})._create_payments()
        dso = self._cash(start, self.today)['dso']
        self.assertAlmostEqual(dso['invoiced'] - before.get('invoiced', 0.0), 4000.0, places=2)
        self.assertAlmostEqual(dso['receivables'] - before.get('receivables', 0.0), 1000.0, places=2,
                               msg="the paid invoice is no longer outstanding")
        self.assertAlmostEqual(dso['days'], dso['receivables'] / dso['invoiced'] * 30, places=4)

    def test_an_invoice_falls_in_the_week_it_is_due(self):
        start = self.today - timedelta(days=self.today.weekday())
        self._invoice(500.0, self.today, due=start + timedelta(weeks=3, days=2))
        forecast = self._cash(self.today, self.today)['forecast']
        self.assertGreaterEqual(forecast['weeks'][3]['inflow'], 500.0)
        self.assertEqual(len(forecast['weeks']), 13)

    def test_a_late_invoice_is_expected_in_the_first_week(self):
        self._invoice(700.0, self.today - timedelta(days=60), due=self.today - timedelta(days=30))
        forecast = self._cash(self.today, self.today)['forecast']
        self.assertGreaterEqual(forecast['weeks'][0]['inflow'], 700.0)

    def test_the_forecast_is_frozen_and_compared_with_the_actual(self):
        """Run rate of 3 000 a month; the month then brings 3 300: 9.1% above."""
        Snapshot = self.env['gec.forecast.snapshot']
        month = self.today.replace(day=1) - relativedelta(months=2)
        income = self.env['account.account'].create({
            'name': 'T Forecast Income', 'code': 'TST970', 'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)]})
        for i, amount in ((3, 3000.0), (2, 3000.0), (1, 3000.0), (0, 3300.0)):
            self.env['account.analytic.line'].create({
                'name': 'T sale', 'amount': amount, 'company_id': self.company.id,
                'general_account_id': income.id, self.target_col: self.bl_a.id,
                'date': month - relativedelta(months=i) + timedelta(days=9),
            })
        Snapshot.search([('company_id', '=', self.company.id), ('month', '=', month)]).unlink()
        before = Snapshot._gec_forecast_for(self.company, month)[0]
        snapshot = Snapshot._gec_record(self.company, [month])
        self.assertEqual(snapshot.basis, 'run_rate')
        self.assertAlmostEqual(snapshot.forecast_revenue, before, places=2)
        self.assertGreaterEqual(snapshot.forecast_revenue, 3000.0)
        self.assertGreater(snapshot.actual_revenue, 0.0)
        self.assertAlmostEqual(snapshot.error_pct,
                               (snapshot.actual_revenue - snapshot.forecast_revenue) / snapshot.actual_revenue,
                               places=6)
        self.assertFalse(Snapshot._gec_record(self.company, [month]))
        accuracy = self._cash(month, month + relativedelta(months=1, days=-1))['accuracy']
        self.assertEqual(accuracy['months'][0]['month'], fields.Date.to_string(month))

    def test_the_month_now_running_is_not_judged_yet(self):
        snapshot = self.env['gec.forecast.snapshot'].create({
            'company_id': self.company.id, 'month': self.today.replace(day=1) + relativedelta(months=1),
            'forecast_revenue': 1000.0, 'basis': 'run_rate'})
        self.assertEqual(snapshot.actual_revenue, 0.0)
        self.assertEqual(snapshot.error_pct, 0.0)
