from odoo import api, models

STRUCTS = ('monthly', 'hourly', 'daily', 'unit')
# PIT and pension are payable and reconcilable so gec_payroll_bank can pay them with the salaries (Tax Code art. 154).
SALARY_EXPENSE = 'ge_account_720100'
PENSION_ER_EXPENSE = 'ge_account_721000'
ALLOWANCE_EXPENSE = 'ge_account_720110'
TERMINATION_EXPENSE = 'ge_account_720700'
OVERTIME_EXPENSE = 'ge_account_720200'
BENEFIT_DEDUCTION = 'ge_account_720900'
NET_PAYABLE = 'ge_account_310310'
PIT_PAYABLE = 'gec_account_331320'
PENSION_PAYABLE = 'ge_account_332010'
ADVANCE_NET = 'ge_account_150310'
ADVANCE_PENSION = 'ge_account_332011'
ADVANCE_PIT = 'ge_account_331311'
MOVED_ACCOUNTS_KEY = 'geo_payroll.payroll_accounts_20261112'
# New default: the default this module shipped before 2026-11-12 (accountant's table of that day).
OLD_DEFAULT_ACCOUNTS = {
    ALLOWANCE_EXPENSE: 'ge_account_720100',
    PENSION_ER_EXPENSE: 'ge_account_740900',
    OVERTIME_EXPENSE: 'ge_account_720100',
}
EARNING_RULES = ('basic', 'daily_basic', 'timesheet_basic', 'unit_basic', 'worklog_daily', 'timesheet_extra', 'unit_extra')
# These rules book the same way in every structure; a negative PIT total in the debit field posts as a credit.
TAX_RULE_ACCOUNTS = {
    'pension_ee': {'debit': PENSION_PAYABLE},
    'pit': {'debit': PIT_PAYABLE},
    'pension_er': {'debit': PENSION_ER_EXPENSE, 'credit': PENSION_PAYABLE},
    'net': {'credit': NET_PAYABLE},
}
ADVANCE_RULE_ACCOUNTS = {
    'advance_pay': {'debit': ADVANCE_NET},
    'adv_pee_pre': {'debit': ADVANCE_PENSION, 'credit': PENSION_PAYABLE},
    'adv_pit_pre': {'debit': ADVANCE_PIT, 'credit': PIT_PAYABLE},
    'adv_per_pre': {'debit': ADVANCE_PENSION, 'credit': PENSION_PAYABLE},
}
# Default accounts of each rule, by structure kind: the rule's xmlid is geo_payroll.rule_geo_<kind>_<rule>.
RULE_ACCOUNTS = {
    'monthly': {
        **dict.fromkeys(EARNING_RULES, {'debit': SALARY_EXPENSE}),
        'worklog_ot': {'debit': OVERTIME_EXPENSE},
        **TAX_RULE_ACCOUNTS,
        'bonus': {'debit': ALLOWANCE_EXPENSE},
        'termination': {'debit': TERMINATION_EXPENSE},
        # benefit_ded credits an expense, not a payable: a partnerless payable blocks the payment register.
        'benefit_ded': {'debit': BENEFIT_DEDUCTION},
        'benefit_kind': {'debit': ALLOWANCE_EXPENSE},
        'benefit_kind_ded': {'debit': BENEFIT_DEDUCTION},
        **ADVANCE_RULE_ACCOUNTS,
        # Repayment month: the legs consume the prepaid assets; the company share becomes expense.
        'repay_net': {'credit': ADVANCE_NET},
        'repay_pee': {'credit': ADVANCE_PENSION},
        'repay_pit': {'credit': ADVANCE_PIT},
        'repay_per': {'debit': PENSION_ER_EXPENSE, 'credit': ADVANCE_PENSION},
    },
    'benefits': {
        'bonus': {'debit': ALLOWANCE_EXPENSE},
        **ADVANCE_RULE_ACCOUNTS,
        **TAX_RULE_ACCOUNTS,
    },
    'overtime': {
        'worklog_ot': {'debit': OVERTIME_EXPENSE},
        **TAX_RULE_ACCOUNTS,
    },
}
BASE_RULES = EARNING_RULES + ('worklog_ot',) + tuple(TAX_RULE_ACCOUNTS)
ACCOUNT_REFS = sorted({account for rules in RULE_ACCOUNTS.values() for accounts in rules.values() for account in accounts.values()})


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @api.model
    def _gec_rules_mapping(self):
        """Skip missing xmlids: on a fresh install the benefit and overtime data load after this runs."""
        mapping = {}
        for kind, rules in RULE_ACCOUNTS.items():
            for rule, accounts in rules.items():
                record = self.env.ref(f'geo_payroll.rule_geo_{kind}_{rule}', raise_if_not_found=False)
                if record:
                    mapping[record] = dict(accounts)
        return mapping

    @api.model
    def _gec_structures(self, kinds):
        structures = [self.env.ref(f'geo_payroll.structure_geo_{kind}', raise_if_not_found=False) for kind in kinds]
        return self.env['hr.payroll.structure'].union([structure for structure in structures if structure])

    def _load_payroll_accounts(self, template_code, companies):
        super()._load_payroll_accounts(template_code, companies)
        if template_code == 'ge':
            self._gec_configure_payroll_account_ge(companies)

    @api.model
    def _gec_configure_payroll_account_ge(self, companies):
        rules_mapping = self._gec_rules_mapping()
        base_rules = self.env['hr.salary.rule'].union([self.env.ref(f'geo_payroll.rule_geo_monthly_{rule}') for rule in BASE_RULES])
        for company in companies:
            # An account on a base rule means an accountant owns this company's mapping.
            if any(rule.account_debit or rule.account_credit for rule in base_rules.with_company(company)):
                continue
            self._configure_payroll_account(company, 'GE', account_refs=ACCOUNT_REFS, rules_mapping=rules_mapping, default_account=SALARY_EXPENSE)
        self._gec_fill_missing_rule_accounts(companies, rules_mapping)
        self._gec_fill_salary_journal_default_account(companies)

    @api.model
    def _gec_fill_salary_journal_default_account(self, companies):
        """Give Georgian salary journals a default account where empty; core books rounding cents on it."""
        structures = self._gec_structures(STRUCTS + ('benefits', 'overtime'))
        for company in companies:
            account = self.with_company(company).ref(SALARY_EXPENSE, raise_if_not_found=False)
            journals = structures.with_company(company).journal_id.filtered(
                lambda journal: not journal.default_account_id and journal.company_id == company)
            if account and journals:
                journals.default_account_id = account

    @api.model
    def _gec_fill_missing_rule_accounts(self, companies, mapping):
        """Fill rules that have no account in a company; never overwrite an account an accountant set."""
        structures = self._gec_structures(('benefits', 'overtime'))
        for company in companies:
            template = self.with_company(company)
            for rule, rule_accounts in mapping.items():
                rule_company = rule.with_company(company)
                if rule_company.account_debit or rule_company.account_credit:
                    continue
                vals = {}
                debit = rule_accounts.get('debit') and template.ref(rule_accounts['debit'], raise_if_not_found=False)
                credit = rule_accounts.get('credit') and template.ref(rule_accounts['credit'], raise_if_not_found=False)
                if debit:
                    vals['account_debit'] = debit.id
                if credit:
                    vals['account_credit'] = credit.id
                if vals:
                    rule_company.write(vals)
            for structure in structures.filtered(lambda s: not s.with_company(company).journal_id):
                journal = template.ref('hr_payroll_account_journal', raise_if_not_found=False)
                if journal:
                    structure.with_company(company).journal_id = journal

    @api.model
    def _gec_move_rule_accounts(self, companies):
        """Once per database: a rule still on the default shipped before 2026-11-12 takes the accountant's new account.
        A rule an accountant pointed elsewhere keeps its account, and so do the archived rule copies of old payslips."""
        params = self.env['ir.config_parameter'].sudo()
        if params.get_bool(MOVED_ACCOUNTS_KEY):
            return
        mapping = self._gec_rules_mapping()
        for company in companies:
            template = self.with_company(company)
            for rule, rule_accounts in mapping.items():
                old = OLD_DEFAULT_ACCOUNTS.get(rule_accounts.get('debit'))
                new = old and template.ref(rule_accounts['debit'], raise_if_not_found=False)
                rule_company = rule.with_company(company)
                if new and rule_company.account_debit == template.ref(old, raise_if_not_found=False):
                    rule_company.account_debit = new
        params.set_bool(MOVED_ACCOUNTS_KEY, True)

    @api.model
    def _gec_configure_ge_payroll_accounts(self):
        companies = self.env['res.company'].search([('chart_template', '=', 'ge')])
        if companies:
            self._gec_configure_payroll_account_ge(companies)
            self._gec_move_rule_accounts(companies)
