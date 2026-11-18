from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GecBankConnectionMixin(models.AbstractModel):
    """A company's connection to one bank API: the fields every bank connection shares.
    Credentials, tokens, approver and API log live on the bank model."""

    _name = 'gec.bank.connection.mixin'
    _description = 'Bank Connection Mixin'
    _inherit = ['mail.thread']
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company,
        ondelete='cascade', index=True, tracking=True)
    processing_mode = fields.Selection(
        selection=[('direct', 'Direct (bank auto-confirms)'),
                   ('bank_confirm', 'Manual confirmation in Internet Banking'),
                   ('odoo_approve', 'Approve in Odoo first')],
        string='Processing Mode', required=True, default='odoo_approve', tracking=True)
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('active', 'Active'),
                   ('error', 'Error'), ('blocked', 'Blocked')],
        string='State', required=True, default='draft', copy=False, tracking=True)
    allow_self_approval = fields.Boolean(
        string='Allow Self-Approval', default=False, tracking=True,
        help="Off (recommended): the user who created a transfer cannot approve it, so releasing "
             "money always takes two people. Turn it on only if your team has nobody else to "
             "approve.")
    last_error_code = fields.Integer(string='Last Error Code', readonly=True, copy=False)
    last_error_message = fields.Char(string='Last Error', readonly=True, copy=False)
    log_retention_days = fields.Integer(
        string='Log Retention (days)', default=90,
        help="Routine API log entries older than this are removed by Odoo's daily "
             "vacuum, so the log table cannot grow without bound. Set 0 to keep "
             "everything. Transfer logs are never deleted - they are the audit "
             "trail for money movement.")

    @api.ondelete(at_uninstall=False)
    def _unlink_except_logged(self):
        """A connection with API logs cannot be deleted: its logs are the audit trail."""
        logged = self.filtered('log_ids')
        if logged:
            raise UserError(_("A bank connection with API logs cannot be deleted: the logs are the audit trail of its transfers."))

    def _gec_bank_label(self):
        """The bank's name in messages; each bank returns its own, translated (override)."""
        return self._description

    def _gec_bank_unusable_errors(self, company):
        """Why ``company`` cannot use this bank: no connection (``self`` empty) or blocked.
        Shared by the send and channel checks."""
        if not self:
            return [_("No %(bank)s connection is configured for company %(company)s.",
                      bank=self._gec_bank_label(), company=company.display_name)]
        if self.state == 'blocked':
            return [_("The %(bank)s connection is blocked. Contact the bank.",
                      bank=self._gec_bank_label())]
        return []

    def action_view_logs(self):
        self.ensure_one()
        return {
            'name': _("API Logs"),
            'type': 'ir.actions.act_window',
            'res_model': self._fields['log_ids'].comodel_name,
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
        }
