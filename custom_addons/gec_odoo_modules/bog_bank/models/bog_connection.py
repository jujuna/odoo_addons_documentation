import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

BOG_STATEMENT_SYNC_LOOKBACK_DAYS = 7


class BogConnection(models.Model):
    _name = 'bog.connection'
    _description = 'Bank of Georgia Connection'
    _inherit = ['gec.bank.connection.mixin', 'gec.bank.oauth.mixin']

    # No environment selector: BOG publishes one host (api.businessonline.ge).

    client_id = fields.Char(string='Client ID', groups='bog_bank.group_bog_manager', tracking=True)
    client_secret = fields.Char(string='Client Secret', groups='bog_bank.group_bog_manager')

    approval_id = fields.Many2one('bog.approval', string='Approver', ondelete='restrict',
                                  domain="[('company_id', '=', company_id)]", check_company=True, tracking=True)

    log_ids = fields.One2many('bog.api.log', 'connection_id', string='API Logs')

    match_threshold = fields.Float(
        string='Name Match Threshold (%)', default=80.0,
        help="Bank of Georgia returns how closely the beneficiary name matches the actual "
             "account holder on domestic documents. Below this percentage a warning is "
             "logged on the payment. Set 0 to disable the check.")

    _company_uniq = models.Constraint(
        'unique (company_id)',
        'Each company can have only one Bank of Georgia connection.',
    )


    @api.constrains('processing_mode', 'approval_id')
    def _check_approval_when_required(self):
        for record in self:
            if record.processing_mode == 'odoo_approve' and not record.approval_id:
                raise ValidationError(_("An approver is required when processing mode is 'Approve in Odoo first'."))


    def _gec_bank_label(self):
        return _("Bank of Georgia")


    def action_test_connection(self):
        self.ensure_one()
        self.check_access('write')
        self.clear_token()
        self.env['bog.service'].authenticate(self)
        if self.state == 'active':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Bank of Georgia"),
                    'message': _("Connection successful."),
                    'type': 'success',
                    'sticky': False,
                },
            }
        raise UserError(_("Authentication failed: %s") % (self.last_error_message or _("unknown error")))


    @api.model
    def _cron_daily_statement_sync(self):
        """Import the last days' movements of the BOG journals of every usable connection (active, or error after one failed login).
        The window overlaps earlier days; lines are deduplicated."""
        window_start = fields.Date.today() - timedelta(days=BOG_STATEMENT_SYNC_LOOKBACK_DAYS)
        Wizard = self.env['bog.statement.import.wizard']
        Journal = self.env['account.journal']
        for connection in self.search([('state', 'in', ('active', 'error'))]):
            journals = Journal.search([('company_id', 'child_of', connection.company_id.id), ('is_bog', '=', True)])
            journals = journals.filtered(lambda journal: journal.bog_connection_id == connection)
            for journal in journals:
                if not journal.bank_account_number:
                    continue
                try:
                    with self.env.cr.savepoint():
                        # The v2 statement path takes date-only values.
                        Wizard.create({
                            'journal_id': journal.id,
                            'start_date': window_start,
                            'end_date': fields.Date.today(),
                        }).action_import()
                except Exception:
                    _logger.exception("BOG daily statement sync failed for journal %s", journal.id)
                    connection.message_post(body=_("Daily statement sync failed for %s; see API log.")
                                                 % journal.display_name)