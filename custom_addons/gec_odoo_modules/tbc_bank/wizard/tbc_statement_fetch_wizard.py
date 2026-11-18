from odoo import _, fields, models
from odoo.exceptions import UserError


class TbcStatementFetchWizard(models.TransientModel):
    _name = 'tbc.statement.fetch.wizard'
    _description = 'Fetch TBC Statement for a Period'

    journal_id = fields.Many2one('account.journal', string='Journal', required=True, domain="[('is_tbc', '=', True)]")
    period_from = fields.Date(string='From', required=True)
    period_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_fetch(self):
        self.ensure_one()
        connection = self.journal_id.tbc_connection_id[:1]
        if not connection:
            raise UserError(_("No TBC Bank connection is configured for this journal's company."))
        if not self.journal_id.bank_account_number:
            raise UserError(_("The journal has no bank account number (IBAN)."))
        if self.period_from > self.period_to:
            raise UserError(_("The 'From' date must be before the 'To' date."))
        statement = self.env['tbc.statement']._fetch_and_store(connection, self.journal_id, self.period_from, self.period_to, 'period')
        return {
            'name': _("TBC Statement"),
            'type': 'ir.actions.act_window',
            'res_model': 'tbc.statement',
            'res_id': statement.id,
            'view_mode': 'form',
            'target': 'current',
        }
