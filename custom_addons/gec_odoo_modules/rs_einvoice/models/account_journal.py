from odoo import api, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    @api.depends('type', 'company_id')
    @api.depends_context('uid')
    def _compute_show_refresh_out_einvoices_status_button(self):
        """The login fields come from rs_base_methods, hence getattr."""
        super()._compute_show_refresh_out_einvoices_status_button()
        for journal in self:
            if journal.type != 'sale':
                continue
            user = self.env.user.with_company(journal.company_id)
            if getattr(user, 'rs_username', False) and getattr(user, 'rs_un_id', 0):
                journal.show_refresh_out_einvoices_status_button = True

    def button_refresh_out_einvoices_status(self):
        """Runs as the clicking user, with that user's rs.ge login for the company."""
        super().button_refresh_out_einvoices_status()
        for journal in self:
            self.env['rs.einvoice.cron']._rs_refresh_seller_statuses(journal.company_id)
