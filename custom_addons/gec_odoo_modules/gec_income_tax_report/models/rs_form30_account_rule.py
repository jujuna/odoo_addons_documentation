from odoo import Command, api, fields, models

F_STD = ['ge_account_331210', 'gec_account_331320', 'ge_account_331212']

DEFAULT_ACCOUNT_RULES = {
    '1': (['ge_account_720100'], ['ge_account_310310'], ['ge_account_331310', 'gec_account_331320']),
    '2': (['ge_account_510310', 'ge_account_530110'], ['ge_account_340120'], F_STD),
    '3': (['ge_account_820310'], ['ge_account_340110'], F_STD),
    '5': (['ge_account_720500'], ['ge_account_310990'], F_STD),
    '6': (['ge_account_749000'], ['ge_account_310990'], F_STD),
    '7': (['ge_account_740100'], ['ge_account_310110'], F_STD),
    '16': (['ge_account_530110'], ['ge_account_310990'], F_STD),
    '17': (['ge_account_740200'], ['ge_account_310110'], F_STD),
    '19': (['ge_account_741100'], ['ge_account_310110'], F_STD),
    '20': (['ge_account_530110'], ['ge_account_310990'], F_STD),
    '22': (['ge_account_310990'], ['ge_account_120110'], F_STD),
    '23': (['ge_account_310990'], ['ge_account_120110'], F_STD),
    '24': (['ge_account_741100'], ['ge_account_310110'], F_STD),
}


class RsForm30AccountRule(models.Model):
    """Accounts that identify a Form 30 income type on a journal entry, used to propose its Withholding Tax. The default
    rows are provisional: the accountant edits or archives them."""
    _name = 'rs.form30.account.rule'
    _description = 'Form 30 Account Rule'
    _check_company_auto = True
    _order = 'company_id, sequence, income_type_id, id'

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade', default=lambda self: self.env.company.root_id,
        domain="[('parent_id', '=', False)]")
    income_type_id = fields.Many2one('rs.form30.income.type', required=True, ondelete='restrict', index=True)
    expense_account_ids = fields.Many2many('account.account', 'rs_form30_account_rule_expense_rel', 'rule_id', 'account_id',
        string='Accrual Debit (C)', check_company=True)
    liability_account_ids = fields.Many2many('account.account', 'rs_form30_account_rule_liability_rel', 'rule_id', 'account_id',
        string='Accrual Credit (D)', check_company=True)
    tax_account_ids = fields.Many2many('account.account', 'rs_form30_account_rule_tax_rel', 'rule_id', 'account_id', string='Withholding Credit (F)',
        check_company=True)
    note = fields.Char()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    liability_not_payable = fields.Boolean(compute='_compute_liability_not_payable',
        help="An Accrual Credit (D) account is not a reconcilable payable account.")

    @api.depends('liability_account_ids.account_type', 'liability_account_ids.reconcile')
    def _compute_liability_not_payable(self):
        for rule in self:
            rule.liability_not_payable = any(
                account.account_type != 'liability_payable' or not account.reconcile
                for account in rule.liability_account_ids)

    @api.model
    def _rs_form30_seed_account_rules(self, companies=None):
        if companies is None:
            companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        income_types = {t.code: t.id for t in self.env['rs.form30.income.type'].search([])}
        vals_list = []
        for company in companies:
            if self.with_context(active_test=False).search_count([('company_id', '=', company.id)]):
                continue
            template = self.env['account.chart.template'].with_company(company)
            for code, xmlid_lists in DEFAULT_ACCOUNT_RULES.items():
                accounts = []
                for xmlids in xmlid_lists:
                    found = (template.ref(xmlid, raise_if_not_found=False) for xmlid in xmlids)
                    accounts.append([account.id for account in found if account])
                if code in income_types and all(accounts):
                    vals_list.append({
                        'company_id': company.id,
                        'income_type_id': income_types[code],
                        'expense_account_ids': [Command.set(accounts[0])],
                        'liability_account_ids': [Command.set(accounts[1])],
                        'tax_account_ids': [Command.set(accounts[2])],
                    })
        self.create(vals_list)
