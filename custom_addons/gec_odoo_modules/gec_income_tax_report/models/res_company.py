from odoo import Command, api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    rs_form30_pension_account_ids = fields.Many2many('account.account', 'res_company_rs_form30_pension_rel', 'company_id', 'account_id',
        string='Form 30 Pension Liability Accounts', check_company=True,
        help="Accounts that hold the 2% pension withheld from the recipient. A journal entry with a withholding tax reads the pension of a row from "
        "the credits on these accounts.")
    rs_form30_employer_pension_account_ids = fields.Many2many('account.account', 'res_company_rs_form30_er_pension_rel', 'company_id', 'account_id',
        string='Form 30 Employer Pension Expense Accounts', check_company=True,
        help="Accounts that hold the pension the employer pays on top. Their debits are taken off the pension of a row, so the employer's share is "
        "not declared as the recipient's.")

    @api.model
    def _rs_form30_seed_pension_accounts(self, companies=None):
        if companies is None:
            companies = self.search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        for company in companies:
            if company.rs_form30_pension_account_ids or company.rs_form30_employer_pension_account_ids:
                continue
            template = self.env['account.chart.template'].with_company(company)
            liability, employer = (
                [account.id for account in (template.ref(xmlid, raise_if_not_found=False) for xmlid in xmlids) if account]
                for xmlids in (['ge_account_332010'], ['ge_account_740900', 'ge_account_721000']))
            company.write({
                'rs_form30_pension_account_ids': [Command.set(liability)],
                'rs_form30_employer_pension_account_ids': [Command.set(employer)],
            })
