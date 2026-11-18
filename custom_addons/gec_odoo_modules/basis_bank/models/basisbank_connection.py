import logging

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.basisbank_service import TECHNICAL_ERROR_CODE, TICKET_LIFETIME_SECONDS

_logger = logging.getLogger(__name__)


class BasisbankConnection(models.Model):
    _name = 'basisbank.connection'
    _description = 'Basis Bank Connection'
    _inherit = ['gec.bank.connection.mixin']

    login_name = fields.Char(string='Login Name', groups='basis_bank.group_basisbank_manager', tracking=True)
    password = fields.Char(string='Password', groups='basis_bank.group_basisbank_manager')
    api_host = fields.Char(string='API Host', required=True, default='bis.bankonline.ge', groups='basis_bank.group_basisbank_manager')
    api_version = fields.Char(string='API Version', required=True, default='v2', groups='basis_bank.group_basisbank_manager')
    approval_id = fields.Many2one('basisbank.approval', string='Approver', compute='_compute_approval_id', store=True, readonly=False,
        ondelete='restrict', domain="[('company_id', '=', company_id)]", check_company=True, tracking=True)
    ticket_id = fields.Char(string='Ticket Id', readonly=True, copy=False, groups='base.group_system')
    ticket_expiry = fields.Datetime(string='Ticket Expiry', readonly=True, copy=False, groups='base.group_system')
    log_ids = fields.One2many('basisbank.api.log', 'connection_id', string='API Logs')

    _company_uniq = models.Constraint('unique (company_id)', 'Each company can have only one Basis Bank connection.')

    @api.model_create_multi
    def create(self, vals_list):
        """A new connection turns its company's Basis-BIC journals into Basis journals."""
        connections = super().create(vals_list)
        self.env['account.journal']._basisbank_refresh_journals(connections.company_id)
        return connections

    def write(self, vals):
        """Moving a connection to another company moves the Basis journal flag with it."""
        companies = self.company_id
        res = super().write(vals)
        if 'company_id' in vals:
            self.env['account.journal']._basisbank_refresh_journals(companies | self.company_id)
        return res

    def unlink(self):
        """Without a connection, the company's journals fall back to standard payment rules."""
        companies = self.company_id
        res = super().unlink()
        self.env['account.journal']._basisbank_refresh_journals(companies)
        return res

    @api.depends('processing_mode')
    def _compute_approval_id(self):
        """Drop the approver when Odoo approval is switched off; a hidden leftover approver made forms offer Submit."""
        for connection in self:
            if connection.processing_mode == 'odoo_approve':
                connection.approval_id = connection.approval_id
            else:
                connection.approval_id = False

    @api.constrains('processing_mode', 'approval_id')
    def _check_approval_when_required(self):
        for record in self:
            if record.processing_mode == 'odoo_approve' and not record.approval_id:
                raise ValidationError(_("An approver is required when processing mode is 'Approve in Odoo first'."))

    def _gec_bank_label(self):
        return _("Basis Bank")

    def ticket_is_valid(self):
        self.ensure_one()
        if not self.sudo().ticket_id or not self.sudo().ticket_expiry:
            return False
        return self.sudo().ticket_expiry > fields.Datetime.now() + timedelta(seconds=30)

    @api.private
    def store_ticket(self, ticket_id, lifetime_seconds=TICKET_LIFETIME_SECONDS):
        self.ensure_one()
        self.sudo().write({'ticket_id': ticket_id, 'ticket_expiry': fields.Datetime.now() + timedelta(seconds=lifetime_seconds)})

    @api.private
    def clear_ticket(self):
        for record in self:
            record.sudo().write({'ticket_id': False, 'ticket_expiry': False})

    @api.private
    def refresh_ticket(self, lifetime_seconds=TICKET_LIFETIME_SECONDS):
        """Extend the session expiry: each bank call resets the 10-minute inactivity window."""
        for record in self:
            if record.sudo().ticket_id:
                record.sudo().ticket_expiry = fields.Datetime.now() + timedelta(seconds=lifetime_seconds)

    def action_test_connection(self):
        self.ensure_one()
        self.check_access('write')
        self.clear_ticket()
        if self.env['basisbank.service'].authenticate(self) and self.state == 'active':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': _("Basis Bank"), 'message': _("Connection successful."), 'type': 'success', 'sticky': False},
            }
        raise UserError(_("Authentication failed: %s") % (self.last_error_message or _("unknown error")))

    def action_reauthenticate(self):
        self.ensure_one()
        self.check_access('write')
        self.clear_ticket()
        self.env['basisbank.service'].authenticate(self)
        return True

    def action_basisbank_logout(self):
        """End the current Basis Bank session."""
        self.ensure_one()
        self.check_access('write')
        self.env['basisbank.service'].logout(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Basis Bank"), 'message': _("Logged out of Basis Bank."), 'type': 'success', 'sticky': False},
        }

    def action_basisbank_change_password(self):
        """Open the change-password wizard for this connection."""
        self.ensure_one()
        return {
            'name': _("Change Basis Bank Password"),
            'type': 'ir.actions.act_window',
            'res_model': 'basisbank.change.password.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_connection_id': self.id},
        }

    @api.private
    def basisbank_change_password(self, new_password, otp):
        """Change the bank password using the stored current one, an OTP, and a live session."""
        self.ensure_one()
        old_password = self.sudo().password or ''
        if not old_password:
            raise UserError(_("This connection has no current password set."))
        service = self.env['basisbank.service']
        response = service.change_password(self, old_password, new_password, otp)
        error_code = response.get('ErrorCode', TECHNICAL_ERROR_CODE)
        if error_code != 0:
            raise UserError(_("Basis Bank could not change the password: %s")
                            % service.error_message(error_code, fallback=response.get('ErrorMessage', '')))
        self.sudo().write({'password': new_password})
        self.clear_ticket()
        self.message_post(body=_("Basis Bank password changed."))
        return True

    @api.model
    def _cron_daily_statement_sync(self):
        """Import yesterday-to-today statement for each active connection's Basis journals, isolated per journal."""
        yesterday = fields.Date.today() - timedelta(days=1)
        today = fields.Date.today()
        Wizard = self.env['basisbank.statement.import.wizard']
        Journal = self.env['account.journal']
        service = self.env['basisbank.service']
        for connection in self.search([('state', '=', 'active')]):
            if not connection.ticket_is_valid() and not service.authenticate(connection):
                connection.message_post(body=_("Daily statement sync skipped: Basis Bank authentication failed."))
                continue
            journals = Journal.search([
                ('company_id', 'child_of', connection.company_id.id),
                ('is_basisbank', '=', True),
            ]).filtered(lambda journal: journal.basisbank_connection_id == connection)
            for journal in journals:
                if not journal.bank_account_number:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Wizard.create({
                            'journal_id': journal.id,
                            'start_date': yesterday,
                            'end_date': today,
                        }).action_import()
                except Exception:
                    _logger.exception("Basis Bank daily sync failed for journal %s", journal.id)
                    connection.message_post(body=_("Daily statement sync failed for %s; see API log.") % journal.display_name)
