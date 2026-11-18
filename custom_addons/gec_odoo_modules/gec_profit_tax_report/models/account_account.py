from odoo import api, fields, models

# Rows each account of the Georgian chart feeds by default (chart template xmlid per row). Contacts then
# decide whether an item really counts: see rs.cit.declaration._cit_partner_row().
DEFAULT_CELL_ACCOUNTS = {
    '16.1': ['ge_account_340120'],
    '18.1.1': ['ge_account_280210'],
    '18.1.2': ['ge_account_820610'],
    '18.1.3': ['ge_account_150110', 'ge_account_150120'],
    '18.1.5': ['ge_account_760200'],
    '18.2': ['ge_account_280110'],
    '18.3': ['ge_account_140410', 'ge_account_140710', 'ge_account_270510', 'ge_account_270990'],
    '19': ['ge_account_820710'],
    '19.1': ['ge_account_820510'],
    '20': ['ge_account_750300'],
}
# Balance groups of annexes 2 and 3: account code prefixes, then single accounts.
DEFAULT_BALANCE_GROUPS = {
    'inventory': (['16'], []),
    'fixed_asset': (['21', '22'], []),
    'loan_given': ([], ['ge_account_140410', 'ge_account_140710', 'ge_account_270510', 'ge_account_270990']),
    'loan_received': ([], ['ge_account_320110', 'ge_account_320210', 'ge_account_320510',
                           'ge_account_410110', 'ge_account_410510']),
    'capital': ([], ['ge_account_510110', 'ge_account_510210']),
    'investment': ([], ['ge_account_280110']),
}


class AccountAccount(models.Model):
    _inherit = 'account.account'

    gec_cit_cell_id = fields.Many2one(
        'rs.cit.cell', string='Profit Tax Row', ondelete='restrict',
        domain="[('kind', '=', 'auto'), ('measure', 'not in', ('market', 'register'))]",
        help="Row of the monthly profit tax declaration that journal items on this account feed. "
             "A journal item can choose another row.")
    gec_cit_balance_group = fields.Selection([
        ('inventory', 'Inventory'),
        ('fixed_asset', 'Fixed Assets'),
        ('loan_given', 'Loans Given'),
        ('loan_received', 'Loans Received'),
        ('capital', 'Own Capital'),
        ('investment', 'Capital in Other Enterprises'),
    ], string='Profit Tax Balance Group',
        help="Balances of annex 2 (inventory and fixed assets at year end, March declaration) and annex 3 "
             "(loans and capital, every month) of the profit tax declaration.")

    @api.model
    def _gec_cit_seed_cells(self, companies=None):
        """Set the default profit tax rows, balance groups and accounting settings on the Georgian chart,
        leaving values already chosen alone."""
        if companies is None:
            companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        cells = {cell.code: cell for cell in self.env['rs.cit.cell'].search([])}
        for company in companies:
            template = self.env['account.chart.template'].with_company(company)
            for code, xmlids in DEFAULT_CELL_ACCOUNTS.items():
                for xmlid in xmlids:
                    account = template.ref(xmlid, raise_if_not_found=False)
                    if account and not account.gec_cit_cell_id:
                        account.gec_cit_cell_id = cells[code]
            for group, (prefixes, xmlids) in DEFAULT_BALANCE_GROUPS.items():
                accounts = self.browse()
                for prefix in prefixes:
                    accounts |= self.with_company(company).search([
                        ('company_ids', 'in', company.id), ('code', '=like', f'{prefix}%')])
                for xmlid in xmlids:
                    accounts |= template.ref(xmlid, raise_if_not_found=False) or self.browse()
                accounts.filtered(lambda a: not a.gec_cit_balance_group).gec_cit_balance_group = group
            if not company.gec_cit_journal_id:
                company.gec_cit_journal_id = self.env['account.journal'].search([
                    ('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
            if not company.gec_cit_expense_account_id:
                company.gec_cit_expense_account_id = template.ref('ge_account_910010', raise_if_not_found=False)
            if not company.gec_cit_payable_account_id:
                company.gec_cit_payable_account_id = template.ref('ge_account_331110', raise_if_not_found=False)
