from odoo import fields, models

# Part I box 6, as the rs.ge form offers it.
COMPANY_STATUSES = [
    ('resident', 'Resident Enterprise'),
    ('pe', 'Permanent Establishment of a Non-Resident'),
    ('international', 'International Company'),
]
# Statuses granted on top, not chosen in Part I: they decide column 3, line 16.1.4 and annex 1.7.
SPECIAL_STATUSES = [
    ('investment', 'Investment Company'),
    ('startup', 'Innovative Startup'),
    ('innovative_sme', 'Innovative Small or Medium Company'),
    ('research', 'Research and Development Company'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    gec_cit_company_status = fields.Selection(
        COMPANY_STATUSES, string='Profit Tax Status', default='resident',
        help="Part I box 6 of the profit tax declaration. International Company also moves line 16.1.3 to "
             "column 3 at 5%.")
    gec_cit_special_status = fields.Selection(
        SPECIAL_STATUSES, string='Special Status',
        help="A status granted on top of the Part I status. It is not printed in Part I, but decides column 3: "
             "investment company 5% (line 16.1.4), innovative startup and innovative small or medium company 15%, "
             "research and development company 10%.")
    gec_cit_financial = fields.Boolean(
        string='Bank, Credit Union, Microfinance or Lending Entity',
        help="Loans to individuals and non-residents then stay out of line 18.3; loans to shareholders feed line 18.4.")
    gec_cit_insurer = fields.Boolean(
        string='Insurance Organisation',
        help="Old profits are those of 2015-2023 instead of 2008-2016 (lines 16.1.1 and 25.1, annexes 1 and 1.1).")
    gec_cit_gambling = fields.Boolean(
        string='Gambling Organiser',
        help="Gaming hall, online casino or online betting organiser: shows part IV of the declaration.")
    gec_cit_post_entry = fields.Boolean(
        string='Post Profit Tax Entry',
        help="Confirming a declaration posts its profit tax, except the dividend tax the CIT wizard already books.")
    gec_cit_journal_id = fields.Many2one(
        'account.journal', string='Profit Tax Journal', check_company=True,
        domain="[('type', '=', 'general')]")
    gec_cit_expense_account_id = fields.Many2one(
        'account.account', string='Profit Tax Expense Account', check_company=True)
    gec_cit_payable_account_id = fields.Many2one(
        'account.account', string='Profit Tax Payable Account', check_company=True)
