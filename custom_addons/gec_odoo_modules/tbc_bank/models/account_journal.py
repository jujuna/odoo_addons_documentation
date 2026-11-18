from odoo import _, api, fields, models

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_payment_method import TBC_BANK_BIC, TBC_METHOD_CODE


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    tbc_connection_id = fields.Many2one('tbc.connection', string='TBC Bank Connection', compute='_compute_tbc_connection_id',
        search='_search_tbc_connection_id')
    is_tbc = fields.Boolean(string='Is TBC Bank Journal', compute='_compute_is_tbc', store=True)

    @api.depends('company_id', 'is_tbc')
    def _compute_tbc_connection_id(self):
        # sudo: only resolves the connection so users outside the TBC groups can read journals;
        # secrets stay behind field groups.
        Connection = self.env['tbc.connection'].sudo()
        tbc_journals = self.filtered(lambda j: j.is_tbc and j.company_id)
        (self - tbc_journals).tbc_connection_id = False
        if not tbc_journals:
            return
        connections = Connection.search([('company_id', 'in', tbc_journals.company_id.parent_ids.ids)])
        by_company = {c.company_id.id: c for c in connections}
        for journal in tbc_journals:
            journal.tbc_connection_id = next(
                (by_company[company.id] for company in journal.company_id.parent_ids[::-1] if company.id in by_company), False)

    def _search_tbc_connection_id(self, operator, value):
        """Translate a search on this computed field into one on the owning companies and their branches."""
        connections = self.env['tbc.connection'].sudo().search([('id', operator, value)])
        return [('is_tbc', '=', True), ('company_id', 'child_of', connections.company_id.ids)]

    @api.depends('bank_account_id.bank_bic', 'type')
    def _compute_is_tbc(self):
        for journal in self:
            journal.is_tbc = journal._is_tbc_journal()

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._tbc_apply_bank_feed_source()
        return journals

    def write(self, vals):
        res = super().write(vals)
        if {'bank_account_id', 'bank_account_number', 'bank_bic', 'type'} & set(vals):
            self._tbc_apply_bank_feed_source()
        return res

    def _tbc_apply_bank_feed_source(self):
        """Select the TBC bank feed on a TBC journal whose source is still undefined."""
        self.filtered(lambda journal: journal.is_tbc and journal.bank_statements_source == 'undefined').write({'bank_statements_source': 'tbcbank'})

    def _gec_bank_match_key_fields(self):
        """A movement's paymentId is TBC's transfer id or our request id; the docs do not say which."""
        if self.is_tbc:
            return ('gec_bank_reference', 'gec_bank_request_id')
        return super()._gec_bank_match_key_fields()

    def _gec_bank_dashboard_logo(self):
        """TBC Bank's mark behind the dashboard card of a journal with TBC's BIC."""
        if self._is_tbc_journal():
            return '/tbc_bank/static/src/img/tbc_logo.svg'
        return super()._gec_bank_dashboard_logo()

    def _get_bank_statements_available_sources(self):
        """Add the TBC Bank bank-feed source."""
        sources = super()._get_bank_statements_available_sources()
        sources.append(('tbcbank', _("TBC Bank")))
        return sources

    def _default_outbound_payment_methods(self):
        methods = super()._default_outbound_payment_methods()
        if self._is_tbc_journal() and self._is_payment_method_available(TBC_METHOD_CODE):
            tbc_method = self.env.ref('tbc_bank.account_payment_method_tbc', raise_if_not_found=False)
            if tbc_method:
                methods |= tbc_method
        return methods

    def _is_tbc_journal(self):
        return self.type == 'bank' and bic_prefix(self.bank_bic) == TBC_BANK_BIC

    def _tbc_account_number(self):
        """The journal's IBAN without spaces, as TBC expects it."""
        self.ensure_one()
        return self.bank_account_id.sanitized_account_number or False

    def _tbc_method_line(self):
        """Return this journal's outbound 'TBC Bank Transfer' payment method line."""
        self.ensure_one()
        return self.outbound_payment_method_line_ids.filtered(lambda l: l.payment_method_id.code == TBC_METHOD_CODE)[:1]

    def action_tbc_import_statement(self):
        self.ensure_one()
        return {
            'name': _("Import TBC Bank Statement"),
            'type': 'ir.actions.act_window',
            'res_model': 'tbc.statement.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_journal_id': self.id},
        }
