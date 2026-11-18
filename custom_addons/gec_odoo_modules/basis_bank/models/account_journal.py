from odoo import _, api, fields, models

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_payment_method import BASIS_BANK_BIC, BASISBANK_METHOD_CODE


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    basisbank_connection_id = fields.Many2one('basisbank.connection', string='Basis Bank Connection', compute='_compute_basisbank_connection_id',
        search='_search_basisbank_connection_id')
    is_basisbank = fields.Boolean(string='Is Basis Bank Journal', compute='_compute_is_basisbank', store=True)

    @api.depends('company_id', 'bank_account_id.bank_bic', 'type')
    def _compute_basisbank_connection_id(self):
        """The connection serving a Basis-BIC journal: its company's, else the nearest parent's."""
        # sudo: the serving connection is not sensitive; accountants may lack connection access.
        Connection = self.env['basisbank.connection'].sudo()
        basis_journals = self.filtered(lambda j: j._is_basisbank_journal() and j.company_id)
        (self - basis_journals).basisbank_connection_id = False
        if not basis_journals:
            return
        connections = Connection.search([('company_id', 'in', basis_journals.company_id.parent_ids.ids)])
        by_company = {c.company_id.id: c for c in connections}
        for journal in basis_journals:
            journal.basisbank_connection_id = next(
                (by_company[company.id] for company in journal.company_id.parent_ids[::-1]
                 if company.id in by_company), False)

    def _search_basisbank_connection_id(self, operator, value):
        """Translate a search on this computed field into one on the owning companies and their branches."""
        connections = self.env['basisbank.connection'].search([('id', operator, value)])
        if not connections:
            return [('id', '=', False)]
        return [('is_basisbank', '=', True), ('company_id', 'child_of', connections.company_id.ids)]

    @api.depends('basisbank_connection_id')
    def _compute_is_basisbank(self):
        """A Basis journal has Basis Bank's BIC and a Basis connection on its company or a parent.
        A connection in Error or Blocked state still counts, so a failed login never lifts the payment guard."""
        for journal in self:
            journal.is_basisbank = bool(journal.basisbank_connection_id)

    @api.model
    def _basisbank_refresh_journals(self, companies):
        """Re-evaluate is_basisbank on the bank journals of these companies and their branches."""
        journals = self.sudo().with_context(active_test=False).search([('type', '=', 'bank'), ('company_id', 'child_of', companies.ids)])
        journals.invalidate_recordset(['basisbank_connection_id'])
        journals.modified(['basisbank_connection_id'])

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._basisbank_apply_bank_feed_source()
        return journals

    def write(self, vals):
        res = super().write(vals)
        if {'bank_account_id', 'bank_account_number', 'bank_bic', 'type'} & set(vals):
            self._basisbank_apply_bank_feed_source()
        return res

    def _basisbank_apply_bank_feed_source(self):
        """Point journals with Basis Bank's BIC at the Basis Bank feed, keyed on the BIC (not is_basisbank).
        Fills only an undefined source."""
        for journal in self:
            if journal._is_basisbank_journal() and journal.bank_statements_source == 'undefined':
                journal.bank_statements_source = 'basisbank'

    def _get_bank_statements_available_sources(self):
        """Add the Basis Bank bank-feed source."""
        sources = super()._get_bank_statements_available_sources()
        sources.append(('basisbank', _("Basis Bank")))
        return sources

    def _default_outbound_payment_methods(self):
        methods = super()._default_outbound_payment_methods()
        if self._is_basisbank_journal() and self._is_payment_method_available(BASISBANK_METHOD_CODE):
            basisbank_method = self.env.ref('basis_bank.account_payment_method_basisbank', raise_if_not_found=False)
            if basisbank_method:
                methods |= basisbank_method
        return methods

    def _is_basisbank_journal(self):
        """A bank journal whose bank account BIC is Basis Bank's, in the 8- or 11-character form."""
        return self.type == 'bank' and bic_prefix(self.bank_bic) == BASIS_BANK_BIC

    def _gec_bank_dashboard_logo(self):
        """Basis Bank's mark on the dashboard card of a journal with its BIC, with or without a connection."""
        if self._is_basisbank_journal():
            return '/basis_bank/static/src/img/basis_logo.svg'
        return super()._gec_bank_dashboard_logo()
