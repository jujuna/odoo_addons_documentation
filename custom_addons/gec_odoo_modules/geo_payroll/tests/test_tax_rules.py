from odoo import Command
from odoo.tests import tagged

from odoo.addons.geo_payroll.models.account_chart_template import MOVED_ACCOUNTS_KEY

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoTaxRules(GeoPayrollCase):
    def _compute_fixed(self, **employee_values):
        employee = self._make_employee('fixed', wage=1000.0, **employee_values)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        return payslip

    def test_non_member_pit_on_full_gross(self):
        payslip = self._compute_fixed()
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 1000.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), 0.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_ER'), 0.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -200.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 800.0)

    def test_member_pension_reduces_pit_base(self):
        payslip = self._compute_fixed(pension_fund_member=True)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 1000.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -20.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -196.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_ER'), 20.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 784.0)

    def test_company_contribution_stays_out_of_net(self):
        payslip = self._compute_fixed(pension_fund_member=True)
        self.assertAlmostEqual(
            self._line_total(payslip, 'NET'),
            self._line_total(payslip, 'GROSS')
            + self._line_total(payslip, 'PENSION_EE')
            + self._line_total(payslip, 'PIT'),
        )

    def test_member_taxes_on_daily_scheme(self):
        employee = self._make_employee('daily', pension_fund_member=True)
        self._approve_log(employee, log_type='daily', units=1.0)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'DAILY_BASIC'), 80.0)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 80.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -1.6)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -15.68)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_ER'), 1.6)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 62.72)

    def _compute_with_termination(self, **employee_values):
        employee = self._make_employee('fixed', wage=1000.0, **employee_values)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        rule = self.env.ref('geo_payroll.rule_geo_monthly_termination')
        payslip.input_line_ids = [Command.create({'salary_rule_id': rule.id, 'name': 'Termination Payment', 'amount': 500.0})]
        payslip.compute_sheet()
        return payslip

    def test_termination_payment_is_taxed_like_salary(self):
        payslip = self._compute_with_termination()
        self.assertAlmostEqual(self._line_total(payslip, 'TERMINATION'), 500.0)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 1500.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -300.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 1200.0)

    def test_termination_payment_is_charged_pension_for_a_member(self):
        payslip = self._compute_with_termination(pension_fund_member=True)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -30.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_ER'), 30.0)

    def test_pit_ignores_other_deductions(self):
        self.env['hr.salary.rule'].create({
            'name': 'Loan Repayment',
            'code': 'LOAN',
            'sequence': 130,
            'category_ids': [Command.set(self.env.ref('hr_payroll.DED').ids)],
            'condition_select': 'none',
            'amount_select': 'fix',
            'amount_fix': -100.0,
            'struct_ids': [Command.set(self.structures['monthly'].ids)],
        })
        payslip = self._compute_fixed(pension_fund_member=True)
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), -100.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PENSION_EE'), -20.0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -196.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 684.0)

    def test_journal_entry_per_account_balances(self):
        company = self.company
        AccountAccount = self.env['account.account']
        accounts = {
            code: AccountAccount.create({
                'name': f'GEO Test {code}',
                'code': f'T{code}',
                'account_type': account_type,
                'reconcile': account_type == 'liability_payable',
            })
            for code, account_type in [
                ('7410', 'expense'), ('7490', 'expense'),
                ('3130', 'liability_payable'), ('3181', 'liability_payable'),
                ('3182', 'liability_payable'), ('3320', 'liability_current'),
            ]
        }
        journal = self.env['account.journal'].create({
            'name': 'GEO Test Salaries',
            'code': 'TSLR',
            'type': 'general',
            'company_id': company.id,
        })
        structure = self.structures['monthly']
        structure.with_company(company).journal_id = journal
        for rule in structure.rule_ids.with_company(company):
            if rule.code in ('GROSS', 'LOAN'):
                continue
            if rule.code == 'NET':
                rule.account_credit = accounts['3130']
            elif rule.code == 'PENSION_ER':
                rule.account_debit = accounts['7490']
                rule.account_credit = accounts['3181']
            elif rule.code == 'PENSION_EE':
                rule.account_debit = accounts['3182']
            elif rule.code == 'PIT':
                rule.account_debit = accounts['3320']
            else:
                rule.account_debit = accounts['7410']
        payslip = self._compute_fixed(pension_fund_member=True)
        payslip.action_payslip_done()
        move = payslip.move_id
        self.assertTrue(move)
        expected = {
            accounts['7410'].id: (1000.0, 0.0),
            accounts['7490'].id: (20.0, 0.0),
            accounts['3130'].id: (0.0, 784.0),
            accounts['3182'].id: (0.0, 20.0),
            accounts['3320'].id: (0.0, 196.0),
            accounts['3181'].id: (0.0, 20.0),
        }
        totals = {}
        for line in move.line_ids:
            debit, credit = totals.get(line.account_id.id, (0.0, 0.0))
            totals[line.account_id.id] = (debit + line.debit, credit + line.credit)
        self.assertEqual(set(totals), set(expected))
        for account_id, (debit, credit) in expected.items():
            self.assertAlmostEqual(totals[account_id][0], debit)
            self.assertAlmostEqual(totals[account_id][1], credit)
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), 1020.0)
        net_lines = move.line_ids.filtered(lambda l: l.account_id == accounts['3130'])
        self.assertEqual(net_lines.partner_id, payslip.employee_id.work_contact_id)

    def test_timesheet_extra_empty_projects_pays_any_project(self):
        employee = self._make_employee('daily_hourly')
        employee.version_id.timesheet_pay_project_ids = [Command.clear()]
        line = self._make_timesheet(employee, hours=2.0, project=self.other_project)
        payslip = self._make_payslip(employee, worked_hours=self.period_hours, worked_days=self.period_days)
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'TIMESHEET_EXTRA'), 20.0)
        self.assertTrue(line.gec_settlement_ids.filtered('active_claim'))

    def test_salary_journal_gets_a_default_account_for_rounding(self):
        """The journal gets a default account for core's rounding cent; an accountant's choice is kept."""
        template = self.env['account.chart.template'].with_company(self.company)
        salary_expense = template.ref('ge_account_720100', raise_if_not_found=False)
        if not salary_expense:
            self.skipTest("the company has no Georgian chart")
        empty = self.env['account.journal'].create({
            'name': 'GEO Rounding Salaries', 'code': 'TRND', 'type': 'general', 'company_id': self.company.id})
        chosen = self.env['account.journal'].create({
            'name': 'GEO Chosen Salaries', 'code': 'TCHS', 'type': 'general', 'company_id': self.company.id,
            'default_account_id': self.env['account.account'].create({
                'name': 'GEO Rounding', 'code': 'TRND1', 'account_type': 'expense'}).id})
        self.structures['monthly'].with_company(self.company).journal_id = empty
        self.structures['hourly'].with_company(self.company).journal_id = chosen
        chosen_account = chosen.default_account_id
        template._gec_fill_salary_journal_default_account(self.company)
        self.assertEqual(empty.default_account_id, salary_expense)
        self.assertEqual(chosen.default_account_id, chosen_account)

    def test_configurator_keeps_manual_accounts_and_fills_empty_rules(self):
        geo_rules = self.env['hr.salary.rule'].search([
            ('struct_ids', 'in', [structure.id for structure in self.structures.values()])])
        geo_rules.with_company(self.company).write({'account_debit': False, 'account_credit': False})
        account = self.env['account.account'].create({
            'name': 'GEO Manual Expense',
            'code': 'TMAN1',
            'account_type': 'expense',
        })
        monthly_basic = self.env.ref('geo_payroll.rule_geo_monthly_basic')
        pension_ee = self.env.ref('geo_payroll.rule_geo_monthly_pension_ee')
        monthly_basic.with_company(self.company).account_debit = account
        self.env['account.chart.template']._gec_configure_payroll_account_ge(self.company)
        self.assertEqual(monthly_basic.with_company(self.company).account_debit, account)
        if not self.env['account.chart.template'].with_company(self.company).ref('ge_account_332010', raise_if_not_found=False):
            self.skipTest("the company has no Georgian chart")
        self.assertTrue(pension_ee.with_company(self.company).account_debit)

    def _georgian_chart_company(self):
        company = self.env['res.company'].create({'name': self._next_name('GEO Chart Company'), 'country_id': self.env.ref('base.ge').id})
        self.env['account.chart.template'].try_loading('ge', company, install_demo=False)
        return company

    def _rule(self, name, company):
        return self.env.ref(f'geo_payroll.rule_geo_{name}').with_company(company)

    def test_configurator_books_bonus_pension_and_termination_on_their_accounts(self):
        company = self._georgian_chart_company()
        self.env['account.chart.template']._gec_configure_payroll_account_ge(company)
        template = self.env['account.chart.template'].with_company(company)
        expected = {
            'monthly_bonus': 'ge_account_720110',
            'monthly_benefit_kind': 'ge_account_720110',
            'benefits_bonus': 'ge_account_720110',
            'monthly_termination': 'ge_account_720700',
            'monthly_pension_er': 'ge_account_721000',
            'benefits_pension_er': 'ge_account_721000',
            'monthly_basic': 'ge_account_720100',
            'monthly_worklog_ot': 'ge_account_720200',
            'overtime_worklog_ot': 'ge_account_720200',
        }
        for name, xmlid in expected.items():
            self.assertEqual(self._rule(name, company).account_debit, template.ref(xmlid), name)

    def test_old_default_accounts_move_once_and_an_accountants_account_stays(self):
        company = self._georgian_chart_company()
        template = self.env['account.chart.template'].with_company(company)
        old_salary, old_pension = template.ref('ge_account_720100'), template.ref('ge_account_740900')
        own = self.env['account.account'].with_company(company).create({'name': 'GEO Own Expense', 'code': 'TOWN1', 'account_type': 'expense'})
        bonus = self._rule('monthly_bonus', company)
        benefit_kind = self._rule('monthly_benefit_kind', company)
        pension_er = self._rule('monthly_pension_er', company)
        basic = self._rule('monthly_basic', company)
        worklog_ot = self._rule('monthly_worklog_ot', company)
        bonus.account_debit = old_salary
        benefit_kind.account_debit = own
        pension_er.account_debit = old_pension
        basic.account_debit = old_salary
        worklog_ot.account_debit = old_salary
        self.env['ir.config_parameter'].sudo().set_bool(MOVED_ACCOUNTS_KEY, False)
        template._gec_move_rule_accounts(company)
        self.assertEqual(bonus.account_debit, template.ref('ge_account_720110'))
        self.assertEqual(pension_er.account_debit, template.ref('ge_account_721000'))
        self.assertEqual(benefit_kind.account_debit, own)
        self.assertEqual(basic.account_debit, old_salary)
        self.assertEqual(worklog_ot.account_debit, template.ref('ge_account_720200'))
        bonus.account_debit = old_salary
        template._gec_move_rule_accounts(company)
        self.assertEqual(bonus.account_debit, old_salary)
