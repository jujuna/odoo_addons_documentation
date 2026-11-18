from odoo import Command, api, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._gec_bank_ensure_api_lines()
        return journals

    def write(self, vals):
        bank_change = {'bank_account_id', 'bank_account_number', 'bank_bic', 'type'} & set(vals)
        held = self._gec_bank_payments_at_bank() if bank_change else None
        res = super().write(vals)
        if bank_change:
            held._gec_bank_check_bank_kept()
            self._gec_bank_ensure_api_lines()
        return res

    def _gec_bank_payments_at_bank(self):
        """Payments of these journals that a bank holds or may hold."""
        Payment = self.env['account.payment']
        blocked = Payment._gec_bank_state_groups()['at_bank'] | {'unknown'}
        return Payment.search([('journal_id', 'in', self.ids), ('gec_bank_state', 'in', list(blocked))])

    def _gec_bank_ensure_api_lines(self):
        """Add the outbound line of each bank API the journal's bank account allows.
        Core links the bank account (so its BIC) only after building the lines; only API channels are added."""
        Line = self.env['account.payment.method.line']
        for journal in self.filtered(lambda journal: journal.type == 'bank'):
            existing = journal.outbound_payment_method_line_ids.payment_method_id
            missing = (journal._default_outbound_payment_methods() - existing).filtered(
                lambda method: Line.new({'payment_method_id': method.id})._gec_bank_channel_kind() == 'api')
            if missing:
                journal.outbound_payment_method_line_ids = [
                    Command.create({'name': method.name, 'payment_method_id': method.id})
                    for method in missing]

    def _gec_bank_match_key_fields(self):
        """Payment fields a statement line's ``gec_bank_match_keys`` match on; override per bank, none by default."""
        return ()

    def _gec_bank_dashboard_logo(self):
        """URL of the bank logo on the journal's dashboard card; each bank returns its own, False by default."""
        return False

    def _fill_bank_cash_dashboard_data(self, dashboard_data):
        """Pass each bank journal's logo to its dashboard card as `gec_bank_logo`."""
        super()._fill_bank_cash_dashboard_data(dashboard_data)
        for journal in self.filtered(lambda journal: journal.type == 'bank'):
            dashboard_data[journal.id]['gec_bank_logo'] = journal._gec_bank_dashboard_logo()

    def _gec_bank_default_outstanding_account(self):
        """Core's default Outstanding Payments account for the journal's company."""
        self.ensure_one()
        chart_template = self.with_context(
            allowed_company_ids=self.company_id.root_id.ids
        ).env['account.chart.template']
        return chart_template.ref('account_journal_payment_credit_account_id', raise_if_not_found=False)
