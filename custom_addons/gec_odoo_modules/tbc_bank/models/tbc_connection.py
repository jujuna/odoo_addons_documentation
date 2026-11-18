import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

STATEMENT_SYNC_LOOKBACK_DAYS = 7


class TbcConnection(models.Model):
    _name = 'tbc.connection'
    _description = 'TBC Bank Connection'
    _inherit = ['gec.bank.connection.mixin', 'gec.bank.oauth.mixin']

    client_id = fields.Char(string='Client ID', groups='tbc_bank.group_tbc_manager', tracking=True)
    client_secret = fields.Char(string='Client Secret', groups='tbc_bank.group_tbc_manager')
    environment = fields.Selection(selection=[('test', 'Test'), ('production', 'Production')], string='Environment', required=True,
        default='test', tracking=True)
    api_host = fields.Char(string='API Host (override)', groups='tbc_bank.group_tbc_manager',
        help='Leave blank to use the default host for the selected environment.')
    approval_id = fields.Many2one('tbc.approval', string='Approver', ondelete='restrict', domain="[('company_id', '=', company_id)]",
        check_company=True, tracking=True)
    log_ids = fields.One2many('tbc.api.log', 'connection_id', string='API Logs')

    _company_uniq = models.Constraint('unique (company_id)', 'Each company can have only one TBC Bank connection.')

    @api.constrains('processing_mode', 'approval_id')
    def _check_approval_when_required(self):
        for record in self:
            if record.processing_mode == 'odoo_approve' and not record.approval_id:
                raise ValidationError(_("An approver is required when processing mode is 'Approve in Odoo first'."))

    def _gec_bank_label(self):
        return _("TBC Bank")

    def action_test_connection(self):
        self.ensure_one()
        self.check_access('write')
        self.clear_token()
        self.env['tbc.service'].authenticate(self)
        if self.state == 'active':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("TBC Bank"),
                    'message': _("Connection successful."),
                    'type': 'success',
                    'sticky': False,
                },
            }
        raise UserError(_("Authentication failed: %s", self.last_error_message or _("unknown error")))

    @api.model
    def _cron_daily_statement_sync(self):
        """Import the last few days' movements of every usable connection's TBC journals (error included). The window overlaps
        earlier days to pick up movements authorized later; lines are deduplicated."""
        window_start = fields.Date.today() - timedelta(days=STATEMENT_SYNC_LOOKBACK_DAYS)
        Wizard = self.env['tbc.statement.import.wizard']
        Journal = self.env['account.journal']
        for connection in self.search([('state', 'in', ('active', 'error'))]):
            journals = Journal.search([('company_id', 'child_of', connection.company_id.id), ('is_tbc', '=', True)])
            journals = journals.filtered(lambda journal: journal.tbc_connection_id == connection)
            for journal in journals:
                if not journal.bank_account_number:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Wizard.create({
                            'journal_id': journal.id,
                            'start_date': fields.Datetime.to_datetime(window_start),
                            'end_date': fields.Datetime.now(),
                        }).action_import()
                except Exception:
                    _logger.exception("TBC daily statement sync failed for journal %s", journal.id)
                    connection.message_post(body=_("Daily statement sync failed for %s; see API log.", journal.display_name))
