from odoo import _, api, fields, models

from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

from .account_payment_method import BOG_BANK_BIC


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    bog_connection_id = fields.Many2one('bog.connection', string='Bank of Georgia Connection',
                                        compute='_compute_bog_connection_id', search='_search_bog_connection_id',)

    is_bog = fields.Boolean(string='Is Bank of Georgia Journal', compute='_compute_is_bog', store=True)


    @api.depends('company_id', 'is_bog')
    def _compute_bog_connection_id(self):
        Connection = self.env['bog.connection'].sudo()
        bog_journals = self.filtered(lambda j: j.is_bog and j.company_id)
        (self - bog_journals).bog_connection_id = False
        if not bog_journals:
            return
        connections = Connection.search([('company_id', 'in', bog_journals.company_id.parent_ids.ids)])
        by_company = {c.company_id.id: c for c in connections}
        for journal in bog_journals:
            journal.bog_connection_id = next(
                (by_company[company.id] for company in journal.company_id.parent_ids[::-1]
                 if company.id in by_company), False)


    @api.depends('bank_account_id.bank_bic', 'type')
    def _compute_is_bog(self):
        for journal in self:
            journal.is_bog = journal._is_bog_journal()


    def _search_bog_connection_id(self, operator, value):
        """Search the computed field through the connection's company and its branches."""
        connections = self.env['bog.connection'].sudo().search([('id', operator, value)])
        return [('is_bog', '=', True), ('company_id', 'child_of', connections.company_id.ids)]


    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._bog_apply_bank_feed_source()
        return journals


    def write(self, vals):
        res = super().write(vals)
        if {'bank_account_id', 'type'} & set(vals):
            self._bog_apply_bank_feed_source()
        return res


    def _bog_apply_bank_feed_source(self):
        for journal in self:
            if journal.is_bog and journal.bank_statements_source == 'undefined':
                journal.bank_statements_source = 'bogbank'


    def _gec_bank_match_key_fields(self):
        """An entry's references are BOG's document key or our document number."""
        if self.is_bog:
            return ('gec_bank_reference', 'bog_document_no')
        return super()._gec_bank_match_key_fields()

    def _gec_bank_dashboard_logo(self):
        """Bank of Georgia's mark behind the dashboard card of a journal with BOG's BIC."""
        if self._is_bog_journal():
            return '/bog_bank/static/src/img/bog_logo.svg'
        return super()._gec_bank_dashboard_logo()

    def _get_bank_statements_available_sources(self):
        """Add the BOG Bank bank-feed source."""
        sources = super()._get_bank_statements_available_sources()
        sources.append(('bogbank', _("BANK OF GEORGIA")))
        return sources


    def _default_outbound_payment_methods(self):
        methods = super()._default_outbound_payment_methods()
        if self._is_bog_journal() and self._is_payment_method_available('bog_transfer'):
            bog_method = self.env.ref('bog_bank.account_payment_method_bog', raise_if_not_found=False)
            if bog_method:
                methods |= bog_method
        return methods


    def _is_bog_journal(self):
        return self.type == 'bank' and bic_prefix(self.bank_bic) == BOG_BANK_BIC


    def action_bog_import_statement(self):
        self.ensure_one()
        return {
            'name': _("Import Bank of Georgia Statement"),
            'type': 'ir.actions.act_window',
            'res_model': 'bog.statement.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_journal_id': self.id},
        }


